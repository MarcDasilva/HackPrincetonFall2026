import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// API base: same origin by default; override with ?api=https://host or window.API_BASE.
const API = (new URLSearchParams(location.search).get('api') || window.API_BASE || '').replace(/\/$/, '');
const $ = (id) => document.getElementById(id);
const FREQS = [250, 500, 1000, 2000, 4000, 6000];
const EXAMPLE = { 250: 15, 500: 20, 1000: 30, 2000: 45, 4000: 55, 6000: 55 };

// ---------- server status ----------
fetch(`${API}/api/health`).then((r) => r.json()).then((h) => {
  const missing = Object.entries(h.weights).filter(([, ok]) => !ok).map(([k]) => k);
  $('apiStatus').textContent = missing.length ? `server up · missing weights: ${missing.join(', ')}` : 'server ready';
}).catch(() => { $('apiStatus').textContent = 'server not reachable'; });

// ---------- audiogram inputs ----------
for (const f of FREQS) {
  const l = document.createElement('label');
  l.htmlFor = `hl${f}`;
  l.textContent = f >= 1000 ? `${f / 1000} kHz` : `${f} Hz`;
  const i = document.createElement('input');
  Object.assign(i, { type: 'number', id: `hl${f}`, min: -10, max: 120, step: 5, value: EXAMPLE[f] });
  l.appendChild(i);
  $('audiogram').appendChild(l);
}

// ---------- photo + box ----------
const canvas = $('photoCanvas'), ctx = canvas.getContext('2d');
let img = null, box = null, drag = null;
$('photo').addEventListener('change', () => {
  const file = $('photo').files[0];
  box = null; updateGo();
  if (!file) return;
  const im = new Image();
  im.onload = () => {
    img = im;
    const scale = Math.min(1, 900 / im.naturalWidth);
    canvas.width = Math.round(im.naturalWidth * scale);
    canvas.height = Math.round(im.naturalHeight * scale);
    $('photoBox').hidden = false;
    $('boxText').textContent = 'Drag a box tightly around the ear.';
    draw();
  };
  im.onerror = () => {
    img = null; $('photoBox').hidden = true;
    $('formError').textContent = 'This browser cannot preview that file. Convert it to JPEG and try again.';
  };
  im.src = URL.createObjectURL(file);
});
function toCanvas(e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * canvas.width / r.width, (e.clientY - r.top) * canvas.height / r.height];
}
canvas.addEventListener('pointerdown', (e) => { if (!img) return; drag = toCanvas(e); box = null; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const p = toCanvas(e);
  box = [Math.min(drag[0], p[0]), Math.min(drag[1], p[1]), Math.max(drag[0], p[0]), Math.max(drag[1], p[1])];
  draw();
});
canvas.addEventListener('pointerup', () => {
  drag = null;
  if (box && (box[2] - box[0] < 8 || box[3] - box[1] < 8)) box = null;
  const nb = naturalBox();
  $('boxText').textContent = nb ? `Box: ${nb.join(', ')} px (drag again to redo)` : 'Drag a box tightly around the ear.';
  draw(); updateGo();
});
function naturalBox() {
  if (!box || !img) return null;
  const s = img.naturalWidth / canvas.width;
  return box.map((v) => Math.round(v * s));
}
function draw() {
  if (!img) return;
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  if (box) {
    ctx.fillStyle = 'rgba(0,0,0,.45)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, box[0] * img.naturalWidth / canvas.width, box[1] * img.naturalHeight / canvas.height,
      (box[2] - box[0]) * img.naturalWidth / canvas.width, (box[3] - box[1]) * img.naturalHeight / canvas.height,
      box[0], box[1], box[2] - box[0], box[3] - box[1]);
    ctx.strokeStyle = '#f39a3d'; ctx.lineWidth = 3;
    ctx.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
  }
}
function updateGo() { $('go').disabled = !(img && box); }

// ---------- submit ----------
$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('formError').textContent = '';
  const fd = new FormData();
  fd.append('photo', $('photo').files[0]);
  fd.append('box', naturalBox().join(','));
  fd.append('side', document.querySelector('input[name="side"]:checked').value);
  fd.append('ear_height_mm', $('height').value);
  fd.append('audiogram', JSON.stringify(Object.fromEntries(FREQS.map((f) => [f, Number($(`hl${f}`).value)]))));
  $('go').disabled = true; $('go').textContent = 'Uploading…';
  try {
    const r = await fetch(`${API}/api/patients`, { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || 'upload failed');
    location.hash = j.id;
    watch(j.id);
  } catch (err) {
    $('formError').textContent = String(err.message || err);
  } finally {
    $('go').textContent = 'Build aid'; updateGo();
  }
});

// ---------- results ----------
let current = null, timer = null, shownAid = null, files = {}, picked = null, fin = null;
document.querySelectorAll('input[name="view"]').forEach((r) => r.addEventListener('change', () => {
  picked = r.value; shownAid = `${r.value}${fin}`; loadModel(`${API}${files[r.value]}?t=${Date.now()}`);
}));
function watch(pid) {
  current = pid; shownAid = null; picked = null;
  $('wavesLink').removeAttribute('href'); $('wavesFrame').removeAttribute('src');
  ['ckOverlay', 'ckMask', 'ckSummary'].forEach((id) => { $(id).removeAttribute('src'); $(id).closest('figure').hidden = true; });
  $('results').hidden = false; $('pid').textContent = pid; $('folder').textContent = `backend/data/patients/${pid}/`;
  clearTimeout(timer); poll();
}
async function poll() {
  try {
    const r = await fetch(`${API}/api/patients/${current}`);
    if (!r.ok) throw new Error('patient not found');
    render(await r.json());
  } catch (err) {
    $('status').textContent = String(err.message || err); $('status').className = 'pill error';
    return;
  }
}
function render(job) {
  $('status').textContent = job.status + (job.step ? ` · ${job.step}` : '');
  $('status').className = `pill ${job.status}`;
  const order = ['ear', 'context', 'waves', 'aid'];
  const at = job.status === 'done' ? order.length : order.indexOf(job.step);
  document.querySelectorAll('#steps li').forEach((li, i) => {
    li.className = i < at || job.status === 'done' ? 'done' : i === at ? 'active' : '';
  });
  $('log').textContent = (job.log || []).join('\n') + (job.error ? `\n\nError: ${job.error}` : '');
  const res = job.results || {};
  if (res.aid) renderDesign(res.aid, job.files);
  if (res.context) renderRefs(res.context.references);
  files = job.files || {}; fin = job.finished_at;
  for (const [id, f] of [['ckOverlay', 'overlay.jpg'], ['ckMask', 'mask.png'], ['ckSummary', 'summary.png']]) {
    const el = $(id);
    el.closest('figure').hidden = !files[f];
    if (files[f] && !el.src) el.src = `${API}${files[f]}`;
  }
  document.querySelectorAll('input[name="view"]').forEach((r) => { r.disabled = !files[r.value]; });
  $('wavesBox').hidden = !files.waves;
  if (files.waves && $('wavesLink').getAttribute('href') !== `${API}${files.waves}`) {
    $('wavesLink').href = `${API}${files.waves}`; $('wavesFrame').src = `${API}${files.waves}`;
  }
  // follow the newest stage until the viewer picks a view by hand
  const latest = ['aid_in_ear.glb', 'ear_world.glb', 'ear.glb'].find((f) => files[f]);
  const want = picked || latest;
  if (want && files[want] && shownAid !== `${want}${job.finished_at}`) {
    shownAid = `${want}${job.finished_at}`;
    document.querySelector(`input[name="view"][value="${want}"]`).checked = true;
    loadModel(`${API}${files[want]}?t=${job.updated_at}`);
  }
  if (job.status === 'queued' || job.status === 'running') timer = setTimeout(poll, 2000);
}
function renderDesign(d, files) {
  const rows = [
    ['Bore length', `${d.bore_length_mm} mm`], ['Coil', `${d.spiral.turns} turns`],
    ['Throat → mouth', `${d.throat_mm2} → ${d.mouth_mm2} mm²`], ['Est. max gain', `${d.est_max_gain_db} dB`],
    ['Est. cutoff', `${d.est_cutoff_hz} Hz`], ['Thinnest wall', `${d.min_wall_to_skin_side_mm} mm`],
    ['Wall between turns', `${d.min_wall_between_turns_mm} mm`], ['Vent', `${d.vent_diameter_mm} mm`],
    ['Printable', d.printable_solid_watertight ? 'yes' : 'no'],
  ];
  $('design').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  const dl = [['aid_print.stl', 'STL for printing'], ['aid.glb', 'Aid (.glb)'], ['aid_in_ear.glb', 'Aid in ear (.glb)'], ['summary.png', 'Context summary']];
  $('downloads').innerHTML = dl.filter(([f]) => files && files[f]).map(([f, l]) => `<a href="${API}${files[f]}" download>${l}</a>`).join('');
}
function renderRefs(refs) {
  $('refs').querySelector('tbody').innerHTML = refs.map((r) =>
    `<tr><td>${r.clip}</td><td class="n">${r.level_db_spl} dB</td><td class="n">${r.unaided.toFixed(2)}</td><td class="n">${r.ceiling.toFixed(2)}</td></tr>`).join('');
}
$('aidForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!current) return;
  const body = { throat_mm2: +$('throat').value, mouth_mm2: +$('mouth').value, vent_diameter_mm: +$('vent').value };
  const r = await fetch(`${API}/api/patients/${current}/aid`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) { $('log').textContent += `\n${j.detail ? JSON.stringify(j.detail) : 'rebuild failed'}`; return; }
  clearTimeout(timer); poll();
});

// ---------- 3D viewer ----------
const vc = $('viewer');
const renderer = new THREE.WebGLRenderer({ canvas: vc, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.localClippingEnabled = true;
renderer.setClearColor(0x10151b);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 2000);
const controls = new OrbitControls(camera, vc); controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 1.4));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(60, 80, 100); scene.add(sun);
const plane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 1e6);
const mats = {
  shell: new THREE.MeshStandardMaterial({ color: 0xe9e4dc, roughness: .55, transparent: true, opacity: .18, depthWrite: false, side: THREE.DoubleSide, clippingPlanes: [plane] }),
  ear: new THREE.MeshStandardMaterial({ color: 0xd9a38c, roughness: .8, transparent: true, opacity: .22, depthWrite: false, side: THREE.DoubleSide, clippingPlanes: [plane] }),
  bore: new THREE.MeshStandardMaterial({ color: 0xf3922d, roughness: .35, emissive: 0x3a1a00 }),
  vent: new THREE.MeshStandardMaterial({ color: 0x4b93ff, roughness: .35, emissive: 0x001a3a }),
};
let model = null, parts = {}, bbox = new THREE.Box3();
function loadModel(url) {
  new GLTFLoader().load(url, (g) => {
    if (model) scene.remove(model);
    model = g.scene; parts = {};
    model.traverse((o) => {
      if (!o.isMesh) return;
      const n = (o.name + ' ' + (o.parent ? o.parent.name : '')).toLowerCase();
      const k = ['shell', 'bore', 'vent', 'ear'].find((x) => n.includes(x));
      if (k) { o.material = mats[k]; parts[k] = o; o.renderOrder = { bore: 1, vent: 1, shell: 2, ear: 3 }[k]; }
    });
    scene.add(model);
    bbox.setFromObject(parts.shell || model);
    const c = bbox.getCenter(new THREE.Vector3()), r = bbox.getSize(new THREE.Vector3()).length();
    controls.target.copy(c);
    camera.position.copy(c).add(new THREE.Vector3(r * 1.6, r * .35, r * .9));
    camera.near = r / 200; camera.far = r * 50; camera.updateProjectionMatrix();
    $('viewerEmpty').hidden = true;
    parts.ear && (parts.ear.visible = $('showEar').checked);
    cut();
  });
}
function cut() {
  if (bbox.isEmpty()) return;
  const v = +$('cut').value;
  plane.constant = bbox.min.x - 1 + (bbox.max.x - bbox.min.x + 2) * v;
}
$('cut').addEventListener('input', cut);
$('opacity').addEventListener('input', (e) => { mats.shell.opacity = +e.target.value; mats.shell.depthWrite = +e.target.value > .95; });
$('showEar').addEventListener('change', (e) => { if (parts.ear) parts.ear.visible = e.target.checked; });
renderer.setAnimationLoop(() => {
  const w = vc.clientWidth, h = vc.clientHeight;
  if (vc.width !== Math.round(w * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix(); }
  controls.update(); renderer.render(scene, camera);
});

// resume a patient from the URL: index.html#<id>
if (/^[a-f0-9]{12}$/.test(location.hash.slice(1))) watch(location.hash.slice(1));
