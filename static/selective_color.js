// 与 selective_color.py 同一算法（移植自 OpenPhoto，MIT / Apache-2.0），用于浏览器实时预览。
(function (root) {
  function applyToRGBA(src, dst, colors, absolute) {
    const active = [];
    for (let i = 0; i < 9; i++) {
      const s = colors[i];
      const d = [0, 1, 2].map((c) => s[c] / 100 + (s[3] / 100) * (1 + s[c] / 100));
      if (d[0] !== 0 || d[1] !== 0 || d[2] !== 0) active.push([i, d]);
    }
    if (!active.length) {
      if (dst !== src) dst.set(src);
      return dst;
    }
    const w = new Float32Array(9);
    const v = new Float32Array(3);
    for (let p = 0, n = src.length; p < n; p += 4) {
      const r = src[p] / 255, g = src[p + 1] / 255, b = src[p + 2] / 255;
      const max = Math.max(r, g, b), min = Math.min(r, g, b);
      const mid = r + g + b - max - min;
      const top = max - mid, bottom = mid - min;
      w[0] = r > g && r > b ? top : 0;
      w[1] = b < r && b < g ? bottom : 0;
      w[2] = g > r && g > b ? top : 0;
      w[3] = r < g && r < b ? bottom : 0;
      w[4] = b > r && b > g ? top : 0;
      w[5] = g < r && g < b ? bottom : 0;
      w[6] = Math.max((min - 0.5) * 2, 0);
      w[7] = 1 - (Math.abs(max - 0.5) + Math.abs(min - 0.5));
      w[8] = Math.max((0.5 - max) * 2, 0);
      v[0] = r; v[1] = g; v[2] = b;
      for (let c = 0; c < 3; c++) {
        const ink = 1 - v[c];
        let change = 0;
        for (let k = 0; k < active.length; k++) {
          const wt = w[active[k][0]];
          if (wt <= 0) continue;
          let d = active[k][1][c];
          if (!absolute) d *= ink;
          if (d < -ink) d = -ink; else if (d > 1 - ink) d = 1 - ink;
          change += wt * d;
        }
        let o = ink + change;
        o = o < 0 ? 0 : o > 1 ? 1 : o;
        dst[p + c] = Math.floor((1 - o) * 255 + 0.5);
      }
      dst[p + 3] = src[p + 3];
    }
    return dst;
  }

  function isIdentity(colors) {
    return colors.every((row) => row.every((x) => x === 0));
  }

  // Photoshop 可选颜色预设 .asv（Adobe 文件格式规范）：大端 int16，
  // 版本 1、方法（0 相对 / 1 绝对）、10 组 青/洋红/黄/黑，第 1 组保留不用，其后依次为
  // 红、黄、绿、青、蓝、洋红、白、中性、黑。
  function parseASV(buffer) {
    const dv = new DataView(buffer);
    if (dv.byteLength < 4 + 10 * 8) throw new Error("文件太短，不是可选颜色预设");
    const version = dv.getInt16(0);
    if (version !== 1) throw new Error("不支持的预设版本：" + version);
    const absolute = dv.getInt16(2) === 1;
    const colors = [];
    for (let i = 1; i < 10; i++) {
      const row = [];
      for (let c = 0; c < 4; c++) row.push(Math.max(-100, Math.min(100, dv.getInt16(4 + i * 8 + c * 2))));
      colors.push(row);
    }
    return { colors, absolute };
  }

  function buildASV(colors, absolute) {
    const buf = new ArrayBuffer(4 + 10 * 8);
    const dv = new DataView(buf);
    dv.setInt16(0, 1);
    dv.setInt16(2, absolute ? 1 : 0);
    for (let i = 0; i < 9; i++) {
      for (let c = 0; c < 4; c++) dv.setInt16(4 + (i + 1) * 8 + c * 2, colors[i][c]);
    }
    return buf;
  }

  const api = { applyToRGBA, isIdentity, parseASV, buildASV };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SelectiveColor = api;
})(this);
