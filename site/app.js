// Board Boxes: draw color-coded boxes over a reference image, pattern them, export a placement prompt.
// Coordinates are KiCad board millimetres. Boxes store their CENTER (x, y) and size (w, h).
(function () {
  'use strict';
  const fetch = window.dashboardFetch;

  const PALETTE = ['#4ea1ff', '#ff6b6b', '#ffd166', '#06d6a0', '#c77dff', '#ff9f1c', '#f15bb5', '#9ef01a', '#00bbf9'];
  const DIRS = { right: [1, 0], down: [0, 1], left: [-1, 0], up: [0, -1] };
  const DIR_ARROW = { right: '→', down: '↓', left: '←', up: '↑' };

  // ---------- STATE ----------
  const S = {
    boardPath: '',
    board: null,             // from KiCad bridge: { bbox, edges, footprints }
    images: [],
    refImg: null,
    refBotImg: null,
    sideView: 'top',         // 'top' | 'bottom' | 'both'
    pointerSide: 'top',
    doc: emptyDoc(),
    view: { x: 0, y: 0, scale: 15 },
    showRef: true,
    show3D: false,
    showParts: true,
    explain: false,
    showGroups: true,
    showTopCu: false,
    showIn1Cu: false,
    showIn2Cu: false,
    showBotCu: false,
    showVias: false,
    showSides: false,
    selectMode: false,
    infoMode: false,
    superMode: false,
    padSel: null,
    padHover: null,
    hoverFp: null,
    infoFp: null,
    activePreset: null,
    mousePos: null,
    render3dImg: null,
    render3dBounds: null,   // the board's own rect inside render3dImg (pixels): parked parts and margins lie outside it
    render3dPath: null,
    render3dBotImg: null,    // render of the back (mirrored by the server so it lies on the board outline)
    render3dBotBounds: null,
    render3dBotPath: null,
    renderIsoPath: null,
    isoView: { x: 0, y: 0, scale: 1 },
    isoDrag: null,
    opacity: 0.75,
    snap: 0.05,
    activeColor: null,
    sel: null,               // { id, i }  (i = instance index inside the box's pattern)
    drag: null,
    pan: null,
    space: false,
    undo: [],
    redo: [],
  };

  function emptyDoc() {
    return { version: 1, ref: '', refBot: '', sideView: '', refFit: { ox: 0, oy: 0, sx: 100, sy: 100 }, colors: [], boxes: [] };
  }

  // ---------- DOM ----------
  const $ = id => document.getElementById(id);
  const canvas = $('canvas');
  const ctx = canvas.getContext('2d');
  const stage = $('stage');

  const uid = p => p + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
  const r2 = v => Math.round(v * 1000) / 1000;
  const fmt = v => (Math.round(v * 100) / 100).toFixed(2);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function toast(msg, type = 'info', ms = 3500) {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = msg;
    $('toasts').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateY(-6px)'; setTimeout(() => el.remove(), 300); }, ms);
  }

  // ---------- VIEW TRANSFORMS ----------
  // Both mode stacks two copies of the same board. S.view maps millimetres onto the
  // top pane; the bottom pane is the same transform shifted down by paneDy.
  let drawPane = 0;

  function resize() {
    const r = stage.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = r.width * dpr;
    canvas.height = r.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    render();
  }

  function paneGeom() {
    const r = stage.getBoundingClientRect();
    const n = S.sideView === 'both' ? 2 : 1;
    const gap = n > 1 ? 36 : 0;
    const h = (r.height - gap * (n - 1)) / n;
    const panes = [];
    for (let i = 0; i < n; i++) {
      const side = S.sideView === 'bottom' ? 'bot' : (S.sideView === 'both' && i === 1 ? 'bot' : 'top');
      panes.push({ i, side, top: i * (h + gap), height: h, width: r.width });
    }
    return panes;
  }
  function dockClearance(pane) {
    if (!pane || pane.i !== 0) return 0;
    const dock = stage.querySelector('.dock');
    if (!dock) return 0;
    const sr = stage.getBoundingClientRect();
    const dr = dock.getBoundingClientRect();
    return Math.max(0, dr.bottom - sr.top) + 8;
  }
  function paneContentBox(pane) {
    const clear = dockClearance(pane);
    const margin = 16;
    const top = pane.top + clear + margin;
    return { top, height: Math.max(36, pane.height - clear - margin * 2) };
  }
  function paneScreenDy(i) {
    const panes = paneGeom();
    const a = paneContentBox(panes[0]);
    const b = paneContentBox(panes[i] || panes[0]);
    return (b.top + b.height / 2) - (a.top + a.height / 2);
  }
  function paneAt(sy) {
    const panes = paneGeom();
    for (let i = panes.length - 1; i >= 0; i--) {
      if (sy >= panes[i].top) return i;
    }
    return 0;
  }
  const toScreen = (x, y) => ({
    x: (x - S.view.x) * S.view.scale,
    y: (y - S.view.y) * S.view.scale + paneScreenDy(drawPane),
  });
  const toBoard = (sx, sy) => {
    const dy = paneScreenDy(paneAt(sy));
    return { x: sx / S.view.scale + S.view.x, y: (sy - dy) / S.view.scale + S.view.y };
  };
  function mouseBoard(e) {
    const r = canvas.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    const panes = paneGeom();
    S.pointerSide = panes[paneAt(sy)]?.side || 'top';
    return toBoard(sx, sy);
  }
  const snap = v => (S.snap > 0 ? Math.round(v / S.snap) * S.snap : v);

  function fit() {
    const bb = S.board?.bbox;
    if (!bb) return;
    const r = stage.getBoundingClientRect();
    const panes = paneGeom();
    let bandH = Infinity;
    for (const p of panes) bandH = Math.min(bandH, paneContentBox(p).height);
    const padX = 36;
    // 0.62: leave room around the board on big monitors (was edge-to-edge).
    S.view.scale = 0.62 * Math.min((r.width - padX * 2) / Math.max(bb.w, 1), bandH / Math.max(bb.h, 1), 80);
    S.view.x = bb.x - (r.width / S.view.scale - bb.w) / 2;
    const box = paneContentBox(panes[0]);
    const boardScreenY = box.top + (box.height - bb.h * S.view.scale) / 2;
    S.view.y = bb.y - boardScreenY / S.view.scale;
    render();
  }


  // ---------- EXPLAIN (hover a part: what its group does) ----------
  const FP_GROUPS = [
    [/^U1$/, 'Monitor IC', 'ADBMS1818: measures 18 cells, runs balancing, talks isoSPI.'],
    [/^J[15]$/, 'Cell taps', 'Harness in: cell voltages C0–C9 (J1) and C9–C18 (J5).'],
    [/^J2$/, 'NTC header', '3 thermistors -> GPIO1–3 of U1.'],
    [/^R2\d\d$/, 'Balance resistors', '33 Ω 1 W. Bleed a high cell when U1 closes its S switch.'],
    [/^R1\d\d$/, 'Cell input filter R', '10 Ω, with C1nn forms the RC filter into U1 C pins.'],
    [/^C1\d\d$/, 'Cell input filter C', '100 nF across adjacent cells; RC filter with R1nn.'],
    [/^D1\d\d$/, 'Cell clamp zeners', '6.8 V per cell: protect U1 inputs from hot-plug spikes.'],
    [/^F1\d\d$/, 'Tap fuses', '250 mA per harness wire: a short on the board opens it.'],
    [/^D301$/, 'Stack TVS', 'SMAJ85A on the stack supply after F119. Eats harness transients.'],
    [/^(Q301|R30[12]|C30[12])$/, 'Stack supply', 'FZT853 + 100 Ω filters: stack -> U1 V+ and 5 V VREG regulator.'],
    [/^C30[345]$/, 'Reference caps', '1 µF on VREG, VREF1, VREF2.'],
    [/^R40[12]$/, 'isoSPI bias', '1 k + 1 k divider: sets isoSPI drive current and threshold.'],
    [/^(T501|R50\d|C50\d|J[36])$/, 'isoSPI A (IN)', 'From master / previous module. Transformer + split termination.'],
    [/^(T601|R60\d|C60\d|J[47])$/, 'isoSPI B (OUT)', 'To next module in daisy chain. Transformer + split termination.'],
    [/^(R70\d|C70\d|TH701)$/, 'NTC inputs', '100 k pull-ups to VREF2 + 100 nF filters on GPIO; TH701 board temp.'],
    [/^TP([1-9]|10)$/, 'Test points', 'Low-voltage probes: V−, VREG, VREF1/2, DRIVE, isoSPI lines. Loops on Guard, bare pads on the back on Lean.'],
    [/^TP1[1-4]$/, 'HV test pads', 'Bare pads: VCOLL, C6, C12, C18. No exposed loop at high voltage.'],
    [/^H\d$/, 'Mounting holes', 'M3, keep-out around them.'],
  ];
  function fpGroup(fp) {
    for (const g of FP_GROUPS) if (g[0].test(fp.ref)) return g;
    return null;
  }
  function showExplain(fp, e) {
    const tip = $('explainTip');
    if (!tip) return;
    if (!fp || !S.explain) { tip.hidden = true; return; }
    const g = fpGroup(fp);
    const n = g ? S.board.footprints.filter(f => g[0].test(f.ref)).length : 1;
    tip.innerHTML = '<b></b><span class="xt-ref"></span><div></div>';
    tip.children[0].textContent = g ? g[1] : fp.ref;
    tip.children[1].textContent = ' ' + fp.ref + ' · ' + fp.value + (n > 1 ? ' · ' + n + ' parts' : '');
    tip.children[2].textContent = g ? g[2] : (fp.fpid.split(':').pop());
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 16, y = e.clientY + 16;
    if (x + w > innerWidth - 8) x = e.clientX - w - 16;
    if (y + h > innerHeight - 8) y = e.clientY - h - 16;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }


  // Coloured outline around each function group (Explain > Groups).
  function drawGroupOutlines(pane) {
    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.font = '600 11px "JetBrains Mono"';
    const tags = [];
    FP_GROUPS.forEach((g, i) => {
      if (g[1] === 'Mounting holes') return; // spans the whole board
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const fp of S.board.footprints) {
        if (!g[0].test(fp.ref) || !fpOnSide(fp, pane.side)) continue;
        const b = getFpBBox(fp);
        x0 = Math.min(x0, b.minX); y0 = Math.min(y0, b.minY); x1 = Math.max(x1, b.maxX); y1 = Math.max(y1, b.maxY);
      }
      if (x0 === Infinity) return;
      const hot = S.hoverFp && g[0].test(S.hoverFp.ref);
      const col = `hsl(${(i * 137.5) % 360}, 85%, 62%)`;
      const a = toScreen(x0, y0), c = toScreen(x1, y1);
      const sx = Math.min(a.x, c.x) - 3, sy = Math.min(a.y, c.y) - 3, w = Math.abs(c.x - a.x) + 6, h = Math.abs(c.y - a.y) + 6;
      ctx.strokeStyle = col; ctx.globalAlpha = hot ? 1 : 0.7; ctx.lineWidth = hot ? 2.5 : 1.5;
      ctx.strokeRect(sx, sy, w, h);
      tags.push({ name: g[1], col, hot, sx, sy, w, h, cx: sx + w / 2, cy: sy + h / 2 });
    });
    // 1) Put each name in the nearest free spot by its box: touching it, then a little
    //    further out with a short leader. Free = no pad/part/silk ref, group box or name.
    const hits = (r, o) => r.x < o.x + o.w && r.x + r.w > o.x && r.y < o.y + o.h && r.y + r.h > o.y;
    const obst = [];
    const sc = S.view.scale, m = 1.3; // mm margin around parts covers their silk reference text
    for (const fp of S.board.footprints) {
      if (!fpOnSide(fp, pane.side)) continue;
      const b = getFpBBox(fp);
      const a = toScreen(b.minX - m, b.minY - m), c = toScreen(b.maxX + m, b.maxY + m);
      obst.push({ x: Math.min(a.x, c.x), y: Math.min(a.y, c.y), w: Math.abs(c.x - a.x), h: Math.abs(c.y - a.y) });
    }
    for (const tx of S.board.texts || []) {
      if ((tx.side === 'B') !== (pane.side === 'bot')) continue;
      const a = toScreen(tx.x - 0.5, tx.y - 0.5), c = toScreen(tx.x + tx.w + 0.5, tx.y + tx.h + 0.5);
      obst.push({ x: Math.min(a.x, c.x), y: Math.min(a.y, c.y), w: Math.abs(c.x - a.x), h: Math.abs(c.y - a.y) });
    }
    for (const k of tags) obst.push({ x: k.sx - 1, y: k.sy - 1, w: k.w + 2, h: k.h + 2 });
    const cw = canvas.clientWidth || canvas.width, chh = canvas.clientHeight || canvas.height;
    const TH = 14;
    for (const k of [...tags].sort((a, b) => b.w * b.h - a.w * a.h)) {
      const tw = ctx.measureText(k.name).width + 6;
      for (const d of [2, 12, 24, 40]) {
        const cands = [
          [k.sx, k.sy - d - TH], [k.sx + k.w - tw, k.sy - d - TH],
          [k.sx, k.sy + k.h + d], [k.sx + k.w - tw, k.sy + k.h + d],
          [k.sx - d - tw, k.cy - TH / 2], [k.sx + k.w + d, k.cy - TH / 2],
        ];
        for (const [x, y] of cands) {
          const r = { x, y, w: tw, h: TH };
          if (x < 0 || y < 0 || x + tw > cw || y + TH > chh) continue;
          if (obst.some(o => hits(r, o))) continue;
          k.place = r; obst.push(r); break;
        }
        if (k.place) break;
      }
      if (!k.place) continue;
      const r = k.place;
      ctx.globalAlpha = k.hot ? 1 : 0.85; ctx.strokeStyle = k.col; ctx.lineWidth = k.hot ? 2 : 1;
      // leader from the nearest point of the box to the nearest point of the label
      const px = Math.min(Math.max(r.x + r.w / 2, k.sx), k.sx + k.w), py = Math.min(Math.max(r.y + r.h / 2, k.sy), k.sy + k.h);
      const qx = Math.min(Math.max(px, r.x), r.x + r.w), qy = Math.min(Math.max(py, r.y), r.y + r.h);
      if (Math.hypot(qx - px, qy - py) > 4) { ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(qx, qy); ctx.stroke(); }
      ctx.fillStyle = 'rgba(10,14,18,.6)'; ctx.fillRect(r.x, r.y, r.w, r.h);
      ctx.fillStyle = k.col; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
      ctx.fillText(k.name, r.x + 3, r.y + TH / 2);
    }
    // 2) Whatever found no room goes to a column outside the board edge, spread so the
    //    names never overlap, with a dashed leader back to the group box.
    const bb = S.board.bbox;
    const tl = toScreen(bb.x, bb.y), br = toScreen(bb.x + bb.w, bb.y + bb.h);
    const midX = (tl.x + br.x) / 2, gap = 15;
    for (const side of ['L', 'R']) {
      const col = tags.filter(k => !k.place && (k.cx < midX) === (side === 'L')).sort((a, b) => a.cy - b.cy);
      // place at ideal y, push down to keep spacing, then pull back up if it ran off the bottom
      let y = -Infinity;
      for (const k of col) { k.ly = Math.max(k.cy, y + gap); y = k.ly; }
      let over = col.length ? col[col.length - 1].ly - (br.y + 20) : 0;
      for (let j = col.length - 1; j >= 0 && over > 0; j--) {
        const lim = j > 0 ? col[j].ly - col[j - 1].ly - gap : Infinity;
        col[j].ly -= over;
        for (let q = j + 1; q < col.length; q++) col[q].ly = Math.max(col[q].ly, col[q - 1].ly + gap);
        over = col[col.length - 1].ly - (br.y + 20);
        if (lim >= over) break;
      }
      for (const k of col) {
        const lx = side === 'L' ? tl.x - 14 : br.x + 14;
        const ax = side === 'L' ? k.sx : k.sx + k.w;
        const ay = Math.min(Math.max(k.ly, k.sy), k.sy + k.h);
        ctx.strokeStyle = k.col; ctx.globalAlpha = k.hot ? 1 : 0.75; ctx.lineWidth = k.hot ? 2 : 1;
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(lx, k.ly); ctx.stroke();
        ctx.fillStyle = k.col; ctx.textBaseline = 'middle';
        ctx.textAlign = side === 'L' ? 'right' : 'left';
        ctx.fillText(k.name, lx + (side === 'L' ? -4 : 4), k.ly);
      }
    }
    ctx.restore();
  }

  // ---------- DATA MODEL ----------
  const color = id => S.doc.colors.find(c => c.id === id);
  const box = id => S.doc.boxes.find(b => b.id === id);
  const colorIndex = id => S.doc.colors.findIndex(c => c.id === id);

  // All visible instances of a box (pattern copies are derived, so they stay linked to the box).
  function instances(b) {
    const p = b.pat;
    if (!p || p.n <= 1) return [{ id: b.id, i: 0, x: b.x, y: b.y, w: b.w, h: b.h, c: b.c }];
    const [dx, dy] = DIRS[p.dir] || DIRS.right;
    const out = [];
    for (let i = 0; i < p.n; i++) {
      if (p.skip && p.skip.includes(i)) continue;
      out.push({ id: b.id, i, x: b.x + dx * p.pitch * i, y: b.y + dy * p.pitch * i, w: b.w, h: b.h, c: b.c });
    }
    return out;
  }
  const allInstances = () => S.doc.boxes.flatMap(instances);
  function instanceOf(sel) {
    if (!sel) return null;
    const b = box(sel.id);
    if (!b) return null;
    return instances(b).find(it => it.i === sel.i) || instances(b)[0] || null;
  }
  function offsetOf(b, i) {
    if (!b.pat) return [0, 0];
    const [dx, dy] = DIRS[b.pat.dir] || DIRS.right;
    return [dx * b.pat.pitch * i, dy * b.pat.pitch * i];
  }
  const liveCount = b => instances(b).length;
  const totalCount = () => S.doc.boxes.reduce((n, b) => n + liveCount(b), 0);
  // Part label on a box: fixed (b.lbl) or counted along its pattern (b.tag = { p: 'R2', start: 18, step: -1 } -> R218, R217, …).
  function tagFor(b, i) {
    if (b.lbl) return b.lbl;
    if (!b.tag) return '';
    return b.tag.p + String(b.tag.start + b.tag.step * i).padStart(2, '0');
  }
  const keepTag = (b, i) => (tagFor(b, i) ? { lbl: tagFor(b, i), auto: b.auto } : {});

  function ensureColorExists() {
    // Keep at least one color group in the doc, but do not arm it for drawing.
    if (S.doc.colors.length) return S.doc.colors[0];
    const c = { id: uid('c'), hex: PALETTE[0], note: '' };
    S.doc.colors.push(c);
    return c;
  }

  function armColor(id, { toastMsg } = {}) {
    if (!color(id)) return false;
    S.activeColor = id;
    if (S.infoMode) toggleInfoMode(false);
    if (S.superMode) toggleSuperMode(false);
    if (toastMsg) toast(toastMsg);
    return true;
  }

  function disarmDraw() {
    S.activeColor = null;
    S.activePreset = null;
    updatePresetChipsUI();
  }

  function ensureArmedColor() {
    // Used when an action truly needs a color (Select mode, finishing a draw).
    ensureColorExists();
    if (!color(S.activeColor)) S.activeColor = S.doc.colors[0].id;
  }

  function addColor(commitIt = true) {
    const used = new Set(S.doc.colors.map(c => c.hex));
    const hex = PALETTE.find(p => !used.has(p)) || PALETTE[S.doc.colors.length % PALETTE.length];
    const c = { id: uid('c'), hex, note: '' };
    S.doc.colors.push(c);
    S.sel = null;
    armColor(c.id);
    if (commitIt) commit();
    else renderLegend();
    toast('Color armed — drag on the board to draw, or click a Quick Size to stamp');
    return c;
  }

  function breakOut(b, i) {
    // Detach instance i into its own standalone box; pattern keeps the rest in place.
    const it = instances(b).find(x => x.i === i);
    if (!it) return null;
    if (!b.pat || liveCount(b) <= 1) return b;
    b.pat.skip = [...(b.pat.skip || []), i];
    const nb = { id: uid('b'), c: b.c, x: it.x, y: it.y, w: b.w, h: b.h, pat: null, ...keepTag(b, i) };
    S.doc.boxes.push(nb);
    return nb;
  }

  function unlinkAll(b) {
    const its = instances(b);
    const idx = S.doc.boxes.indexOf(b);
    const fresh = its.map(it => ({ id: uid('b'), c: b.c, x: it.x, y: it.y, w: b.w, h: b.h, pat: null, ...keepTag(b, it.i) }));
    S.doc.boxes.splice(idx, 1, ...fresh);
    return fresh;
  }

  function removeInstance(b, i) {
    if (!b.pat || liveCount(b) <= 1) {
      S.doc.boxes = S.doc.boxes.filter(x => x !== b);
      return;
    }
    b.pat.skip = [...(b.pat.skip || []), i];
  }

  // ---------- HISTORY + PERSISTENCE ----------
  const snapshot = () => JSON.stringify({ colors: S.doc.colors, boxes: S.doc.boxes });
  let lastSnap = null;
  function commit() {
    const s = snapshot();
    if (s === lastSnap) return;
    if (lastSnap !== null) S.undo.push(lastSnap);
    if (S.undo.length > 100) S.undo.shift();
    S.redo = [];
    lastSnap = s;
    scheduleSave();
    refreshUI();
  }
  function restore(s) {
    const d = JSON.parse(s);
    S.doc.colors = d.colors;
    S.doc.boxes = d.boxes;
    lastSnap = s;
    if (S.sel && !instanceOf(S.sel)) S.sel = null;
    ensureColorExists();
    if (S.activeColor && !color(S.activeColor)) S.activeColor = null;
    scheduleSave();
    refreshUI();
  }
  function undo() {
    if (!S.undo.length) return;
    S.redo.push(lastSnap);
    restore(S.undo.pop());
    toast('Undo');
  }
  function redo() {
    if (!S.redo.length) return;
    S.undo.push(lastSnap);
    restore(S.redo.pop());
    toast('Redo');
  }

  function clearAllBoxes() {
    const n = S.doc.boxes.length;
    if (!n) return toast('No boxes or selections to clear', 'info');
    if (!confirm(`Are you sure you want to clear all ${n} box(es) and component selection(s)?`)) return;
    S.doc.boxes = [];
    S.sel = null;
    commit();
    toast(`Cleared all ${n} box(es). Press Undo to restore.`);
  }

  function toggleSelectMode() {
    S.selectMode = !S.selectMode;
    if (S.selectMode) {
      if (S.infoMode) toggleInfoMode(false);
      if (S.superMode) toggleSuperMode(false);
      if (!S.showParts) {
        S.showParts = true;
        if ($('tglParts')) $('tglParts').classList.add('active');
      }
      ensureArmedColor();
      toast('Select mode: click footprint parts on PCB to group them.');
    } else {
      S.hoverFp = null;
      toast('Select mode exited');
    }
    refreshUI();
  }

  function toggleInfoMode(forceState) {
    S.infoMode = forceState !== undefined ? forceState : !S.infoMode;
    if (S.infoMode) {
      if (S.superMode) toggleSuperMode(false);
      if (S.selectMode) {
        S.selectMode = false;
        if ($('btnSelectMode')) $('btnSelectMode').classList.remove('active');
      }
      // Info is inspect-only — don't leave a color armed for drawing underneath.
      disarmDraw();
      S.sel = null;
      if (!S.showParts) {
        S.showParts = true;
        if ($('tglParts')) $('tglParts').classList.add('active');
      }
      const card = $('partInfoCard');
      if (card) {
        card.classList.remove('hidden');
        if (!S.infoFp) {
          $('infoEmptyHint')?.classList.remove('hidden');
          $('infoBody')?.classList.add('hidden');
          $('infoRef').textContent = 'Select part';
        }
      }
      const eh = $('infoEmptyHint');
      if (eh) eh.textContent = 'Click any component on the board to view its info';
      toast('Info mode: click any component on PCB to view details.');
    } else {
      S.hoverFp = null;
      if ($('partInfoCard')) $('partInfoCard').classList.add('hidden');
      S.infoFp = null;
      toast('Info mode exited');
    }
    refreshUI();
  }

  // ---------- SUPER INFO (single pads) ----------
  function setBadge(text) {
    const b = document.querySelector('#partInfoCard .info-badge');
    if (b) b.textContent = text;
  }

  function superPadColor(pad) {
    if (S.padSel && pad === S.padSel.pad) return '#ffb347';
    if (S.padSel && S.padSel.pad.net && pad.net === S.padSel.pad.net) return '#5ee6ff';
    if (S.padHover === pad) return '#ffffff';
    return 'rgba(255, 255, 255, 0.22)';
  }

  function toggleSuperMode(forceState) {
    S.superMode = forceState !== undefined ? forceState : !S.superMode;
    if (S.superMode) {
      if (S.selectMode) {
        S.selectMode = false;
        if ($('btnSelectMode')) $('btnSelectMode').classList.remove('active');
      }
      if (S.infoMode) toggleInfoMode(false);
      disarmDraw();
      S.sel = null;
      if (!S.showParts) {
        S.showParts = true;
        if ($('tglParts')) $('tglParts').classList.add('active');
      }
      $('partInfoCard')?.classList.remove('hidden');
      setPadPanelEmpty();
      toast('Super info: click any pad to see its net and every other pad on that net.');
    } else {
      S.padSel = null;
      S.padHover = null;
      S.infoFp = null;
      $('partInfoCard')?.classList.add('hidden');
      $('padInfoBody')?.classList.add('hidden');
      $('infoBody')?.classList.remove('hidden');
      const hint = $('infoEmptyHint');
      if (hint) hint.textContent = 'Click any component on the board to view its info';
      toast('Super info exited');
    }
    refreshUI();
  }

  function setPadPanelEmpty() {
    S.padSel = null;
    $('infoBody')?.classList.add('hidden');
    $('padInfoBody')?.classList.add('hidden');
    const hint = $('infoEmptyHint');
    if (hint) {
      hint.textContent = 'Click a pad on the board to see its net';
      hint.classList.remove('hidden');
    }
    $('infoRef').textContent = 'Select pad';
    setBadge('Super info');
  }

  // Which pad is under the pointer. Uses the same rotation as the pad drawing,
  // so what you click is what you see highlighted.
  function hitPad(m) {
    if (!S.board?.footprints) return null;
    const side = S.sideView === 'both' ? (S.pointerSide || 'top') : (S.sideView === 'bottom' ? 'bot' : 'top');
    const tol = Math.max(0.02, 1 / S.view.scale); // about one screen pixel, in mm
    let best = null;
    let bestArea = Infinity;
    let bestDepth = Infinity;
    for (const fp of S.board.footprints) {
      if (!fpOnSide(fp, side)) continue;
      for (const pad of fp.pads || []) {
        const dx = m.x - pad.x;
        const dy = m.y - pad.y;
        if (Math.hypot(dx, dy) > Math.hypot(pad.w, pad.h) / 2 + tol) continue;
        const a = ((pad.angle || 0) * Math.PI) / 180;
        const lx = dx * Math.cos(a) - dy * Math.sin(a);
        const ly = dx * Math.sin(a) + dy * Math.cos(a);
        if (Math.abs(lx) > pad.w / 2 + tol || Math.abs(ly) > pad.h / 2 + tol) continue;
        // Where pads overlap (a thermal via inside the exposed pad), the smaller pad is the one
        // you meant. Ties go to the pad the pointer sits deepest inside.
        const area = pad.w * pad.h;
        const depth = Math.max(Math.abs(lx) / (pad.w / 2 || 1), Math.abs(ly) / (pad.h / 2 || 1));
        if (area < bestArea || (area === bestArea && depth < bestDepth)) {
          best = { fp, pad };
          bestArea = area;
          bestDepth = depth;
        }
      }
    }
    return best;
  }

  function isGroundNet(net) {
    return /(^|\/)V-$/.test(net || '');
  }

  function netKind(net) {
    if (!net) return 'Not connected';
    if (net.startsWith('unconnected-')) return 'No-connect pad (not wired)';
    if (isGroundNet(net)) return 'Ground: V- (bottom of the stack)';
    const n = net.replace(/^\//, '');
    let m;
    if ((m = n.match(/^CELL(\d+)$/))) return `Cell tap ${m[1]} (node between cells ${m[1]} and ${Number(m[1]) + 1})`;
    if ((m = n.match(/^C(\d+)_F$/))) return `Chip C${m[1]} pin, after its 10 ohm series resistor`;
    if ((m = n.match(/^S(\d+)$/))) return `Balance pin S${m[1]}, to the cell's balance resistor`;
    if ((m = n.match(/^TAP(\d+)$/))) return `Guard tap ${m[1]}, after its fuse`;
    if (/^GPIO\d+$/.test(n)) return 'GPIO: thermistor input, pulled up to VREF2';
    if (/^V(P_F|BAT_F)$/.test(n)) return 'Supply: V+ at the top of the stack (chip supply)';
    if (n === 'VREG') return 'Supply: 5 V regulator output (VREG)';
    if (/^VREF[12]$/.test(n)) return 'Reference: VREF (chip reference)';
    if (n === 'VCOLL' || n === 'DRIVE') return 'Regulator Q301: collector (VCOLL) or base (DRIVE)';
    if (/^(IBIAS|ICMP)$/.test(n)) return 'Bias network (IBIAS / ICMP)';
    if (/ISO|^I[PM][AB]$/.test(n)) return 'isoSPI signal';
    return 'Signal';
  }

  function showPadInfo(fp, pad) {
    S.padSel = { fp, pad };
    S.infoFp = fp;
    $('partInfoCard')?.classList.remove('hidden');
    $('infoEmptyHint')?.classList.add('hidden');
    $('infoBody')?.classList.add('hidden');
    $('padInfoBody')?.classList.remove('hidden');
    setBadge('Super info');
    $('infoRef').textContent = `${fp.ref} · pad ${pad.num}`;

    const net = pad.net || '';
    $('padNum').textContent = pad.num;
    $('padPart').textContent = fp.value ? `${fp.ref} (${fp.value})` : fp.ref;
    $('padNet').textContent = net || 'No net';
    $('padKind').textContent = netKind(net);
    $('padGround').textContent = isGroundNet(net) ? 'Yes: V- is the chip ground' : 'No';
    $('padPos').textContent = `(${fmt(pad.x)}, ${fmt(pad.y)}) mm`;
    $('padSize').textContent = `${fmt(pad.w)} × ${fmt(pad.h)} mm`;

    const peers = [];
    if (net) {
      for (const f of S.board.footprints) {
        for (const p of f.pads || []) {
          if (p.net === net && !(f === fp && p.num === pad.num)) peers.push(`${f.ref}.${p.num}`);
        }
      }
    }
    const box = $('padPeers');
    if (!net) {
      $('padPeerHead').textContent = 'Connects to';
      box.textContent = 'Nothing: this pad has no net.';
    } else {
      $('padPeerHead').textContent = `Connects to (${peers.length} other pad${peers.length === 1 ? '' : 's'} on ${net})`;
      if (!peers.length) {
        box.textContent = 'Only this pad is on this net.';
      } else {
        const shown = peers.slice(0, 150);
        box.textContent = shown.join(', ') + (peers.length > shown.length ? ` … +${peers.length - shown.length} more` : '');
      }
    }
    render();
    toast(`Pad <b>${esc(fp.ref)}.${esc(pad.num)}</b> → ${net ? esc(net) : 'no net'}`);
  }

  function renderPartNotes(note) {
    const purpose = $('infoPurpose');
    const list = $('infoIssues');
    if (!purpose || !list) return;
    list.textContent = '';
    if (!note) {
      purpose.textContent = 'No note recorded for this part yet.';
      return;
    }
    purpose.textContent = note.purpose;
    const items = note.issues && note.issues.length ? note.issues : ['None recorded.'];
    for (const t of items) {
      const li = document.createElement('li');
      li.textContent = t;
      list.appendChild(li);
    }
  }

  // ---------- PART INFO HELPERS ----------
  const REF_TYPES = {
    R: 'Resistor', RN: 'Resistor network', RT: 'Thermistor', RV: 'Varistor',
    C: 'Capacitor',
    L: 'Inductor', FB: 'Ferrite bead',
    D: 'Diode', LED: 'LED', ZD: 'Zener diode',
    Q: 'Transistor', U: 'IC', IC: 'IC',
    J: 'Connector', P: 'Connector', CON: 'Connector',
    SW: 'Switch', BT: 'Button',
    F: 'Fuse',
    Y: 'Crystal', X: 'Crystal', XTAL: 'Crystal',
    TP: 'Test point', MH: 'Mounting hole', H: 'Hole',
    K: 'Relay', SSR: 'Solid-state relay',
    ANT: 'Antenna', BAT: 'Battery',
  };

  // EIA-96 2-digit indices → 3 significant digits (01–96)
  const EIA96 = [
    100,102,105,107,110,113,115,118,121,124,127,130,133,137,140,143,
    147,150,154,158,162,165,169,174,178,182,187,191,196,200,205,210,
    215,221,226,232,237,243,249,255,261,267,274,280,287,294,301,309,
    316,324,332,340,348,357,365,374,383,392,402,412,422,432,442,453,
    464,475,487,499,511,523,536,549,562,576,590,604,619,634,649,665,
    681,698,715,732,750,768,787,806,825,845,866,887,909,931,953,976
  ];
  const EIA96_MULT = {
    Z: 0.001, Y: 0.01, R: 0.01, X: 0.1, S: 0.1,
    A: 1, B: 10, H: 10, C: 100, D: 1000, E: 10000, F: 100000
  };

  // Common imperial SMD codes → mm (when metric code missing from footprint name)
  const IMPERIAL_MM = {
    '01005': [0.4, 0.2], '0201': [0.6, 0.3], '0402': [1.0, 0.5],
    '0603': [1.6, 0.8], '0805': [2.0, 1.25], '1206': [3.2, 1.6],
    '1210': [3.2, 2.5], '2010': [5.0, 2.5], '2512': [6.3, 3.2]
  };

  function partTypeFromRef(ref) {
    if (!ref) return 'Unknown';
    // Designator letters before '_' or digits: R_SSR1 → R, LED12 → LED
    const m = String(ref).trim().toUpperCase().match(/^([A-Z]+)/);
    if (!m) return 'Unknown';
    return REF_TYPES[m[1]] || 'Component';
  }

  function formatOhms(ohms) {
    if (!Number.isFinite(ohms) || ohms < 0) return null;
    if (ohms === 0) return '0 Ω';
    if (ohms >= 1e6) {
      const v = ohms / 1e6;
      return `${Number.isInteger(v) ? v : +v.toFixed(2)} MΩ`;
    }
    if (ohms >= 1000) {
      const v = ohms / 1000;
      return `${Number.isInteger(v) ? v : +v.toFixed(2)} kΩ`;
    }
    if (ohms >= 1) return `${Number.isInteger(ohms) ? ohms : +ohms.toFixed(2)} Ω`;
    if (ohms >= 0.001) return `${+(ohms * 1000).toFixed(2)} mΩ`;
    return `${ohms} Ω`;
  }

  function formatFarads(farads) {
    if (!Number.isFinite(farads) || farads <= 0) return null;
    if (farads >= 1e-3) return `${+((farads * 1e3).toFixed(3))} mF`;
    if (farads >= 1e-6) return `${+((farads * 1e6).toFixed(3))} µF`;
    if (farads >= 1e-9) return `${+((farads * 1e9).toFixed(3))} nF`;
    return `${+((farads * 1e12).toFixed(3))} pF`;
  }

  function formatHenries(h) {
    if (!Number.isFinite(h) || h <= 0) return null;
    if (h >= 1) return `${+h.toFixed(3)} H`;
    if (h >= 1e-3) return `${+((h * 1e3).toFixed(3))} mH`;
    if (h >= 1e-6) return `${+((h * 1e6).toFixed(3))} µH`;
    return `${+((h * 1e9).toFixed(3))} nH`;
  }

  function decodePartValue(raw, typeHint) {
    if (!raw || raw === '–') return { display: '–', hint: null, raw: raw || '' };
    const s = String(raw).trim();
    if (!s) return { display: '–', hint: null, raw: '' };

    // Already human-friendly with unit letter
    const withUnit = s.match(/^([\d.]+)\s*([kKmMuUnNpP]?)\s*([ΩΩohrRfFhH]|ohm|ohms)?$/i);
    if (withUnit && withUnit[3]) {
      return { display: s, hint: null, raw: s };
    }

    // Explicit k/M/R resistor shorthand: 10k, 4.7k, 100R, 1M
    const rShort = s.match(/^([\d.]+)\s*([rRkKmM])$/);
    if (rShort) {
      let ohms = parseFloat(rShort[1]);
      const u = rShort[2].toLowerCase();
      if (u === 'k') ohms *= 1e3;
      else if (u === 'm') ohms *= 1e6;
      const nice = formatOhms(ohms);
      if (nice) return { display: nice, hint: `schematic: ${s}`, raw: s };
    }

    // Capacitor shorthand: 100n, 0.1u, 10p, 4.7uF, 100nF
    const cShort = s.match(/^([\d.]+)\s*([pPnNuUµuUmM])\s*[fF]?$/);
    if (cShort && /cap/i.test(typeHint || '')) {
      let f = parseFloat(cShort[1]);
      const u = cShort[2].toLowerCase();
      if (u === 'p') f *= 1e-12;
      else if (u === 'n') f *= 1e-9;
      else if (u === 'u' || u === 'µ') f *= 1e-6;
      else if (u === 'm') f *= 1e-3;
      const nice = formatFarads(f);
      if (nice) return { display: nice, hint: s !== nice ? `schematic: ${s}` : null, raw: s };
    }

    // EIA-96 marking: 2 digits + letter (e.g. 01X → 10 Ω)
    const eia = s.match(/^(\d{2})([A-Z])$/i);
    if (eia) {
      const idx = parseInt(eia[1], 10);
      const mult = EIA96_MULT[eia[2].toUpperCase()];
      if (idx >= 1 && idx <= 96 && mult != null) {
        const ohms = EIA96[idx - 1] * mult;
        const nice = formatOhms(ohms);
        if (nice) {
          return {
            display: nice,
            hint: `marking code ${s} (EIA-96)`,
            raw: s
          };
        }
      }
    }

    // 3-digit / 4-digit SMD resistor codes: 103 → 10 kΩ, 1001 → 1 kΩ
    const smd3 = s.match(/^(\d{2})(\d)$/);
    const smd4 = s.match(/^(\d{3})(\d)$/);
    if ((smd3 || smd4) && /resistor/i.test(typeHint || '')) {
      const m = smd4 || smd3;
      const base = parseInt(m[1], 10);
      const exp = parseInt(m[2], 10);
      const ohms = base * Math.pow(10, exp);
      const nice = formatOhms(ohms);
      if (nice && ohms > 0) {
        return { display: nice, hint: `code ${s}`, raw: s };
      }
    }

    // Inductor shorthand when type is inductor: 10u, 100nH
    const lShort = s.match(/^([\d.]+)\s*([nNuUmM])\s*[hH]?$/);
    if (lShort && /inductor|ferrite/i.test(typeHint || '')) {
      let h = parseFloat(lShort[1]);
      const u = lShort[2].toLowerCase();
      if (u === 'n') h *= 1e-9;
      else if (u === 'u') h *= 1e-6;
      else if (u === 'm') h *= 1e-3;
      const nice = formatHenries(h);
      if (nice) return { display: nice, hint: s !== nice ? `schematic: ${s}` : null, raw: s };
    }

    return { display: s, hint: null, raw: s };
  }

  function metricCodeToMm(code) {
    if (!/^\d{4}$/.test(code)) return null;
    const w = Math.round(parseInt(code.slice(0, 2), 10) / 10 * 10) / 10;
    const h = Math.round(parseInt(code.slice(2, 4), 10) / 10 * 100) / 100;
    const fw = Number.isInteger(w) ? String(w) : w.toFixed(1);
    const fh = Number.isInteger(h) ? String(h) : String(+h.toFixed(2));
    return `${fw} × ${fh} mm`;
  }

  function parseFootprintId(fpid) {
    if (!fpid) return { package: '–', hint: null, libId: '–', shortName: '–' };
    const full = String(fpid);
    const shortName = full.includes(':') ? full.split(':').pop() : full;

    // KiCad chip style: R_0603_1608Metric / C_0402_1005Metric
    let m = shortName.match(/^(?:[A-Za-z]+_)?(\d{4})_(\d{4})Metric$/i);
    if (m) {
      const imperial = m[1];
      const metric = m[2];
      const mm = metricCodeToMm(metric) || (IMPERIAL_MM[imperial] &&
        `${IMPERIAL_MM[imperial][0]} × ${IMPERIAL_MM[imperial][1]} mm`);
      return {
        package: mm ? `${imperial} · ${mm}` : imperial,
        hint: `${imperial} (inch code) = ${metric} (metric code) — same size`,
        libId: full,
        shortName
      };
    }

    // Metric-only: Something_1608Metric
    m = shortName.match(/_(\d{4})Metric$/i);
    if (m) {
      const metric = m[1];
      const mm = metricCodeToMm(metric);
      return {
        package: mm ? `${metric} metric · ${mm}` : `${metric} metric`,
        hint: null,
        libId: full,
        shortName
      };
    }

    // Imperial-only common: R_0603 / LED_0805
    m = shortName.match(/_(\d{4})$/);
    if (m && IMPERIAL_MM[m[1]]) {
      const imp = m[1];
      const [w, h] = IMPERIAL_MM[imp];
      return {
        package: `${imp} · ${w} × ${h} mm`,
        hint: null,
        libId: full,
        shortName
      };
    }

    // SOIC / QFN / SOT style — use short name as package
    return {
      package: shortName.replace(/_/g, ' '),
      hint: null,
      libId: full,
      shortName
    };
  }

  function setInfoHint(el, text) {
    if (!el) return;
    if (text) {
      el.textContent = text;
      el.classList.remove('hidden');
    } else {
      el.textContent = '';
      el.classList.add('hidden');
    }
  }

  function describePart(fp) {
    const type = partTypeFromRef(fp.ref);
    const val = decodePartValue(fp.value, type);
    const pkg = parseFootprintId(fp.fpid);
    return { type, val, pkg };
  }

  function showPartInfo(fp) {
    if (!fp) return;
    S.infoFp = fp;
    const card = $('partInfoCard');
    if (!card) return;
    card.classList.remove('hidden');
    $('infoEmptyHint')?.classList.add('hidden');
    $('infoBody')?.classList.remove('hidden');
    $('padInfoBody')?.classList.add('hidden');
    setBadge('Part Info');

    const { type, val, pkg } = describePart(fp);

    $('infoRef').textContent = fp.ref || '–';
    $('infoType').textContent = type;

    $('infoVal').textContent = val.display;
    setInfoHint($('infoValHint'), val.hint);

    $('infoPkg').textContent = pkg.package;
    setInfoHint($('infoPkgHint'), pkg.hint);

    $('infoFp').textContent = pkg.shortName || '–';
    $('infoFp').title = pkg.libId || '';

    $('infoPos').textContent = `(${fmt(fp.x)}, ${fmt(fp.y)}) mm`;
    $('infoRot').textContent = `${fp.rot}°`;
    const sideEl = $('infoSide');
    if (fp.side === 'B') {
      sideEl.textContent = 'Bottom of board';
      sideEl.title = 'B.Cu';
    } else {
      sideEl.textContent = 'Top of board';
      sideEl.title = 'F.Cu';
    }

    const numPads = fp.pads?.length || 0;
    $('infoPads').textContent = `${numPads} pad${numPads === 1 ? '' : 's'}`;

    const nets = [];
    if (fp.pads && fp.pads.length) {
      fp.pads.forEach(p => {
        if (p.net && !nets.includes(p.net)) nets.push(p.net);
      });
    }
    const netStr = nets.length ? nets.join(', ') : 'Not connected';
    $('infoNets').textContent = netStr;
    $('infoNets').title = nets.length
      ? nets.map((n, i) => `${i + 1}: ${n}`).join('\n')
      : 'No copper nets on this part (NC)';

    if (fp.lcsc) {
      $('infoLcscRow')?.classList.remove('hidden');
      $('infoLcsc').textContent = fp.lcsc;
    } else {
      $('infoLcscRow')?.classList.add('hidden');
    }

    if (fp.mpn) {
      $('infoMpnRow')?.classList.remove('hidden');
      $('infoMpn').textContent = fp.mpn;
    } else {
      $('infoMpnRow')?.classList.add('hidden');
    }

    render();
    renderPartNotes(S.board?.partNotes?.[fp.ref]);
    const toastVal = val.display !== '–' ? val.display : (pkg.package || '');
    toast(`Inspecting <b>${fp.ref}</b>${toastVal ? ` (${toastVal})` : ''}`);
  }

  function copyPartInfo() {
    if (!S.infoFp) return;
    const fp = S.infoFp;
    const { type, val, pkg } = describePart(fp);
    const note = S.board?.partNotes?.[fp.ref];
    const nets = fp.pads ? [...new Set(fp.pads.map(p => p.net).filter(Boolean))].join(', ') : '';
    const text = [
      `Reference: ${fp.ref}`,
      `Type: ${type}`,
      `Value: ${val.display}${val.hint ? ` (${val.hint})` : ''}`,
      `Package: ${pkg.package}`,
      `Library: ${pkg.libId || '–'}`,
      `Position: (${fmt(fp.x)}, ${fmt(fp.y)}) mm`,
      `Rotation: ${fp.rot}°`,
      `Side: ${fp.side === 'B' ? 'Bottom of board' : 'Top of board'}`,
      `Pads: ${fp.pads?.length || 0}`,
      nets ? `Nets: ${nets}` : 'Nets: Not connected',
      fp.lcsc ? `LCSC: ${fp.lcsc}` : '',
      fp.mpn ? `MPN: ${fp.mpn}` : '',
      ...(note ? [`Purpose: ${note.purpose}`, ...note.issues.map(t => `Possible issue: ${t}`)] : [])
    ].filter(Boolean).join('\n');

    navigator.clipboard.writeText(text).then(() => {
      const btn = $('btnCopyInfo');
      if (btn) {
        const old = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = old; }, 1500);
      }
      toast(`Copied <b>${fp.ref}</b> info to clipboard`);
    });
  }

  function closePartInfo() {
    S.infoFp = null;
    if (S.infoMode) {
      $('infoEmptyHint')?.classList.remove('hidden');
      $('infoBody')?.classList.add('hidden');
      $('infoRef').textContent = 'Select part';
    } else {
      $('partInfoCard')?.classList.add('hidden');
    }
    render();
  }

  let saveTimer = null;
  function setSaveState(text, cls) {
    const el = $('saveState');
    el.textContent = text;
    el.title = text && text !== '–' ? text : '';
    el.className = `save-state ${cls || ''}`;
  }
  function scheduleSave() {
    if (!S.boardPath) return;
    setSaveState('unsaved', 'busy');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 500);
  }
  async function save() {
    try {
      const res = await fetch(`/api/boxes?path=${encodeURIComponent(S.boardPath)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(S.doc),
      }).then(r => r.json());
      if (res.error) throw new Error(res.error);
      setSaveState('saved in this browser', 'ok');
    } catch (err) {
      setSaveState('save failed', 'err');
      toast(`Save failed: ${esc(err.message)}`, 'err');
    }
  }

  // ---------- LOADING ----------
  // Plain names in the Board menu (the path stays the value and the tooltip).
  function boardLabel(path) {
    if (/slave-18s-lean\//.test(path)) return '18S Lean · shrink trial';
    if (/slave-18s\//.test(path)) return '18S Guard · full protection';
    return path;
  }

  async function init() {
    resize();
    hookEvents();
    loading('Finding boards…');
    try {
      const [boards, images] = await Promise.all([
        fetch('/api/boards').then(r => r.json()),
        fetch('/api/images').then(r => r.json()),
      ]);
      const bSel = $('boardSelect');
      bSel.innerHTML = boards.map(b => `<option value="${esc(b)}" title="${esc(b)}">${esc(boardLabel(b))}</option>`).join('');
      const saved = localStorage.getItem('pcb_dashboard_last_board');
      // Open on Lean (the board being laid out) unless the user picked another one before.
      bSel.value = (saved && boards.includes(saved)) ? saved :
                   (boards.find(b => /lean/i.test(b)) ||
                    boards.find(b => /slave/i.test(b)) ||
                    boards[0] || '');

      S.images = images;
      const iSel = $('imageSelect');
      const iBot = $('imageSelectBot');

      bSel.addEventListener('change', () => {
        localStorage.setItem('pcb_dashboard_last_board', bSel.value);
        loadBoard(bSel.value);
      });
      iSel.addEventListener('change', () => {
        S.doc.ref = iSel.value;
        loadRef(iSel.value, 'top');
        setSideView(S.sideView, true);
        scheduleSave();
      });
      if (iBot) iBot.addEventListener('change', () => {
        S.doc.refBot = iBot.value;
        loadRef(iBot.value, 'bot');
        setSideView(S.sideView, true);
        scheduleSave();
      });

      if (bSel.value) await loadBoard(bSel.value);
      else loading(null);
    } catch (err) {
      loading(`Can't reach the dashboard server (${esc(err.message)}). Start it with: python _tools/pcb_dashboard/server.py`);
    }
  }

  function loading(text) {
    if (text === null) { $('loading').classList.add('done'); return; }
    $('loading').classList.remove('done');
    $('loadingText').innerHTML = text;
  }

  async function loadBoard(path) {
    S.boardPath = path;
    S.sel = null;
    S.undo = []; S.redo = [];
    loading(`Reading <b>${esc(path.split('/').pop())}</b> from published snapshot…`);
    try {
      const [board, doc] = await Promise.all([
        fetch(`/api/board?path=${encodeURIComponent(path)}`).then(r => r.json()),
        fetch(`/api/boxes?path=${encodeURIComponent(path)}`).then(r => r.json()),
      ]);
      if (board.error) throw new Error(board.error);
      S.board = board;
      S.doc = Object.assign(emptyDoc(), doc && !doc.error ? doc : {});
      S.doc.refFit = Object.assign({ ox: 0, oy: 0, sx: 100, sy: 100 }, S.doc.refFit);
      ensureColorExists();
      // Don't auto-arm the first color — user clicks a color / + Add to draw.
      S.activeColor = null;
      lastSnap = snapshot();

      // Top photo and bottom photo are separate. The old picker took the first
      // _reference file in alphabetical order, so crops/back.png beat crops/front.png.
      const dir = path.split('/').slice(0, -1).join('/');
      const pair = pickRefPair(dir, S.doc.ref, S.doc.refBot);
      S.doc.ref = pair.top;
      S.doc.refBot = pair.bot;
      fillImageSelect($('imageSelect'), dir, pair.top);
      fillImageSelect($('imageSelectBot'), dir, pair.bot);
      // Open on the full-width top view, even if Both was used last session.
      const side = pair.bot && !pair.top ? 'bottom' : 'top';
      await Promise.all([loadRef(pair.top, 'top'), loadRef(pair.bot, 'bot')]);
      setSideView(side, false);

      fillRefFit();
      setSaveState(doc && doc.exists ? 'loaded' : 'new file', 'ok');
      loading(null);
      await checkRenderStatus(path);
      fit();
      refreshUI();
    } catch (err) {
      S.board = null;
      loading(`Couldn't read the board: ${esc(err.message)}`);
    }
  }

  async function checkRenderStatus(boardPath) {
    const badgeTop = $('renderTimeBadge');
    const badgeIso = $('renderIsoTimeBadge');
    const btnViewIso = $('btnViewIso');
    const dockIso = $('tglIsoView');
    if (!boardPath) return;
    try {
      const res = await fetch(`/api/render_status?path=${encodeURIComponent(boardPath)}`).then(r => r.json());
      // Top status
      const topInfo = res.top || (res.kind === 'top' || !res.kind ? res : null);
      if (topInfo && topInfo.exists) {
        if (badgeTop) {
          badgeTop.textContent = `Top: ${topInfo.timestamp}`;
          badgeTop.classList.add('fresh');
        }
        S.render3dPath = topInfo.image;
        await load3DRender(topInfo.image);
        S.show3D = S.sideView !== 'both';
        if ($('tgl3D')) $('tgl3D').classList.toggle('active', S.show3D);
      } else {
        if (badgeTop) {
          badgeTop.textContent = 'Top: –';
          badgeTop.classList.remove('fresh');
        }
        S.render3dPath = null;
        S.render3dImg = null;
        S.render3dBounds = null;
        S.show3D = false;
        if ($('tgl3D')) $('tgl3D').classList.remove('active');
      }

      // Bottom status: the back of the board, for parts on B.Cu (Lean's test pads)
      const botInfo = res.bottom;
      if (botInfo && botInfo.exists) {
        if ($('renderBotTimeBadge')) {
          $('renderBotTimeBadge').textContent = `Bottom: ${botInfo.timestamp}`;
          $('renderBotTimeBadge').classList.add('fresh');
        }
        S.render3dBotPath = botInfo.image;
        await load3DRender(botInfo.image, 'bot');
      } else {
        if ($('renderBotTimeBadge')) {
          $('renderBotTimeBadge').textContent = 'Bottom: –';
          $('renderBotTimeBadge').classList.remove('fresh');
        }
        S.render3dBotPath = null;
        S.render3dBotImg = null;
        S.render3dBotBounds = null;
      }
      syncSideButtons();

      // Iso status
      const isoInfo = res.iso;
      if (isoInfo && isoInfo.exists) {
        if (badgeIso) {
          badgeIso.textContent = `Iso: ${isoInfo.timestamp}`;
          badgeIso.classList.remove('hidden');
          badgeIso.classList.add('fresh');
        }
        if ($('isoTimeBadge')) $('isoTimeBadge').textContent = `Render: ${isoInfo.timestamp}`;
        S.renderIsoPath = isoInfo.image;
        if (btnViewIso) btnViewIso.classList.remove('hidden');
        if (dockIso) dockIso.classList.add('active');
      } else {
        if (badgeIso) {
          badgeIso.textContent = 'Iso: –';
          badgeIso.classList.add('hidden');
          badgeIso.classList.remove('fresh');
        }
        S.renderIsoPath = null;
        if (btnViewIso) btnViewIso.classList.add('hidden');
        if (dockIso) dockIso.classList.remove('active');
      }
      render();
    } catch {
      if (badgeTop) badgeTop.textContent = 'Top: –';
      if (badgeIso) badgeIso.textContent = 'Iso: –';
    }
  }

  function boardImageBounds(img) {
    // Where the board itself sits in a top render, in image pixels. The PNG also holds parts
    // parked off the outline (Lean try 1 parks isoSPI port A right of the board) and, in old
    // renders, empty margins, so the opaque area is not the board. The board is one solid piece:
    // its columns and rows hold an unbroken opaque run at least half as long as the longest one.
    // A parked part, or a row of them with gaps between, is much shorter.
    try {
      const w = img.naturalWidth, h = img.naturalHeight;
      if (!w || !h) return null;
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const { data } = g.getImageData(0, 0, w, h);
      const colRun = new Uint32Array(w), colCur = new Uint32Array(w), rowRun = new Uint32Array(h);
      for (let y = 0, k = 3; y < h; y++) {
        let cur = 0, best = 0;
        for (let x = 0; x < w; x++, k += 4) {
          if (data[k] > 200) {
            if (++cur > best) best = cur;
            if (++colCur[x] > colRun[x]) colRun[x] = colCur[x];
          } else {
            cur = 0;
            colCur[x] = 0;
          }
        }
        rowRun[y] = best;
      }
      const span = runs => {
        const half = runs.reduce((m, v) => Math.max(m, v), 0) / 2;
        let a = -1, b = -1;
        runs.forEach((v, i) => { if (half && v >= half) { if (a < 0) a = i; b = i; } });
        return [a, b];
      };
      const [x0, x1] = span(colRun), [y0, y1] = span(rowRun);
      if (x0 < 0 || y0 < 0) return null;
      return { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
    } catch {
      return null;
    }
  }

  function load3DRender(path, slot = 'top') {
    const [imgKey, boundsKey] = slot === 'bot' ? ['render3dBotImg', 'render3dBotBounds'] : ['render3dImg', 'render3dBounds'];
    return new Promise(resolve => {
      if (!path) {
        S[imgKey] = null;
        S[boundsKey] = null;
        render();
        return resolve();
      }
      const img = new Image();
      img.onload = () => {
        S[imgKey] = img;
        S[boundsKey] = boardImageBounds(img) || { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight };
        render();
        resolve();
      };
      img.onerror = () => {
        S[imgKey] = null;
        S[boundsKey] = null;
        resolve();
      };
      img.src = window.dashboardAsset(path);
    });
  }

  async function triggerRender3D(kind = 'top') {
    if (!S.boardPath) return toast('No board selected', 'warn');
    const isIso = kind === 'iso', isBot = kind === 'bottom';
    const label = isIso ? 'Iso' : (isBot ? 'Bottom' : 'Top');
    const btn = isIso ? $('btnIsoRender3D') : (isBot ? $('btnBotRender3D') : $('btnTopRender3D'));
    const badge = isIso ? $('renderIsoTimeBadge') : (isBot ? $('renderBotTimeBadge') : $('renderTimeBadge'));
    const oldHtml = btn ? btn.innerHTML : '';

    if (btn) {
      btn.disabled = true;
      btn.classList.add('btn-spinning');
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Rendering ${label}…`;
    }
    if (badge) {
      badge.textContent = 'Rendering…';
      badge.classList.remove('hidden');
    }

    try {
      const res = await fetch(`/api/render_3d?path=${encodeURIComponent(S.boardPath)}&kind=${kind}`, { method: 'POST' }).then(r => r.json());
      if (res.error) throw new Error(res.error);

      if (isIso) {
        S.renderIsoPath = res.image;
        if (badge) {
          badge.textContent = `Iso: ${res.timestamp}`;
          badge.classList.remove('hidden');
          badge.classList.add('fresh');
        }
        if ($('isoTimeBadge')) $('isoTimeBadge').textContent = `Render: ${res.timestamp}`;
        if ($('btnViewIso')) $('btnViewIso').classList.remove('hidden');
        if ($('tglIsoView')) $('tglIsoView').classList.add('active');
        toast(`⚡ Isometric 3D render generated! (${res.timestamp})`);
        openIsoViewer();
      } else if (isBot) {
        S.render3dBotPath = res.image;
        await load3DRender(res.image, 'bot');
        S.show3D = true;
        if ($('tgl3D')) $('tgl3D').classList.add('active');
        if (badge) {
          badge.textContent = `Bottom: ${res.timestamp}`;
          badge.classList.add('fresh');
        }
        syncSideButtons();
        toast(`⚡ 3D Bottom render generated! (${res.timestamp})`);
        render();
      } else {
        S.render3dPath = res.image;
        await load3DRender(res.image);
        S.show3D = true;
        if ($('tgl3D')) $('tgl3D').classList.add('active');
        if (badge) {
          badge.textContent = `Top: ${res.timestamp}`;
          badge.classList.add('fresh');
        }
        toast(`⚡ 3D Top-down render generated! (${res.timestamp})`);
        render();
      }
    } catch (err) {
      toast(`3D Render failed: ${esc(err.message)}`, 'err');
      if (badge) badge.textContent = `${label}: Failed`;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('btn-spinning');
        btn.innerHTML = oldHtml;
      }
    }
  }

  let fullSchematicView = false;
  async function triggerRenderSchematic(fullSystem = false) {
    if (!S.boardPath) return toast('No board selected', 'warn');
    const btn = $('btnSchematic');
    const oldHtml = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.classList.add('btn-spinning');
      btn.textContent = 'Rendering schematic…';
    }
    try {
      const endpoint = fullSystem ? 'render_full_schematic' : 'render_schematic';
      const response = await fetch(`/api/${endpoint}?path=${encodeURIComponent(S.boardPath)}`, { method: 'POST' });
      const responseText = await response.text();
      let res;
      try {
        res = JSON.parse(responseText);
      } catch {
        const hint = response.status === 404
          ? 'Dashboard API not found. Run Start Dashboards.cmd, then reload the page.'
          : `Dashboard returned HTTP ${response.status} instead of JSON.`;
        throw new Error(hint);
      }
      if (!response.ok && !res.error) throw new Error(`Dashboard returned HTTP ${response.status}.`);
      if (res.error) throw new Error(res.error);
      fullSchematicView = fullSystem;
      const pdfEndpoint = fullSystem ? 'full_schematic_pdf' : 'schematic_pdf';
      $('schematicFrame').src = window.dashboardSchematic(S.boardPath);
      $('schematicSubTitle').textContent = fullSystem
        ? `Full schematic · ${res.pages} pages · ${res.timestamp}`
        : `Published snapshot · ${res.timestamp} · scroll to navigate sheets`;
      $('schematicModal').classList.add('open');
    } catch (err) {
      toast(`Schematic render failed: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.classList.remove('btn-spinning');
        btn.innerHTML = oldHtml;
      }
    }
  }

  function closeSchematicViewer() {
    $('schematicModal')?.classList.remove('open');
  }

  // ---------- ISOMETRIC 3D VIEWER ----------
  function openIsoViewer() {
    if (!S.renderIsoPath) {
      toast('Generating Isometric 3D render…');
      triggerRender3D('iso');
      return;
    }
    const modal = $('isoModal');
    const img = $('isoImg');
    $('isoSubTitle').textContent = `Inspect component height, colors & 3D shapes on ${S.boardPath.split('/').pop()}`;
    modal.classList.add('open');
    const doFit = () => requestAnimationFrame(() => fitIso());
    img.onload = doFit;
    img.src = window.dashboardAsset(S.renderIsoPath);
    if (img.complete && img.naturalWidth) {
      doFit();
    }
    setTimeout(doFit, 60);
  }

  function closeIsoViewer() {
    $('isoModal').classList.remove('open');
  }

  function fitIso() {
    const vp = $('isoViewport');
    const img = $('isoImg');
    if (!img.naturalWidth || !img.naturalHeight) return;
    const pad = 40;
    const vw = vp.clientWidth - pad * 2;
    const vh = vp.clientHeight - pad * 2;
    const sc = Math.min(vw / img.naturalWidth, vh / img.naturalHeight, 1.0);
    S.isoView.scale = Math.max(0.1, sc);
    S.isoView.x = (vp.clientWidth - img.naturalWidth * S.isoView.scale) / 2;
    S.isoView.y = (vp.clientHeight - img.naturalHeight * S.isoView.scale) / 2;
    applyIsoTransform();
  }

  function applyIsoTransform() {
    const wrap = $('isoCanvasWrap');
    wrap.style.transform = `translate(${S.isoView.x}px, ${S.isoView.y}px) scale(${S.isoView.scale})`;
    $('isoZoomLevel').textContent = `${Math.round(S.isoView.scale * 100)}%`;
  }

  function zoomIso(factor, cx, cy) {
    const vp = $('isoViewport');
    const img = $('isoImg');
    if (!img.naturalWidth) return;
    if (cx === undefined) cx = vp.clientWidth / 2;
    if (cy === undefined) cy = vp.clientHeight / 2;
    const oldScale = S.isoView.scale;
    const newScale = Math.min(6.0, Math.max(0.15, oldScale * factor));
    S.isoView.x = cx - (cx - S.isoView.x) * (newScale / oldScale);
    S.isoView.y = cy - (cy - S.isoView.y) * (newScale / oldScale);
    S.isoView.scale = newScale;
    applyIsoTransform();
  }

  const refGen = { top: 0, bot: 0 };
  function loadRef(path, slot = 'top') {
    const gen = ++refGen[slot];
    return new Promise(resolve => {
      const apply = img => {
        if (refGen[slot] !== gen) return resolve();
        if (slot === 'bot') S.refBotImg = img;
        else S.refImg = img;
        render();
        resolve();
      };
      if (!path) return apply(null);
      const img = new Image();
      img.onload = () => apply(img);
      img.onerror = () => { toast(`Couldn't load image <code>${esc(path)}</code>`, 'err'); apply(null); };
      img.src = window.dashboardAsset(path);
    });
  }

  function sideRole(p) {
    const base = String(p).split('/').pop().toLowerCase().replace(/\.[a-z0-9]+$/i, '');
    if (/top_reference/.test(base)) return 'front';
    if (/(?:^|_)(front|top)(?:_|$)/.test(base)) return 'front';
    if (/(?:^|_)(back|bottom)(?:_|$)/.test(base)) return 'back';
    return '';
  }
  function looksLikeBack(p) { return sideRole(p) === 'back'; }
  function looksLikeFront(p) { return sideRole(p) === 'front'; }
  function imgRank(p) {
    let s = 0;
    if (p.includes('/crops/')) s += 20;
    if (/(?:^|\/)_reference\//.test(p)) s += 5;
    if (p.includes('/full/')) s -= 8;
    if (p.includes('/photos/') && !p.includes('/full/') && !p.includes('/crops/')) s += 2;
    return s;
  }
  function bestImage(list, pred) {
    return list.filter(pred).sort((a, b) => imgRank(b) - imgRank(a) || a.localeCompare(b))[0] || '';
  }
  function boardImages(dir) {
    return (S.images || []).map(i => i.path).filter(p => !dir || p.startsWith(dir + '/'));
  }
  function pickRefPair(dir, savedTop, savedBot) {
    const local = boardImages(dir);
    const known = p => local.includes(p);
    let top = savedTop && known(savedTop) && !looksLikeBack(savedTop) && !/_3d_/i.test(savedTop) ? savedTop : '';
    let bot = savedBot && known(savedBot) && savedBot !== top ? savedBot : '';
    if (!top) top = bestImage(local, looksLikeFront);
    if (!bot) bot = bestImage(local, p => looksLikeBack(p) && p !== top);
    if (!top) top = bestImage(local, p => /(?:^|\/)_reference\//.test(p) && !looksLikeBack(p) && p !== bot);
    if (top && bot === top) bot = '';
    return { top, bot };
  }
  function fillImageSelect(sel, dir, chosen) {
    if (!sel) return;
    let imgs = (S.images || []).filter(i => !dir || i.path.startsWith(dir + '/'));
    if (chosen && !imgs.some(i => i.path === chosen)) {
      const extra = (S.images || []).find(i => i.path === chosen);
      if (extra) imgs = [extra, ...imgs];
    }
    imgs.sort((a, b) => imgRank(b.path) - imgRank(a.path) || a.path.localeCompare(b.path));
    sel.innerHTML = '<option value="">(none)</option>' + imgs.map(i => {
      const label = i.path.startsWith(dir + '/') ? i.path.slice(dir.length + 1) : i.path;
      return `<option value="${esc(i.path)}">${esc(label)}</option>`;
    }).join('');
    sel.value = chosen && [...sel.options].some(o => o.value === chosen) ? chosen : '';
  }
  // The back can be shown whenever there is something to show: a bottom photo, a bottom 3D render, or
  // a part on B.Cu (Lean's test pads), so Board Boxes works on the back without any photo.
  function hasBack() {
    return !!(S.doc.refBot || S.render3dBotImg || (S.board && S.board.footprints.some(fp => fp.side === 'B')));
  }
  function hasFront() {
    return !!(S.doc.ref || S.render3dImg || !S.board || S.board.footprints.some(fp => fp.side !== 'B'));
  }
  function syncSideButtons() {
    document.querySelectorAll('#sideView button').forEach(b => {
      b.classList.toggle('on', b.dataset.side === S.sideView);
      if (b.dataset.side === 'both') b.disabled = !(hasFront() && hasBack());
      if (b.dataset.side === 'bottom') b.disabled = !hasBack();
      if (b.dataset.side === 'top') b.disabled = !hasFront();
    });
  }
  function setSideView(mode, refit) {
    if (mode === 'both' && !(hasFront() && hasBack())) mode = hasBack() && !hasFront() ? 'bottom' : 'top';
    if (mode === 'bottom' && !hasBack()) mode = 'top';
    if (mode === 'top' && !hasFront() && hasBack()) mode = 'bottom';
    S.sideView = mode;
    syncSideButtons();
    if (refit && S.board) fit();
    else render();
  }

  function fillRefFit() {
    const f = S.doc.refFit;
    $('refOx').value = f.ox; $('refOy').value = f.oy; $('refSx').value = f.sx; $('refSy').value = f.sy;
  }

  // ---------- RENDER ----------
  function fpOnSide(fp, side) {
    if (!fp) return false;
    const back = fp.side === 'B';
    const tht = (fp.pads || []).some(p => p.tht);
    if (side === 'bot') return back || tht;
    return !back;
  }
  function layerOnPane(pane, layer) {
    if (S.sideView !== 'both') return true;
    if (layer === 'F.Cu') return pane.side === 'top';
    if (layer === 'B.Cu') return pane.side === 'bot';
    return true;
  }

  function render() {
    const r = stage.getBoundingClientRect();
    ctx.clearRect(0, 0, r.width, r.height);
    if (!S.board) return;
    const panes = paneGeom();
    for (const pane of panes) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, pane.top, r.width, pane.height);
    ctx.clip();
    drawPane = pane.i;
    const bb = S.board.bbox;
    const sc = S.view.scale;
    const refImg = pane.side === 'bot' ? S.refBotImg : S.refImg;
    const hasRef = S.showRef && refImg;
    const img3D = pane.side === 'bot' ? S.render3dBotImg : S.render3dImg;
    const has3D = S.show3D && !!img3D;

    // Layer 1: Reference image (photo). Top render never covers the bottom photo.
    if (hasRef) {
      const f = S.doc.refFit;
      const p = toScreen(bb.x + f.ox, bb.y + f.oy);
      ctx.save();
      ctx.globalAlpha = (S.sideView === 'both' || has3D) ? 1 : S.opacity;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(refImg, p.x, p.y, bb.w * (f.sx / 100) * sc, bb.h * (f.sy / 100) * sc);
      ctx.restore();
    }

    // Layer 2: 3D CAD render (KiCad 3D model). The board's rect in the image goes onto the board
    // outline; the rest of the image (parts parked off the board) is drawn around it at the same scale.
    if (has3D) {
      const p = toScreen(bb.x, bb.y);
      const img = img3D;
      const src = (pane.side === 'bot' ? S.render3dBotBounds : S.render3dBounds) || { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight };
      const kx = bb.w * sc / src.w, ky = bb.h * sc / src.h;
      ctx.save();
      ctx.globalAlpha = S.opacity;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, p.x - src.x * kx, p.y - src.y * ky, img.naturalWidth * kx, img.naturalHeight * ky);
      ctx.restore();
    }

    // board outline
    ctx.save();
    ctx.strokeStyle = 'rgba(60, 240, 208, 0.85)';
    ctx.lineWidth = 1.5;
    for (const seg of S.board.edges || []) {
      if (seg.length < 2) continue;
      ctx.beginPath();
      seg.forEach((pt, k) => { const s = toScreen(pt[0], pt[1]); k ? ctx.lineTo(s.x, s.y) : ctx.moveTo(s.x, s.y); });
      ctx.stroke();
    }
    ctx.restore();

    // Planning drawings from the board's Dwgs.User layer (the long-term XR slot overlay): dashed, labelled.
    if ((S.board.user_lines || []).length || (S.board.user_texts || []).length) {
      ctx.save();
      ctx.strokeStyle = 'rgba(190, 150, 255, 0.7)';
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      for (const seg of S.board.user_lines || []) {
        if (seg.length < 2) continue;
        ctx.beginPath();
        seg.forEach((pt, k) => { const s = toScreen(pt[0], pt[1]); k ? ctx.lineTo(s.x, s.y) : ctx.moveTo(s.x, s.y); });
        ctx.stroke();
      }
      ctx.fillStyle = 'rgba(190, 150, 255, 0.9)';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      for (const t of S.board.user_texts || []) {
        const p = toScreen(t.x, t.y);
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(-(t.angle || 0) * Math.PI / 180);
        ctx.font = `600 ${Math.min(14, Math.max(9, (t.size || 1.5) * sc * 0.9))}px "JetBrains Mono"`;
        ctx.fillText(t.text, 0, 0);
        ctx.restore();
      }
      ctx.restore();
    }

    if (S.showSides) drawSideLabels(bb, sc);
    if (S.explain && S.showGroups) drawGroupOutlines(pane);

    // existing footprints (dimmed pads or color-highlighted if selected)
    if (S.showParts || S.selectMode || S.infoMode || S.superMode || S.explain) {
      ctx.save();
      for (const fp of S.board.footprints) {
        if (!fpOnSide(fp, pane.side)) continue;
        const selB = S.doc.boxes.find(b => b.ref === fp.ref);
        const col = selB ? color(selB.c) : null;
        const hex = col ? col.hex : null;
        const hg = S.explain && S.hoverFp ? fpGroup(S.hoverFp) : null;
        const isHover = ((S.selectMode || S.infoMode) && S.hoverFp === fp) || (S.explain && S.hoverFp && (S.hoverFp === fp || (hg && hg[0].test(fp.ref))));
        const isInfoSel = S.infoFp === fp;

        ctx.fillStyle = isInfoSel ? '#ffb347' : (hex ? hex + '88' : (isHover ? (S.infoMode ? 'rgba(255, 179, 71, 0.65)' : 'rgba(60, 240, 208, 0.55)') : 'rgba(255, 255, 255, 0.22)'));
        for (const pad of fp.pads) {
          const c = toScreen(pad.x, pad.y);
          if (S.superMode) ctx.fillStyle = superPadColor(pad);
          ctx.save();
          ctx.translate(c.x, c.y);
          ctx.rotate((-pad.angle * Math.PI) / 180);
          const w = Math.max(1, pad.w * sc), h = Math.max(1, pad.h * sc);
          ctx.fillRect(-w / 2, -h / 2, w, h);
          ctx.restore();
        }
        if (sc > 8 || hex || isHover || isInfoSel) {
          const c = toScreen(fp.x, fp.y);
          ctx.font = `600 ${Math.min(12, Math.max(9, sc * 0.52))}px "JetBrains Mono"`;
          ctx.fillStyle = isInfoSel ? '#ffb347' : (hex ? '#ffffff' : (isHover ? (S.infoMode ? '#ffb347' : '#3cf0d0') : 'rgba(255, 255, 255, 0.45)'));
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(fp.ref, c.x, c.y);
        }
      }
      ctx.restore();
    }

    // Bottom copper traces (B.Cu)
    if (S.showBotCu && layerOnPane(pane, 'B.Cu') && S.board.tracks) {
      ctx.save();
      ctx.strokeStyle = '#4488ff';
      ctx.lineCap = 'round';
      for (const tr of S.board.tracks) {
        if (tr.layer === 'B.Cu') {
          const p1 = toScreen(tr.x1, tr.y1), p2 = toScreen(tr.x2, tr.y2);
          ctx.lineWidth = Math.max(1, tr.w * sc);
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }
      ctx.restore();
    }

    // Inner copper traces (In2.Cu under In1.Cu), drawn on every pane: they have no side
    for (const [on, name, colour] of [[S.showIn2Cu, 'In2.Cu', '#ffa94d'], [S.showIn1Cu, 'In1.Cu', '#5fd38a']]) {
      if (!on || !S.board.tracks) continue;
      ctx.save();
      ctx.strokeStyle = colour;
      ctx.lineCap = 'round';
      for (const tr of S.board.tracks) {
        if (tr.layer !== name) continue;
        const p1 = toScreen(tr.x1, tr.y1), p2 = toScreen(tr.x2, tr.y2);
        ctx.lineWidth = Math.max(1, tr.w * sc);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
      ctx.restore();
    }

    // Top copper traces (F.Cu)
    if (S.showTopCu && layerOnPane(pane, 'F.Cu') && S.board.tracks) {
      ctx.save();
      ctx.strokeStyle = '#ff4444';
      ctx.lineCap = 'round';
      for (const tr of S.board.tracks) {
        if (tr.layer === 'F.Cu') {
          const p1 = toScreen(tr.x1, tr.y1), p2 = toScreen(tr.x2, tr.y2);
          ctx.lineWidth = Math.max(1, tr.w * sc);
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }
      ctx.restore();
    }

    // Vias
    if (S.showVias && S.board.vias) {
      ctx.save();
      for (const v of S.board.vias) {
        const p = toScreen(v.x, v.y);
        const rOuter = Math.max(1.5, (v.width / 2) * sc);
        const rDrill = Math.max(0.75, (v.drill / 2) * sc);
        ctx.fillStyle = '#ffc857';
        ctx.beginPath();
        ctx.arc(p.x, p.y, rOuter, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#07090e';
        ctx.beginPath();
        ctx.arc(p.x, p.y, rDrill, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // boxes
    const selBox = S.sel ? box(S.sel.id) : null;
    for (const b of S.doc.boxes) {
      const col = color(b.c);
      const hex = col ? col.hex : '#888';
      const its = instances(b);
      const groupSel = selBox === b;

      // link line through pattern
      if (its.length > 1) {
        ctx.save();
        ctx.strokeStyle = hex;
        ctx.globalAlpha = groupSel ? 0.9 : 0.35;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        its.forEach((it, k) => { const s = toScreen(it.x, it.y); k ? ctx.lineTo(s.x, s.y) : ctx.moveTo(s.x, s.y); });
        ctx.stroke();
        ctx.restore();
      }

      for (const it of its) {
        const p = toScreen(it.x - it.w / 2, it.y - it.h / 2);
        const w = it.w * sc, h = it.h * sc;
        const isSel = groupSel && S.sel.i === it.i;
        ctx.save();
        ctx.fillStyle = hex + (groupSel ? '55' : '38');
        ctx.fillRect(p.x, p.y, w, h);
        ctx.strokeStyle = isSel ? '#ffffff' : hex;
        ctx.lineWidth = isSel ? 2 : groupSel ? 1.6 : 1.2;
        ctx.strokeRect(p.x, p.y, w, h);
        if (it.i === firstLive(b) && its.length > 1) {   // mark the pattern anchor
          ctx.fillStyle = hex;
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + Math.min(8, w / 2), p.y); ctx.lineTo(p.x, p.y + Math.min(8, h / 2)); ctx.fill();
        }
        // color number & component ref
        const ci = colorIndex(b.c) + 1;
        const lbl = tagFor(b, it.i);
        const tagText = b.ref ? `${ci} · ${b.ref}` : (lbl || String(ci));
        if (lbl && Math.max(w, h) > 18) {
          // part label along the box's long side (vertical boxes get vertical text)
          const tall = h > w * 1.4;
          ctx.font = `700 ${Math.min(12, Math.max(8, Math.min(w, h) * 0.75))}px "JetBrains Mono"`;
          ctx.fillStyle = '#fff';
          ctx.globalAlpha = 0.95;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.translate(p.x + w / 2, p.y + h / 2);
          if (tall) ctx.rotate(-Math.PI / 2);
          ctx.fillText(tagText, 0, 0);
        } else if (w > 12 && h > 10) {
          ctx.font = `700 ${Math.min(13, Math.max(9, h * 0.55, w * 0.35))}px "JetBrains Mono"`;
          ctx.fillStyle = '#fff';
          ctx.globalAlpha = 0.95;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(tagText, p.x + w / 2, p.y + h / 2);
        }
        ctx.restore();
        if (isSel) drawHandles(p.x, p.y, w, h);
      }
    }

    // box being drawn
    if (S.drag?.mode === 'draw') {
      const d = S.drag;
      const p1 = toScreen(d.x0, d.y0), p2 = toScreen(d.x1, d.y1);
      const hex = color(S.activeColor)?.hex || '#fff';
      ctx.save();
      ctx.fillStyle = hex + '40';
      ctx.strokeStyle = hex;
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.5;
      const x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y);
      ctx.fillRect(x, y, Math.abs(p2.x - p1.x), Math.abs(p2.y - p1.y));
      ctx.strokeRect(x, y, Math.abs(p2.x - p1.x), Math.abs(p2.y - p1.y));
      ctx.font = '500 11px "JetBrains Mono"';
      ctx.fillStyle = '#fff';
      ctx.setLineDash([]);
      ctx.fillText(`${fmt(Math.abs(d.x1 - d.x0))} × ${fmt(Math.abs(d.y1 - d.y0))} mm`, x, y - 6);
      ctx.restore();
    }

    // Ghost preview for active package preset
    if (S.activePreset && S.mousePos && !S.drag && !S.pan && S.board) {
      const cx = snap(S.mousePos.x), cy = snap(S.mousePos.y);
      const pw = S.activePreset.w, ph = S.activePreset.h;
      const p1 = toScreen(cx - pw / 2, cy - ph / 2);
      const sw = pw * sc, sh = ph * sc;
      const hex = color(S.activeColor)?.hex || '#3cf0d0';
      ctx.save();
      ctx.fillStyle = hex + '25';
      ctx.strokeStyle = hex;
      ctx.setLineDash([3, 3]);
      ctx.lineWidth = 1.5;
      ctx.fillRect(p1.x, p1.y, sw, sh);
      ctx.strokeRect(p1.x, p1.y, sw, sh);
      ctx.font = '600 11px "JetBrains Mono"';
      ctx.fillStyle = hex;
      ctx.setLineDash([]);
      ctx.fillText(`${S.activePreset.name} (${fmt(pw)}×${fmt(ph)})`, p1.x, p1.y - 5);
      ctx.restore();
    }

    // Select mode hover indicator over unselected footprint
    if (S.selectMode && S.hoverFp && fpOnSide(S.hoverFp, pane.side) && !S.doc.boxes.some(b => b.ref === S.hoverFp.ref)) {
      const bb = getFpBBox(S.hoverFp);
      const p = toScreen(bb.x - bb.w / 2, bb.y - bb.h / 2);
      ctx.save();
      ctx.strokeStyle = '#3cf0d0';
      ctx.setLineDash([3, 2]);
      ctx.lineWidth = 1.5;
      ctx.strokeRect(p.x, p.y, bb.w * sc, bb.h * sc);
      ctx.font = '600 11px "JetBrains Mono"';
      ctx.fillStyle = '#3cf0d0';
      ctx.fillText(`Select ${S.hoverFp.ref}`, p.x, p.y - 5);
      ctx.restore();
    }

    // Info mode hover indicator
    if (S.infoMode && S.hoverFp && fpOnSide(S.hoverFp, pane.side) && S.hoverFp !== S.infoFp) {
      const bb = getFpBBox(S.hoverFp);
      const p = toScreen(bb.x - bb.w / 2, bb.y - bb.h / 2);
      ctx.save();
      ctx.strokeStyle = '#ffb347';
      ctx.setLineDash([3, 2]);
      ctx.lineWidth = 1.5;
      ctx.strokeRect(p.x, p.y, bb.w * sc, bb.h * sc);
      ctx.font = '600 11px "JetBrains Mono"';
      ctx.fillStyle = '#ffb347';
      ctx.fillText(`Inspect ${S.hoverFp.ref}`, p.x, p.y - 5);
      ctx.restore();
    }

    // Info mode selected footprint persistent highlight & badge
    if (S.infoFp && fpOnSide(S.infoFp, pane.side)) {
      const bb = getFpBBox(S.infoFp);
      const p = toScreen(bb.x - bb.w / 2, bb.y - bb.h / 2);
      ctx.save();
      ctx.strokeStyle = '#ffb347';
      ctx.lineWidth = 2.5;
      ctx.setLineDash([]);
      ctx.shadowColor = 'rgba(255, 179, 71, 0.6)';
      ctx.shadowBlur = 10;
      ctx.strokeRect(p.x - 2, p.y - 2, bb.w * sc + 4, bb.h * sc + 4);

      // Corner bracket accents
      const cornerLen = Math.min(12, Math.max(5, bb.w * sc * 0.25));
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#ffffff';
      ctx.beginPath();
      // NW
      ctx.moveTo(p.x - 4, p.y - 4 + cornerLen);
      ctx.lineTo(p.x - 4, p.y - 4);
      ctx.lineTo(p.x - 4 + cornerLen, p.y - 4);
      // NE
      ctx.moveTo(p.x + bb.w * sc + 4 - cornerLen, p.y - 4);
      ctx.lineTo(p.x + bb.w * sc + 4, p.y - 4);
      ctx.lineTo(p.x + bb.w * sc + 4, p.y - 4 + cornerLen);
      // SW
      ctx.moveTo(p.x - 4, p.y + bb.h * sc + 4 - cornerLen);
      ctx.lineTo(p.x - 4, p.y + bb.h * sc + 4);
      ctx.lineTo(p.x - 4 + cornerLen, p.y + bb.h * sc + 4);
      // SE
      ctx.moveTo(p.x + bb.w * sc + 4 - cornerLen, p.y + bb.h * sc + 4);
      ctx.lineTo(p.x + bb.w * sc + 4, p.y + bb.h * sc + 4);
      ctx.lineTo(p.x + bb.w * sc + 4, p.y + bb.h * sc + 4 - cornerLen);
      ctx.stroke();

      // Tooltip badge above component
      const infoDesc = describePart(S.infoFp);
      const badgeVal = infoDesc.val.display !== '–'
        ? infoDesc.val.display
        : (infoDesc.pkg.package !== '–' ? infoDesc.pkg.package : '');
      const badgeText = badgeVal ? `${S.infoFp.ref}: ${badgeVal}` : (S.infoFp.ref || '');
      ctx.font = '700 11px "JetBrains Mono", monospace';
      const tw = ctx.measureText(badgeText).width;
      const bx = p.x + (bb.w * sc) / 2 - tw / 2 - 8;
      const by = p.y - 24;
      ctx.fillStyle = 'rgba(15, 20, 30, 0.92)';
      ctx.strokeStyle = '#ffb347';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(bx, by, tw + 16, 20, 4);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#ffb347';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(badgeText, bx + 8, by + 10);
      ctx.restore();
    }
    ctx.restore();
    }
    drawPane = 0;
    paintPaneLabels(panes);
  }

  function paintPaneLabels(panes) {
    if (!panes || panes.length < 2) return;
    const r = stage.getBoundingClientRect();
    const fileOf = p => {
      const path = p ? (p.split('/').slice(-2).join('/')) : '';
      return path || 'none';
    };
    const mid = panes[1].top - (panes[1].top - (panes[0].top + panes[0].height)) / 2;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.beginPath();
    ctx.moveTo(20, mid);
    ctx.lineTo(r.width - 20, mid);
    ctx.stroke();
    ctx.font = '600 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const topName = fileOf(S.doc.ref);
    const botName = fileOf(S.doc.refBot);
    const text = `TOP  ${topName}      ·      BOTTOM  ${botName}`;
    const tw = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(7, 9, 14, 0.94)';
    ctx.fillRect(r.width / 2 - tw / 2 - 12, mid - 10, tw + 24, 20);
    ctx.fillStyle = '#c5d0de';
    ctx.fillText(text, r.width / 2, mid);
    ctx.restore();
  }

  function firstLive(b) { return instances(b)[0]?.i ?? 0; }

  // Screen-edge labels for board LEFT / RIGHT / TOP / BOTTOM (KiCad mm: +X right, +Y down).
  function drawSideLabels(bb, sc) {
    const pad = Math.max(14, Math.min(28, sc * 1.1));
    const tl = toScreen(bb.x, bb.y);
    const br = toScreen(bb.x + bb.w, bb.y + bb.h);
    const cx = (tl.x + br.x) / 2;
    const cy = (tl.y + br.y) / 2;
    const fontSize = Math.max(11, Math.min(16, sc * 0.7));

    ctx.save();
    ctx.font = `700 ${fontSize}px "Space Grotesk", "JetBrains Mono", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.letterSpacing = '0.08em';

    const labels = [
      { text: 'TOP',    x: cx,           y: tl.y - pad, rot: 0 },
      { text: 'BOTTOM', x: cx,           y: br.y + pad, rot: 0 },
      { text: 'LEFT',   x: tl.x - pad,   y: cy,         rot: -Math.PI / 2 },
      { text: 'RIGHT',  x: br.x + pad,   y: cy,         rot: Math.PI / 2 },
    ];

    for (const L of labels) {
      ctx.save();
      ctx.translate(L.x, L.y);
      ctx.rotate(L.rot);
      const tw = ctx.measureText(L.text).width;
      const bw = tw + 14, bh = fontSize + 8;
      ctx.fillStyle = 'rgba(7, 9, 14, 0.82)';
      ctx.strokeStyle = 'rgba(60, 240, 208, 0.55)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(-bw / 2, -bh / 2, bw, bh, 4);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = '#3cf0d0';
      ctx.fillText(L.text, 0, 0.5);
      ctx.restore();
    }
    ctx.restore();
  }

  function drawHandles(x, y, w, h) {
    ctx.save();
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = '#07090e';
    for (const [hx, hy] of [[x, y], [x + w, y], [x, y + h], [x + w, y + h]]) {
      ctx.fillRect(hx - 4, hy - 4, 8, 8);
      ctx.strokeRect(hx - 4, hy - 4, 8, 8);
    }
    ctx.restore();
  }

  // ---------- HIT TESTING ----------
  function getFpBBox(fp) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    if (fp.pads && fp.pads.length) {
      for (const p of fp.pads) {
        const pw = (p.w || 0.6) / 2, ph = (p.h || 0.6) / 2;
        minX = Math.min(minX, p.x - pw);
        maxX = Math.max(maxX, p.x + pw);
        minY = Math.min(minY, p.y - ph);
        maxY = Math.max(maxY, p.y + ph);
      }
    }
    if (fp.outline && fp.outline.length) {
      for (const seg of fp.outline) {
        for (const pt of seg) {
          minX = Math.min(minX, pt[0]);
          maxX = Math.max(maxX, pt[0]);
          minY = Math.min(minY, pt[1]);
          maxY = Math.max(maxY, pt[1]);
        }
      }
    }
    minX = Math.min(minX, fp.x - 0.4);
    maxX = Math.max(maxX, fp.x + 0.4);
    minY = Math.min(minY, fp.y - 0.4);
    maxY = Math.max(maxY, fp.y + 0.4);

    const pad = 0.2;
    return {
      x: (minX + maxX) / 2,
      y: (minY + maxY) / 2,
      w: Math.max(0.5, (maxX - minX) + pad * 2),
      h: Math.max(0.5, (maxY - minY) + pad * 2),
      minX: minX - pad,
      maxX: maxX + pad,
      minY: minY - pad,
      maxY: maxY + pad
    };
  }

  function hitFootprint(m) {
    if (!S.board?.footprints) return null;
    const tol = Math.max(0.5, 8 / S.view.scale); // mm
    let best = null;
    let bestScore = Infinity;
    const side = S.sideView === 'both' ? (S.pointerSide || 'top') : (S.sideView === 'bottom' ? 'bot' : 'top');
    for (const fp of S.board.footprints) {
      if (!fpOnSide(fp, side)) continue;
      const bb = getFpBBox(fp);
      const centerDist = Math.hypot(m.x - fp.x, m.y - fp.y);
      const inBBox = (m.x >= bb.minX - tol && m.x <= bb.maxX + tol && m.y >= bb.minY - tol && m.y <= bb.maxY + tol);
      const nearCenter = centerDist <= Math.max(1.2, 12 / S.view.scale);
      if (inBBox || nearCenter) {
        const dist = Math.hypot(m.x - bb.x, m.y - bb.y);
        const area = bb.w * bb.h;
        const score = area * 4 + dist;
        if (score < bestScore) {
          bestScore = score;
          best = fp;
        }
      }
    }
    return best;
  }

  function hitHandle(m) {
    const it = instanceOf(S.sel);
    if (!it) return null;
    const tol = 6 / S.view.scale;
    const corners = { nw: [it.x - it.w / 2, it.y - it.h / 2], ne: [it.x + it.w / 2, it.y - it.h / 2],
                      sw: [it.x - it.w / 2, it.y + it.h / 2], se: [it.x + it.w / 2, it.y + it.h / 2] };
    for (const [k, [cx, cy]] of Object.entries(corners)) {
      if (Math.abs(m.x - cx) <= tol && Math.abs(m.y - cy) <= tol) return k;
    }
    return null;
  }
  function hitBox(m) {
    const tol = 3 / S.view.scale;
    const its = allInstances();
    // prefer smallest box under cursor
    let best = null;
    for (const it of its) {
      if (Math.abs(m.x - it.x) <= it.w / 2 + tol && Math.abs(m.y - it.y) <= it.h / 2 + tol) {
        if (!best || it.w * it.h < best.w * best.h) best = it;
      }
    }
    return best;
  }

  // ---------- MOUSE ----------
  function onDown(e) {
    if (!S.board) return;
    const m = mouseBoard(e);
    if (e.button === 1 || e.button === 2 || S.space) {
      S.pan = { x: e.clientX, y: e.clientY };
      canvas.className = 'panning';
      e.preventDefault();
      return;
    }
    if (e.button !== 0) return;

    // Super info: click a single pad to see its net and the pads on that net.
    if (S.superMode) {
      const hit = hitPad(m);
      if (hit) showPadInfo(hit.fp, hit.pad);
      else setPadPanelEmpty();
      render();
      return;
    }

    // Component info inspection mode: click any component to inspect details.
    // Never fall through into draw/move — that was fighting Info mode.
    if (S.infoMode) {
      const hitFp = hitFootprint(m);
      if (hitFp) showPartInfo(hitFp);
      return;
    }

    // Component selection mode: click existing footprint to group it
    if (S.selectMode) {
      const hitFp = hitFootprint(m);
      if (hitFp) {
        ensureArmedColor();
        const existing = S.doc.boxes.find(b => b.ref === hitFp.ref);
        if (existing) {
          if (existing.c === S.activeColor) {
            // Deselect / remove from group
            S.doc.boxes = S.doc.boxes.filter(b => b !== existing);
            if (S.sel?.id === existing.id) S.sel = null;
            commit();
            toast(`Deselected <b>${hitFp.ref}</b>`);
            return;
          } else {
            // Move into active color group
            existing.c = S.activeColor;
            S.sel = { id: existing.id, i: 0 };
            commit();
            toast(`Moved <b>${hitFp.ref}</b> to active group`);
            return;
          }
        } else {
          // Add footprint as a box in the active color group
          const bb = getFpBBox(hitFp);
          const nb = {
            id: uid('b'),
            c: S.activeColor,
            x: r2(bb.x),
            y: r2(bb.y),
            w: r2(bb.w),
            h: r2(bb.h),
            ref: hitFp.ref,
            val: hitFp.value || '',
            fpid: hitFp.fpid || '',
            pat: null
          };
          S.doc.boxes.push(nb);
          S.sel = { id: nb.id, i: 0 };
          commit();
          toast(`Selected <b>${hitFp.ref}</b> into group`);
          return;
        }
      }
      S.sel = null;
      refreshUI();
      return;
    }

    const handle = hitHandle(m);
    if (handle) {
      const it = instanceOf(S.sel);
      S.drag = { mode: 'resize', handle, b: box(S.sel.id), i: S.sel.i,
                 fx: handle.includes('w') ? it.x + it.w / 2 : it.x - it.w / 2,      // fixed opposite corner
                 fy: handle.includes('n') ? it.y + it.h / 2 : it.y - it.h / 2 };
      return;
    }

    const hit = hitBox(m);
    if (hit) {
      let b = box(hit.id), i = hit.i;
      if (e.altKey && b.pat && liveCount(b) > 1) {
        b = breakOut(b, i);
        i = 0;
        toast('Broke box out of pattern');
      }
      S.sel = { id: b.id, i };
      S.drag = { mode: 'move', b, m0: m, x0: b.x, y0: b.y, moved: false };
      refreshUI();
      return;
    }

    S.sel = null;
    if (!S.activeColor || !color(S.activeColor)) {
      refreshUI();
      toast('Click a color (or + Add) to start drawing boxes', 'info');
      return;
    }
    let x = snap(m.x), y = snap(m.y);
    const previous = S.doc.boxes.filter(b => b.c === S.activeColor).at(-1);
    if (e.shiftKey && S.activePreset && previous) {
      if (Math.abs(x - previous.x) < Math.abs(y - previous.y)) x = previous.x;
      else y = previous.y;
    }
    S.drag = { mode: 'draw', x0: x, y0: y, x1: x, y1: y };
    refreshUI();
  }

  function onMove(e) {
    const m = mouseBoard(e);
    $('hudX').textContent = fmt(m.x);
    $('hudY').textContent = fmt(m.y);
    S.mousePos = m;
    if (S.activePreset && !S.drag && !S.pan) {
      render();
    }

    if (S.pan) {
      S.view.x -= (e.clientX - S.pan.x) / S.view.scale;
      S.view.y -= (e.clientY - S.pan.y) / S.view.scale;
      S.pan = { x: e.clientX, y: e.clientY };
      render();
      return;
    }

    if (S.explain && !S.drag && !S.selectMode && !S.infoMode) {
      const prev = S.hoverFp;
      S.hoverFp = hitFootprint(m);
      showExplain(S.hoverFp, e);
      if (S.hoverFp !== prev) render();
      return;
    }

    if (S.superMode && !S.drag) {
      const h = hitPad(m);
      const next = h ? h.pad : null;
      if (next !== S.padHover) {
        S.padHover = next;
        canvas.className = next ? 'over-box' : '';
        render();
      }
      return;
    }

    if ((S.selectMode || S.infoMode) && !S.drag) {
      const prevHover = S.hoverFp;
      S.hoverFp = hitFootprint(m);
      if (S.hoverFp !== prevHover) {
        canvas.className = S.hoverFp ? 'over-box' : '';
        render();
      }
      return;
    }

    const d = S.drag;
    if (d?.mode === 'draw') {
      d.x1 = snap(m.x); d.y1 = snap(m.y);
      render();
      return;
    }
    if (d?.mode === 'move') {
      d.b.x = r2(snap(d.x0 + (m.x - d.m0.x)));
      d.b.y = r2(snap(d.y0 + (m.y - d.m0.y)));
      if (e.shiftKey) {
        if (Math.abs(m.x - d.m0.x) < Math.abs(m.y - d.m0.y)) d.b.x = d.x0;
        else d.b.y = d.y0;
      }
      d.moved = true;
      render(); fillSelbar();
      return;
    }
    if (d?.mode === 'resize') {
      const x = snap(m.x), y = snap(m.y);
      const w = Math.max(0.05, Math.abs(x - d.fx)), h = Math.max(0.05, Math.abs(y - d.fy));
      const cx = (x + d.fx) / 2, cy = (y + d.fy) / 2;
      const [ox, oy] = offsetOf(d.b, d.i);
      d.b.w = r2(w); d.b.h = r2(h);
      d.b.x = r2(cx - ox); d.b.y = r2(cy - oy);
      render(); fillSelbar();
      return;
    }

    if (!S.board) return;
    const hd = hitHandle(m);
    canvas.className = hd ? (hd === 'nw' || hd === 'se' ? 'resize-nwse' : 'resize-nesw') : hitBox(m) ? 'over-box' : '';
  }

  function onUp() {
    if (S.pan) { S.pan = null; canvas.className = ''; return; }
    const d = S.drag;
    S.drag = null;
    if (!d) return;
    if (d.mode === 'draw') {
      const w = Math.abs(d.x1 - d.x0), h = Math.abs(d.y1 - d.y0);
      if (w * S.view.scale < 4 || h * S.view.scale < 4) {
        if (S.activePreset) {
          if (!S.activeColor || !color(S.activeColor)) {
            toast('Click a color (or + Add) before stamping a Quick Size', 'info');
            render();
            return;
          }
          const cx = snap(d.x0), cy = snap(d.y0);
          const b = {
            id: uid('b'),
            c: S.activeColor,
            x: r2(cx),
            y: r2(cy),
            w: r2(S.activePreset.w),
            h: r2(S.activePreset.h),
            pat: null
          };
          const col = color(S.activeColor);
          if (col && !col.note) {
            col.note = S.activePreset.name;
            renderLegend();
          }
          S.doc.boxes.push(b);
          S.sel = { id: b.id, i: 0 };
          commit();
          refreshUI();
          toast(`Placed ${S.activePreset.name} at (${fmt(cx)}, ${fmt(cy)})`);
          return;
        }
        render();
        return;
      }
      if (!S.activeColor || !color(S.activeColor)) {
        render();
        return;
      }
      const b = { id: uid('b'), c: S.activeColor, x: r2((d.x0 + d.x1) / 2), y: r2((d.y0 + d.y1) / 2), w: r2(w), h: r2(h), pat: null };
      S.doc.boxes.push(b);
      S.sel = { id: b.id, i: 0 };
      commit();
      return;
    }
    commit();
  }

  function onWheel(e) {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    const before = toBoard(sx, sy);
    S.view.scale = Math.max(1, Math.min(400, S.view.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    const after = toBoard(sx, sy);
    S.view.x += before.x - after.x;
    S.view.y += before.y - after.y;
    render();
  }

  // ---------- KEYBOARD ----------
  document.addEventListener('keydown', e => {
    if (e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (!(e.ctrlKey || e.metaKey) || e.altKey || S.drag) return;
    const key = e.key.toLowerCase();
    if (key === 'z' || key === 'y') {
      e.preventDefault();
      if (key === 'y' || e.shiftKey) redo(); else undo();
    }
  });
  // (Previously: undo/redo, fit, modes, delete, arrows, space-pan, etc.)

  function duplicate() {
    const b = S.sel && box(S.sel.id);
    if (!b) return;
    const nb = JSON.parse(JSON.stringify(b));
    nb.id = uid('b');
    nb.x = r2(b.x + 1); nb.y = r2(b.y + 1);
    S.doc.boxes.push(nb);
    S.sel = { id: nb.id, i: firstLive(nb) };
    commit();
  }

  function breakSelected() {
    const b = S.sel && box(S.sel.id);
    if (!b || !b.pat || liveCount(b) <= 1) return toast('Not part of a pattern', 'warn');
    const nb = breakOut(b, S.sel.i);
    S.sel = { id: nb.id, i: 0 };
    commit();
  }

  // ---------- SELECTION BAR ----------
  function fillSelbar() {
    const it = instanceOf(S.sel);
    const bar = $('selbar');
    if (!it) { bar.classList.add('hidden'); return; }
    bar.classList.remove('hidden');
    const b = box(S.sel.id);
    const p = b.pat || { n: 1, dir: 'right', pitch: 0 };
    const active = document.activeElement;
    const set = (id, v) => { if ($(id) !== active) $(id).value = v; };
    set('inX', fmt(it.x)); set('inY', fmt(it.y)); set('inW', fmt(b.w)); set('inH', fmt(b.h));
    set('inCount', p.n);
    const along = p.dir === 'left' || p.dir === 'right' ? b.w : b.h;
    set('inPitch', p.n > 1 ? fmt(p.pitch) : '');
    set('inGap', p.n > 1 ? fmt(p.pitch - along) : '');
    $('inPitch').disabled = $('inGap').disabled = p.n <= 1;
    document.querySelectorAll('#dirBtns button').forEach(btn => btn.classList.toggle('on', btn.dataset.dir === p.dir && p.n > 1));
    const linked = b.pat && liveCount(b) > 1;
    $('btnBreakOne').disabled = $('btnBreakAll').disabled = !linked;
    $('btnBreakOne').style.opacity = $('btnBreakAll').style.opacity = linked ? 1 : 0.4;
    $('selColors').innerHTML = S.doc.colors.map((c, k) =>
      `<button data-c="${c.id}" class="${c.id === b.c ? 'on' : ''}" style="background:${c.hex}" title="${k + 1}: ${esc(c.note || 'no note')}"></button>`).join('');
  }

  function selbarInput(id) {
    const b = S.sel && box(S.sel.id);
    if (!b) return;
    const v = parseFloat($(id).value);
    if (!isFinite(v)) return;
    const [ox, oy] = offsetOf(b, S.sel.i);
    switch (id) {
      case 'inX': b.x = r2(v - ox); break;
      case 'inY': b.y = r2(v - oy); break;
      case 'inW': b.w = r2(Math.max(0.05, v)); break;
      case 'inH': b.h = r2(Math.max(0.05, v)); break;
      case 'inCount': setCount(b, Math.max(1, Math.min(200, Math.round(v)))); break;
      case 'inPitch': if (b.pat) b.pat.pitch = r2(v); break;
      case 'inGap': if (b.pat) b.pat.pitch = r2(v + (b.pat.dir === 'left' || b.pat.dir === 'right' ? b.w : b.h)); break;
    }
    commit();
  }

  function setCount(b, n) {
    if (n <= 1) {
      if (b.pat) {
        // collapse to the selected instance's position
        const it = instanceOf(S.sel);
        b.x = it.x; b.y = it.y;
        b.pat = null;
        S.sel = { id: b.id, i: 0 };
      }
      return;
    }
    if (!b.pat) b.pat = { n, dir: 'right', pitch: r2(b.w + 0.5), skip: [] };
    b.pat.n = n;
    b.pat.skip = (b.pat.skip || []).filter(i => i < n);
  }

  function setDir(dir) {
    const b = S.sel && box(S.sel.id);
    if (!b) return;
    if (!b.pat) setCount(b, 2);
    const oldAlong = b.pat.dir === 'left' || b.pat.dir === 'right' ? b.w : b.h;
    const gap = b.pat.pitch - oldAlong;
    b.pat.dir = dir;
    b.pat.pitch = r2((dir === 'left' || dir === 'right' ? b.w : b.h) + gap);   // keep the same gap
    commit();
  }

  // ---------- LEGEND ----------
  function renderLegend() {
    const ul = $('colorList');
    // Never wipe the list while a note/color field is focused — that drops caret mid-type.
    const focused = document.activeElement;
    if (focused && ul.contains(focused) && focused.matches('input, textarea, select')) {
      const counts = {};
      S.doc.boxes.forEach(b => { counts[b.c] = (counts[b.c] || 0) + liveCount(b); });
      ul.querySelectorAll('.color-row').forEach(row => {
        const id = row.dataset.c;
        row.classList.toggle('active', id === S.activeColor);
        const cnt = row.querySelector('.cnt');
        if (cnt) cnt.textContent = String(counts[id] || 0);
        const swatch = row.querySelector('.swatch');
        const c = color(id);
        if (swatch && c) swatch.style.background = c.hex;
      });
      return;
    }
    const counts = {};
    S.doc.boxes.forEach(b => { counts[b.c] = (counts[b.c] || 0) + liveCount(b); });
    ul.innerHTML = S.doc.colors.map((c, k) => {
      const compBoxes = S.doc.boxes.filter(b => b.c === c.id && b.ref);
      const chips = compBoxes.map(b => `
        <span class="fp-tag ${S.sel?.id === b.id ? 'active' : ''}" data-id="${b.id}" title="${b.ref} (${b.val || b.fpid || ''})">
          ${b.ref}
          <span class="del-fp" data-del-fp="${b.id}" title="Remove ${b.ref}">×</span>
        </span>
      `).join('');

      return `
      <li class="color-item" data-c="${c.id}">
        <div class="color-row ${c.id === S.activeColor ? 'active' : ''}" data-c="${c.id}" style="--row-color:${c.hex}">
          <span class="key">${k < 9 ? k + 1 : ''}</span>
          <span class="swatch" style="background:${c.hex}" title="Change color"><input type="color" value="${c.hex}" data-c="${c.id}"></span>
          <input class="note" data-c="${c.id}" value="${esc(c.note)}" placeholder="${compBoxes.length ? compBoxes.map(b => b.ref).join(', ') : 'what part is this?'}">
          <span class="cnt">${counts[c.id] || 0}</span>
          <button class="del" data-c="${c.id}" title="Delete color and its boxes">×</button>
        </div>
        ${chips ? `<div class="color-fps">${chips}</div>` : ''}
      </li>`;
    }).join('');
  }

  function onLegendClick(e) {
    const delFp = e.target.closest('[data-del-fp]');
    if (delFp) {
      const bid = delFp.dataset.delFp;
      const b = box(bid);
      const refName = b?.ref || 'component';
      S.doc.boxes = S.doc.boxes.filter(x => x.id !== bid);
      if (S.sel?.id === bid) S.sel = null;
      commit();
      toast(`Removed <b>${refName}</b> from group`);
      return;
    }

    const fpTag = e.target.closest('.fp-tag');
    if (fpTag) {
      const bid = fpTag.dataset.id;
      const b = box(bid);
      if (b) {
        S.sel = { id: bid, i: 0 };
        S.activeColor = b.c;
        refreshUI();
      }
      return;
    }

    const del = e.target.closest('.del');
    const row = e.target.closest('.color-row');
    if (!row) return;
    const id = row.dataset.c;
    if (del) {
      const n = S.doc.boxes.filter(b => b.c === id).reduce((a, b) => a + liveCount(b), 0);
      // Regular X does NOT ask to confirm (user can use Undo button)
      S.doc.colors = S.doc.colors.filter(c => c.id !== id);
      S.doc.boxes = S.doc.boxes.filter(b => b.c !== id);
      if (S.sel && !instanceOf(S.sel)) S.sel = null;
      if (S.activeColor === id) S.activeColor = null;
      ensureColorExists();
      commit();
      toast(`Deleted color group (${n} item${n === 1 ? '' : 's'}). Undo available.`, 'info');
      return;
    }
    // Clicking the note / color picker must not rebuild the list (that steals focus mid-type).
    if (e.target.closest('input, textarea, select')) return;
    // Clicking a color arms it for drawing (and leaves Info mode).
    armColor(id);
    S.sel = null;
    refreshUI();
    toast('Color armed — drag on the board to draw');
  }

  // ---------- SAVE / OPEN AS .TXT (work from a laptop without the local server) ----------
  function saveTxt() {
    if (!S.boardPath) return;
    const { exists, ...doc } = S.doc;
    const d = new Date(), p = v => String(v).padStart(2, '0');
    const stamp = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`;
    const name = `${S.boardPath.split('/').pop().replace(/\.kicad_pcb$/i, '')}-boxes-${stamp}.txt`;
    const body = JSON.stringify({ board: S.boardPath, saved: d.toISOString(), ...doc }, null, 1);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([body], { type: 'text/plain' }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast(`Saved <b>${esc(name)}</b> (${totalCount()} boxes)`);
  }

  function openTxt(file) {
    const rd = new FileReader();
    rd.onload = () => {
      let d;
      try { d = JSON.parse(rd.result); } catch { d = null; }
      if (!d || !Array.isArray(d.colors) || !Array.isArray(d.boxes)) return toast('That file isn\'t a Board Boxes save', 'err');
      if (d.board && d.board !== S.boardPath &&
          !confirm(`This file was saved from ${d.board}.\nLoad its boxes onto ${S.boardPath} anyway?`)) return;
      S.doc.colors = d.colors;
      S.doc.boxes = d.boxes;
      S.sel = null;
      S.activeColor = null;
      ensureColorExists();
      commit();
      scheduleSave();
      toast(`Loaded ${d.boxes.length} boxes from <b>${esc(file.name)}</b>. Undo puts the old ones back.`);
    };
    rd.readAsText(file);
  }

  // ---------- EXPORT ----------
  function buildPrompt() {
    const boxesFile = S.boardPath.replace(/\.kicad_pcb$/i, '.boxes.json');
    const lines = [];
    lines.push(`### PCB context / requested work on \`${S.boardPath}\``);
    lines.push('');
    lines.push(`Reference image: \`${S.doc.ref || '(none)'}\``);
    if (S.doc.refBot) lines.push(`Bottom reference image: \`${S.doc.refBot}\``);
    if (S.render3dPath) {
      lines.push(`Top-Down 3D CAD render: \`${S.render3dPath}\``);
    }
    if (S.render3dBotPath) {
      lines.push(`Bottom 3D CAD render (mirrored to board coordinates): \`${S.render3dBotPath}\``);
    }
    if (S.renderIsoPath) {
      lines.push(`Isometric 3D CAD render: \`${S.renderIsoPath}\``);
    }
    lines.push(`Box file (same data, machine-readable): \`${boxesFile}\``);
    lines.push('');
    lines.push('X/Y = center in KiCad board coordinates (mm). W×H = part/box size.');
    lines.push('');
    lines.push('Interpret the user’s accompanying request first. Selected existing footprints are deliberate pointers to the component(s) or area they mean, even if they do not know the reference designator. Use the listed reference, value, footprint, position and board context to identify them; do not rely on a screenshot alone. Selection is context, not by itself a request to move, replace, or modify a part.');
    lines.push('');
    lines.push('Answer informational questions (such as identifying a part or checking whether it appears in the schematic) from the project files without making placement changes. Make PCB edits only when the request asks for them. For requested placement work, treat box X/Y as the target center and align the footprint there; use color notes to understand additions or corrections. If a missing or unclear note prevents the requested change, ask a focused question before changing the PCB.');

    let patLetter = 0;
    const patName = new Map();
    S.doc.boxes.forEach(b => { if (b.pat && liveCount(b) > 1) patName.set(b.id, String.fromCharCode(65 + (patLetter++ % 26))); });

    S.doc.colors.forEach((c, k) => {
      const bs = S.doc.boxes.filter(b => b.c === c.id);
      const its = bs.flatMap(b => instances(b).map(it => ({ ...it, b })));
      if (!its.length) return;
      const compRefs = bs.filter(b => b.ref).map(b => b.ref);
      const titleExtra = compRefs.length ? ` · Selected: ${compRefs.join(', ')}` : '';
      lines.push('');
      lines.push(`#### Color ${k + 1} (${c.hex}): ${c.note ? c.note : '**(no color note)**'} · ${its.length} item${its.length > 1 ? 's' : ''}${titleExtra}`);
      lines.push('');
      lines.push('| # | Ref / Item | Value / Footprint | X (mm) | Y (mm) | W×H (mm) | Details / Pattern |');
      lines.push('|---|---|---|---|---|---|---|');
      let n = 0;
      for (const b of bs) {
        const list = instances(b);
        const name = patName.get(b.id);
        list.forEach((it, j) => {
          n++;
          const pat = name ? `${name} ${j + 1}/${list.length} · ${fmt(b.pat.pitch)} mm ${DIR_ARROW[b.pat.dir]}` : (b.ref ? 'Component on PCB' : '–');
          const lbl = tagFor(b, it.i);
          const refStr = b.ref ? `**${b.ref}**` : lbl ? `**${lbl}** (planned)` : `Box ${n}`;
          const valStr = b.ref ? `${b.val || '–'} / ${b.fpid || '–'}` : '–';
          lines.push(`| ${n} | ${refStr} | ${valStr} | ${fmt(it.x)} | ${fmt(it.y)} | ${fmt(it.w)}×${fmt(it.h)} | ${pat} |`);
        });
      }
    });
    return lines.join('\n');
  }

  function flashCopied(btn, text) {
    if (!btn) return;
    const oldHtml = btn.innerHTML;
    btn.innerHTML = text;
    btn.classList.add('btn-copied');
    setTimeout(() => {
      btn.innerHTML = oldHtml;
      btn.classList.remove('btn-copied');
    }, 1500);
  }

  function openPrompt() {
    if (!totalCount()) return toast('No boxes yet. Drag on the board to draw one.', 'warn');
    const text = buildPrompt();
    $('modalText').textContent = text;
    const notes = S.doc.colors.filter(c => !c.note && S.doc.boxes.some(b => b.c === c.id)).length;
    $('modalSub').textContent = `${totalCount()} boxes` + (notes ? ` · ⚠ ${notes} color(s) without a note` : '');
    $('modal').classList.add('open');
    copy(text);
  }
  function copy(text) {
    navigator.clipboard.writeText(text).then(() => {
      toast('Prompt copied to clipboard');
      flashCopied($('btnExport'), `Copied! ✓ <em id="boxCount">${totalCount()}</em>`);
      flashCopied($('btnCopy'), 'Copied! ✓');
    }, () => toast('Clipboard blocked: select and copy manually', 'warn'));
  }

  // ---------- OPACITY CYCLING ----------
  let cycleRaf = null;
  let cycleStartTime = null;

  function setOpacity(val) {
    S.opacity = Math.max(0, Math.min(1, val));
    const pct = Math.round(S.opacity * 100);
    const slider = $('opacity');
    if (slider && document.activeElement !== slider) slider.value = pct;
    const valEl = $('opacityVal');
    if (valEl) valEl.textContent = `${pct}%`;
    render();
  }

  function startOpacityCycle() {
    stopOpacityCycle();
    cycleStartTime = performance.now();
    function tick(now) {
      if (!$('cycleOpacity').checked) return;
      const sec = Math.max(0.2, parseFloat($('cycleSec').value) || 2.0);
      const elapsed = (now - cycleStartTime) / 1000;
      // Smooth sine wave ping-pong 0 to 1
      const progress = (Math.sin((elapsed / sec) * Math.PI * 2 - Math.PI / 2) + 1) / 2;
      setOpacity(progress);
      cycleRaf = requestAnimationFrame(tick);
    }
    cycleRaf = requestAnimationFrame(tick);
  }

  function stopOpacityCycle() {
    if (cycleRaf) {
      cancelAnimationFrame(cycleRaf);
      cycleRaf = null;
    }
  }

  // ---------- UI REFRESH ----------
  function refreshUI() {
    renderLegend();
    fillSelbar();
    $('boxCount').textContent = totalCount();
    if ($('btnUndo')) $('btnUndo').disabled = S.undo.length === 0;
    if ($('btnRedo')) $('btnRedo').disabled = S.redo.length === 0;
    if ($('btnSelectMode')) $('btnSelectMode').classList.toggle('active', !!S.selectMode);
    if ($('btnInfoMode')) $('btnInfoMode').classList.toggle('active', !!S.infoMode);
    if ($('btnSuperInfo')) $('btnSuperInfo').classList.toggle('active', !!S.superMode);
    render();
  }

  // ---------- PRESETS ----------
  function updatePresetChipsUI() {
    const pc = $('presetChips');
    if (!pc) return;
    pc.querySelectorAll('.chip').forEach(c => {
      const active = S.activePreset && c.dataset.name === S.activePreset.name;
      c.classList.toggle('active', !!active);
    });
  }

  function onPresetClick(chip) {
    const name = chip.dataset.name;
    const w = parseFloat(chip.dataset.w);
    const h = parseFloat(chip.dataset.h);

    if (S.activePreset && S.activePreset.name === name) {
      S.activePreset = null;
      updatePresetChipsUI();
      render();
      toast('Preset cleared');
      return;
    }

    // Preserve flipped orientation if user already flipped preset
    const keepFlipped = S.activePreset ? S.activePreset.flipped : false;
    S.activePreset = {
      name,
      w: keepFlipped ? h : w,
      h: keepFlipped ? w : h,
      flipped: keepFlipped
    };
    updatePresetChipsUI();

    // Deselect any box so quick sizes acts purely as a stamp tool to drop new parts
    // and never accidentally resizes or resets orientation of existing boxes!
    S.sel = null;
    if (S.infoMode) toggleInfoMode(false);
    if (S.superMode) toggleSuperMode(false);
    S.selectMode = false;
    if (!S.activeColor || !color(S.activeColor)) {
      ensureArmedColor();
      toast(`Preset ${name} ready — color armed. Click board to stamp (${fmt(S.activePreset.w)} × ${fmt(S.activePreset.h)} mm)`);
    } else {
      toast(`Preset ${name} active (${fmt(S.activePreset.w)} × ${fmt(S.activePreset.h)} mm) — click board to drop`);
    }
    refreshUI();
  }

  function flipPreset() {
    if (S.activePreset) {
      const tmp = S.activePreset.w;
      S.activePreset.w = S.activePreset.h;
      S.activePreset.h = tmp;
      S.activePreset.flipped = !S.activePreset.flipped;
      updatePresetChipsUI();
      toast(`Flipped preset: ${fmt(S.activePreset.w)} × ${fmt(S.activePreset.h)} mm`);
      render();
      return;
    }
    const b = S.sel && box(S.sel.id);
    if (b) {
      const tmp = b.w;
      b.w = b.h;
      b.h = tmp;
      commit();
      fillSelbar();
      toast(`Flipped box: ${fmt(b.w)} × ${fmt(b.h)} mm`);
    }
  }

  // ---------- EVENTS ----------
  function hookEvents() {
    let resizeFitTimer = 0;
    window.addEventListener('resize', () => {
      resize();
      if ($('isoModal')?.classList.contains('open')) {
        fitIso();
      }
      // Re-fit after the topbar/legend reflow so the board doesn't stay tiny/off-screen.
      clearTimeout(resizeFitTimer);
      resizeFitTimer = setTimeout(() => { if (S.board) fit(); }, 120);
    });
    // The stage can change size without a window resize (page still laying out on first
    // load, a hidden pane being shown). Re-fit then too, or the board opens as a speck.
    if (window.ResizeObserver) {
      let lastW = 0, lastH = 0;
      new ResizeObserver(entries => {
        const { width, height } = entries[0].contentRect;
        if (Math.abs(width - lastW) < 2 && Math.abs(height - lastH) < 2) return;
        lastW = width; lastH = height;
        clearTimeout(resizeFitTimer);
        resizeFitTimer = setTimeout(() => { resize(); if (S.board) fit(); }, 120);
      }).observe(stage);
    }
    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    const tglGroups = $('tglGroups');
    if (tglGroups) tglGroups.onclick = () => { S.showGroups = !S.showGroups; tglGroups.classList.toggle('active', S.showGroups); render(); };
    canvas.addEventListener('mouseleave', () => {
      S.mousePos = null;
      if (S.activePreset) render();
    });
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    // Undo/redo shortcuts are registered above.

    $('tglRef').onclick = () => { S.showRef = !S.showRef; $('tglRef').classList.toggle('active', S.showRef); render(); };
    const sideView = $('sideView');
    if (sideView) {
      sideView.addEventListener('click', e => {
        const btn = e.target.closest('button');
        if (!btn || btn.disabled) return;
        S.doc.sideView = btn.dataset.side;
        setSideView(btn.dataset.side, true);
        scheduleSave();
      });
    }
    const tgl3D = $('tgl3D');
    if (tgl3D) {
      tgl3D.onclick = () => {
        if (!S.render3dImg && !S.render3dBotImg) {
          toast('No 3D render yet. Click <b>Render 3D</b> in the top bar to generate one.', 'info');
          return;
        }
        S.show3D = !S.show3D;
        tgl3D.classList.toggle('active', S.show3D);
        render();
      };
    }
    const tglExplain = $('tglExplain');
    if (tglExplain) tglExplain.onclick = () => {
      S.explain = !S.explain; tglExplain.classList.toggle('active', S.explain);
      const tg = $('tglGroups'); if (tg) tg.hidden = !S.explain;
      if (!S.explain) { S.hoverFp = null; showExplain(null); }
      render();
    };
    canvas.addEventListener('mouseleave', () => { if (S.explain) { S.hoverFp = null; showExplain(null); render(); } });
    $('tglParts').onclick = () => { S.showParts = !S.showParts; $('tglParts').classList.toggle('active', S.showParts); render(); };

    const tglTopCu = $('tglTopCu');
    if (tglTopCu) {
      tglTopCu.onclick = () => {
        S.showTopCu = !S.showTopCu;
        tglTopCu.classList.toggle('active', S.showTopCu);
        render();
      };
    }
    for (const [id, key] of [['tglIn1Cu', 'showIn1Cu'], ['tglIn2Cu', 'showIn2Cu']]) {
      const b = $(id);
      if (b) b.onclick = () => { S[key] = !S[key]; b.classList.toggle('active', S[key]); render(); };
    }
    const tglBotCu = $('tglBotCu');
    if (tglBotCu) {
      tglBotCu.onclick = () => {
        S.showBotCu = !S.showBotCu;
        tglBotCu.classList.toggle('active', S.showBotCu);
        render();
      };
    }
    const tglVias = $('tglVias');
    if (tglVias) {
      tglVias.onclick = () => {
        S.showVias = !S.showVias;
        tglVias.classList.toggle('active', S.showVias);
        render();
      };
    }
    const tglSides = $('tglSides');
    if (tglSides) {
      tglSides.classList.toggle('active', !!S.showSides);
      tglSides.onclick = () => {
        S.showSides = !S.showSides;
        tglSides.classList.toggle('active', S.showSides);
        render();
      };
    }

    const pChips = $('presetChips');
    if (pChips) {
      pChips.addEventListener('click', e => {
        const chip = e.target.closest('.chip');
        if (chip) onPresetClick(chip);
      });
    }
    const btnFlipPreset = $('btnFlipPreset');
    if (btnFlipPreset) btnFlipPreset.onclick = flipPreset;
    $('opacity').oninput = e => {
      if ($('cycleOpacity').checked) $('cycleOpacity').checked = false;
      stopOpacityCycle();
      setOpacity(e.target.value / 100);
    };
    $('cycleOpacity').onchange = e => {
      if (e.target.checked) startOpacityCycle();
      else stopOpacityCycle();
    };
    $('snap').onchange = e => { S.snap = parseFloat(e.target.value); };
    $('btnFit').onclick = fit;

    const btnTop = $('btnTopRender3D');
    if (btnTop) btnTop.onclick = () => triggerRender3D('top');
    const btnBot = $('btnBotRender3D');
    if (btnBot) btnBot.onclick = () => triggerRender3D('bottom');
    const btnSchematic = $('btnSchematic');
    if (btnSchematic) btnSchematic.onclick = triggerRenderSchematic;
    const btnFullSchematic = $('btnFullSchematic');
    if (btnFullSchematic) btnFullSchematic.onclick = () => triggerRenderSchematic(true);
    const btnSchematicRerender = $('btnSchematicRerender');
    if (btnSchematicRerender) btnSchematicRerender.onclick = () => triggerRenderSchematic(fullSchematicView);
    const btnSchematicClose = $('btnSchematicClose');
    if (btnSchematicClose) btnSchematicClose.onclick = closeSchematicViewer;
    $('schematicModal')?.addEventListener('click', e => { if (e.target === $('schematicModal')) closeSchematicViewer(); });
    const btnIso = $('btnIsoRender3D');
    if (btnIso) btnIso.onclick = () => triggerRender3D('iso');
    const btnViewIso = $('btnViewIso');
    if (btnViewIso) btnViewIso.onclick = openIsoViewer;
    const tglIsoView = $('tglIsoView');
    if (tglIsoView) tglIsoView.onclick = openIsoViewer;

    const btnUndo = $('btnUndo');
    if (btnUndo) btnUndo.onclick = undo;
    const btnRedo = $('btnRedo');
    if (btnRedo) btnRedo.onclick = redo;

    const btnSelectMode = $('btnSelectMode');
    if (btnSelectMode) btnSelectMode.onclick = toggleSelectMode;
    const btnInfoMode = $('btnInfoMode');
    if (btnInfoMode) btnInfoMode.onclick = () => toggleInfoMode();
    const btnSuperInfo = $('btnSuperInfo');
    if (btnSuperInfo) btnSuperInfo.onclick = () => toggleSuperMode();
    const btnCopyInfo = $('btnCopyInfo');
    if (btnCopyInfo) btnCopyInfo.onclick = copyPartInfo;
    const btnCloseInfo = $('btnCloseInfo');
    if (btnCloseInfo) btnCloseInfo.onclick = closePartInfo;
    const btnClearAll = $('btnClearAll');
    if (btnClearAll) btnClearAll.onclick = clearAllBoxes;

    // Isometric Viewer modal controls
    const btnIsoZoomIn = $('btnIsoZoomIn');
    if (btnIsoZoomIn) btnIsoZoomIn.onclick = () => zoomIso(1.25);
    const btnIsoZoomOut = $('btnIsoZoomOut');
    if (btnIsoZoomOut) btnIsoZoomOut.onclick = () => zoomIso(0.8);
    const btnIsoFit = $('btnIsoFit');
    if (btnIsoFit) btnIsoFit.onclick = fitIso;
    const btnIso100 = $('btnIso100');
    if (btnIso100) btnIso100.onclick = () => {
      const vp = $('isoViewport');
      const img = $('isoImg');
      if (!img.naturalWidth) return;
      S.isoView.scale = 1.0;
      S.isoView.x = (vp.clientWidth - img.naturalWidth) / 2;
      S.isoView.y = (vp.clientHeight - img.naturalHeight) / 2;
      applyIsoTransform();
    };
    const btnIsoRerender = $('btnIsoRerender');
    if (btnIsoRerender) btnIsoRerender.onclick = () => triggerRender3D('iso');
    const btnIsoClose = $('btnIsoClose');
    if (btnIsoClose) btnIsoClose.onclick = closeIsoViewer;
    $('isoModal')?.addEventListener('click', e => { if (e.target === $('isoModal')) closeIsoViewer(); });

    const isoVp = $('isoViewport');
    if (isoVp) {
      isoVp.addEventListener('wheel', e => {
        e.preventDefault();
        const r = isoVp.getBoundingClientRect();
        zoomIso(e.deltaY < 0 ? 1.15 : 0.87, e.clientX - r.left, e.clientY - r.top);
      }, { passive: false });
      isoVp.addEventListener('mousedown', e => {
        if (e.button === 0) {
          S.isoDrag = { x: e.clientX, y: e.clientY, ox: S.isoView.x, oy: S.isoView.y };
          isoVp.classList.add('grabbing');
        }
      });
      isoVp.addEventListener('dblclick', () => {
        if (Math.abs(S.isoView.scale - 1.0) < 0.15) fitIso();
        else {
          const img = $('isoImg');
          if (!img.naturalWidth) return;
          S.isoView.scale = 1.0;
          S.isoView.x = (isoVp.clientWidth - img.naturalWidth) / 2;
          S.isoView.y = (isoVp.clientHeight - img.naturalHeight) / 2;
          applyIsoTransform();
        }
      });
    }
    window.addEventListener('mousemove', e => {
      if (S.isoDrag) {
        S.isoView.x = S.isoDrag.ox + (e.clientX - S.isoDrag.x);
        S.isoView.y = S.isoDrag.oy + (e.clientY - S.isoDrag.y);
        applyIsoTransform();
      }
    });
    window.addEventListener('mouseup', () => {
      if (S.isoDrag) {
        S.isoDrag = null;
        $('isoViewport')?.classList.remove('grabbing');
      }
    });

    $('btnAddColor').onclick = () => addColor();
    $('colorList').addEventListener('click', onLegendClick);
    $('colorList').addEventListener('input', e => {
      const id = e.target.dataset.c;
      const c = color(id);
      if (!c) return;
      if (e.target.classList.contains('note')) { c.note = e.target.value; scheduleSave(); fillSelbar(); }
      if (e.target.type === 'color') { c.hex = e.target.value; e.target.parentElement.style.background = c.hex; render(); }
    });
    // Color picker: commit on change. Note fields: save on input only — commit() rebuilds
    // the legend and would fight with typing if fired from here on every blur.
    $('colorList').addEventListener('change', e => {
      if (!e.target.dataset.c) return;
      if (e.target.classList.contains('note')) { scheduleSave(); return; }
      commit();
    });

    ['inX', 'inY', 'inW', 'inH', 'inCount', 'inPitch', 'inGap'].forEach(id => $(id).addEventListener('change', () => selbarInput(id)));
    $('dirBtns').addEventListener('click', e => { const d = e.target.dataset.dir; if (d) setDir(d); });
    $('selColors').addEventListener('click', e => {
      const id = e.target.dataset.c;
      const b = S.sel && box(S.sel.id);
      if (id && b) { b.c = id; S.activeColor = id; commit(); }
    });
    $('btnBreakOne').onclick = breakSelected;
    $('btnBreakAll').onclick = () => {
      const b = S.sel && box(S.sel.id);
      if (!b || !b.pat) return;
      const fresh = unlinkAll(b);
      S.sel = { id: fresh[0].id, i: 0 };
      commit();
      toast(`Unlinked ${fresh.length} boxes`);
    };
    $('btnDelete').onclick = () => {
      const b = S.sel && box(S.sel.id);
      if (!b) return;
      removeInstance(b, S.sel.i);
      S.sel = null;
      commit();
    };

    ['refOx', 'refOy', 'refSx', 'refSy'].forEach(id => $(id).addEventListener('input', () => {
      S.doc.refFit = {
        ox: parseFloat($('refOx').value) || 0, oy: parseFloat($('refOy').value) || 0,
        sx: parseFloat($('refSx').value) || 100, sy: parseFloat($('refSy').value) || 100,
      };
      render(); scheduleSave();
    }));
    $('btnRefReset').onclick = () => { S.doc.refFit = { ox: 0, oy: 0, sx: 100, sy: 100 }; fillRefFit(); render(); scheduleSave(); };

    $('btnExport').onclick = openPrompt;
    $('btnSaveTxt').onclick = saveTxt;
    $('btnOpenTxt').onclick = () => $('openTxtFile').click();
    $('openTxtFile').onchange = e => { const f = e.target.files[0]; if (f) openTxt(f); e.target.value = ''; };
    $('btnCopy').onclick = () => copy($('modalText').textContent);
    $('btnClose').onclick = () => $('modal').classList.remove('open');
    $('modal').addEventListener('click', e => { if (e.target === $('modal')) $('modal').classList.remove('open'); });
  }

  init();
})();
