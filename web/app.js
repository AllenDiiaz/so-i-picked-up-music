// Tension feedback front end: WebSocket (bridge/bridge.py) -> Three.js scene.
//
// Data: protocol v1 (docs/protocol.md), one message every 50 ms. Three feedback designs can be
// switched with the buttons or keys 1/2/3:
//   A  a ring around the left forearm: thickness and colour follow tension
//   B  a light strip along the fretboard: brightness and colour follow tension
//   C  a soft glow at the screen edges (DOM overlay), leaving the centre clear
// The scene is in metres with the floor at y = 0 (a seated player), so it can be used as is in
// an immersive-ar session with a 'local-floor' reference space. WebXR is untested on Quest.
import * as THREE from "three";

// ---------------------------------------------------------------------------------------------
// Configuration
const params = new URLSearchParams(location.search);
const WS_URL = params.get("ws") || `ws://${location.hostname || "localhost"}:8765`;
const COLORS = {
  relax: 0x8c8c8c, medium: 0x00a087, hard: 0xe64b35, chord: 0x3c5488,
  calibrating: 0x4dbbd5, saturated: 0xf39b7f, nodata: 0x3b3b3b,
};
const LEVEL_NAME = { 0: "relax", 1: "medium", 2: "hard" };
// No device message for this long -> "no data". ?nodata_ms= lets the screenshot test pause the stream.
const NO_DATA_MS = Number(params.get("nodata_ms")) || 1000;
const HISTORY_MS = 10000;       // chart length
// Thresholds of the 07 firmware (emg_dsp.h), drawn in the chart. Provisional.
const ENTER = [1.49, 2.72];
const EXIT = [1.35, 2.45];

// Smoothing. Messages arrive every 50 ms, so unsmoothed values step at 20 Hz and visibly
// flicker. Each displayed value follows its target with an exponential filter of time constant
// TAU_MS: a step reaches 63 % after 60 ms, 81 % after 100 ms and half-way after ~42 ms. That
// keeps the extra visual delay well under 100 ms while removing the 20 Hz staircase; a longer
// TAU would look calmer but lag behind real changes in tension.
const TAU_MS = 60;

// ---------------------------------------------------------------------------------------------
// State
const state = {
  mode: (params.get("mode") || localStorageGet("mode") || "A").toUpperCase(),
  ws: null,
  wsOpen: false,
  last: null,               // latest device message
  lastRecvMs: 0,            // browser clock (epoch ms) of its arrival
  status: null,             // latest bridge status message
  history: [],              // {t, norm, level} for the chart (browser clock)
  pendingRender: [],        // arrival times of messages not yet shown in a rendered frame
  netLat: [],               // bridge_rx -> browser arrival (ms)
  renderLat: [],            // browser arrival -> frame rendered (ms)
  display: { intensity: 0, color: new THREE.Color(COLORS.nodata) },
  frames: 0,
};
window.__mvp = state;       // for debugging and headless screenshots

function localStorageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function localStorageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
}
const nowMs = () => performance.timeOrigin + performance.now();   // same clock as bridge_rx_ms

// ---------------------------------------------------------------------------------------------
// WebSocket with automatic reconnect
let reconnectDelay = 500;
function connect() {
  const ws = new WebSocket(WS_URL);
  state.ws = ws;
  ws.onopen = () => { state.wsOpen = true; reconnectDelay = 500; };
  ws.onclose = () => {
    state.wsOpen = false;
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 5000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (ev) => {
    const recv = nowMs();
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "status") { state.status = msg; return; }
    if (msg.type !== "emg" || msg.v !== 1) return;
    state.last = msg;
    state.lastRecvMs = recv;
    if (typeof msg.bridge_rx_ms === "number") pushStat(state.netLat, recv - msg.bridge_rx_ms);
    state.pendingRender.push(recv);
    state.history.push({ t: recv, norm: msg.norm, level: msg.level, saturated: msg.saturated });
    while (state.history.length && state.history[0].t < recv - HISTORY_MS) state.history.shift();
  };
}
function pushStat(list, value) {
  list.push(value);
  if (list.length > 40) list.shift();
}
const mean = (list) => (list.length ? list.reduce((a, b) => a + b, 0) / list.length : NaN);

// What the display should show right now.
function currentView() {
  if (!state.wsOpen) return { key: "nodata", label: "bridge not connected", intensity: 0 };
  const m = state.last;
  if (!m || nowMs() - state.lastRecvMs > NO_DATA_MS) return { key: "nodata", label: "no data", intensity: 0 };
  if (m.calibrating) return { key: "calibrating", label: "calibrating — relax", intensity: 0.35, pulse: true };
  if (m.saturated) return { key: "saturated", label: "saturated — check electrodes", intensity: 0.5, pulse: true };
  if (m.level < 0) return { key: "nodata", label: "no baseline yet", intensity: 0 };
  // 0 at the relax baseline, 1 at 1.3x the hard entry ratio.
  const intensity = Math.min(1, Math.max(0, (m.norm - 1) / (ENTER[1] * 1.3 - 1)));
  return { key: LEVEL_NAME[m.level], label: LEVEL_NAME[m.level], intensity };
}

// ---------------------------------------------------------------------------------------------
// Scene (metres, floor at y = 0)
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.domElement.className = "webgl";
renderer.xr.enabled = true;
document.body.prepend(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x121212);
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.01, 20);
camera.position.set(0.05, 1.32, 0.55);           // roughly the player's eyes
camera.lookAt(-0.12, 0.98, -0.12);
scene.add(new THREE.HemisphereLight(0xffffff, 0x222222, 1.4));
const sun = new THREE.DirectionalLight(0xffffff, 1.0);
sun.position.set(0.5, 2, 1);
scene.add(sun);

// Placeholders for the real guitar and arm; hidden in AR, where the real ones are visible.
const placeholders = new THREE.Group();
scene.add(placeholders);
const ghost = new THREE.MeshStandardMaterial({ color: 0x5a5a5a, transparent: true, opacity: 0.35, roughness: 0.9 });
const body = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.19, 0.1, 40), ghost);
body.rotation.x = Math.PI / 2;
body.scale.set(1, 1, 1.25);
body.position.set(0.18, 0.92, -0.18);
placeholders.add(body);

// Guitar neck: from the body towards the player's left, slightly raised.
const neckStart = new THREE.Vector3(0.0, 0.95, -0.16);
const neckEnd = new THREE.Vector3(-0.52, 1.06, -0.08);
const neckDir = neckEnd.clone().sub(neckStart);
const neckLength = neckDir.length();
const neckMid = neckStart.clone().add(neckEnd).multiplyScalar(0.5);
const neckQuat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(1, 0, 0), neckDir.clone().normalize());
const neck = new THREE.Mesh(new THREE.BoxGeometry(neckLength, 0.022, 0.05), ghost);
neck.position.copy(neckMid);
neck.quaternion.copy(neckQuat);
placeholders.add(neck);

// Left forearm: elbow near the body, wrist at the neck (fretting hand).
const elbow = new THREE.Vector3(-0.2, 0.9, 0.2);
const wrist = new THREE.Vector3(-0.38, 1.02, -0.05);
const armDir = wrist.clone().sub(elbow);
const armMid = elbow.clone().add(wrist).multiplyScalar(0.5);
const armQuat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), armDir.clone().normalize());
const forearm = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.04, armDir.length(), 24), ghost);
forearm.position.copy(armMid);
forearm.quaternion.copy(armQuat);
placeholders.add(forearm);

// A: ring around the forearm (flexor belly, 40 % from the elbow). Its tube is rebuilt only
// when the thickness changes noticeably.
const ringMaterial = new THREE.MeshStandardMaterial({ color: COLORS.relax, emissive: COLORS.relax, emissiveIntensity: 0.6 });
let ringTube = -1;
const ring = new THREE.Mesh(new THREE.TorusGeometry(0.052, 0.004, 16, 64), ringMaterial);
ring.position.copy(elbow.clone().lerp(wrist, 0.4));
ring.quaternion.copy(armQuat).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
scene.add(ring);
function setRingThickness(tube) {
  if (Math.abs(tube - ringTube) < 0.0004) return;
  ringTube = tube;
  ring.geometry.dispose();
  ring.geometry = new THREE.TorusGeometry(0.052, tube, 16, 64);
}

// B: light strip along the fretboard, just above it.
const stripMaterial = new THREE.MeshBasicMaterial({ color: COLORS.relax, transparent: true, opacity: 0.2 });
const strip = new THREE.Mesh(new THREE.BoxGeometry(neckLength * 0.92, 0.003, 0.012), stripMaterial);
strip.position.copy(neckMid).add(new THREE.Vector3(0, 0.014, 0).applyQuaternion(neckQuat));
strip.quaternion.copy(neckQuat);
scene.add(strip);
const stripGlowMaterial = new THREE.MeshBasicMaterial({
  color: COLORS.relax, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false,
});
const stripGlow = new THREE.Mesh(new THREE.BoxGeometry(neckLength * 0.95, 0.008, 0.04), stripGlowMaterial);
stripGlow.position.copy(strip.position);
stripGlow.quaternion.copy(neckQuat);
scene.add(stripGlow);

// C: edge glow is the #edge-glow DOM element.
const edgeGlow = document.getElementById("edge-glow");

// ---------------------------------------------------------------------------------------------
// UI
const $ = (id) => document.getElementById(id);
function setMode(mode) {
  state.mode = mode;
  localStorageSet("mode", mode);
  document.querySelectorAll("button[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  ring.visible = mode === "A";
  strip.visible = stripGlow.visible = mode === "B";
  edgeGlow.style.display = mode === "C" ? "block" : "none";
}
document.querySelectorAll("button[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
addEventListener("keydown", (e) => { if ({ 1: "A", 2: "B", 3: "C" }[e.key]) setMode({ 1: "A", 2: "B", 3: "C" }[e.key]); });
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// WebXR: offer AR only where immersive-ar is supported. Untested on Quest.
if (navigator.xr) {
  navigator.xr.isSessionSupported("immersive-ar").then((ok) => {
    if (!ok) return;
    const button = $("enter-ar");
    button.hidden = false;
    button.addEventListener("click", async () => {
      renderer.xr.setReferenceSpaceType("local-floor");
      const session = await navigator.xr.requestSession("immersive-ar", {
        requiredFeatures: ["local-floor"],
        optionalFeatures: ["dom-overlay"],
        domOverlay: { root: $("overlay") },
      });
      placeholders.visible = false;
      scene.background = null;              // pass-through
      session.addEventListener("end", () => { placeholders.visible = true; scene.background = new THREE.Color(0x121212); });
      await renderer.xr.setSession(session);
    });
  }).catch(() => {});
}

// Chart: last 10 s of norm, coloured by level, with entry (dashed) and exit (dotted) thresholds.
const chart = $("chart");
const ctx = chart.getContext("2d");
function drawChart(now) {
  const w = chart.width, h = chart.height, top = 4.5;
  const y = (v) => h - (Math.min(v, top) / top) * h;
  ctx.clearRect(0, 0, w, h);
  ctx.lineWidth = 1;
  for (const [values, dash] of [[ENTER, [6, 4]], [EXIT, [2, 4]]]) {
    ctx.setLineDash(dash);
    ctx.strokeStyle = "#666";
    for (const v of values) { ctx.beginPath(); ctx.moveTo(0, y(v)); ctx.lineTo(w, y(v)); ctx.stroke(); }
  }
  ctx.setLineDash([]);
  ctx.lineWidth = 2.5;
  const pts = state.history;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const key = b.saturated ? "saturated" : (LEVEL_NAME[b.level] || "nodata");
    ctx.strokeStyle = "#" + COLORS[key].toString(16).padStart(6, "0");
    ctx.beginPath();
    ctx.moveTo(w * (1 - (now - a.t) / HISTORY_MS), y(a.norm));
    ctx.lineTo(w * (1 - (now - b.t) / HISTORY_MS), y(b.norm));
    ctx.stroke();
  }
}

// ---------------------------------------------------------------------------------------------
// Frame loop
const target = new THREE.Color();
let lastFrame = performance.now();
function frame() {
  const t = performance.now();
  const dt = Math.min(100, t - lastFrame);
  lastFrame = t;
  const now = nowMs();
  const view = currentView();

  // Exponential approach with TAU_MS (see the comment at the top).
  const k = 1 - Math.exp(-dt / TAU_MS);
  let goal = view.intensity;
  if (view.pulse) goal *= 0.6 + 0.4 * Math.sin(t / 250);      // calibrating / saturated: slow pulse
  state.display.intensity += (goal - state.display.intensity) * k;
  target.setHex(COLORS[view.key]);
  state.display.color.lerp(target, k);
  const level = state.display.intensity;
  const color = state.display.color;

  // A: forearm ring
  setRingThickness(0.003 + 0.017 * level);
  ringMaterial.color.copy(color);
  ringMaterial.emissive.copy(color);
  ringMaterial.emissiveIntensity = view.key === "nodata" ? 0.05 : 0.4 + 1.2 * level;
  // B: fretboard strip
  stripMaterial.color.copy(color);
  stripMaterial.opacity = view.key === "nodata" ? 0.08 : 0.35 + 0.65 * level;
  stripGlowMaterial.color.copy(color);
  stripGlowMaterial.opacity = view.key === "nodata" ? 0 : 0.6 * level;
  // C: edge glow
  const css = "#" + color.getHexString();
  edgeGlow.style.boxShadow = `inset 0 0 ${60 + 120 * level}px ${20 + 60 * level}px ${css}`;
  edgeGlow.style.opacity = view.key === "nodata" ? 0.15 : (0.25 + 0.75 * level).toFixed(3);

  renderer.render(scene, camera);
  state.frames++;
  const rendered = nowMs();
  for (const recv of state.pendingRender) pushStat(state.renderLat, rendered - recv);
  state.pendingRender.length = 0;

  // Panel (cheap enough to update every frame)
  const conn = $("conn");
  conn.textContent = state.wsOpen ? `bridge connected · ${WS_URL}` : `bridge not connected · retrying ${WS_URL}`;
  conn.className = "pill " + (state.wsOpen ? (view.key === "nodata" ? "warn" : "ok") : "bad");
  $("state-dot").style.background = css;
  $("state-text").textContent = view.label;
  const m = state.last;
  $("v-norm").textContent = !m || view.key === "nodata" ? "—"
    : m.calibrating || m.baseline_mV <= 0 ? `— (${m.rms_mV.toFixed(1)} mV)` : `${m.norm.toFixed(2)}×  (${m.rms_mV.toFixed(1)} mV)`;
  $("v-base").textContent = m && m.baseline_mV > 0 ? `${m.baseline_mV.toFixed(2)} mV` : "—";
  const net = mean(state.netLat), ren = mean(state.renderLat);
  $("v-net").textContent = Number.isFinite(net) ? `${net.toFixed(1)} ms` : "—";
  $("v-render").textContent = Number.isFinite(ren) ? `${ren.toFixed(1)} ms` : "—";
  const s = state.status;
  $("v-loss").textContent = s && s.received + s.lost > 0
    ? `${(100 * s.lost / (s.received + s.lost)).toFixed(2)} % (${s.lost} of ${s.received + s.lost})` : "—";
  drawChart(now);
}
renderer.setAnimationLoop(frame);

setMode(["A", "B", "C"].includes(state.mode) ? state.mode : "A");
connect();
