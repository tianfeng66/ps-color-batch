(() => {
  const $ = (s) => document.querySelector(s);
  const SC = window.SelectiveColor;
  const AD = window.Adjust;
  const TOKEN = window.TOKEN;

  const RANGES = [
    { name: "红色", color: "#ff0000" }, { name: "黄色", color: "#ffff00" }, { name: "绿色", color: "#00ff00" },
    { name: "青色", color: "#00ffff" }, { name: "蓝色", color: "#0000ff" }, { name: "洋红", color: "#ff00ff" },
    { name: "白色", color: "#ffffff" }, { name: "中性色", color: "#807f7f" }, { name: "黑色", color: "#000000" },
  ];
  const INKS = [
    { name: "青色", short: "青", grad: "linear-gradient(90deg,#ff0000,#8a8a8a 49.5%,transparent 49.5%,transparent 50.5%,#8a8a8a 50.5%,#00ffff)" },
    { name: "洋红", short: "洋红", grad: "linear-gradient(90deg,#00ff00,#8a8a8a 49.5%,transparent 49.5%,transparent 50.5%,#8a8a8a 50.5%,#ff00ff)" },
    { name: "黄色", short: "黄", grad: "linear-gradient(90deg,#0000ff,#8a8a8a 49.5%,transparent 49.5%,transparent 50.5%,#8a8a8a 50.5%,#ffff00)" },
    { name: "黑色", short: "黑", grad: "linear-gradient(90deg,#ffffff,#8a8a8a 49.5%,transparent 49.5%,transparent 50.5%,#8a8a8a 50.5%,#000000)" },
  ];
  const HS_CH = [
    { name: "全局颜色（主要）" }, { name: "红色" }, { name: "黄色" }, { name: "绿色" },
    { name: "青色" }, { name: "蓝色" }, { name: "洋红" },
  ];
  const zeros = () => Array.from({ length: 9 }, () => [0, 0, 0, 0]);
  const defaults = () => ({
    colors: zeros(), absolute: false,
    hs: { master: [0, 0, 0], ranges: Array.from({ length: 6 }, () => [0, 0, 0]), colorize: false, cz: [0, 25, 0] },
    vib: [0, 0],
  });

  const S = {
    ...defaults(), range: 0, hsCh: 0, tab: "sc", preview: true,
    items: [], idx: -1, presets: [],
    viewMode: "split", srcMode: "live", thumbMode: "after", split: 0.5, peek: false,
    outDir: "", job: null, results: {}, resultJob: {},
  };

  const settings = () => ({ colors: S.colors, absolute: S.absolute, hs: S.hs, vib: S.vib });

  // ---------- 通用 ----------
  function u(path, params) {
    const q = new URLSearchParams({ ...params, t: TOKEN });
    return `${path}?${q}`;
  }
  async function api(path, body) {
    const opt = { headers: { "X-Token": TOKEN } };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    let r;
    try {
      r = await fetch(path, opt);
    } catch (e) {
      throw new Error("连不上工具服务，可能终端窗口被关了。请重新双击「启动.command」");
    }
    if (r.status === 403) throw new Error("页面已过期（工具重启过），请按 ⌘R 刷新页面");
    const j = await r.json().catch(() => ({ error: `服务返回异常（${r.status}）` }));
    if (!r.ok || j.error) throw new Error(j.error || r.statusText);
    return j;
  }
  let toastTimer;
  function toast(msg, ms = 2600) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), ms);
  }
  const fail = (e) => toast("出错了：" + e.message, 5000);
  function loadImg(src) {
    return new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = () => rej(new Error("图片读取失败（文件损坏或格式不支持）"));
      img.src = src;
    });
  }
  function fmtSec(s) {
    if (s == null) return "计算中";
    s = Math.round(s);
    if (s < 60) return `${s} 秒`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} 分 ${s % 60} 秒`;
    return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
  }
  const isTyping = (el) => el && el.matches && el.matches("input, textarea, select");

  // ---------- 调整面板 ----------
  const clampInt = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v)));
  const sg = (v) => `${v > 0 ? "+" : ""}${v}`;
  let dragging = false;
  window.addEventListener("pointerup", () => { if (dragging) { dragging = false; scheduleRender(false); } });

  // 一行「名称 + 数值框 + 滑块」，get/set 读写当前对应的参数
  function makeSlider(parent, { label, min, max, unit = "", get, set }) {
    const row = document.createElement("div");
    row.className = "srow";
    row.innerHTML = `<div class="top"><span></span><input type="text"></div><input type="range" step="1">`;
    row.querySelector("span").textContent = label;
    const txt = row.querySelector("input[type=text]");
    const rng = row.querySelector("input[type=range]");
    const lim = { min, max };
    const fmt = (v) => `${v}${unit}`;
    const put = (v, live) => {
      v = clampInt(v, lim.min, lim.max);
      set(v);
      txt.value = fmt(v);
      rng.value = v;
      settingsChanged(live);
    };
    rng.addEventListener("pointerdown", () => { dragging = true; });
    rng.addEventListener("input", () => put(+rng.value, dragging));
    rng.addEventListener("change", () => { dragging = false; put(+rng.value, false); rng.blur(); });
    txt.addEventListener("focus", () => setTimeout(() => txt.select(), 0));
    const commit = () => {
      const v = parseInt(txt.value.replace(/[%°\s]/g, ""), 10);
      put(Number.isFinite(v) ? v : get(), false);
    };
    txt.addEventListener("change", commit);
    txt.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === "Escape") { commit(); txt.blur(); }
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        put(get() + (e.shiftKey ? 10 : 1) * (e.key === "ArrowUp" ? 1 : -1), false);
        txt.select();
      }
    });
    parent.appendChild(row);
    const ctl = {
      setRange(a, b) { lim.min = a; lim.max = b; rng.min = a; rng.max = b; },
      setGrad(g) { rng.style.background = g; },
      update() {
        const v = get();
        if (document.activeElement !== txt) txt.value = fmt(v);
        rng.value = v;
      },
    };
    ctl.setRange(min, max);
    return ctl;
  }

  // 可选颜色
  const dotsEl = $("#dots");
  RANGES.forEach((r, i) => {
    const b = document.createElement("button");
    b.className = "dot";
    b.style.background = r.color;
    b.title = r.name;
    b.onclick = () => { S.range = i; updatePanel(); };
    dotsEl.appendChild(b);
  });
  const dotName = document.createElement("div");
  dotName.className = "dot-name";
  dotsEl.after(dotName);
  const scRows = INKS.map((ink, c) => {
    const r = makeSlider($("#sliders"), {
      label: ink.name, min: -100, max: 100, unit: "%",
      get: () => S.colors[S.range][c], set: (v) => { S.colors[S.range][c] = v; },
    });
    r.setGrad(ink.grad);
    return r;
  });
  document.querySelectorAll("input[name=method]").forEach((r) =>
    r.addEventListener("change", () => { S.absolute = r.value === "abs" && r.checked; settingsChanged(false); }));

  // 色相/饱和度
  const hsChSel = $("#hsCh");
  HS_CH.forEach((c, i) => {
    const o = document.createElement("option");
    o.value = i;
    hsChSel.appendChild(o);
  });
  hsChSel.addEventListener("change", () => { S.hsCh = +hsChSel.value; hsChSel.blur(); updatePanel(); saveLocal(); });
  const hsVals = () => (S.hs.colorize ? S.hs.cz : S.hsCh === 0 ? S.hs.master : S.hs.ranges[S.hsCh - 1]);
  const hsRows = ["色相", "饱和度", "明度"].map((label, k) => makeSlider($("#hsSliders"), {
    label, min: -100, max: 100, get: () => hsVals()[k], set: (v) => { hsVals()[k] = v; },
  }));
  $("#hsColorize").addEventListener("change", (e) => {
    S.hs.colorize = e.target.checked;
    updatePanel();
    settingsChanged(false);
  });
  const hueGrad = (from, to) => {
    const stops = [];
    for (let k = 0; k <= 6; k++) stops.push(`hsl(${from + ((to - from) * k) / 6},100%,50%)`);
    return `linear-gradient(90deg,${stops.join(",")})`;
  };
  const hsModified = (i) => (i === 0 ? S.hs.master : S.hs.ranges[i - 1]).some((v) => v);

  const W_BAR = 360;
  const barCtx = ["#hueBarA", "#hueBarW", "#hueBarB"].map((s) => $(s).getContext("2d"));
  function drawHueBars() {
    const a = new Uint8ClampedArray(W_BAR * 4);
    const tmp = [0, 0, 0];
    for (let x = 0; x < W_BAR; x++) {
      const h = x - 180;
      const c = hslRGB(h, tmp);
      a.set([c[0], c[1], c[2], 255], x * 4);
    }
    const b = AD.applyHS(a.slice(), S.hs);
    barCtx[0].putImageData(new ImageData(a, W_BAR, 1), 0, 0);
    barCtx[2].putImageData(new ImageData(b, W_BAR, 1), 0, 0);
    const showW = !S.hs.colorize && S.hsCh > 0;
    $("#hueBarW").hidden = !showW;
    if (showW) {
      const w = new Uint8ClampedArray(W_BAR * 4);
      for (let x = 0; x < W_BAR; x++) {
        const g = 60 + 195 * AD.rangeWeight((x - 180 + 360) % 360, AD.HUE_RANGES[S.hsCh - 1]);
        w.set([g, g, g, 255], x * 4);
      }
      barCtx[1].putImageData(new ImageData(w, W_BAR, 1), 0, 0);
    }
  }
  function hslRGB(h, out) {
    const f = (n) => { const k = (n + h / 30 + 12) % 12; return 255 * (0.5 - 0.5 * Math.max(-1, Math.min(k - 3, 9 - k, 1))); };
    out[0] = Math.round(f(0)); out[1] = Math.round(f(8)); out[2] = Math.round(f(4));
    return out;
  }

  // 自然饱和度
  const vibRows = ["自然饱和度", "饱和度"].map((label, k) => makeSlider($("#vibSliders"), {
    label, min: -100, max: 100, get: () => S.vib[k], set: (v) => { S.vib[k] = v; },
  }));
  vibRows[0].setGrad("linear-gradient(90deg,#8a8a8a,#d9b26a 50%,#ff9a3c)");
  vibRows[1].setGrad("linear-gradient(90deg,#8a8a8a,#ff2a2a)");

  // 分页
  const tabsEl = $("#tabs");
  tabsEl.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b) setTab(b.dataset.v);
  });
  function setTab(t) {
    S.tab = t;
    tabsEl.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.v === t));
    ["sc", "hs", "vib"].forEach((k) => { $(`#tab-${k}`).hidden = k !== t; });
    updateResetLabel();
    saveLocal();
  }
  function updateResetLabel() {
    const label = S.tab === "sc" ? "复位此颜色"
      : S.tab === "vib" ? "复位此项"
      : S.hs.colorize ? "复位着色" : S.hsCh ? "复位此颜色" : "复位全局颜色";
    $("#btnResetColor").textContent = label;
  }
  $("#btnResetColor").onclick = () => {
    if (S.tab === "sc") S.colors[S.range] = [0, 0, 0, 0];
    else if (S.tab === "vib") S.vib = [0, 0];
    else if (S.hs.colorize) S.hs.cz = [0, 25, 0];
    else if (S.hsCh) S.hs.ranges[S.hsCh - 1] = [0, 0, 0];
    else S.hs.master = [0, 0, 0];
    updatePanel();
    settingsChanged(false);
  };
  $("#btnResetAll").onclick = () => { applySettings(defaults()); };
  $("#optPreview").addEventListener("change", (e) => { S.preview = e.target.checked; settingsChanged(false, true); });

  function updateMarks() {
    [...dotsEl.children].forEach((d, i) => {
      d.classList.toggle("sel", i === S.range);
      d.classList.toggle("mod", S.colors[i].some((x) => x !== 0));
    });
    HS_CH.forEach((c, i) => { hsChSel.options[i].textContent = c.name + (hsModified(i) ? "  ●" : ""); });
    const mod = { sc: !SC.isIdentity(S.colors), hs: !AD.hsIdentity(S.hs), vib: S.vib.some((v) => v) };
    tabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("mod", mod[b.dataset.v]));
  }
  function updatePanel() {
    updateMarks();
    dotName.textContent = RANGES[S.range].name;
    scRows.forEach((r) => r.update());
    document.querySelector(`input[name=method][value=${S.absolute ? "abs" : "rel"}]`).checked = true;

    const cz = S.hs.colorize;
    hsChSel.disabled = cz;
    hsChSel.value = cz ? 0 : S.hsCh;
    $("#hsColorize").checked = cz;
    const lim = cz ? [[0, 360], [0, 100], [-100, 100]] : [[-180, 180], [-100, 100], [-100, 100]];
    const base = cz ? S.hs.cz[0] : [0, 0, 60, 120, 180, 240, 300][S.hsCh];
    hsRows.forEach((r, k) => { r.setRange(...lim[k]); r.update(); });
    hsRows[0].setGrad(cz ? hueGrad(0, 360) : hueGrad(base - 180, base + 180));
    hsRows[1].setGrad(`linear-gradient(90deg,#808080,hsl(${base},100%,50%))`);
    hsRows[2].setGrad("linear-gradient(90deg,#000,#808080,#fff)");
    drawHueBars();

    vibRows.forEach((r) => r.update());
    $("#optPreview").checked = S.preview;
    updateResetLabel();
    syncPresetSel();
    updateSummary();
  }
  function updateSummary() {
    const lines = [];
    const sc = [];
    S.colors.forEach((row, i) => {
      if (!row.some((x) => x)) return;
      sc.push(`${RANGES[i].name}（${row.map((v, c) => (v ? INKS[c].short + sg(v) : "")).filter(Boolean).join(" ")}）`);
    });
    if (sc.length) lines.push(`可选颜色：${sc.join("、")} · ${S.absolute ? "绝对" : "相对"}`);
    const hsTxt = (v) => ["色相", "饱和度", "明度"].map((n, k) => (v[k] ? n + sg(v[k]) : "")).filter(Boolean).join(" ");
    if (S.hs.colorize) lines.push(`色相/饱和度：着色（色相 ${S.hs.cz[0]} 饱和度 ${S.hs.cz[1]} 明度 ${sg(S.hs.cz[2])}）`);
    else {
      const hs = HS_CH.map((c, i) => (hsModified(i) ? `${i ? c.name : "全局"}（${hsTxt(i ? S.hs.ranges[i - 1] : S.hs.master)}）` : "")).filter(Boolean);
      if (hs.length) lines.push(`色相/饱和度：${hs.join("、")}`);
    }
    if (S.vib.some((v) => v)) lines.push(`自然饱和度：${["自然饱和度", "饱和度"].map((n, k) => (S.vib[k] ? n + sg(S.vib[k]) : "")).filter(Boolean).join(" ")}`);
    if (lines.length > 1) lines.push("处理顺序：可选颜色 → 色相/饱和度 → 自然饱和度");
    $("#summary").textContent = lines.length ? lines.join("\n") : "还没有任何调整";
  }

  function settingsChanged(live, previewOnly) {
    updateMarks();
    if (!previewOnly) {
      if (S.tab === "hs") drawHueBars();
      syncPresetSel();
      updateSummary();
      saveLocal();
    }
    if (S.srcMode === "result") setSrcMode("live");
    scheduleRender(live);
    scheduleThumbs();
  }

  // ---------- 预设 ----------
  const presetSel = $("#presetSel");
  const canon = (s) => JSON.stringify([s.colors, !!s.absolute, s.hs.master, s.hs.ranges, !!s.hs.colorize,
    s.hs.colorize ? s.hs.cz : null, s.vib]);
  function applySettings(s) {
    const copy = JSON.parse(JSON.stringify(s));
    S.colors = copy.colors;
    S.absolute = !!copy.absolute;
    S.hs = copy.hs;
    S.vib = copy.vib;
    updatePanel();
    settingsChanged(false);
  }
  function syncPresetSel() {
    let value = "__custom";
    if (AD.isIdentity(settings())) value = "__default";
    else {
      const cur = canon(settings());
      const hit = S.presets.find((p) => canon(p.settings) === cur);
      if (hit) value = "p:" + hit.name;
    }
    presetSel.innerHTML = "";
    const add = (v, label) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = label;
      presetSel.appendChild(o);
    };
    add("__default", "默认设置");
    S.presets.forEach((p) => add("p:" + p.name, p.name));
    if (value === "__custom") add("__custom", "自定");
    presetSel.value = value;
  }
  presetSel.addEventListener("change", () => {
    const v = presetSel.value;
    presetSel.blur();
    if (v === "__default") applySettings(defaults());
    else if (v.startsWith("p:")) {
      const p = S.presets.find((x) => "p:" + x.name === v);
      if (p) applySettings(p.settings);
    }
  });
  async function refreshPresets() {
    try { S.presets = await api("/api/presets"); } catch (e) { S.presets = []; }
    syncPresetSel();
  }
  const menu = $("#presetMenu");
  $("#presetMenuBtn").onclick = (e) => {
    const r = e.target.getBoundingClientRect();
    menu.style.left = `${r.right - 240}px`;
    menu.style.top = `${r.bottom + 4}px`;
    menu.hidden = !menu.hidden;
    e.stopPropagation();
  };
  document.addEventListener("click", (e) => {
    menu.hidden = true;
    const b = e.target.closest && e.target.closest("button");
    if (b) b.blur();
  });
  menu.addEventListener("click", async (e) => {
    const act = e.target.dataset.act;
    if (!act) return;
    menu.hidden = true;
    try {
      if (act === "save") {
        const curName = presetSel.value.startsWith("p:") ? presetSel.value.slice(2) : "";
        const name = prompt("预设名称（同名会覆盖之前存的）。三种调整会一起存进这个预设", curName || "我的调色");
        if (!name || !name.trim()) return;
        S.presets = await api("/api/presets", { name: name.trim(), settings: settings() });
        syncPresetSel();
        toast(`已存储预设「${name.trim()}」`);
      } else if (act === "delete") {
        if (!presetSel.value.startsWith("p:")) return toast("当前不是已存储的预设");
        const name = presetSel.value.slice(2);
        if (!confirm(`删除预设「${name}」？（只删除预设，不影响任何图片）`)) return;
        S.presets = await api("/api/presets/delete", { name });
        syncPresetSel();
        toast("已删除");
      } else if (act === "import") {
        $("#asvInput").click();
      } else if (act === "export") {
        if (SC.isIdentity(S.colors)) return toast("「可选颜色」还没有调整，没有可导出的内容");
        const name = presetSel.value.startsWith("p:") ? presetSel.value.slice(2) : "可选颜色预设";
        const blob = new Blob([SC.buildASV(S.colors, S.absolute)], { type: "application/octet-stream" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${name}.asv`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        const only = AD.hsIdentity(S.hs) && !S.vib.some((v) => v) ? "" : "（.asv 只包含「可选颜色」部分）";
        toast(`已导出到「下载」文件夹${only}，可在 PS 可选颜色的预设菜单里「载入预设」`, 5000);
      }
    } catch (err) { fail(err); }
  });
  $("#asvInput").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const p = SC.parseASV(await f.arrayBuffer());
      S.colors = p.colors;
      S.absolute = p.absolute;
      setTab("sc");
      updatePanel();
      settingsChanged(false);
      toast(`已把「${f.name}」载入到「可选颜色」。想以后直接选，点 ☰ → 存储预设`, 4000);
    } catch (err) { fail(err); }
  });

  // ---------- 预览渲染 ----------
  const cvB = $("#cvBefore"), cvA = $("#cvAfter");
  const ctxB = cvB.getContext("2d", { willReadFrequently: true });
  const ctxA = cvA.getContext("2d");
  let orig = null, small = null, lastFullMs = 0, renderQueued = false, renderLive = false, loadToken = 0;

  function scheduleRender(live) {
    renderLive = live;
    if (!renderQueued) {
      renderQueued = true;
      requestAnimationFrame(doRender);
    }
  }
  function doRender() {
    renderQueued = false;
    if (!orig || S.srcMode === "result") return;
    if (!S.preview || AD.isIdentity(settings())) {
      ctxA.putImageData(orig, 0, 0);
      return;
    }
    if (renderLive && small && lastFullMs > 45) {
      AD.applyAll(small.src.data, small.out.data, settings());
      small.ctx.putImageData(small.out, 0, 0);
      ctxA.imageSmoothingQuality = "high";
      ctxA.drawImage(small.canvas, 0, 0, cvA.width, cvA.height);
      return;
    }
    const out = ctxA.createImageData(orig.width, orig.height);
    const t0 = performance.now();
    AD.applyAll(orig.data, out.data, settings());
    lastFullMs = performance.now() - t0;
    ctxA.putImageData(out, 0, 0);
  }

  async function showItem(i) {
    if (i < 0 || i >= S.items.length) return;
    S.idx = i;
    const it = S.items[i];
    thumbEls.forEach((t, k) => t.el.classList.toggle("sel", k === i));
    thumbEls[i] && thumbEls[i].el.scrollIntoView({ block: "nearest" });
    const token = ++loadToken;
    $("#loading").hidden = false;
    $("#imgInfo").textContent = it.rel;
    try {
      const img = await loadImg(u("/api/preview", { id: it.id, max: 1800 }));
      if (token !== loadToken) return;
      cvB.width = cvA.width = img.naturalWidth;
      cvB.height = cvA.height = img.naturalHeight;
      ctxB.clearRect(0, 0, cvB.width, cvB.height);
      ctxB.drawImage(img, 0, 0);
      orig = ctxB.getImageData(0, 0, cvB.width, cvB.height);
      const k = Math.min(1, 800 / Math.max(img.naturalWidth, img.naturalHeight));
      const sw = Math.max(1, Math.round(img.naturalWidth * k)), sh = Math.max(1, Math.round(img.naturalHeight * k));
      const sc = document.createElement("canvas");
      sc.width = sw; sc.height = sh;
      const sctx = sc.getContext("2d", { willReadFrequently: true });
      sctx.drawImage(img, 0, 0, sw, sh);
      small = { canvas: sc, ctx: sctx, src: sctx.getImageData(0, 0, sw, sh), out: sctx.createImageData(sw, sh) };
      $("#empty").hidden = true;
      $("#canvasWrap").hidden = false;
      layout();
      updateSrcButtons();
      if (S.srcMode === "result" && S.resultJob[it.id]) await loadResult();
      else { setSrcMode("live", true); doRender(); }
      api(u("/api/info", { id: it.id })).then((info) => {
        if (token !== loadToken) return;
        const extra = [];
        if (info.icc) extra.push("带色彩配置");
        if (info.bits) extra.push(`${info.bits} 位`);
        if (info.mode !== "RGB" && info.mode !== "RGBA") extra.push(`${info.mode} 模式`);
        $("#imgInfo").textContent = `${i + 1}/${S.items.length} · ${it.rel} · ${info.width}×${info.height} · ${info.format}${extra.length ? " · " + extra.join(" · ") : ""}`;
      }).catch(() => {});
    } catch (e) {
      if (token === loadToken) fail(e);
    } finally {
      if (token === loadToken) $("#loading").hidden = true;
    }
  }

  async function loadResult() {
    const it = S.items[S.idx];
    const jid = S.resultJob[it.id];
    if (!jid) return;
    const token = loadToken;
    const img = await loadImg(u("/api/result-preview", { job: jid, id: it.id, max: 1800 }));
    if (token !== loadToken) return;
    ctxA.clearRect(0, 0, cvA.width, cvA.height);
    ctxA.drawImage(img, 0, 0, cvA.width, cvA.height);
  }

  // ---------- 对比查看 ----------
  const wrap = $("#canvasWrap"), paneB = $("#paneBefore"), paneA = $("#paneAfter"), splitter = $("#splitter");
  function place(el, x, y, w, h) {
    Object.assign(el.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
  }
  function layout() {
    if (!orig) return;
    const W = wrap.clientWidth, H = wrap.clientHeight, iw = orig.width, ih = orig.height;
    const mode = S.peek ? "single" : S.viewMode;
    wrap.classList.toggle("split", mode === "split");
    wrap.classList.toggle("after-only", mode === "after");
    wrap.classList.toggle("peek", S.peek);
    paneA.style.clipPath = "none";
    if (mode === "side") {
      const gap = 12, pw = (W - gap) / 2;
      const s = Math.min(pw / iw, H / ih, 1);
      const w = iw * s, h = ih * s, top = (H - h) / 2;
      place(paneB, (pw - w) / 2, top, w, h);
      place(paneA, pw + gap + (pw - w) / 2, top, w, h);
      return;
    }
    const s = Math.min(W / iw, H / ih, 1);
    const w = iw * s, h = ih * s, x = (W - w) / 2, y = (H - h) / 2;
    place(paneB, x, y, w, h);
    place(paneA, x, y, w, h);
    if (mode === "split") {
      paneA.style.clipPath = `inset(0 0 0 ${S.split * 100}%)`;
      place(splitter, x + w * S.split - 1, y, 2, h);
    }
  }
  window.addEventListener("resize", layout);
  wrap.addEventListener("pointerdown", (e) => {
    if (S.viewMode !== "split" || S.peek) return;
    const move = (ev) => {
      const r = paneB.getBoundingClientRect();
      S.split = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      layout();
    };
    move(e);
    wrap.setPointerCapture(e.pointerId);
    wrap.onpointermove = move;
    wrap.onpointerup = () => { wrap.onpointermove = null; };
  });
  function segment(el, key, onChange) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      S[key] = b.dataset.v;
      el.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      onChange && onChange();
    });
  }
  segment($("#viewMode"), "viewMode", layout);
  segment($("#thumbMode"), "thumbMode", () => { settingsVer++; runThumbs(); });
  $("#srcMode").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && !b.disabled) setSrcMode(b.dataset.v);
  });
  function setSrcMode(mode, silent) {
    S.srcMode = mode;
    $("#srcMode").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.v === mode));
    $("#tagAfter").textContent = mode === "result" ? "导出文件" : "调整后";
    if (silent) return;
    if (mode === "result") loadResult().catch(fail);
    else scheduleRender(false);
  }
  function updateSrcButtons() {
    const it = S.items[S.idx];
    const btn = $("#srcMode").querySelector("[data-v=result]");
    btn.disabled = !(it && S.resultJob[it.id]);
    if (btn.disabled && S.srcMode === "result") setSrcMode("live", true);
  }

  document.addEventListener("keydown", (e) => {
    if (e.altKey && e.code === "KeyP") {
      e.preventDefault();
      S.preview = !S.preview;
      $("#optPreview").checked = S.preview;
      settingsChanged(false, true);
      return;
    }
    if (isTyping(e.target) && e.target.type !== "checkbox" && e.target.type !== "radio") return;
    if (e.code === "Space") {
      e.preventDefault();
      if (!S.peek) { S.peek = true; layout(); }
    } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      showItem(Math.min(S.items.length - 1, S.idx + 1));
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      showItem(Math.max(0, S.idx - 1));
    }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && S.peek) { S.peek = false; layout(); }
  });
  window.addEventListener("blur", () => { if (S.peek) { S.peek = false; layout(); } });

  // ---------- 缩略图 ----------
  const THUMB = 240;
  let thumbEls = [], settingsVer = 0, thumbTimer;
  const thumbsEl = $("#thumbs");
  const io = new IntersectionObserver((ents) => {
    for (const en of ents) {
      if (!en.isIntersecting) continue;
      io.unobserve(en.target);
      loadThumb(+en.target.dataset.i);
    }
  }, { root: thumbsEl, rootMargin: "400px" });

  function buildThumbs() {
    io.disconnect();
    thumbsEl.innerHTML = "";
    thumbEls = S.items.map((it, i) => {
      const el = document.createElement("div");
      el.className = "thumb";
      el.dataset.i = i;
      el.title = it.rel;
      el.innerHTML = `<canvas width="${THUMB}" height="${THUMB}"></canvas><div class="nm"></div><span class="badge" hidden></span>`;
      el.querySelector(".nm").textContent = it.name;
      el.onclick = () => showItem(i);
      const t = { el, cv: el.querySelector("canvas"), badge: el.querySelector(".badge"), orig: null, x: 0, y: 0, ver: -1 };
      el.addEventListener("mouseenter", () => { if (t.orig) t.cv.getContext("2d").putImageData(t.orig, t.x, t.y); });
      el.addEventListener("mouseleave", () => renderThumb(t));
      thumbsEl.appendChild(el);
      io.observe(el);
      updateBadge(i, t);
      return t;
    });
    $("#countText").textContent = `${S.items.length} 张`;
  }
  async function loadThumb(i) {
    const t = thumbEls[i], it = S.items[i];
    if (!t || !it) return;
    try {
      const img = await loadImg(u("/api/thumb", { id: it.id }));
      if (thumbEls[i] !== t) return;
      const k = Math.min(THUMB / img.naturalWidth, THUMB / img.naturalHeight, 1);
      const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
      t.x = Math.floor((THUMB - w) / 2);
      t.y = Math.floor((THUMB - h) / 2);
      const ctx = t.cv.getContext("2d", { willReadFrequently: true });
      ctx.clearRect(0, 0, THUMB, THUMB);
      ctx.drawImage(img, t.x, t.y, w, h);
      t.orig = ctx.getImageData(t.x, t.y, w, h);
      renderThumb(t);
    } catch (e) {
      t.el.querySelector(".nm").textContent = "⚠️ " + it.name;
    }
  }
  function renderThumb(t) {
    if (!t.orig) return;
    const ctx = t.cv.getContext("2d");
    if (S.thumbMode === "before" || !S.preview || AD.isIdentity(settings())) ctx.putImageData(t.orig, t.x, t.y);
    else {
      const out = ctx.createImageData(t.orig.width, t.orig.height);
      AD.applyAll(t.orig.data, out.data, settings());
      ctx.putImageData(out, t.x, t.y);
    }
    t.ver = settingsVer;
  }
  function scheduleThumbs() {
    settingsVer++;
    clearTimeout(thumbTimer);
    thumbTimer = setTimeout(runThumbs, 200);
  }
  function runThumbs() {
    const ver = settingsVer;
    let i = 0;
    const step = () => {
      if (ver !== settingsVer) return;
      const t0 = performance.now();
      while (i < thumbEls.length && performance.now() - t0 < 14) {
        const t = thumbEls[i++];
        if (t.orig && t.ver !== ver) renderThumb(t);
      }
      if (i < thumbEls.length) requestAnimationFrame(step);
    };
    step();
  }
  function updateBadge(i, t) {
    t = t || thumbEls[i];
    const it = S.items[i];
    const r = it && S.results[it.id];
    if (!t) return;
    if (!r) { t.badge.hidden = true; return; }
    t.badge.hidden = false;
    if (r.status === "ok") {
      t.badge.className = "badge " + (r.warnings && r.warnings.length ? "warn" : "ok");
      t.badge.textContent = "✓";
      t.badge.title = r.warnings && r.warnings.length ? r.warnings.join("；") : "已导出";
    } else {
      t.badge.className = "badge bad";
      t.badge.textContent = r.status === "skipped" ? "跳过" : r.status === "stopped" ? "未做" : "✗";
      t.badge.title = r.message || "";
    }
  }

  // ---------- 载入图片 ----------
  async function loadPaths(paths) {
    paths = paths.map((p) => p.trim()).filter(Boolean);
    if (!paths.length) return;
    toast("正在读取图片列表…", 60000);
    try {
      const append = $("#optAppend").checked;
      const r = await api("/api/load", { paths, recursive: $("#optRecursive").checked, append });
      const keepIdx = append && S.idx >= 0 ? S.idx : 0;
      S.items = r.items;
      if (!append) { S.results = {}; S.resultJob = {}; }
      buildThumbs();
      const roots = r.roots;
      const desc = roots.length === 1
        ? `${roots[0].kind === "folder" ? "文件夹" : "图片"}：${roots[0].path}`
        : `${roots.length} 个来源`;
      $("#libInfo").textContent = `${desc} · 共 ${S.items.length} 张`;
      $("#libInfo").title = roots.map((x) => `${x.path}（${x.count} 张）`).join("\n");
      const skipped = Object.entries(r.unsupported || {}).map(([ext, n]) => `${ext} ${n} 个`).join("、");
      const skipTxt = skipped ? `；另有不支持的文件已忽略：${skipped}` : "";
      if (r.missing.length) toast(`有 ${r.missing.length} 个路径不存在或不是支持的图片：${r.missing.slice(0, 2).join("、")}${skipTxt}`, 7000);
      else if (!S.items.length) toast(`没有找到图片（支持 jpg / png / tif / webp / bmp）${skipTxt}。图片在子文件夹里的话，勾选「包含子文件夹」再选一次`, 7000);
      else toast(`已载入 ${S.items.length} 张${skipTxt}`, skipTxt ? 7000 : 2600);
      if (S.items.length) showItem(Math.min(keepIdx, S.items.length - 1));
      else { orig = null; $("#canvasWrap").hidden = true; $("#empty").hidden = false; }
    } catch (e) { fail(e); }
  }
  async function pick(kind) {
    try {
      const r = await api("/api/pick", { kind });
      if (r.paths.length) loadPaths(r.paths);
    } catch (e) { fail(e); }
  }
  $("#btnFolders").onclick = () => pick("folders");
  $("#btnFiles").onclick = () => pick("files");
  $("#btnPaste").onclick = () => { $("#modal").hidden = false; $("#pasteArea").focus(); };
  $("#pasteCancel").onclick = () => { $("#modal").hidden = true; };
  $("#pasteOk").onclick = () => {
    $("#modal").hidden = true;
    loadPaths($("#pasteArea").value.split(/\r?\n/));
  };
  $("#btnClear").onclick = async () => {
    if (!S.items.length) return;
    if (!confirm("清空左侧列表？（只是清空列表，不会删除任何文件）")) return;
    await api("/api/clear", {}).catch(fail);
    S.items = []; S.results = {}; S.resultJob = {}; S.idx = -1; orig = null;
    buildThumbs();
    $("#canvasWrap").hidden = true; $("#empty").hidden = false;
    $("#libInfo").textContent = "还没有载入图片";
    $("#imgInfo").textContent = "";
  };
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    toast("浏览器拿不到拖进来的文件路径。请点「选择文件夹 / 选择图片」，或在访达里选中后按 ⌥⌘C 复制路径，再点「粘贴路径」", 7000);
  });

  // ---------- 导出 ----------
  function showOutDir() {
    $("#outDir").textContent = S.outDir || "自动：在原文件夹旁边新建「原文件夹名_调色_时间」";
  }
  $("#btnOutPick").onclick = async () => {
    try {
      const r = await api("/api/pick", { kind: "outdir" });
      if (r.paths.length) { S.outDir = r.paths[0].replace(/\/$/, ""); showOutDir(); saveLocal(); }
    } catch (e) { fail(e); }
  };
  $("#btnOutAuto").onclick = () => { S.outDir = ""; showOutDir(); saveLocal(); };

  async function startExport(kind) {
    if (!S.items.length) return toast("先载入图片");
    if (S.job && (S.job.state === "running" || S.job.state === "preparing")) return toast("正在导出，请等这一批完成或点「停止」");
    const sample = kind === "sample";
    const ids = kind === "current" ? [S.items[S.idx].id] : null;
    const n = kind === "current" ? 1 : sample ? Math.min(5, S.items.length) : S.items.length;
    try {
      const out = S.outDir || (await api("/api/default-out", { sample })).path;
      const msgs = [`将导出 ${n} 张到：\n${out}`, "原图不会被修改；同名文件不会被覆盖（自动加 _1、_2）。"];
      if (AD.isIdentity(settings())) msgs.unshift("⚠️ 当前没有任何调整，导出的图颜色和原图一样。");
      if (!confirm(msgs.join("\n\n"))) return;
      const r = await api("/api/export", {
        ...settings(), ids, sample, out_dir: out,
        format: $("#optFormat").value, quality: +$("#optQuality").value || 95, compare: $("#optCompare").checked,
      });
      S.job = { id: r.job, out_dir: r.out_dir, total: r.total, since: 0, state: "running" };
      $("#errors").innerHTML = "";
      $("#progress").hidden = false;
      $("#btnStop").hidden = false;
      $("#progress .bar i").style.width = "0";
      $("#progText").textContent = `准备中… 共 ${r.total} 张`;
      poll();
    } catch (e) { fail(e); }
  }
  async function poll() {
    const j = S.job;
    let r;
    try {
      r = await api(u("/api/job", { id: j.id, since: j.since }));
    } catch (e) {
      fail(e);
      setTimeout(poll, 2000);
      return;
    }
    j.since += r.results.length;
    j.state = r.state;
    for (const res of r.results) {
      S.results[res.id] = res;
      if (res.out) S.resultJob[res.id] = j.id;
      const i = S.items.findIndex((x) => x.id === res.id);
      if (i >= 0) updateBadge(i);
      if (res.status === "failed" || res.status === "skipped") addLine("e", `${res.name}：${res.message}`);
      else if (res.warnings && res.warnings.length) addLine("w", `${res.name}：${res.warnings.join("；")}`);
    }
    updateSrcButtons();
    $("#progress .bar i").style.width = `${(r.processed / r.total) * 100}%`;
    const failTxt = r.failed ? ` · 失败/跳过 ${r.failed}` : "";
    if (r.state === "preparing") {
      $("#progText").textContent = `正在准备调色表（约 5～15 秒，之后每张都很快）… 共 ${r.total} 张`;
      setTimeout(poll, 400);
      return;
    }
    if (r.state === "running") {
      $("#progText").textContent = `已完成 ${r.processed} / ${r.total}${failTxt} · 预计剩余 ${fmtSec(r.eta)}`;
      setTimeout(poll, 600);
      return;
    }
    $("#btnStop").hidden = true;
    if (r.error) addLine("e", `导出中断：${r.error}`);
    const head = r.error ? "导出中断" : r.state === "stopped" ? "已停止" : "全部完成";
    $("#progText").textContent = `${head}：成功 ${r.done} 张${failTxt} · 用时 ${fmtSec(r.elapsed)} · 处理记录已写入「处理记录.json」`;
    toast(`${head}：成功 ${r.done} 张。点上方「导出文件」可对比真实导出结果`, 5000);
    const it = S.items[S.idx];
    if (it && S.resultJob[it.id]) setSrcMode("result");
  }
  function addLine(cls, text) {
    const d = document.createElement("div");
    d.className = cls;
    d.textContent = text;
    $("#errors").appendChild(d);
  }
  $("#btnSample").onclick = () => startExport("sample");
  $("#btnCurrent").onclick = () => startExport("current");
  $("#btnAll").onclick = () => startExport("all");
  $("#btnStop").onclick = () => S.job && api("/api/job/stop", { id: S.job.id }).then(() => toast("正在停止，已经开始的几张会做完")).catch(fail);
  $("#btnOpenOut").onclick = () => S.job && api("/api/reveal", { path: S.job.out_dir }).catch(fail);

  // ---------- 本地记忆 ----------
  function saveLocal() {
    localStorage.setItem("sc_state", JSON.stringify({
      colors: S.colors, absolute: S.absolute, hs: S.hs, vib: S.vib, tab: S.tab, hsCh: S.hsCh, outDir: S.outDir,
      format: $("#optFormat").value, quality: $("#optQuality").value, compare: $("#optCompare").checked,
      recursive: $("#optRecursive").checked,
    }));
  }
  function loadLocal() {
    try {
      const s = JSON.parse(localStorage.getItem("sc_state") || "{}");
      if (Array.isArray(s.colors) && s.colors.length === 9) S.colors = s.colors;
      S.absolute = !!s.absolute;
      const triple = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
      const h = s.hs;
      if (h && triple(h.master) && Array.isArray(h.ranges) && h.ranges.length === 6 && h.ranges.every(triple) && triple(h.cz)) {
        S.hs = { master: h.master, ranges: h.ranges, colorize: !!h.colorize, cz: h.cz };
      }
      if (Array.isArray(s.vib) && s.vib.length === 2 && s.vib.every(Number.isFinite)) S.vib = s.vib;
      if (["sc", "hs", "vib"].includes(s.tab)) S.tab = s.tab;
      if (Number.isInteger(s.hsCh) && s.hsCh >= 0 && s.hsCh < 7) S.hsCh = s.hsCh;
      S.outDir = s.outDir || "";
      if (s.format) $("#optFormat").value = s.format;
      if (s.quality) $("#optQuality").value = s.quality;
      $("#optCompare").checked = !!s.compare;
      $("#optRecursive").checked = !!s.recursive;
    } catch (e) { /* 忽略损坏的本地记录 */ }
  }
  ["#optFormat", "#optQuality", "#optCompare", "#optRecursive"].forEach((s) => $(s).addEventListener("change", saveLocal));

  // ---------- 启动 ----------
  loadLocal();
  showOutDir();
  setTab(S.tab);
  updatePanel();
  refreshPresets();
  api("/api/items").then((r) => {
    if (!r.items.length) return;
    S.items = r.items;
    buildThumbs();
    $("#libInfo").textContent = `${r.roots.length === 1 ? r.roots[0].path : r.roots.length + " 个来源"} · 共 ${S.items.length} 张`;
    showItem(0);
  }).catch(() => {});
})();
