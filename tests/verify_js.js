// 浏览器预览用的 JS 算法对照 Photoshop 输出：node tests/verify_js.js
const fs = require("fs");
const path = require("path");
const SC = require("../static/selective_color.js");
const AD = require("../static/adjust.js");
const dir = path.join(__dirname, "fixtures");
const probe = fs.readFileSync(path.join(dir, "probe.rgb"));
const rgba = new Uint8ClampedArray(64 * 72 * 4);
for (let i = 0; i < 64 * 72; i++) { rgba.set(probe.subarray(i * 3, i * 3 + 3), i * 4); rgba[i * 4 + 3] = 255; }

function toSettings(p) {
  const colors = Array.from({ length: 9 }, () => [0, 0, 0, 0]);
  for (const k in p.colors || {}) colors[k] = p.colors[k];
  const hs = p.hs || {};
  const ranges = Array.from({ length: 6 }, () => [0, 0, 0]);
  for (const k in hs.ranges || {}) ranges[k] = hs.ranges[k];
  return {
    colors, absolute: !!p.absolute,
    hs: { master: hs.master || [0, 0, 0], ranges, colorize: !!hs.colorize, cz: hs.cz || [0, 25, 0] },
    vib: p.vib || [0, 0],
  };
}

let failed = 0;
const { cases } = JSON.parse(fs.readFileSync(path.join(__dirname, "ps_cases.json"), "utf8"));
for (const cs of cases) {
  const want = fs.readFileSync(path.join(dir, cs.file));
  const out = AD.applyAll(rgba, new Uint8ClampedArray(rgba.length), toSettings(cs.settings));
  let worst = 0, off = 0;
  for (let i = 0; i < 64 * 72; i++) for (let c = 0; c < 3; c++) {
    const d = Math.abs(out[i * 4 + c] - want[i * 3 + c]);
    worst = Math.max(worst, d);
    if (d > 1) off++;
  }
  const ok = worst <= cs.worst && off <= (cs.off ?? (cs.worst <= 1 ? 0 : Infinity));
  if (!ok) failed++;
  console.log(`${cs.file.padEnd(16)} 最大误差 ${worst} 级（允许 ${cs.worst}）  误差>1 的通道 ${String(off).padStart(4)}  ${ok ? "通过" : "不通过"}`);
}
const colors = Array.from({ length: 9 }, (_, i) => [i * 10 - 40, -i * 5, 3 * i, 100 - i * 20]);
const back = SC.parseASV(SC.buildASV(colors, true));
const asvOk = JSON.stringify(back.colors) === JSON.stringify(colors) && back.absolute;
if (!asvOk) failed++;
console.log("asv 往返", asvOk ? "通过" : "不通过");
console.log(failed ? `\n不通过 ${failed} 项` : "\n全部通过");
process.exit(failed ? 1 : 0);
