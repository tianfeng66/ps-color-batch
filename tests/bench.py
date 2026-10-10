"""粗略测速：python3 tests/bench.py"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import adjust  # noqa: E402
from selective_color import empty_settings  # noqa: E402

colors = empty_settings()
colors[0] = [40, -20, 10, 5]
cases = {
    "只有可选颜色": adjust.normalize({"colors": colors}),
    "只有色相/饱和度（全局+红色）": adjust.normalize({"hs": {"master": [0, 20, 0], "ranges": [[0, 30, 0]] + [[0, 0, 0]] * 5}}),
    "三种叠加": adjust.normalize({"colors": colors, "hs": {"master": [10, 20, -5], "ranges": [[0, 30, 0]] * 6},
                              "vib": [30, 10]}),
}
img = np.random.default_rng(0).integers(0, 256, (4000, 6000, 3), dtype=np.uint8)
threads = int(sys.argv[1]) if len(sys.argv) > 1 else 2
for name, s in cases.items():
    t0 = time.time()
    lut = adjust.build_lut(s, threads)
    t1 = time.time()
    adjust.apply_uint8(img, s, lut)
    t2 = time.time()
    print(f"{name}：建表（{threads} 线程）{t1 - t0:.1f}s · 2400万像素查表 {t2 - t1:.2f}s")
