"""用 OpenPhoto 仓库里 Photoshop 2026 导出的对照数据验证算法（可选颜色、色相/饱和度、自然饱和度）。

用法：python3 tests/verify_against_photoshop.py [对照数据目录，默认 tests/fixtures]
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adjust  # noqa: E402
from selective_color import empty_settings  # noqa: E402

HERE = Path(__file__).resolve().parent


def to_settings(partial: dict) -> dict:
    """ps_cases.json 里只写改动的项，这里补全成完整设置。"""
    colors = empty_settings()
    for i, v in (partial.get("colors") or {}).items():
        colors[int(i)] = v
    hs = dict(partial.get("hs") or {})
    ranges = [[0, 0, 0] for _ in range(6)]
    for i, v in (hs.get("ranges") or {}).items():
        ranges[int(i)] = v
    hs["ranges"] = ranges
    return adjust.normalize({"colors": colors, "absolute": partial.get("absolute"), "hs": hs,
                             "vib": partial.get("vib")})


def describe(s: dict) -> str:
    rec = adjust.describe(s)
    rec.pop("原始参数")
    rec.pop("处理顺序")
    return json.dumps(rec, ensure_ascii=False)[:70]


def main(fixtures: Path) -> int:
    probe = np.frombuffer((fixtures / "probe.rgb").read_bytes(), np.uint8).reshape(72, 64, 3)
    cases = json.loads((HERE / "ps_cases.json").read_text("utf-8"))["cases"]
    failed = 0
    for case in cases:
        s = to_settings(case["settings"])
        want = np.frombuffer((fixtures / case["file"]).read_bytes(), np.uint8).reshape(72, 64, 3)
        got = adjust.apply_uint8(probe, s)
        diff = np.abs(got.astype(int) - want.astype(int))
        worst, off = int(diff.max()), int((diff > 1).sum())
        ok = worst <= case["worst"] and off <= case.get("off", 0 if case["worst"] <= 1 else 10 ** 9)
        failed += not ok
        print(f"{case['file']:16s} 最大误差 {worst} 级（允许 {case['worst']}）  误差>1 的通道 {off:4d}  "
              f"{'通过' if ok else '不通过'}  {describe(s)}")

    # 查表（批量导出用）必须和逐像素计算完全一样：三种调整叠在一起测
    mixed = to_settings({"colors": {"0": [40, -20, 10, 5], "7": [0, 0, -30, 0]},
                         "hs": {"master": [15, 20, -10], "ranges": {"1": [-20, 30, 10], "4": [10, -40, -20]}},
                         "vib": [30, 15]})
    rng = np.random.default_rng(1)
    img = np.concatenate([probe.reshape(-1, 3), rng.integers(0, 256, (20000, 3), dtype=np.uint8)])[None]
    for name, s in [("三种叠加", mixed), ("着色", to_settings({"hs": {"colorize": True, "cz": [30, 60, -15]}}))]:
        same = np.array_equal(adjust.apply_uint8(img, s), adjust.apply_uint8(img, s, adjust.build_lut(s)))
        failed += not same
        print(f"查表与逐像素一致（{name}）：{'通过' if same else '不通过'}")
    print("\n全部通过" if not failed else f"\n不通过 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fixtures"))
