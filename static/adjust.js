// 与 adjust.py 同一算法（移植自 OpenPhoto，MIT / Apache-2.0），用于浏览器实时预览。
// 处理顺序：可选颜色 → 色相/饱和度 → 自然饱和度，每一步取整到 8 位。
(function (root) {
  const SC = root.SelectiveColor || require("./selective_color.js");
  const HUE_RANGES = [[315, 345, 15, 45], [15, 45, 75, 105], [75, 105, 135, 165],
    [135, 165, 195, 225], [195, 225, 255, 285], [255, 285, 315, 345]];

  const mod = (v, m) => ((v % m) + m) % m;
  const toByte = (v) => { v = Math.floor(v + 0.5); return v < 0 ? 0 : v > 255 ? 255 : v; };

  function hueOf(r, g, b, mx, mn) {
    const d = mx - mn;
    if (d <= 0) return 0;
    let h;
    if (mx === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    return h * 60;
  }

  function rangeWeight(h, [a, b, c, d]) {
    const t = mod(h - a, 360);
    b = mod(b - a, 360); c = mod(c - a, 360); d = mod(d - a, 360);
    if (t < b) return Math.max((t - 0.5) / b, 0);
    if (t <= c) return 1;
    if (t < d) return Math.min((d - t + 0.5) / (d - c), 1);
    return 0;
  }

  function hslToRgb(h, s, l, out) {
    if (s === 0) { out[0] = out[1] = out[2] = l; return out; }
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    const ch = (t) => {
      t = mod(t, 1);
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 0.5) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    const hh = h / 360;
    out[0] = ch(hh + 1 / 3); out[1] = ch(hh); out[2] = ch(hh - 1 / 3);
    return out;
  }

  function turnHue(c, deg, mx, mn, h0) {
    if (deg === 0 || mx === mn) return;
    const h = mod(h0 + deg, 360) / 60;
    const sector = Math.min(Math.floor(h), 5);
    const f = h - sector;
    const up = mn + (mx - mn) * f, down = mx - (mx - mn) * f;
    const t = [[mx, up, mn], [down, mx, mn], [mn, mx, up], [mn, down, mx], [up, mn, mx], [mx, mn, down]][sector];
    c[0] = t[0]; c[1] = t[1]; c[2] = t[2];
  }

  function saturate(c, amount) {
    if (amount === 0) return;
    const mx = Math.max(c[0], c[1], c[2]), mn = Math.min(c[0], c[1], c[2]);
    if (mx === mn) return;
    const l = (mx + mn) / 2;
    if (amount < 0) {
      for (let k = 0; k < 3; k++) c[k] = l + (c[k] - l) * (1 + amount);
      return;
    }
    const d = (mx - mn) / 255, lf = l / 255;
    const s = lf < 0.5 ? d / (2 * lf) : d / (2 - 2 * lf);
    const a = amount + s >= 1 ? s : 1 - amount;
    const k = 1 / a - 1;
    for (let i = 0; i < 3; i++) c[i] = c[i] + (c[i] - l) * k;
  }

  function hsIdentity(hs) {
    return !hs.colorize && hs.master.every((v) => !v) && hs.ranges.every((r) => r.every((v) => !v));
  }

  // RGBA 字节数组原地处理
  function applyHS(d, hs) {
    const [hue, sat, light] = hs.colorize ? hs.cz : hs.master;
    const lk = light / 100, sm = sat / 100;
    const lighten = light >= 0 ? (v) => v + (255 - v) * lk : (v) => v * (1 + lk);
    const active = [];
    if (!hs.colorize) hs.ranges.forEach((r, i) => { if (r[0] || r[1] || r[2]) active.push([HUE_RANGES[i], r]); });
    const c = new Float64Array(3);
    for (let p = 0, n = d.length; p < n; p += 4) {
      const r = d[p], g = d[p + 1], b = d[p + 2];
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      if (hs.colorize) {
        hslToRgb(hue, sm, lighten((mx + mn) / 2) / 255, c);
        d[p] = toByte(c[0] * 255); d[p + 1] = toByte(c[1] * 255); d[p + 2] = toByte(c[2] * 255);
        continue;
      }
      const h0 = mx > mn ? hueOf(r, g, b, mx, mn) : 0;
      let dh = hue, ds = 0, dl = 0;
      if (mx > mn) {
        for (let k = 0; k < active.length; k++) {
          const w = rangeWeight(h0, active[k][0]);
          if (w === 0) continue;
          const v = active[k][1];
          dh += w * v[0]; ds += w * v[1]; dl += w * v[2];
        }
      }
      c[0] = r; c[1] = g; c[2] = b;
      turnHue(c, dh, mx, mn, h0);
      c[0] = lighten(c[0]); c[1] = lighten(c[1]); c[2] = lighten(c[2]);
      if (dl !== 0) {
        const m2 = Math.max(c[0], c[1], c[2]), n2 = Math.min(c[0], c[1], c[2]), k = dl / 100;
        for (let i = 0; i < 3; i++) c[i] = k > 0 ? c[i] + (m2 - c[i]) * k : n2 + (c[i] - n2) * (1 + k);
      }
      saturate(c, Math.max(-100, Math.min(100, ds)) / 100);
      saturate(c, sm);
      d[p] = toByte(c[0]); d[p + 1] = toByte(c[1]); d[p + 2] = toByte(c[2]);
    }
    return d;
  }

  const toLin = (v) => (v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  const toSrgb = (v) => (v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055);
  const LIN = Float64Array.from({ length: 256 }, (_, i) => toLin(i / 255));

  function applyVib(d, [vib, sat]) {
    const v0 = vib / 100, kS = 1 + sat / 100;
    const c = new Float64Array(3);
    for (let p = 0, n = d.length; p < n; p += 4) {
      let lin0, lin1, lin2;
      if (v0) {
        const r = d[p] / 255, g = d[p + 1] / 255, b = d[p + 2] / 255;
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, dd = mx - mn;
        const h = hueOf(r, g, b, mx, mn);
        let s = dd === 0 ? 0 : l > 0.5 ? dd / (2 - mx - mn) : dd / (mx + mn);
        let v = v0;
        if (v > 0) v *= 1 - 0.7 * Math.exp(-(((h - 25) / 20) ** 2));
        s = Math.max(0, Math.min(1, s * (1 + v * (1 - s))));
        hslToRgb(h, s, l, c);
        if (!sat) { d[p] = toByte(c[0] * 255); d[p + 1] = toByte(c[1] * 255); d[p + 2] = toByte(c[2] * 255); continue; }
        lin0 = toLin(c[0]); lin1 = toLin(c[1]); lin2 = toLin(c[2]);
      } else {
        lin0 = LIN[d[p]]; lin1 = LIN[d[p + 1]]; lin2 = LIN[d[p + 2]];
      }
      const gray = 0.2878 * lin0 + 0.7122 * lin1;
      const f = (x) => toByte(toSrgb(Math.max(0, Math.min(1, gray + (x - gray) * kS))) * 255);
      d[p] = f(lin0); d[p + 1] = f(lin1); d[p + 2] = f(lin2);
    }
    return d;
  }

  function isIdentity(s) {
    return SC.isIdentity(s.colors) && hsIdentity(s.hs) && !s.vib[0] && !s.vib[1];
  }

  function applyAll(src, dst, s) {
    if (!SC.isIdentity(s.colors)) SC.applyToRGBA(src, dst, s.colors, s.absolute);
    else if (dst !== src) dst.set(src);
    if (!hsIdentity(s.hs)) applyHS(dst, s.hs);
    if (s.vib[0] || s.vib[1]) applyVib(dst, s.vib);
    return dst;
  }

  const api = { applyAll, applyHS, isIdentity, hsIdentity, rangeWeight, HUE_RANGES };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Adjust = api;
})(this);
