"""浏览器预览（JS）与导出（Python）在随机颜色上的结果对照：python3 tests/cross_check.py（需要 node）"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import adjust  # noqa: E402

CASES = {
    "三种叠加": {"colors": [[40, -20, 10, 5]] + [[0, 0, 0, 0]] * 6 + [[0, 0, -30, 0], [0, 0, 0, 0]],
             "hs": {"master": [15, 20, -10], "ranges": [[0, 0, 0], [-20, 30, 10], [0, 0, 0], [0, 0, 0],
                                                         [10, -40, -20], [0, 0, 0]]},
             "vib": [30, 15]},
    "自然饱和度 +60": {"vib": [60, 0]},
    "自然饱和度 −50 饱和度 +20": {"vib": [-50, 20]},
    "着色": {"hs": {"colorize": True, "cz": [30, 60, -15]}},
    "各颜色 明度/饱和度": {"hs": {"master": [0, -10, 5], "ranges": [[5, 40, -30], [-10, -60, 20], [20, 30, 40],
                                                            [-30, 50, -50], [0, 100, 10], [180, -100, 100]]}},
}

JS = r"""
const fs = require("fs");
const AD = require(process.argv[2]);
const [inp, cfg] = [fs.readFileSync(process.argv[3]), JSON.parse(fs.readFileSync(process.argv[4], "utf8"))];
const out = AD.applyAll(new Uint8ClampedArray(inp), new Uint8ClampedArray(inp.length), cfg);
fs.writeFileSync(process.argv[5], Buffer.from(out.buffer));
"""


def main() -> int:
    rng = np.random.default_rng(7)
    rgba = rng.integers(0, 256, (200000, 4), dtype=np.uint8)
    rgba[:, 3] = 255
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "in.bin").write_bytes(rgba.tobytes())
        (td / "run.js").write_text(JS)
        for name, partial in CASES.items():
            s = adjust.normalize(partial)
            (td / "cfg.json").write_text(json.dumps(s))
            subprocess.run(["node", str(td / "run.js"), str(HERE.parent / "static" / "adjust.js"),
                            str(td / "in.bin"), str(td / "cfg.json"), str(td / "out.bin")], check=True)
            js = np.frombuffer((td / "out.bin").read_bytes(), np.uint8).reshape(-1, 4)[:, :3]
            py = adjust.apply_uint8(rgba[None], s)[0, :, :3]
            diff = np.abs(js.astype(int) - py.astype(int))
            # 恰好落在 .5 上的值两边可能取整不同；几种调整叠加时，饱和度很高的颜色会把这 1 级放大
            ok = (diff > 0).mean() < 0.01 and (diff.max() <= 1 if len(partial) == 1 else (diff > 1).mean() < 0.001)
            failed += not ok
            print(f"{name:24s} 最大差 {diff.max()} 级 · 有差异的通道 {(diff > 0).mean() * 100:.3f}%  {'通过' if ok else '不通过'}")
    print("\n全部通过" if not failed else f"\n不通过 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
