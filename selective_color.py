"""Photoshop「图像 › 调整 › 可选颜色」的像素算法。

移植自 OpenPhoto（https://github.com/yuanzhixiang/openphoto，MIT / Apache-2.0）
crates/op-core/src/adjust.rs 的 selective_color：作者用 Photoshop 2026 的实际输出拟合，
与 Photoshop 相差不超过 1 个色阶。
"""

from __future__ import annotations

from typing import List, Sequence

import numpy as np

RANGES = ["reds", "yellows", "greens", "cyans", "blues", "magentas", "whites", "neutrals", "blacks"]
RANGE_NAMES = ["红色", "黄色", "绿色", "青色", "蓝色", "洋红", "白色", "中性色", "黑色"]


def normalize(colors: Sequence[Sequence[int]]) -> List[List[int]]:
    """9 个颜色范围 × [青, 洋红, 黄, 黑]，每项 −100～100 的整数。"""
    if len(colors) != 9:
        raise ValueError("需要 9 个颜色范围")
    out = []
    for row in colors:
        if len(row) != 4:
            raise ValueError("每个颜色范围需要 青/洋红/黄/黑 4 个值")
        out.append([max(-100, min(100, int(round(float(v))))) for v in row])
    return out


def is_identity(colors: Sequence[Sequence[int]]) -> bool:
    return all(v == 0 for row in colors for v in row)


def _weights(rgb: np.ndarray) -> List[np.ndarray]:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    md = r + g + b - mx - mn
    top = mx - md
    bottom = md - mn
    zero = np.zeros_like(r)
    return [
        np.where((r > g) & (r > b), top, zero),
        np.where((b < r) & (b < g), bottom, zero),
        np.where((g > r) & (g > b), top, zero),
        np.where((r < g) & (r < b), bottom, zero),
        np.where((b > r) & (b > g), top, zero),
        np.where((g < r) & (g < b), bottom, zero),
        np.maximum((mn - 0.5) * 2.0, 0.0),
        1.0 - (np.abs(mx - 0.5) + np.abs(mn - 0.5)),
        np.maximum((0.5 - mx) * 2.0, 0.0),
    ]


def _apply_float(rgb: np.ndarray, colors: Sequence[Sequence[int]], absolute: bool) -> np.ndarray:
    weights = _weights(rgb)
    out = np.empty_like(rgb)
    for c in range(3):
        ink = 1.0 - rgb[..., c]
        change = np.zeros_like(ink)
        for w, settings in zip(weights, colors):
            a = settings[c] / 100.0
            k = settings[3] / 100.0
            d = a + k * (1.0 + a)
            if d == 0.0:
                continue
            d = d * ink if not absolute else np.full_like(ink, d)
            change += w * np.clip(d, -ink, 1.0 - ink)
        out[..., c] = 1.0 - np.clip(ink + change, 0.0, 1.0)
    return out


def _to_uint8(res: np.ndarray) -> np.ndarray:
    return np.clip(np.floor(res * 255.0 + 0.5), 0, 255).astype(np.uint8)


def empty_settings() -> List[List[int]]:
    return [[0, 0, 0, 0] for _ in range(9)]
