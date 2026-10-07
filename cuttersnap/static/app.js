import * as THREE from 'three';
import { STLLoader } from '/static/vendor/STLLoader.js';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const canvas = $('photo');
const ctx = canvas.getContext('2d');
const state = { file: null, img: null, scale: 1, tool: 'box', rect: null, fg: [], bg: [], drag: null, outline: null };

function setStatus(msg) { $('status').textContent = msg; }

// ---- photo + marks ---------------------------------------------------------
function loadFile(file) {
  if (!file) return;
  state.file = file;
  const img = new Image();
  img.onload = () => {
    state.img = img;
    state.rect = null; state.fg = []; state.bg = []; state.outline = null;
    const maxW = canvas.parentElement.clientWidth;
    state.scale = Math.min(1, maxW / img.width, 900 / img.height);
    canvas.width = Math.round(img.width * state.scale);
    canvas.height = Math.round(img.height * state.scale);
    $('hint').classList.add('hidden');
    $('trace').disabled = false;
    $('make').disabled = true;
    draw();
    setStatus('Draw a box around the cookie, then Trace outline. Single-cookie photos can skip the box.');
  };
  img.src = URL.createObjectURL(file);
}

function draw() {
  if (!state.img) return;
  const s = state.scale;
  ctx.drawImage(state.img, 0, 0, canvas.width, canvas.height);
  const r = state.drag || state.rect;
  if (r) {
    ctx.strokeStyle = '#2a8ef0'; ctx.lineWidth = 2;
    ctx.strokeRect(r[0] * s, r[1] * s, r[2] * s, r[3] * s);
  }
  if (state.outline) {
    ctx.strokeStyle = '#e020e0'; ctx.lineWidth = 2.5; ctx.beginPath();
    state.outline.forEach(([x, y], i) => (i ? ctx.lineTo(x * s, y * s) : ctx.moveTo(x * s, y * s)));
    ctx.closePath(); ctx.stroke();
  }
  for (const [pts, color] of [[state.fg, '#1fb84a'], [state.bg, '#e0302a']]) {
    ctx.fillStyle = color;
    for (const [x, y] of pts) { ctx.beginPath(); ctx.arc(x * s, y * s, 6, 0, 7); ctx.fill(); }
  }
}

function toImage(ev) {
  const b = canvas.getBoundingClientRect();
  const k = canvas.width / b.width / state.scale;
  return [Math.round((ev.clientX - b.left) * k), Math.round((ev.clientY - b.top) * k)];
}

canvas.addEventListener('pointerdown', (ev) => {
  if (!state.img) return;
  const p = toImage(ev);
  if (state.tool === 'box') { state.drag = [p[0], p[1], 0, 0]; state.start = p; canvas.setPointerCapture(ev.pointerId); }
  else { (state.tool === 'fg' ? state.fg : state.bg).push(p); draw(); }
});
canvas.addEventListener('pointermove', (ev) => {
  if (!state.drag) return;
  const [x, y] = toImage(ev), [sx, sy] = state.start;
  state.drag = [Math.min(x, sx), Math.min(y, sy), Math.abs(x - sx), Math.abs(y - sy)];
  draw();
});
canvas.addEventListener('pointerup', () => {
  if (!state.drag) return;
  if (state.drag[2] > 8 && state.drag[3] > 8) state.rect = state.drag;
  state.drag = null; draw();
});

document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('[data-tool]').forEach((o) => o.classList.toggle('active', o === b));
  state.tool = b.dataset.tool;
}));
$('clear').addEventListener('click', () => { state.rect = null; state.fg = []; state.bg = []; state.outline = null; draw(); });
$('file').addEventListener('change', (e) => loadFile(e.target.files[0]));
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => { e.preventDefault(); loadFile(e.dataTransfer.files[0]); });

// ---- API ------------------------------------------------------------------
async function apiError(res) {
  try { return (await res.json()).detail; } catch { return res.statusText; }
}

$('trace').addEventListener('click', async () => {
  const form = new FormData();
  form.append('image', state.file);
  if (state.rect) form.append('rect', JSON.stringify(state.rect));
  form.append('fg', JSON.stringify(state.fg));
  form.append('bg', JSON.stringify(state.bg));
  form.append('size_mm', $('size').value);
  setStatus('Tracing…'); $('trace').disabled = true;
  try {
    const res = await fetch('/api/trace', { method: 'POST', body: form });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    state.outline = data.outline_px; state.outlineMm = data.outline_mm;
    draw();
    $('make').disabled = false;
    setStatus(`Outline is ${data.width_mm} × ${data.height_mm} mm. Wrong edge? Add cookie / not cookie clicks and trace again.`);
  } catch (e) { setStatus(`Could not trace: ${e.message}`); }
  $('trace').disabled = false;
});

$('make').addEventListener('click', async () => {
  setStatus('Building cutter…'); $('make').disabled = true;
  try {
    const res = await fetch('/api/cutter', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        outline_mm: state.outlineMm, nozzle_mm: +$('nozzle').value,
        height: +$('height').value, flange_w: +$('flange').value, spread: +$('spread').value,
      }),
    });
    if (!res.ok) throw new Error(await apiError(res));
    const blob = await res.blob();
    const link = $('download');
    if (link.href) URL.revokeObjectURL(link.href);
    link.href = URL.createObjectURL(blob);
    link.classList.remove('hidden');
    showPreview(await blob.arrayBuffer());
    const warn = res.headers.get('X-CutterSnap-Warning');
    setStatus('Cutter ready. Print it base-down with no supports.' + (warn ? ` Note: ${warn}` : ''));
  } catch (e) { setStatus(`Could not build cutter: ${e.message}`); }
  $('make').disabled = false;
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
