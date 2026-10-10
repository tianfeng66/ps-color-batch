"""可选颜色批处理（可选颜色 · 色相/饱和度 · 自然饱和度）：本机网页工具的服务端（只用 Python 标准库 + Pillow + numpy）。"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

import adjust

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
VERSION = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "dev"
DATA_DIR = Path.home() / "Library" / "Application Support" / "可选颜色批处理"
PRESETS_FILE = DATA_DIR / "presets.json"
EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif", "WEBP": ".webp", "BMP": ".bmp"}
SKIPPED_EXTS = {".heic", ".heif", ".psd", ".psb", ".gif", ".avif", ".raw", ".cr2", ".nef", ".arw", ".dng"}
TOKEN = secrets.token_urlsafe(16)


def _ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 8.0


# 每个并行任务处理一张 1 亿像素的大图约占 1.5 GB 内存
WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2, int(_ram_gb() // 4)))
LUT_THREADS = max(1, min(4, os.cpu_count() or 2))
lut_lock = threading.Lock()
lut_cache: dict = {}
decode_slots = threading.BoundedSemaphore(3)
reserve_lock = threading.Lock()
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

state_lock = threading.Lock()
ITEMS: "OrderedDict[str, dict]" = OrderedDict()
ROOTS: List[dict] = []
JOBS: Dict[str, dict] = {}
preview_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
thumb_cache: Dict[tuple, bytes] = {}
cache_lock = threading.Lock()


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def is_image(p: Path) -> bool:
    return p.suffix.lower() in EXTS and not p.name.startswith(".")


def scan_inputs(paths: List[str], recursive: bool) -> dict:
    roots, items, missing = [], [], []
    unsupported: Dict[str, int] = {}
    for raw in paths:
        p = Path(os.path.expanduser(raw.strip().strip("'\""))).resolve() if raw.strip() else None
        if p is None:
            continue
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            found = []
            for f in it:
                if any(part.startswith(".") for part in f.relative_to(p).parts):
                    continue
                if f.is_file() and is_image(f):
                    found.append(f)
                elif f.suffix.lower() in SKIPPED_EXTS:
                    unsupported[f.suffix.lower()] = unsupported.get(f.suffix.lower(), 0) + 1
            found.sort(key=lambda f: natural_key(str(f.relative_to(p))))
            roots.append({"path": str(p), "kind": "folder", "count": len(found)})
            items += [(f, p, str(f.relative_to(p)), "folder") for f in found]
        elif p.is_file() and is_image(p):
            roots.append({"path": str(p), "kind": "file", "count": 1})
            items.append((p, p.parent, p.name, "file"))
        else:
            missing.append(raw)
    return {"roots": roots, "items": items, "missing": missing, "unsupported": unsupported}


def load_library(paths: List[str], recursive: bool, append: bool) -> dict:
    res = scan_inputs(paths, recursive)
    with state_lock:
        if not append:
            ITEMS.clear()
            ROOTS.clear()
        seen = {it["path"] for it in ITEMS.values()}
        for f, base, rel, kind in res["items"]:
            if str(f) in seen:
                continue
            seen.add(str(f))
            iid = uuid.uuid4().hex[:12]
            ITEMS[iid] = {"id": iid, "path": str(f), "rel": rel, "root": str(base), "kind": kind,
                          "name": f.name, "size": f.stat().st_size}
        ROOTS.extend(res["roots"])
        return {"items": list(ITEMS.values()), "roots": list(ROOTS), "missing": res["missing"],
                "unsupported": res["unsupported"]}


def with_out_rel(items: List[dict]) -> List[dict]:
    """一个文件夹：保持原结构；多个文件夹：每个文件夹一个子目录（重名时加上级目录名）；单独选的图放根目录。"""
    folder_roots = list(OrderedDict.fromkeys(it["root"] for it in items if it["kind"] == "folder"))
    single = len(folder_roots) == 1 and all(it["kind"] == "folder" for it in items)
    name_count = Counter(Path(r).name for r in folder_roots)
    labels: Dict[str, str] = {}
    used: set = set()
    for r in folder_roots:
        p = Path(r)
        base = p.name if name_count[p.name] == 1 else f"{p.parent.name}_{p.name}"
        label, i = base, 2
        while label in used:
            label = f"{base}_{i}"
            i += 1
        used.add(label)
        labels[r] = label
    out = []
    for it in items:
        if it["kind"] == "folder" and not single:
            out_rel = str(Path(labels[it["root"]]) / it["rel"])
        else:
            out_rel = it["rel"]
        out.append(dict(it, out_rel=out_rel))
    return out


def get_item(iid: str) -> dict:
    with state_lock:
        it = ITEMS.get(iid)
    if not it:
        raise KeyError("图片不在当前列表里，请重新载入")
    return it


# ---------- 预览 ----------

def display_image(path: str, max_side: int) -> Image.Image:
    """读成显示用的 RGB / RGBA，保持原始通道数值（不做色彩管理），按 EXIF 方向转正。"""
    with Image.open(path) as im:
        if im.format == "JPEG":
            try:
                im.draft("RGB", (max_side, max_side))
            except Exception:
                pass
        im = ImageOps.exif_transpose(im) or im
        if is_high_gray(im.mode):
            im = gray16_to_rgb(im)
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if has_alpha else "RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return im


def is_high_gray(mode: str) -> bool:
    return mode.startswith("I;16") or mode == "I"


def gray16_to_rgb(im: Image.Image) -> Image.Image:
    gray = np.asarray(im).astype(np.uint32)
    return Image.fromarray((np.clip(gray, 0, 65535) >> 8).astype(np.uint8)).convert("RGB")


def encode(im: Image.Image, fast_png: bool) -> Tuple[bytes, str]:
    buf = io.BytesIO()
    if im.mode == "RGBA" or fast_png:
        im.save(buf, "PNG", compress_level=1)
        return buf.getvalue(), "image/png"
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def cached_preview(path: str, max_side: int, thumb: bool) -> Tuple[bytes, str]:
    key = (path, os.path.getmtime(path), max_side)
    with cache_lock:
        hit = (thumb_cache if thumb else preview_cache).get(key)
    if hit:
        return hit
    with decode_slots:
        im = display_image(path, max_side)
    data = encode(im, fast_png=not thumb)
    with cache_lock:
        if thumb:
            if len(thumb_cache) > 5000:
                thumb_cache.clear()
            thumb_cache[key] = data
        else:
            preview_cache[key] = data
            while len(preview_cache) > 6:
                preview_cache.popitem(last=False)
    return data


def image_info(path: str) -> dict:
    with Image.open(path) as im:
        info = {"width": im.width, "height": im.height, "format": im.format, "mode": im.mode,
                "icc": bool(im.info.get("icc_profile"))}
        bits = bits_per_sample(im)
        if bits > 8:
            info["bits"] = bits
        return info


def bits_per_sample(im: Image.Image) -> int:
    if im.format == "TIFF":
        bps = im.tag_v2.get(258)
        if isinstance(bps, tuple):
            return max(bps) if bps else 8
        if isinstance(bps, int):
            return bps
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        return 16
    return 8


# ---------- 导出 ----------

def unique_path(p: Path, reserved: Optional[set] = None) -> Path:
    """找一个不存在的文件名；reserved 是同一任务里其他线程已占用、还没写完的名字。"""
    reserved = reserved if reserved is not None else set()
    with reserve_lock:
        stem, suf = p.stem, p.suffix
        for i in range(0, 10000):
            q = p if i == 0 else p.with_name(f"{stem}_{i}{suf}")
            if not q.exists() and str(q) not in reserved:
                reserved.add(str(q))
                return q
    raise RuntimeError("同名文件太多")


def default_out_dir(sample: bool) -> Path:
    stamp = time.strftime("%m%d-%H%M%S")
    tag = "调色_试跑" if sample else "调色"
    with state_lock:
        first = ROOTS[0] if ROOTS else None
    if not first:
        raise ValueError("还没有载入图片")
    p = Path(first["path"])
    if first["kind"] == "folder":
        return p.parent / f"{p.name}_{tag}_{stamp}"
    return p.parent / f"{tag}_{stamp}"


TIFF_KEEP_TAGS = (270, 271, 272, 305, 306, 315, 33432)


def save_kwargs(src: Image.Image, fmt: str, opts: dict) -> dict:
    info = src.info
    kw = {}
    if info.get("icc_profile"):
        kw["icc_profile"] = info["icc_profile"]
    if info.get("dpi"):
        kw["dpi"] = info["dpi"]
    exif = info.get("exif")
    if fmt == "JPEG":
        kw["quality"] = int(opts.get("quality", 95))
        kw["optimize"] = True
        sampling = -1
        if src.format in ("JPEG", "MPO"):
            try:
                from PIL import JpegImagePlugin
                sampling = JpegImagePlugin.get_sampling(src)
            except Exception:
                sampling = -1
            if info.get("progressive") or info.get("progression"):
                kw["progressive"] = True
        kw["subsampling"] = sampling if sampling >= 0 else 0
        if exif:
            kw["exif"] = exif
    elif fmt == "PNG":
        kw["compress_level"] = 6
        if exif:
            kw["exif"] = exif
    elif fmt == "WEBP":
        kw["quality"] = int(opts.get("quality", 95))
        kw["method"] = 4
        if exif:
            kw["exif"] = exif
    elif fmt == "TIFF":
        comp = info.get("compression") if src.format == "TIFF" else None
        if not comp or comp in ("group3", "group4", "tiff_ccitt"):
            comp = "tiff_lzw"
        kw["compression"] = comp
        if comp == "jpeg":
            kw["quality"] = int(opts.get("quality", 95))
        if src.format == "TIFF":
            tags = {}
            for t in TIFF_KEEP_TAGS:
                if t not in src.tag_v2:
                    continue
                v = src.tag_v2[t]
                if isinstance(v, str):
                    # Pillow 按 latin-1 解码 ASCII 标签；原样换回字节，中文（UTF-8）才不会变成 ???
                    try:
                        v = v.encode("latin-1")
                    except UnicodeEncodeError:
                        pass
                tags[t] = v
            if tags:
                kw["tiffinfo"] = tags
    elif fmt == "BMP":
        kw.pop("icc_profile", None)
    return kw


def process_one(item: dict, out_root: Path, settings: dict, opts: dict,
                lut: Optional[np.ndarray] = None, reserved: Optional[set] = None) -> dict:
    t0 = time.time()
    warnings = []
    with Image.open(item["path"]) as im:
        fmt = "JPEG" if im.format == "MPO" else im.format
        if fmt not in FORMAT_EXT:
            fmt = "PNG"
        if im.mode == "CMYK":
            return {"status": "skipped", "message": "CMYK 模式的图暂不支持，请先在 PS 里转成 RGB"}
        if getattr(im, "n_frames", 1) > 1:
            warnings.append(f"多页/动图只处理了第 1 帧（共 {im.n_frames} 帧）")
        bits = bits_per_sample(im)
        if bits > 8:
            warnings.append(f"原图 {bits} 位，输出为 8 位")
        mode = im.mode
        if mode in ("RGB", "RGBA"):
            work = im
            work.load()
        elif is_high_gray(mode):
            work = gray16_to_rgb(im)
            warnings.append(f"原图是 {mode} 灰度模式，已转为 RGB")
        else:
            has_alpha = mode in ("LA", "PA", "RGBa") or (mode == "P" and "transparency" in im.info)
            work = im.convert("RGBA" if has_alpha else "RGB")
            warnings.append(f"原图是 {mode} 模式，已转为 {work.mode}")

        target = opts.get("format", "keep")
        out_fmt = fmt if target == "keep" else target
        arr = np.asarray(work)
        out = adjust.apply_uint8(arr, settings, lut)
        out_im = Image.fromarray(out)
        if out_fmt in ("JPEG", "BMP") and out_im.mode == "RGBA":
            bg = Image.new("RGB", out_im.size, (255, 255, 255))
            bg.paste(out_im, mask=out_im.getchannel("A"))
            out_im = bg
            warnings.append("透明区域已填白（JPEG 不支持透明）")

        rel = Path(item["out_rel"])
        dest = out_root / rel
        if target != "keep" or FORMAT_EXT[out_fmt] != {".jpeg": ".jpg", ".tiff": ".tif"}.get(
                dest.suffix.lower(), dest.suffix.lower()):
            dest = dest.with_suffix(FORMAT_EXT[out_fmt])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = unique_path(dest, reserved)
        if Path(item["path"]).resolve() == dest.resolve():
            raise RuntimeError("输出路径和原图相同，已拒绝写入")
        kw = save_kwargs(im, out_fmt, opts)
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex[:8]}.part")
        try:
            try:
                out_im.save(tmp, format=out_fmt, **kw)
            except Exception:
                if out_fmt != "TIFF":
                    raise
                kw["compression"] = "tiff_lzw"
                kw.pop("tiffinfo", None)
                out_im.save(tmp, format=out_fmt, **kw)
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()

        compare_path = None
        if opts.get("compare"):
            compare_path = save_compare(work, out_im, im, out_root, rel, reserved)
    return {"status": "ok", "out": str(dest), "compare": compare_path, "warnings": warnings,
            "seconds": round(time.time() - t0, 2)}


def load_font(size: int):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size), True
            except Exception:
                continue
    return ImageFont.load_default(), False


def save_compare(before: Image.Image, after: Image.Image, src: Image.Image, out_root: Path, rel: Path,
                 reserved: Optional[set] = None) -> str:
    max_h = 1200
    pair = []
    orientation = src.getexif().get(0x0112, 1)
    for im in (before, after):
        im = im.convert("RGB") if im.mode != "RGB" else im
        method = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                  4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                  6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                  8: Image.Transpose.ROTATE_90}.get(orientation)
        if method is not None:
            im = im.transpose(method)
        im = im.copy()
        im.thumbnail((max_h * 3, max_h), Image.Resampling.LANCZOS)
        pair.append(im)
    gap, bar = 24, 64
    w = pair[0].width + pair[1].width + gap
    h = max(pair[0].height, pair[1].height) + bar
    sheet = Image.new("RGB", (w, h), (32, 32, 32))
    sheet.paste(pair[0], (0, bar))
    sheet.paste(pair[1], (pair[0].width + gap, bar))
    draw = ImageDraw.Draw(sheet)
    font, cjk = load_font(32)
    labels = ("调整前", "调整后") if cjk else ("BEFORE", "AFTER")
    draw.text((16, 14), labels[0], fill=(230, 230, 230), font=font)
    draw.text((pair[0].width + gap + 16, 14), labels[1], fill=(230, 230, 230), font=font)
    dest = out_root / "_前后对比" / rel.with_suffix(".jpg")
    dest = dest.with_name(dest.stem + "_对比.jpg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest, reserved)
    sheet.save(dest, "JPEG", quality=90)
    return str(dest)


def friendly_error(e: Exception) -> str:
    if isinstance(e, FileNotFoundError):
        return "找不到原图（可能被移动、改名或删除了），请重新载入图片"
    if isinstance(e, PermissionError):
        return f"没有权限写入：{e.filename or ''}（共享盘只读？请点「更改…」换个输出位置）"
    if isinstance(e, OSError) and e.errno == 28:
        return "磁盘空间不足"
    if isinstance(e, MemoryError):
        return "内存不足（图太大），请关掉其他软件后单独导出这张"
    return f"{type(e).__name__}: {e}"


def run_job(job: dict):
    try:
        _run_job(job)
    except Exception as e:
        traceback.print_exc()
        job["error"] = friendly_error(e)
    finally:
        job["finished"] = job["finished"] or time.time()
        job["state"] = "stopped" if job["stop"] else "done"


def pixels_exceed(items: List[dict], limit: int) -> bool:
    total = 0
    for it in items:
        try:
            with Image.open(it["path"]) as im:
                total += im.size[0] * im.size[1]
        except Exception:
            continue
        if total > limit:
            return True
    return False


def get_lut(settings: dict, items: List[dict]) -> Optional[np.ndarray]:
    """设置没变就复用上次的调色表；图少的时候逐像素算更快，不建表。"""
    key = json.dumps(settings, sort_keys=True)
    with lut_lock:
        if lut_cache.get("key") == key:
            return lut_cache["lut"]
    if not pixels_exceed(items, adjust.LUT_WORTH_PIXELS):
        return None
    try:
        lut = adjust.build_lut(settings, LUT_THREADS)
    except MemoryError:
        return None
    with lut_lock:
        lut_cache.update(key=key, lut=lut)
    return lut


def _run_job(job: dict):
    out_root = Path(job["out_dir"])
    settings, opts = job["settings"], job["opts"]
    items = job["items"]
    reserved: set = set()
    lut = None if adjust.is_identity(settings) else get_lut(settings, items)
    job["state"] = "running"

    def task(item):
        if job["stop"]:
            return {"status": "stopped", "message": "已停止，未处理"}
        try:
            return process_one(item, out_root, settings, opts, lut, reserved)
        except Exception as e:
            traceback.print_exc()
            return {"status": "failed", "message": friendly_error(e)}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(task, item): item for item in items}
        for fut in as_completed(futures):
            item = futures[fut]
            res = fut.result()
            res["id"] = item["id"]
            res["name"] = item["rel"]
            with state_lock:
                job["results"].append(res)
                if res["status"] == "ok":
                    job["done"] += 1
                elif res["status"] in ("failed", "skipped"):
                    job["failed"] += 1
    job["finished"] = time.time()
    by_id = {r["id"]: r for r in job["results"]}
    record = {
        "工具": f"可选颜色批处理 v{VERSION}",
        "开始时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job["started"])),
        "耗时秒": round(job["finished"] - job["started"], 1),
        "参数": adjust.describe(settings),
        "导出选项": opts,
        "成功": job["done"],
        "失败或跳过": job["failed"],
        "明细": [{"原图": it["path"], **{k: v for k, v in by_id.get(it["id"], {}).items() if k != "id"}}
               for it in items],
    }
    try:
        (out_root / "处理记录.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        traceback.print_exc()


def start_job(body: dict) -> dict:
    settings = adjust.normalize(body)
    ids = body.get("ids") or []
    sample = bool(body.get("sample"))
    with state_lock:
        all_items = list(ITEMS.values())
    items = with_out_rel(all_items)
    if ids:
        wanted = set(ids)
        items = [it for it in items if it["id"] in wanted]
    if sample:
        items = items[:5]
    if not items:
        raise ValueError("没有要导出的图片")
    out_dir = body.get("out_dir")
    out_root = Path(os.path.expanduser(out_dir)) if out_dir else default_out_dir(sample)
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        probe = out_root / f".写入测试_{uuid.uuid4().hex[:6]}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"无法在「{out_root}」写入文件（{friendly_error(e)}）。请点「更改…」换个输出位置")
    opts = {"format": body.get("format", "keep"), "quality": max(1, min(100, int(body.get("quality") or 95))),
            "compare": bool(body.get("compare"))}
    if opts["format"] not in ("keep", "JPEG", "PNG", "TIFF"):
        raise ValueError("不支持的输出格式")
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "out_dir": str(out_root), "items": items, "settings": settings,
           "opts": opts, "results": [], "done": 0, "failed": 0, "total": len(items),
           "started": time.time(), "finished": None, "stop": False, "state": "preparing"}
    JOBS[jid] = job
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return {"job": jid, "out_dir": str(out_root), "total": len(items)}


def job_status(jid: str, since: int) -> dict:
    job = JOBS.get(jid)
    if not job:
        raise KeyError("任务不存在")
    with state_lock:
        results = job["results"][since:]
        processed = len(job["results"])
    elapsed = (job["finished"] or time.time()) - job["started"]
    eta = elapsed / processed * (job["total"] - processed) if processed else None
    return {"state": job["state"], "total": job["total"], "processed": processed, "done": job["done"],
            "failed": job["failed"], "elapsed": round(elapsed, 1), "eta": round(eta, 1) if eta is not None else None,
            "results": results, "out_dir": job["out_dir"], "error": job.get("error")}


def job_result_path(jid: str, iid: str) -> str:
    job = JOBS.get(jid)
    if not job:
        raise KeyError("任务不存在")
    for r in job["results"]:
        if r["id"] == iid and r.get("out"):
            return r["out"]
    raise KeyError("这张图还没有导出结果")


# ---------- 预设 ----------

def read_presets() -> list:
    try:
        raw = json.loads(PRESETS_FILE.read_text("utf-8"))
    except Exception:
        return []
    out = []
    for p in raw:
        try:
            out.append({"name": p["name"], "settings": adjust.normalize(p.get("settings") or p)})
        except Exception:
            continue
    return out


def write_presets(presets: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PRESETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(presets, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, PRESETS_FILE)


# ---------- macOS 选择框 ----------

def osa_pick(kind: str) -> List[str]:
    if kind == "files":
        choose = ('set picked to choose file with prompt "选择要处理的图片（可按住 ⌘ 多选）" '
                  'of type {"public.image"} with multiple selections allowed')
    elif kind == "folders":
        choose = 'set picked to choose folder with prompt "选择图片文件夹（可按住 ⌘ 多选）" with multiple selections allowed'
    elif kind == "outdir":
        choose = 'set picked to {choose folder with prompt "选择输出文件夹"}'
    else:
        raise ValueError("未知选择类型")
    script = f'''
activate
{choose}
set out to ""
repeat with x in picked
    set out to out & POSIX path of x & linefeed
end repeat
return out
'''
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode != 0:
        if "-128" in p.stderr:
            return []
        raise RuntimeError(p.stderr.strip() or "打开选择框失败")
    return [line for line in p.stdout.splitlines() if line.strip()]


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "SelectiveColor/1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, msg: str, code=400):
        self._json({"error": msg}, code)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _token_ok(self, qs) -> bool:
        return self.headers.get("X-Token") == TOKEN or qs.get("t", [""])[0] == TOKEN

    def do_GET(self):
        if not self._host_ok():
            return self._err("forbidden", 403)
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_text("utf-8")
            html = html.replace("__TOKEN__", TOKEN).replace("__VERSION__", VERSION)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            f = (STATIC / u.path[len("/static/"):]).resolve()
            if STATIC not in f.parents or not f.is_file():
                return self._err("not found", 404)
            ctype = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(
                f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype + "; charset=utf-8")
        if u.path == "/api/ping":
            return self._json({"ok": True, "version": VERSION})
        if not self._token_ok(qs):
            return self._err("forbidden", 403)
        try:
            if u.path in ("/api/thumb", "/api/preview"):
                it = get_item(qs["id"][0])
                thumb = u.path == "/api/thumb"
                size = 240 if thumb else max(400, min(4000, int(qs.get("max", ["1800"])[0])))
                data, ctype = cached_preview(it["path"], size, thumb)
                return self._send(200, data, ctype)
            if u.path == "/api/result-preview":
                path = job_result_path(qs["job"][0], qs["id"][0])
                size = max(400, min(4000, int(qs.get("max", ["1800"])[0])))
                data, ctype = cached_preview(path, size, False)
                return self._send(200, data, ctype)
            if u.path == "/api/info":
                it = get_item(qs["id"][0])
                return self._json(image_info(it["path"]))
            if u.path == "/api/job":
                return self._json(job_status(qs["id"][0], int(qs.get("since", ["0"])[0])))
            if u.path == "/api/presets":
                return self._json(read_presets())
            if u.path == "/api/items":
                with state_lock:
                    return self._json({"items": list(ITEMS.values()), "roots": list(ROOTS)})
        except KeyError as e:
            return self._err(str(e).strip("'"), 404)
        except Exception as e:
            traceback.print_exc()
            return self._err(f"{type(e).__name__}: {e}", 500)
        return self._err("not found", 404)

    def do_POST(self):
        if not self._host_ok():
            return self._err("forbidden", 403)
        u = urlparse(self.path)
        if not self._token_ok(parse_qs(u.query)):
            return self._err("forbidden", 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/pick":
                return self._json({"paths": osa_pick(body.get("kind", "folders"))})
            if u.path == "/api/load":
                return self._json(load_library(body.get("paths", []), bool(body.get("recursive")),
                                               bool(body.get("append"))))
            if u.path == "/api/clear":
                with state_lock:
                    ITEMS.clear()
                    ROOTS.clear()
                return self._json({"ok": True})
            if u.path == "/api/export":
                return self._json(start_job(body))
            if u.path == "/api/job/stop":
                job = JOBS.get(body.get("id"))
                if job:
                    job["stop"] = True
                return self._json({"ok": True})
            if u.path == "/api/default-out":
                return self._json({"path": str(default_out_dir(bool(body.get("sample"))))})
            if u.path == "/api/presets":
                name = (body.get("name") or "").strip()
                if not name:
                    raise ValueError("预设名称不能为空")
                presets = [p for p in read_presets() if p["name"] != name]
                presets.append({"name": name, "settings": adjust.normalize(body.get("settings") or {})})
                write_presets(presets)
                return self._json(presets)
            if u.path == "/api/presets/delete":
                presets = [p for p in read_presets() if p["name"] != body.get("name")]
                write_presets(presets)
                return self._json(presets)
            if u.path == "/api/reveal":
                p = Path(body.get("path", ""))
                if not p.exists():
                    raise ValueError("路径不存在")
                subprocess.run(["open", str(p)] if p.is_dir() else ["open", "-R", str(p)])
                return self._json({"ok": True})
        except (ValueError, KeyError) as e:
            return self._err(str(e).strip("'"), 400)
        except Exception as e:
            traceback.print_exc()
            return self._err(f"{type(e).__name__}: {e}", 500)
        return self._err("not found", 404)


def can_bind(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port(start: int) -> int:
    for _ in range(6):
        if can_bind(start):
            return start
        time.sleep(0.3)
    for port in range(start + 1, start + 30):
        if can_bind(port):
            return port
    raise RuntimeError("找不到可用端口")


def main():
    ap = argparse.ArgumentParser(description="可选颜色批处理")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("paths", nargs="*", help="启动时直接载入的文件夹或图片")
    args = ap.parse_args()
    if args.paths:
        load_library(args.paths, recursive=False, append=False)
    port = free_port(args.port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"可选颜色批处理 v{VERSION} 已启动：{url}", flush=True)
    print("使用期间请不要关闭这个窗口；关闭窗口即停止工具。", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
