"""接口冒烟测试：python3 tests/api_smoke.py <测试素材目录> [端口]"""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adjust  # noqa: E402
import selective_color as sc  # noqa: E402

src = Path(sys.argv[1]).resolve()
base = f"http://127.0.0.1:{sys.argv[2] if len(sys.argv) > 2 else 8790}"
html = urllib.request.urlopen(base + "/").read().decode()
token = re.search(r'TOKEN = "([^"]+)"', html).group(1)


def call(path, body=None):
    req = urllib.request.Request(base + path, headers={"X-Token": token, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    return json.loads(urllib.request.urlopen(req).read())


def digest(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


before = {p: digest(p) for p in src.rglob("*") if p.is_file()}

try:
    urllib.request.urlopen(urllib.request.Request(base + "/api/items"))
    print("无 token 请求未被拒绝 ✗")
except urllib.error.HTTPError as e:
    print("无 token 请求被拒绝", e.code, "✓")

r = call("/api/load", {"paths": [str(src)], "recursive": True, "append": False})
print("载入", len(r["items"]), "张：", [i["rel"] for i in r["items"]])

colors = sc.empty_settings()
colors[0] = [-30, 20, 40, 10]
colors[3] = [50, -20, 0, 0]
colors[7] = [10, 0, -15, 5]
colors[8] = [0, 0, 0, 25]
settings = {"colors": colors, "absolute": False,
            "hs": {"master": [5, 15, -5], "ranges": [[0, -40, 10], [10, 20, 0], [0, 0, 0], [0, 0, 0], [0, 30, -10], [0, 0, 0]]},
            "vib": [25, 10]}
out_dir = src.parent / "测试输出"
job = call("/api/export", {**settings, "out_dir": str(out_dir), "compare": True})
while True:
    st = call(f"/api/job?id={job['job']}")
    if st["state"] not in ("running", "preparing"):
        break
    time.sleep(0.3)
print(f"任务 {st['state']}：成功 {st['done']}，失败/跳过 {st['failed']}，用时 {st['elapsed']} 秒")

items = {i["id"]: i for i in r["items"]}
for res in st["results"]:
    it = items[res["id"]]
    if res["status"] != "ok":
        print(f"  {it['rel']:28s} {res['status']}：{res['message']}")
        continue
    with Image.open(it["path"]) as a, Image.open(res["out"]) as b:
        checks = [f"{a.format}->{b.format}", f"{a.mode}->{b.mode}", f"{a.size == b.size and '尺寸同' or '尺寸变'}"]
        if a.info.get("icc_profile"):
            checks.append("ICC 保留" if a.info.get("icc_profile") == b.info.get("icc_profile") else "ICC 丢失 ✗")
        if a.getexif().get(0x0112):
            checks.append("EXIF方向保留" if a.getexif().get(0x0112) == b.getexif().get(0x0112) else "EXIF方向丢失 ✗")
        if a.info.get("dpi"):
            checks.append("DPI 保留" if tuple(map(round, a.info["dpi"])) == tuple(map(round, b.info.get("dpi", (0, 0)))) else "DPI 丢失 ✗")
        if a.format == "TIFF":
            checks.append(f"压缩 {a.info.get('compression')}->{b.info.get('compression')}")
        work = a.convert("RGBA" if a.mode in ("RGBA", "LA") else "RGB")
        want = adjust.apply_uint8(np.asarray(work), adjust.normalize(settings))
        got = np.asarray(b.convert(work.mode))
        diff = np.abs(want.astype(int) - got.astype(int))
        checks.append(f"与算法差 max {diff.max()} / 均值 {diff.mean():.2f}")
    print(f"  {it['rel']:28s} " + " · ".join(checks) + (f" · 提示：{'；'.join(res['warnings'])}" if res["warnings"] else ""))

record = json.loads((out_dir / "处理记录.json").read_text("utf-8"))
print("处理记录包含三种调整", "✓" if {"可选颜色", "色相/饱和度", "自然饱和度"} <= set(record["参数"]) else "✗")

presets = call("/api/presets", {"name": "__冒烟测试__", "settings": settings})
saved = [p for p in presets if p["name"] == "__冒烟测试__"]
print("预设保存三种调整", "✓" if saved and saved[0]["settings"] == adjust.normalize(settings) else "✗")
left = call("/api/presets/delete", {"name": "__冒烟测试__"})
print("预设删除", "✓" if not [p for p in left if p["name"] == "__冒烟测试__"] else "✗")

after = {p: digest(p) for p in src.rglob("*") if p.is_file()}
print("原图全部未改动 ✓" if before == after else "原图被改动 ✗")
print("输出文件：", sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file()))
