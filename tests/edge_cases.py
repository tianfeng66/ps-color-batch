"""边界情况测试（需要先启动 app.py）：python3 tests/edge_cases.py [临时工作目录] [端口]"""

import hashlib
import tempfile
import json
import os
import re
import shutil
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adjust  # noqa: E402
import selective_color as sc  # noqa: E402
from make_samples import gradient  # noqa: E402

base = f"http://127.0.0.1:{sys.argv[2] if len(sys.argv) > 2 else 8790}"
try:
    token = re.search(r'TOKEN = "([^"]+)"', urllib.request.urlopen(base + "/").read().decode()).group(1)
except OSError:
    sys.exit(f"连不上 {base}，请先运行 python3 app.py --no-browser")
work = (Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="sc_edge_")) / "可选颜色边界测试").resolve()
failures = []


def call(path, body=None):
    req = urllib.request.Request(base + path, headers={"X-Token": token, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def check(name, ok, detail=""):
    print(f"{'✓' if ok else '✗'} {name}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def wait(job_id):
    while True:
        st = call(f"/api/job?id={job_id}")
        if st["state"] not in ("running", "preparing"):
            return st
        time.sleep(0.2)


def tiff48(path, arr16):
    """手写一个未压缩的 48 位 RGB TIFF（Pillow 写不了 16 位 RGB）。"""
    h, w, _ = arr16.shape
    data = arr16.astype("<u2").tobytes()
    entries = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, 3, None), (259, 3, 1, 1), (262, 3, 1, 2),
               (273, 4, 1, None), (277, 3, 1, 3), (278, 4, 1, h), (279, 4, 1, len(data)), (284, 3, 1, 1)]
    ifd_off = 8
    ifd_size = 2 + len(entries) * 12 + 4
    bps_off = ifd_off + ifd_size
    data_off = bps_off + 6
    out = bytearray(b"II*\x00" + struct.pack("<I", ifd_off) + struct.pack("<H", len(entries)))
    for tag, typ, cnt, val in entries:
        if tag == 258:
            val = bps_off
        if tag == 273:
            val = data_off
        if typ == 3 and cnt == 1:
            out += struct.pack("<HHIHH", tag, typ, cnt, val, 0)
        else:
            out += struct.pack("<HHII", tag, typ, cnt, val)
    out += struct.pack("<I", 0) + struct.pack("<HHH", 16, 16, 16) + data
    path.write_bytes(bytes(out))


def digest_tree(p):
    return {str(f): hashlib.md5(f.read_bytes()).hexdigest() for f in p.rglob("*") if f.is_file()}


shutil.rmtree(work, ignore_errors=True)
src = work / "源图"
src.mkdir(parents=True)
g = gradient(400, 300)
Image.fromarray(g).quantize(64).save(src / "p_调色板.png", transparency=0)
Image.fromarray(np.dstack([g[..., 0], g[..., 1]])).convert("LA").save(src / "la_灰度透明.png")
Image.fromarray((g[..., 1].astype(np.uint16) * 257)).save(src / "i16_16位灰度.png")
tiff48(src / "rgb48_16位.tif", g.astype(np.uint16) * 257)
Image.fromarray(g).save(src / "deflate_带标签.tif", compression="tiff_adobe_deflate",
                        tiffinfo={270: "测试描述".encode("utf-8"), 315: "测试作者".encode("utf-8")})
Image.fromarray(g).save(src / "jpeg压缩.tif", compression="jpeg")
Image.fromarray(g).save(src / "bmp图.bmp")
Image.fromarray(g).save(src / "同名.png")
Image.fromarray(g).save(src / "同名.jpg", quality=95)
Image.fromarray(np.dstack([g, np.full(g.shape[:2], 128, np.uint8)])).save(src / "rgba_半透明.png")
(src / "苹果照片.heic").write_bytes(b"not really")
(src / "设计稿.psd").write_bytes(b"not really")
(src / ".隐藏.jpg").write_bytes(b"x")
for parent in ("A", "B"):
    d = work / parent / "图片"
    d.mkdir(parents=True)
    Image.fromarray(g).save(d / "一样的名字.png")
before = digest_tree(work)

colors = sc.empty_settings()
colors[0] = [40, -30, 20, 0]
colors[7] = [-20, 10, 30, 15]
settings = {"colors": colors, "absolute": False,
            "hs": {"master": [-10, 20, 5], "ranges": [[0, -30, 0], [0, 0, 0], [15, 25, -10], [0, 0, 0], [0, 0, 0], [0, 40, 0]]},
            "vib": [20, -10]}

# 1. 载入：不支持的格式要被统计，隐藏文件不载入
r = call("/api/load", {"paths": [str(src)], "recursive": False})
names = sorted(i["rel"] for i in r["items"])
check("载入数量 10 张（隐藏文件 / heic / psd 不算）", len(names) == 10, str(names))
check("报告了被忽略的 heic、psd", r.get("unsupported") == {".heic": 1, ".psd": 1}, str(r.get("unsupported")))

# 2. 保持原格式导出，逐张核对
out1 = work / "输出_保持格式"
st = wait(call("/api/export", {**settings, "out_dir": str(out1)})["job"])
check("保持格式导出全部成功（三种调整叠加）", st["done"] == 10 and st["failed"] == 0, f"done={st['done']} failed={st['failed']}")
res = {x["name"]: x for x in st["results"]}
for name, x in sorted(res.items()):
    if x["status"] != "ok":
        print("   ", name, x)
        continue
    with Image.open(src / name) as a, Image.open(x["out"]) as b:
        line = f"{a.format}/{a.mode} -> {b.format}/{b.mode}"
        if name.endswith((".png", ".bmp")) or "deflate" in name or "rgb48" in name:
            if a.mode in ("I;16", "I"):
                base_rgb = np.repeat((np.asarray(a).astype(np.uint32) >> 8).astype(np.uint8)[..., None], 3, 2)
            else:
                base_rgb = np.asarray(a.convert("RGBA" if "A" in b.mode else "RGB"))
            want = adjust.apply_uint8(base_rgb, adjust.normalize(settings))
            diff = int(np.abs(want.astype(int) - np.asarray(b).astype(int)).max())
            check(f"{name} 无损输出与算法一致", diff == 0, f"{line} 差 {diff}")
        else:
            check(f"{name} 有损格式正常写出", b.size == a.size, line)
        if "deflate" in name:
            utf = lambda v: v.encode("latin-1").decode("utf-8") if isinstance(v, str) else v  # noqa: E731
            check("TIFF 中文标签和压缩方式保留", b.info.get("compression") == "tiff_adobe_deflate"
                  and utf(b.tag_v2.get(270)) == "测试描述" and utf(b.tag_v2.get(315)) == "测试作者",
                  f"{b.info.get('compression')} {utf(b.tag_v2.get(270))} {utf(b.tag_v2.get(315))}")
    if x["warnings"]:
        print("    提示：", name, "；".join(x["warnings"]))
check("16 位 TIFF 有「输出为 8 位」提示", any("8 位" in w for w in res["rgb48_16位.tif"]["warnings"]))

# 3. 全部转 JPEG：同名.png / 同名.jpg 不能互相覆盖，透明图填白
out2 = work / "输出_转JPEG"
st = wait(call("/api/export", {"colors": colors, "absolute": True, "out_dir": str(out2), "format": "JPEG",
                               "quality": 300})["job"])
files = sorted(p.name for p in out2.iterdir() if p.suffix == ".jpg")
check("转 JPEG 全部成功", st["done"] == 10, f"done={st['done']} failed={st['failed']}")
check("同名.png 和 同名.jpg 输出成两个文件", "同名.jpg" in files and "同名_1.jpg" in files, str(files))
check("没有残留临时文件", not list(out2.rglob("*.part")))
check("透明图转 JPEG 有填白提示", any("填白" in w for x in st["results"] if "rgba" in x["name"] for w in x["warnings"]))

# 4. 两个同名文件夹追加载入：输出不冲突
call("/api/load", {"paths": [str(work / "A" / "图片")], "recursive": False})
r = call("/api/load", {"paths": [str(work / "B" / "图片")], "recursive": False, "append": True})
out3 = work / "输出_同名文件夹"
st = wait(call("/api/export", {"colors": colors, "absolute": False, "out_dir": str(out3)})["job"])
outs = sorted(str(p.relative_to(out3)) for p in out3.rglob("*.png"))
check("两个同名文件夹分别放进 A_图片 / B_图片", outs == ["A_图片/一样的名字.png", "B_图片/一样的名字.png"], str(outs))

# 5. 不做任何调整导出：像素和原图一样
call("/api/load", {"paths": [str(src / "rgba_半透明.png")]})
out4 = work / "输出_无调整"
st = wait(call("/api/export", {"colors": sc.empty_settings(), "absolute": False, "out_dir": str(out4)})["job"])
with Image.open(src / "rgba_半透明.png") as a, Image.open(out4 / "rgba_半透明.png") as b:
    check("无调整导出与原图像素完全一致", np.array_equal(np.asarray(a), np.asarray(b)))

# 6. 只读输出目录：给出可读的错误，不崩溃
ro = work / "只读目录"
ro.mkdir()
os.chmod(ro, 0o555)
r = call("/api/export", {"colors": colors, "absolute": False, "out_dir": str(ro / "子")})
os.chmod(ro, 0o755)
check("只读目录给出中文提示", "无法在" in (r.get("error") or ""), r.get("error", "")[:80])

# 7. 中途停止
many = work / "很多图"
many.mkdir()
big = gradient(3000, 2000)
for i in range(24):
    Image.fromarray(big).save(many / f"图{i:02d}.jpg", quality=90)
call("/api/load", {"paths": [str(many)]})
job = call("/api/export", {"colors": colors, "absolute": False, "out_dir": str(work / "输出_停止")})["job"]
time.sleep(2.0)
call("/api/job/stop", {"id": job})
st = wait(job)
stopped = sum(1 for x in st["results"] if x["status"] == "stopped")
check("停止后状态为 stopped，且有未处理的图", st["state"] == "stopped" and stopped > 0,
      f"state={st['state']} 完成 {st['done']} 未处理 {stopped}")
check("停止后也写了处理记录", (work / "输出_停止" / "处理记录.json").exists())
check("停止后没有残留临时文件", not list((work / "输出_停止").rglob("*.part")))

# 8. 预览 / 缩略图接口对特殊模式不报错
r = call("/api/load", {"paths": [str(src)]})
bad = []
for it in r["items"]:
    for ep in ("thumb", "preview"):
        try:
            urllib.request.urlopen(f"{base}/api/{ep}?id={it['id']}&t={token}").read()
        except Exception as e:
            bad.append(f"{it['rel']} {ep} {e}")
check("所有图的缩略图和预览都能出", not bad, "；".join(bad))
with urllib.request.urlopen(f"{base}/api/preview?id={[i for i in r['items'] if 'i16' in i['rel']][0]['id']}&t={token}") as f:
    from io import BytesIO
    px = np.asarray(Image.open(BytesIO(f.read())).convert("L"))
check("16 位灰度预览不是一片白", px.mean() < 230, f"平均亮度 {px.mean():.0f}")

src_after = {k: v for k, v in digest_tree(work).items() if k in before}
check("所有原图未被改动", src_after == before)
if len(sys.argv) <= 1:
    shutil.rmtree(work.parent, ignore_errors=True)
print("\n全部通过" if not failures else f"\n失败 {len(failures)} 项：{failures}")
sys.exit(1 if failures else 0)
