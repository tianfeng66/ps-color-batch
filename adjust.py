"""Photoshop「色相/饱和度」「自然饱和度」的像素算法，以及三种调整串起来的整体处理。

移植自 OpenPhoto（https://github.com/yuanzhixiang/openphoto，MIT / Apache-2.0）
crates/op-core/src/adjust.rs 的 HueSaturation::apply 与 Adjustment::Vibrance：
作者用 Photoshop 2026 的实际输出拟合。

处理顺序固定为 可选颜色 → 色相/饱和度 → 自然饱和度，每一步的结果都取整到 8 位，
和 PS 里按这个顺序叠三个调整图层一致。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

import selective_color as sc

HS_CHANNELS = ["全局颜色（主要）", "红色", "黄色", "绿色", "青色", "蓝色", "洋红"]
# PS 默认的六个颜色范围（开始渐入、完全作用起、完全作用止、渐出结束，单位度）
HUE_RANGES = [(315, 345, 15, 45), (15, 45, 75, 105), (75, 105, 135, 165),
              (135, 165, 195, 225), (195, 225, 255, 285), (255, 285, 315, 345)]
# 逐像素计算时每次处理的像素数：中间结果是几十个这么大的 float64 数组
STRIP_PIXELS = 1 << 18
# 一次导出的总像素超过它时，先建全部颜色的查表更快（建表本身就是算这么多像素）
LUT_WORTH_PIXELS = 1 << 24


def _int(v, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(float(v)))))


def _triple(v, limits) -> list:
    v = list(v) if v is not None else [0, 0, 0]
    if len(v) != 3:
        raise ValueError("色相/饱和度每组需要 色相/饱和度/明度 3 个值")
    return [_int(x, lo, hi) for x, (lo, hi) in zip(v, limits)]


def normalize(body: dict) -> dict:
    """前端传来的全部参数 → 规范化的设置。只带 colors/absolute 的旧格式也能用。"""
    hs = body.get("hs") or {}
    ranges = hs.get("ranges") or [[0, 0, 0]] * 6
    if len(ranges) != 6:
        raise ValueError("色相/饱和度需要 6 个颜色范围")
    vib = body.get("vib") or [0, 0]
    if len(vib) != 2:
        raise ValueError("自然饱和度需要 自然饱和度/饱和度 2 个值")
    adjust = [(-180, 180), (-100, 100), (-100, 100)]
    return {
        "colors": sc.normalize(body.get("colors") or sc.empty_settings()),
        "absolute": bool(body.get("absolute")),
        "hs": {
            "master": _triple(hs.get("master"), adjust),
            "ranges": [_triple(r, adjust) for r in ranges],
            "colorize": bool(hs.get("colorize")),
            "cz": _triple(hs.get("cz") or [0, 25, 0], [(0, 360), (0, 100), (-100, 100)]),
        },
        "vib": [_int(vib[0], -100, 100), _int(vib[1], -100, 100)],
    }


def hs_identity(hs: dict) -> bool:
    return not hs["colorize"] and not any(hs["master"]) and not any(v for r in hs["ranges"] for v in r)


def is_identity(s: dict) -> bool:
    return sc.is_identity(s["colors"]) and hs_identity(s["hs"]) and not any(s["vib"])


# ---------- 色相/饱和度 ----------

def _max_min(c):
    return c.max(axis=-1), c.min(axis=-1)


def _hue(c, mx, mn):
    """HSL 色相（度），灰色为 0。"""
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    d = mx - mn
    safe = np.where(d > 0, d, 1)
    h = np.where(mx == r, (g - b) / safe + np.where(g < b, 6, 0),
                 np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4))
    return np.where(d > 0, h * 60, 0).astype(np.float64)


def _range_weight(h, bounds):
    a, b, c, d = bounds
    t = np.mod(h - a, 360)
    b, c, d = (b - a) % 360, (c - a) % 360, (d - a) % 360
    return np.where(t < b, np.maximum((t - 0.5) / b, 0),
                    np.where(t <= c, 1, np.where(t < d, np.minimum((d - t + 0.5) / (d - c), 1), 0)))


def _turn_hue(c, deg):
    """色相转 deg 度，保持最大、最小通道不变。deg 可以逐像素不同。"""
    mx, mn = _max_min(c)
    h = np.mod(_hue(c, mx, mn) + deg, 360) / 60
    sector = np.minimum(np.floor(h), 5)
    f = h - sector
    up, down = mn + (mx - mn) * f, mx - (mx - mn) * f
    cond = [sector == k for k in range(5)]
    out = np.stack([
        np.select(cond, [mx, down, mn, mn, up], mx),
        np.select(cond, [up, mx, mx, down, mn], mn),
        np.select(cond, [mn, mn, up, mx, mx], down),
    ], axis=-1)
    keep = (np.asarray(deg) == 0) | (mx == mn)
    return np.where(keep[..., None], c, out)


def _saturate(c, amount):
    """PS 的饱和度一步（−1～1）。amount 可以逐像素不同。"""
    amount = np.broadcast_to(np.asarray(amount, np.float64), c.shape[:-1])
    mx, mn = _max_min(c)
    l = (mx + mn) / 2
    lf, d = l / 255, (mx - mn) / 255
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(lf < 0.5, d / (2 * lf), d / (2 - 2 * lf))
        a = np.where(amount + s >= 1, s, 1 - amount)
        k = 1 / a - 1
    toward = l[..., None] + (c - l[..., None]) * (1 + amount)[..., None]
    away = c + (c - l[..., None]) * k[..., None]
    out = np.where((amount < 0)[..., None], toward, away)
    keep = (amount == 0) | (mx == mn)
    return np.where(keep[..., None], c, out)


def _hsl_to_rgb(h, s, l):
    """h 度，s、l 为 0～1；可以是数组或标量。返回 0～1。"""
    h, s, l = (np.asarray(x, np.float64) for x in (h, s, l))
    q = np.where(l < 0.5, l * (1 + s), l + s - l * s)
    p = 2 * l - q

    def ch(t):
        t = np.mod(t, 1.0)
        return np.where(t < 1 / 6, p + (q - p) * 6 * t,
                        np.where(t < 0.5, q, np.where(t < 2 / 3, p + (q - p) * (2 / 3 - t) * 6, p)))

    hh = h / 360
    out = np.stack(np.broadcast_arrays(ch(hh + 1 / 3), ch(hh), ch(hh - 1 / 3)), axis=-1)
    return np.where((s == 0)[..., None], l[..., None], out)


def hue_saturation(c, hs: dict):
    """c：…×3 的 float64，0～255。返回 0～255（未取整）。"""
    hue, sat, light = hs["cz"] if hs["colorize"] else hs["master"]

    def lighten(v):
        return v + (255 - v) * light / 100 if light >= 0 else v * (1 + light / 100)

    mx, mn = _max_min(c)
    if hs["colorize"]:
        l = lighten((mx + mn) / 2) / 255
        return _hsl_to_rgb(hue, sat / 100, l) * 255

    dh = np.full(mx.shape, float(hue), np.float64)
    ds = np.zeros(mx.shape, np.float64)
    dl = np.zeros(mx.shape, np.float64)
    active = [(b, r) for b, r in zip(HUE_RANGES, hs["ranges"]) if any(r)]
    if active:
        h = _hue(c, mx, mn)
        colored = mx > mn
        for bounds, (rh, rs, rl) in active:
            w = np.where(colored, _range_weight(h, bounds), 0).astype(np.float64)
            dh += w * rh
            ds += w * rs
            dl += w * rl
    out = lighten(_turn_hue(c, dh))
    if dl.any():
        mx2, mn2 = _max_min(out)
        k = (dl / 100)[..., None]
        out = np.where(k > 0, out + (mx2[..., None] - out) * k, mn2[..., None] + (out - mn2[..., None]) * (1 + k))
    out = _saturate(out, np.clip(ds, -100, 100) / 100)
    return _saturate(out, sat / 100)


# ---------- 自然饱和度 ----------

def _srgb_to_linear(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(v):
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(np.maximum(v, 0), 1 / 2.4) - 0.055)


def vibrance(c, vib):
    """c：…×3 的 float64，0～255。返回 0～1（未取整）。
    「饱和度」与 PS 一致；「自然饱和度」是 OpenPhoto 的近似（偏向低饱和颜色、避开肤色）。"""
    v_amt, s_amt = vib
    rgb = c / 255
    if v_amt:
        mx, mn = _max_min(rgb)
        h = _hue(rgb, mx, mn)
        l = (mx + mn) / 2
        d = mx - mn
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(d == 0, 0, np.where(l > 0.5, d / (2 - mx - mn), d / (mx + mn)))
        v = v_amt / 100
        if v > 0:
            v = v * (1 - 0.7 * np.exp(-((h - 25) / 20) ** 2))
        s = np.clip(s * (1 + v * (1 - s)), 0, 1)
        rgb = _hsl_to_rgb(h, s, l)
    if s_amt:
        lin = _srgb_to_linear(rgb)
        gray = (0.2878 * lin[..., 0] + 0.7122 * lin[..., 1])[..., None]
        rgb = _linear_to_srgb(np.clip(gray + (lin - gray) * (1 + s_amt / 100), 0, 1))
    return rgb


# ---------- 串起来 ----------

def _round(v):
    return np.clip(np.floor(v + 0.5), 0, 255).astype(np.float64)


def _apply_float(rgb, s: dict) -> np.ndarray:
    """rgb：…×3 的 float64，0～255 的整数值。返回 uint8。"""
    out = rgb
    if not sc.is_identity(s["colors"]):
        out = sc._to_uint8(sc._apply_float(out / 255, s["colors"], s["absolute"])).astype(np.float64)
    if not hs_identity(s["hs"]):
        out = _round(hue_saturation(out, s["hs"]))
    if any(s["vib"]):
        out = _round(vibrance(out, s["vib"]) * 255)
    return out.astype(np.uint8)


def apply_uint8(arr: np.ndarray, s: dict, lut: Optional[np.ndarray] = None) -> np.ndarray:
    """arr：H×W×3 或 H×W×4 的 uint8（RGB），返回新数组，alpha 原样保留。
    传入 build_lut 的结果时改为查表，结果与逐像素计算完全相同。"""
    out = arr.copy()
    if is_identity(s):
        return out
    rows = max(1, STRIP_PIXELS // max(1, arr.shape[1]))
    for y0 in range(0, arr.shape[0], rows):
        strip = arr[y0:y0 + rows, :, :3]
        if lut is not None:
            idx = (strip[..., 0].astype(np.uint32) << 16) | (strip[..., 1].astype(np.uint32) << 8) | strip[..., 2]
            px = np.take(lut, idx).view(np.uint8).reshape(idx.shape + (4,))
            out[y0:y0 + rows, :, :3] = px[..., :3]
        else:
            out[y0:y0 + rows, :, :3] = _apply_float(strip.astype(np.float64), s)
    return out


def build_lut(s: dict, threads: int = 1) -> np.ndarray:
    """全部 256³ 种 RGB 的结果表（64 MB），下标 R<<16 | G<<8 | B，每项 R、G、B、0 打包成 uint32。"""
    lut = np.zeros((1 << 24, 4), np.uint8)
    step = STRIP_PIXELS

    def fill(start):
        i = np.arange(start, start + step, dtype=np.uint32)
        rgb = np.stack([(i >> 16) & 255, (i >> 8) & 255, i & 255], axis=-1).astype(np.float64)
        lut[start:start + step, :3] = _apply_float(rgb, s)

    starts = range(0, 1 << 24, step)
    if threads > 1:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            list(pool.map(fill, starts))
    else:
        for start in starts:
            fill(start)
    return lut.view(np.uint32).ravel()


def describe(s: dict) -> dict:
    """写进处理记录.json 的可读参数。"""
    rec = {"处理顺序": "可选颜色 → 色相/饱和度 → 自然饱和度"}
    if not sc.is_identity(s["colors"]):
        rec["可选颜色"] = {
            "方法": "绝对" if s["absolute"] else "相对",
            "颜色": {name: dict(zip(["青色", "洋红", "黄色", "黑色"], row))
                   for name, row in zip(sc.RANGE_NAMES, s["colors"]) if any(row)},
        }
    hs = s["hs"]
    if not hs_identity(hs):
        keys = ["色相", "饱和度", "明度"]
        if hs["colorize"]:
            rec["色相/饱和度"] = {"着色": dict(zip(keys, hs["cz"]))}
        else:
            rows = [("全局颜色（主要）", hs["master"])] + list(zip(HS_CHANNELS[1:], hs["ranges"]))
            rec["色相/饱和度"] = {name: dict(zip(keys, v)) for name, v in rows if any(v)}
    if any(s["vib"]):
        rec["自然饱和度"] = dict(zip(["自然饱和度", "饱和度"], s["vib"]))
    rec["原始参数"] = s
    return rec
