import * as THREE from 'three';
import { STLLoader } from '/static/vendor/STLLoader.js';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const canvas = $('photo');
const ctx = canvas.getContext('2d');
const state = {
  file: null, img: null, hash: '', scale: 1, view: [0, 0, 1, 1], zoomed: false, tool: 'box', rect: null, fg: [], bg: [], edge: [],
  drag: null, moving: -1, outline: null, outlineMm: null, traceSeq: 0,
  frame: null, stampMm: [], stampPx: [], stampSeq: 0, checkSeq: 0, rounded: [],
};

function setStatus(msg) { $('status').textContent = msg; }

// ---- photo + marks ---------------------------------------------------------
function loadFile(file) {
  if (!file) return;
  state.file = file;
  const img = new Image();
  img.onload = () => {
    state.img = img;
    if (!state.keepMarks) { state.rect = null; state.fg = []; state.bg = []; state.edge = []; resetCutter(); }
    state.keepMarks = false;
    state.zoomed = false;
    fitView([0, 0, img.width, img.height]);
    $('hint').classList.add('hidden');
    $('trace').disabled = false;
    $('zoom').disabled = false; $('zoom').textContent = 'Zoom to box';
    draw();
    if (!state.outline) setStatus('Draw a box around the cookie, then Trace outline. Single-cookie photos can skip the box.');
  };
  img.src = URL.createObjectURL(file);
  state.hash = '';
  hashFile(file).then((h) => { if (state.file === file) state.hash = h; });
}

async function hashFile(file) {
  // crypto.subtle only exists on https or localhost; the hash is a convenience
  if (!globalThis.crypto?.subtle) return '';
  const buf = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

// show the part of the photo given as [x, y, w, h] in photo pixels
function fitView(v) {
  const maxW = canvas.parentElement.clientWidth;
  state.view = v;
  state.scale = Math.min(state.zoomed ? 4 : 1, maxW / v[2], 900 / v[3]);
  canvas.width = Math.round(v[2] * state.scale);
  canvas.height = Math.round(v[3] * state.scale);
}

function draw() {
  if (!state.img) return;
  const s = state.scale, [vx, vy, vw, vh] = state.view;
  const X = (x) => (x - vx) * s, Y = (y) => (y - vy) * s;
  ctx.drawImage(state.img, vx, vy, vw, vh, 0, 0, canvas.width, canvas.height);
  const r = state.drag || state.rect;
  if (r) {
    ctx.strokeStyle = '#2a8ef0'; ctx.lineWidth = 2;
    ctx.strokeRect(X(r[0]), Y(r[1]), r[2] * s, r[3] * s);
  }
  if (state.stampPx.length && $('stamp-on').checked) {
    ctx.fillStyle = 'rgba(20, 120, 255, 0.6)';
    ctx.fill(stampPath(X, Y), 'evenodd');
  }
  if (state.outline) {
    ctx.strokeStyle = '#e020e0'; ctx.lineWidth = 2.5; ctx.beginPath();
    state.outline.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.closePath(); ctx.stroke();
    // where the corner rules rounded the traced edge
    ctx.strokeStyle = '#ff8c1a'; ctx.lineWidth = 2.5;
    for (const [x, y] of state.rounded) { ctx.beginPath(); ctx.arc(X(x), Y(y), 11, 0, 7); ctx.stroke(); }
  }
  for (const [pts, color] of [[state.fg, '#1fb84a'], [state.bg, '#e0302a']]) {
    ctx.fillStyle = color;
    for (const [x, y] of pts) { ctx.beginPath(); ctx.arc(X(x), Y(y), 6, 0, 7); ctx.fill(); }
  }
  ctx.fillStyle = '#ffd23f'; ctx.strokeStyle = '#3a2a00'; ctx.lineWidth = 1.5;
  for (const [x, y] of state.edge) { ctx.beginPath(); ctx.arc(X(x), Y(y), 5, 0, 7); ctx.fill(); ctx.stroke(); }
}

function toImage(ev) {
  const b = canvas.getBoundingClientRect();
  const k = canvas.width / b.width / state.scale;
  return [Math.round((ev.clientX - b.left) * k + state.view[0]), Math.round((ev.clientY - b.top) * k + state.view[1])];
}

// index of the edge point under the pointer, or -1
function edgeAt(p) {
  const r = (state.touch ? 22 : 10) / state.scale;  // fingers need a bigger target
  return state.edge.findIndex(([x, y]) => Math.hypot(x - p[0], y - p[1]) <= r);
}

// A new edge point is appended, as when clicking round the cookie in order,
// unless it sits close to the line between two existing points: then it
// goes between them, to fix the outline there.
function insertEdge(p) {
  const e = state.edge;
  const d = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  let best = e.length, ratio = 0.3;
  for (let i = 0; i + 1 < e.length; i++) {
    const r = (d(e[i], p) + d(p, e[i + 1]) - d(e[i], e[i + 1])) / Math.max(1, d(e[i], e[i + 1]));
    if (r < ratio) { ratio = r; best = i + 1; }
  }
  e.splice(best, 0, p);
}

// stamp lines as one canvas path; with i set, only shape i
function stampPath(X, Y, i = -1) {
  const path = new Path2D();
  state.stampPx.forEach((shape, k) => {
    if (i >= 0 && k !== i) return;
    for (const ring of shape) {
      ring.forEach(([x, y], j) => (j ? path.lineTo(X(x), Y(y)) : path.moveTo(X(x), Y(y))));
      path.closePath();
    }
  });
  return path;
}

// leave the clicked line off the stamp
function eraseStampLine(p) {
  const id = (v) => v;
  const i = state.stampPx.findIndex((_, k) => ctx.isPointInPath(stampPath(id, id, k), p[0], p[1], 'evenodd'));
  if (i < 0) return;
  state.stampPx.splice(i, 1); state.stampMm.splice(i, 1);
  $('download-stamp').classList.add('hidden');
  draw();
}

canvas.addEventListener('pointerdown', (ev) => {
  state.touch = ev.pointerType === 'touch';
  if (!state.img) return;
  const p = toImage(ev);
  if (state.tool === 'erase') { eraseStampLine(p); return; }
  if (state.tool === 'box') { state.drag = [p[0], p[1], 0, 0]; state.start = p; canvas.setPointerCapture(ev.pointerId); }
  else if (state.tool === 'edge') {
    const i = edgeAt(p);
    if (ev.shiftKey || ev.button === 2) { if (i >= 0) { state.edge.splice(i, 1); edgeChanged(); } return; }
    if (i >= 0) state.moving = i; else { insertEdge(p); state.moving = state.edge.indexOf(p); }
    canvas.setPointerCapture(ev.pointerId); draw();
  }
  else { (state.tool === 'fg' ? state.fg : state.bg).push(p); draw(); }
});
canvas.addEventListener('contextmenu', (ev) => { if (state.tool === 'edge') ev.preventDefault(); });
canvas.addEventListener('pointermove', (ev) => {
  if (state.moving >= 0) { state.edge[state.moving] = toImage(ev); draw(); return; }
  if (!state.drag) return;
  const [x, y] = toImage(ev), [sx, sy] = state.start;
  state.drag = [Math.min(x, sx), Math.min(y, sy), Math.abs(x - sx), Math.abs(y - sy)];
  draw();
});
canvas.addEventListener('pointerup', () => {
  if (state.moving >= 0) { state.moving = -1; edgeChanged(); return; }
  if (!state.drag) return;
  if (state.drag[2] > 8 && state.drag[3] > 8) state.rect = state.drag;
  state.drag = null; draw();
});

document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('[data-tool]').forEach((o) => o.classList.toggle('active', o === b));
  state.tool = b.dataset.tool;
  if (state.tool === 'edge' && state.img && state.edge.length < 3)
    setStatus('Click 3 or more points on the cookie\'s outer edge, in order around it. The outline follows the edge between them.');
}));
// zoom in on the box (or the outline) so edge points can be placed precisely
$('zoom').addEventListener('click', () => {
  const img = state.img;
  let r = state.rect;
  if (!state.zoomed && !r && state.outline) {
    const xs = state.outline.map((p) => p[0]), ys = state.outline.map((p) => p[1]);
    r = [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
  }
  if (!state.zoomed && !r) { setStatus('Draw a box around the cookie first, then zoom.'); return; }
  state.zoomed = !state.zoomed;
  if (state.zoomed) {
    const pad = 0.12 * Math.max(r[2], r[3]);
    const x0 = Math.max(0, r[0] - pad), y0 = Math.max(0, r[1] - pad);
    const x1 = Math.min(img.width, r[0] + r[2] + pad), y1 = Math.min(img.height, r[1] + r[3] + pad);
    fitView([x0, y0, x1 - x0, y1 - y0]);
  } else fitView([0, 0, img.width, img.height]);
  $('zoom').textContent = state.zoomed ? 'Whole photo' : 'Zoom to box';
  draw();
});
function selectTool(name) { document.querySelector(`[data-tool="${name}"]`).click(); }
function resetCutter() {
  state.outline = null; state.outlineMm = null;
  for (const id of ['make', 'edit', 'save', 'keep']) $(id).disabled = true;
  $('download').classList.add('hidden');
  $('download-pusher').classList.add('hidden');
  $('download-stamp').classList.add('hidden');
  state.frame = null; state.stampMm = []; state.stampPx = []; state.check = null; state.rounded = [];
  showReport([]);
}
$('clear').addEventListener('click', () => {
  state.rect = null; state.fg = []; state.bg = []; state.edge = []; resetCutter(); draw();
});

// with edge points the outline is re-traced after every change
let edgeTimer;
function edgeChanged() {
  draw();
  clearTimeout(edgeTimer);
  if (state.edge.length >= 3) edgeTimer = setTimeout(trace, 150);
  else { resetCutter(); draw(); }
}

$('edit').addEventListener('click', () => {
  // about one point every 8% of the way round, at least 8
  const o = state.outline;
  const n = Math.max(8, Math.min(24, Math.round(o.length / 40)));
  state.edge = Array.from({ length: n }, (_, i) => o[Math.floor((i * o.length) / n)].map(Math.round));
  selectTool('edge');
  draw();
  setStatus('Drag the yellow points onto the cookie\'s real edge. Click to add a point, shift-click to remove one.');
});
$('file').addEventListener('change', (e) => loadFile(e.target.files[0]));
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => { e.preventDefault(); loadFile(e.dataTransfer.files[0]); });

// ---- API ------------------------------------------------------------------
async function apiError(res) {
  try { return (await res.json()).detail; } catch { return res.statusText; }
}

async function trace() {
  const seq = ++state.traceSeq;
  const form = new FormData();
  form.append('image', state.file);
  if (state.edge.length >= 3) form.append('edge', JSON.stringify(state.edge));
  else {
    if (state.rect) form.append('rect', JSON.stringify(state.rect));
    form.append('fg', JSON.stringify(state.fg));
    form.append('bg', JSON.stringify(state.bg));
  }
  form.append('size_mm', $('size').value);
  setStatus('Tracing…');
  try {
    const res = await fetch('/api/trace', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    if (seq !== state.traceSeq) return; // a newer trace has started
    resetCutter();
    state.outline = data.outline_px; state.outlineMm = data.outline_mm; state.frame = data.frame;
    state.rounded = data.rounded_px || [];
    draw();
    for (const id of ['make', 'edit', 'save', 'keep']) $(id).disabled = false;
    findStampLines();
    refreshCheck();
    setStatus((state.edge.length >= 3
      ? 'Drag or add yellow points where it misses the edge.'
      : 'Wrong edge? Add cookie / not cookie clicks and trace again, or use Edit as points.'));
  } catch (e) { if (seq === state.traceSeq) { resetCutter(); draw(); setStatus(`Could not trace: ${e.message}`); } }
}
function cutterBody() {
  return {
    outline_mm: state.outlineMm, nozzle_mm: +$('nozzle').value,
    height: +$('height').value, flange_w: +$('flange').value, spread: +$('spread').value,
    halo: +$('halo').value, text: $('initials').value.trim(), flip: $('flip').checked,
  };
}
// radius check of the blade's cutting face, which dough spread makes sharper
async function refreshCheck() {
  if (!state.outlineMm) return;
  const seq = ++state.checkSeq;
  state.check = null;
  showReport(outlineReport());
  try {
    const res = await fetch('/api/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cutterBody()) });
    if (!res.ok) throw new Error(await apiError(res));
    const check = await res.json();
    if (seq !== state.checkSeq) return;
    state.check = check;
    showReport(outlineReport());
  } catch (e) { if (seq === state.checkSeq) setStatus(`Could not check the outline: ${e.message}`); }
}
// what the finished cookie will measure, and what the checks found
function outlineReport() {
  if (!state.outlineMm) return [];
  const xs = state.outlineMm.map((p) => p[0]), ys = state.outlineMm.map((p) => p[1]);
  const spread = +$('spread').value || 0, halo = +$('halo').value || 0, grow = halo - spread;
  const w = Math.max(...xs) - Math.min(...xs) + 2 * grow, h = Math.max(...ys) - Math.min(...ys) + 2 * grow;
  const c = state.check || {};
  const how = [spread && `${spread} mm dough spread`, halo && `a ${halo} mm halo`].filter(Boolean).join(' and ');
  const lines = [[`Cookie (inside of the cutter): ${w.toFixed(1)} × ${h.toFixed(1)} mm` + (how ? `, after ${how}` : ''), true]];
  if (c.min_convex_radius_mm != null) {
    lines.push([`Sharpest point rounded to ${c.min_convex_radius_mm} mm radius (minimum 1.5) and tightest notch ${c.min_concave_radius_mm} mm (minimum 2.5)`, c.ok]);
  }
  if (state.rounded.length) {
    lines.push([`Corners rounded in ${state.rounded.length} ${state.rounded.length === 1 ? 'place' : 'places'} (orange rings on the photo), so dough cuts and releases cleanly`, true]);
  }
  if (c.facet_mm != null) {
    lines.push([`Smooth curves: the STL's flat facets stay within ${c.facet_mm} mm of the true curve, too small to print`, c.facet_mm <= 0.05]);
  }
  return lines;
}
function showReport(lines) {
  const ul = $('report');
  ul.replaceChildren(...lines.map(([text, ok]) => {
    const li = document.createElement('li');
    li.textContent = (ok ? '✓ ' : '✗ ') + text;
    if (!ok) li.className = 'bad';
    return li;
  }));
  ul.classList.toggle('hidden', !lines.length);
}

document.querySelectorAll('[data-size]').forEach((b) => b.addEventListener('click', () => {
  $('size').value = b.dataset.size;
  $('size').dispatchEvent(new Event('change'));
}));
// the outline is traced at a size, so a new size means a new trace
$('size').addEventListener('change', () => { if (state.outlineMm && state.img) trace(); });
for (const id of ['spread', 'halo']) $(id).addEventListener('change', refreshCheck);

// ---- matching stamp ----------------------------------------------------------
async function findStampLines() {
  const on = $('stamp-on').checked;
  $('erase-tool').classList.toggle('hidden', !on);
  const seq = ++state.stampSeq;
  if (!on || !state.frame || !state.file) { stampBusy(false); draw(); return; }
  stampBusy(true);  // Make and Save wait for the lines, or the stamp would be left out
  const form = new FormData();
  form.append('image', state.file);
  form.append('outline_mm', JSON.stringify(state.outlineMm));
  form.append('frame', JSON.stringify(state.frame));
  form.append('level', $('stamp-level').value);
  form.append('line_mm', $('stamp-line').value);
  try {
    const res = await fetch('/api/stamp-lines', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    if (seq !== state.stampSeq) return;
    state.stampMm = data.lines_mm; state.stampPx = data.lines_px;
    $('download-stamp').classList.add('hidden');
    draw();
    if (!data.lines_mm.length) setStatus('No icing lines found for a stamp. Try more stamp detail.');
  } catch (e) { if (seq === state.stampSeq) setStatus(`Could not find stamp lines: ${e.message}`); }
  if (seq === state.stampSeq) stampBusy(false);
}
function stampBusy(busy) {
  for (const id of ['make', 'save', 'keep']) $(id).disabled = busy || !state.outlineMm;
}
let stampTimer;
for (const id of ['stamp-on', 'stamp-level', 'stamp-line']) {
  $(id).addEventListener('change', () => { clearTimeout(stampTimer); stampTimer = setTimeout(findStampLines, 100); });
}

$('trace').addEventListener('click', async () => {
  $('trace').disabled = true;
  await trace();
  $('trace').disabled = false;
});

$('make').addEventListener('click', async () => {
  if (!state.outlineMm) return;
  setStatus('Building cutter…'); $('make').disabled = true;
  try {
    for (const id of ['download', 'download-pusher', 'download-stamp']) $(id).classList.add('hidden');
    const body = JSON.stringify(cutterBody());
    const post = (url) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    const wantStamp = $('stamp-on').checked && state.stampMm.length;
    const stampBody = wantStamp && JSON.stringify({ ...JSON.parse(body), lines_mm: state.stampMm, stamp_depth: +$('stamp-depth').value });
    const [res, pres, sres] = await Promise.all([post('/api/cutter'), post('/api/pusher'), wantStamp
      && fetch('/api/stamp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: stampBody })]);
    if (!res.ok) throw new Error(await apiError(res));
    const blob = await res.blob();
    setLink($('download'), blob);
    showPreview(await blob.arrayBuffer());
    const notes = [res.headers.get('X-CutterSnap-Warning')];
    if (pres.ok) setLink($('download-pusher'), await pres.blob());
    else notes.push(`No pusher plate: ${await apiError(pres)}.`);
    if (pres.ok && pres.headers.get('X-CutterSnap-Warning')) notes.push(pres.headers.get('X-CutterSnap-Warning'));
    if (sres && sres.ok) setLink($('download-stamp'), await sres.blob());
    else if (sres) notes.push(`No stamp: ${await apiError(sres)}.`);
    const [w, h] = (res.headers.get('X-CutterSnap-Size') || '').split('x');
    showReport([...outlineReport(),
      [`Cutter footprint with its base: ${w} × ${h} mm, ${$('height').value} mm tall`, true],
      ['Cutter is one solid, watertight piece', true]]);
    setStatus('Cutter ready. Print it base-down with no supports.' + notes.filter(Boolean).map((n) => ` Note: ${n}`).join(''));
  } catch (e) { setStatus(`Could not build cutter: ${e.message}`); }
  $('make').disabled = false;
});

function setLink(link, blob) {
  if (link.href) URL.revokeObjectURL(link.href);
  link.href = URL.createObjectURL(blob);
  link.classList.remove('hidden');
}

// ---- project files -----------------------------------------------------------
const SETTINGS = { nozzle_mm: 'nozzle', height: 'height', flange_w: 'flange', spread: 'spread', halo: 'halo', text: 'initials', flip: 'flip' };
function settingValue(id) {
  const el = $(id);
  return el.type === 'checkbox' ? el.checked : el.type === 'text' ? el.value.trim() : +el.value;
}
function setSetting(id, v) { if ($(id).type === 'checkbox') $(id).checked = !!v; else $(id).value = v; }

function currentProject() {
  return {
    cuttersnap: 1,
    photo: { name: state.file?.name || '', sha256: state.hash },
    marks: { box: state.rect, cookie: state.fg, not_cookie: state.bg, edge: state.edge },
    size_mm: +$('size').value,
    cutter: Object.fromEntries(Object.entries(SETTINGS).map(([k, id]) => [k, settingValue(id)])),
    outline_mm: state.outlineMm,
    outline_px: state.outline,
    frame: state.frame,
    stamp: {
      on: $('stamp-on').checked, level: +$('stamp-level').value, line_mm: +$('stamp-line').value,
      depth: +$('stamp-depth').value, lines_mm: state.stampMm, lines_px: state.stampPx,
    },
  };
}
$('save').addEventListener('click', () => {
  const project = currentProject();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(project)], { type: 'application/json' }));
  a.download = (state.file?.name || 'cookie').replace(/\.[^.]*$/, '') + '.cuttersnap.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

$('open').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  let p;
  try { p = JSON.parse(await f.text()); } catch { setStatus('That file is not a CutterSnap project.'); return; }
  openProject(p, f.name);
});
function openProject(p, label) {
  if (p.cuttersnap !== 1 || !Array.isArray(p.outline_mm)) { setStatus('That file is not a CutterSnap project.'); return; }
  const m = p.marks || {};
  resetCutter();
  state.rect = m.box || null; state.fg = m.cookie || []; state.bg = m.not_cookie || []; state.edge = m.edge || [];
  $('size').value = p.size_mm ?? 90;
  for (const [k, id] of Object.entries(SETTINGS)) {
    const el = $(id), v = p.cutter?.[k];
    if (v != null) setSetting(id, v);
    else if (el.type === 'checkbox') el.checked = el.defaultChecked;
    else el.value = el.defaultValue;  // older projects: back to the page's defaults
  }
  state.outlineMm = p.outline_mm; state.outline = p.outline_px || null; state.frame = p.frame || null;
  const st = p.stamp || {};
  $('stamp-on').checked = !!st.on;
  if (st.level != null) $('stamp-level').value = st.level;
  if (st.line_mm != null) $('stamp-line').value = st.line_mm;
  if (st.depth != null) $('stamp-depth').value = st.depth;
  state.stampMm = st.lines_mm || []; state.stampPx = st.lines_px || [];
  $('erase-tool').classList.toggle('hidden', !st.on);
  $('make').disabled = $('save').disabled = $('keep').disabled = false;
  $('edit').disabled = !state.outline;
  draw();
  refreshCheck();
  const same = state.hash && p.photo?.sha256 === state.hash;
  setStatus(`Opened ${label}. ` + (state.img
    ? (same || !p.photo?.sha256 ? 'Make cutter rebuilds it exactly.' : `Note: it was made from a different photo (${p.photo.name}).`)
    : `Make cutter rebuilds it exactly. To edit the outline, also choose the photo ${p.photo?.name || ''}.`));
  if (!state.img) state.keepMarks = true;
}

// ---- my designs: kept on this CutterSnap for any device ----------------------
async function loadDesigns() {
  let list = [];
  try {
    const res = await fetch('/api/designs');
    if (!res.ok) throw new Error(await apiError(res));
    list = await res.json();
  } catch (e) { $('designs').textContent = `Could not load saved designs: ${e.message}`; return; }
  $('designs').replaceChildren(...(list.length ? list.map(designItem) : [Object.assign(document.createElement('li'), {
    className: 'empty', textContent: 'Nothing saved yet. Make a cutter, then Save to my designs.' })]));
}
function designItem(d) {
  const li = document.createElement('li');
  const xs = d.thumb_mm.map((p) => p[0]), ys = d.thumb_mm.map((p) => p[1]);
  const x0 = Math.min(...xs), y1 = Math.max(...ys), span = Math.max(Math.max(...xs) - x0, y1 - Math.min(...ys)) || 1;
  const pts = d.thumb_mm.map(([x, y]) => `${((x - x0) / span * 40 + 2).toFixed(1)},${((y1 - y) / span * 40 + 2).toFixed(1)}`).join(' ');
  li.innerHTML = `<svg viewBox="0 0 44 44" width="44" height="44" aria-hidden="true"><polygon points="${pts}"/></svg>
    <div class="meta"><strong></strong><span></span></div><div class="acts"></div>`;
  li.querySelector('strong').textContent = d.name;
  li.querySelector('span').textContent = `${d.size_mm} mm · ${new Date(d.saved_at * 1000).toLocaleDateString()}`;
  const acts = li.querySelector('.acts');
  const link = (kind, text) => Object.assign(document.createElement('a'), { href: `/api/designs/${d.id}/${kind}.stl`, textContent: text, className: 'primary', download: '' });
  acts.append(link('cutter', 'Cutter'), link('pusher', 'Pusher'));
  if (d.stamp) acts.append(link('stamp', 'Stamp'));
  const open = Object.assign(document.createElement('button'), { textContent: 'Open' });
  open.addEventListener('click', async () => {
    const res = await fetch(`/api/designs/${d.id}`);
    if (!res.ok) { setStatus(`Could not open: ${await apiError(res)}`); return; }
    openProject((await res.json()).project, d.name);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
  const del = Object.assign(document.createElement('button'), { textContent: 'Delete' });
  del.addEventListener('click', async () => {
    if (!confirm(`Delete "${d.name}" from your designs?`)) return;
    const res = await fetch(`/api/designs/${d.id}`, { method: 'DELETE' });
    if (!res.ok) setStatus(`Could not delete: ${await apiError(res)}`);
    loadDesigns();
  });
  acts.append(open, del);
  return li;
}
$('keep').addEventListener('click', async () => {
  const guess = (state.file?.name || 'Cookie').replace(/\.[^.]*$/, '');
  const name = prompt('Name this design', guess);
  if (name === null) return;
  $('keep').disabled = true;
  try {
    const res = await fetch('/api/designs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, project: currentProject() }) });
    if (!res.ok) throw new Error(await apiError(res));
    setStatus(`Saved "${(await res.json()).name}" to My designs. Download it from any device that opens this CutterSnap.`);
    loadDesigns();
  } catch (e) { setStatus(`Could not save: ${e.message}`); }
  $('keep').disabled = !state.outlineMm;
});
loadDesigns();

// phones rotate and resize: keep the photo fitted to the screen
let fitTimer;
window.addEventListener('resize', () => {
  clearTimeout(fitTimer);
  fitTimer = setTimeout(() => { if (state.img) { fitView(state.view); draw(); } }, 150);
});

// ---- 3D preview -------------------------------------------------------------
let renderer, scene, camera, controls, mesh;
function showPreview(buf) {
  const el = $('preview');
  if (!renderer) {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x886644, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(1, -1, 2); scene.add(sun);
    camera = new THREE.PerspectiveCamera(40, el.clientWidth / el.clientHeight, 1, 2000);
    camera.up.set(0, 0, 1);
    controls = new OrbitControls(camera, renderer.domElement);
    (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
  }
  if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
  const geo = new STLLoader().parse(buf);
  geo.computeBoundingBox();
  const c = geo.boundingBox.getCenter(new THREE.Vector3());
  geo.translate(-c.x, -c.y, 0);
  mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xe0853f, roughness: 0.6 }));
  scene.add(mesh);
  const size = geo.boundingBox.getSize(new THREE.Vector3()).length();
  camera.position.set(0, -size * 0.9, size * 0.8);
  controls.target.set(0, 0, 0);
}
