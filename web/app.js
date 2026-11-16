// Tension feedback front end: WebSocket (bridge/bridge.py) -> Three.js scene.
//
// Data: protocol v1 (docs/protocol.md), one message every 50 ms. Three feedback designs can be
// switched with the buttons or keys 1/2/3:
//   A  a ring around the left forearm: thickness and colour follow tension
//   B  a light strip along the fretboard: brightness and colour follow tension
//   C  a soft glow at the screen edges (DOM overlay), leaving the centre clear
// C is the default and the design in use; A and B stay reachable with keys 1 / 2 or ?designs=all.
// The scene is in metres with the floor at y = 0 (a seated player), so it could be used in an
// immersive-ar session with a 'local-floor' reference space. That WebXR path is written but has
// never been run on a headset: this is a browser view, WebXR-ready, not an AR application.
//
// Coach loop (11_coach_loop or tools/fake_device.py behind bridge.py --serial):
//   - segment state (recording / thinking / feedback), the coach's sentence, and one line that
//     follows the round trip "LLM -> command -> ack";
//   - a two-track timeline: core 1 (sampler) with the arrival of every tension message and the
//     device's own frame-timing numbers, core 0 with the commands, acks and the thinking time;
//   - space starts / ends a segment, m switches designed / naive, f asks the bridge for a sync
//     flash (white frame + beep on every page, time-stamped in the session log).
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
const TIMELINE_MS = Number(params.get("timeline_ms")) || 30000;   // two-core timeline length
const COACH_SHOW_MS = Number(params.get("coach_ms")) || 15000;    // feedback fades out after this
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
  mode: (params.get("mode") || "C").toUpperCase(),
  rtMode: null,             // "designed" | "naive", from the device (cores, ack) or the bridge status
  simulated: false,         // the device says its core numbers are simulated (tools/fake_device.py)
  hardScale: 1,
  segment: { id: 0, state: "idle", since: 0 },
  coach: null,              // latest coach message
  coachAt: 0,
  loop: null,               // { id, llm, command, ack } for the "LLM -> command -> ack" line
  cores: [],                // {t, msg} last TIMELINE_MS of cores messages
  arrivals: [],             // browser arrival times of emg messages, for the core 1 track
  events: [],               // {t, kind, label} for the core 0 track
  thinking: [],             // {t0, t1} spans between segment end and the coach's reply
  lastCores: null,
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
    if (msg.type === "status") { state.status = msg; onStatus(msg); return; }
    if (msg.v !== 1) return;
    if (msg.type !== "emg") { onLoopMessage(msg, recv); return; }
    state.arrivals.push(recv);
    while (state.arrivals.length && state.arrivals[0] < recv - TIMELINE_MS) state.arrivals.shift();
    state.last = msg;
    state.lastRecvMs = recv;
    if (typeof msg.bridge_rx_ms === "number") pushStat(state.netLat, recv - msg.bridge_rx_ms);
    state.pendingRender.push(recv);
    state.history.push({ t: recv, norm: msg.norm, level: msg.level, saturated: msg.saturated });
    while (state.history.length && state.history[0].t < recv - HISTORY_MS) state.history.shift();
  };
}
function send(obj) {
  if (state.wsOpen) state.ws.send(JSON.stringify(obj));
}

// ---------------------------------------------------------------------------------------------
// Coach loop messages (docs/protocol.md): segment, coach, command, ack, cores, sync
function onStatus(msg) {
  if (msg.mode && !state.lastCores) state.rtMode = msg.mode;
  if (typeof msg.hard_scale === "number") state.hardScale = msg.hard_scale;
  if (msg.segment && msg.segment.state !== state.segment.state) {     // a page opened mid-segment
    state.segment = { id: msg.segment.id, state: msg.segment.state, since: nowMs() };
  }
}
function addEvent(t, kind, label) {
  state.events.push({ t, kind, label });
  while (state.events.length && state.events[0].t < t - TIMELINE_MS) state.events.shift();
}
function onLoopMessage(msg, recv) {
  if (msg.type === "segment") {
    state.segment = { id: msg.id, state: msg.state, since: recv };
    if (msg.state === "recording") { state.coach = null; state.loop = null; }
    if (msg.state === "thinking") state.thinking.push({ t0: recv, t1: null });
  } else if (msg.type === "coach") {
    state.coach = msg;
    state.coachAt = recv;
    const span = state.thinking[state.thinking.length - 1];
    if (span && span.t1 === null) span.t1 = recv;
    state.loop = Object.assign(state.loop || {}, { id: msg.id, coach: msg });
    addEvent(recv, "llm", msg.fallback ? "fallback" : "reply");
  } else if (msg.type === "command") {
    addEvent(recv, msg.cmd === "set_params" ? "params" : "cmd", msg.cmd === "segment" ? msg.state : msg.cmd);
    if (msg.cmd === "set_params") state.loop = Object.assign(state.loop || {}, { command: msg, ack: null });
  } else if (msg.type === "ack") {
    addEvent(recv, "ack", "ack");
    if (msg.applied && typeof msg.applied.hard_scale === "number") state.hardScale = msg.applied.hard_scale;
    if (msg.applied && msg.applied.mode) state.rtMode = msg.applied.mode;
    if (msg.cmd === "set_params" && state.loop && state.loop.command && state.loop.command.seq === msg.seq) {
      state.loop.ack = msg;
    }
  } else if (msg.type === "cores") {
    state.lastCores = msg;
    state.rtMode = msg.mode;
    state.simulated = msg.simulated;
    state.hardScale = msg.hard_scale;
    state.cores.push({ t: recv, msg });
    while (state.cores.length && state.cores[0].t < recv - TIMELINE_MS) state.cores.shift();
  } else if (msg.type === "sync") {
    flash(msg.id);
  }
}

// Sync flash: one white frame and a 1 kHz beep, so a screen recording (or a camera filming the
// screen) can be lined up with the bridge's session log, which has the time stamp.
let audio = null;
function flash(id) {
  const el = document.getElementById("flash");
  el.classList.add("on");
  setTimeout(() => el.classList.remove("on"), 120);
  try {
    audio = audio || new AudioContext();
    const osc = audio.createOscillator(), gain = audio.createGain();
    osc.frequency.value = 1000;
    gain.gain.value = 0.2;
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.12);
  } catch { /* no audio device or autoplay blocked: the flash alone still marks the frame */ }
  send({ type: "sync_shown", id, browser_ms: nowMs() });
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
  placeholders.visible = mode !== "C";      // C leaves the centre clear: no guitar / arm stand-ins
}
document.querySelectorAll("button[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
addEventListener("keydown", (e) => {
  if ({ 1: "A", 2: "B", 3: "C" }[e.key]) setMode({ 1: "A", 2: "B", 3: "C" }[e.key]);
  else if (e.key === " ") { e.preventDefault(); send({ type: "segment", action: "toggle" }); }
  else if (e.key === "m") toggleRtMode();
  else if (e.key === "f") send({ type: "sync" });
});
if (params.get("designs") === "all") $("designs").hidden = false;
function toggleRtMode() {
  send({ type: "mode", mode: state.rtMode === "naive" ? "designed" : "naive" });
}
$("btn-segment").addEventListener("click", () => send({ type: "segment", action: "toggle" }));
$("btn-mode").addEventListener("click", toggleRtMode);
$("btn-sync").addEventListener("click", () => send({ type: "sync" }));
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// WebXR: offer AR only where immersive-ar is supported. Written, never run on a headset.
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
      session.addEventListener("end", () => { placeholders.visible = state.mode !== "C"; scene.background = new THREE.Color(0x121212); });
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
  // The hard thresholds move with the coach's hard_scale (11_coach_loop); medium is fixed.
  const hs = state.hardScale || 1;
  for (const [values, dash] of [[[ENTER[0], ENTER[1] * hs], [6, 4]], [[EXIT[0], EXIT[1] * hs], [2, 4]]]) {
    ctx.setLineDash(dash);
    ctx.strokeStyle = "#666";
    for (const v of values) { ctx.beginPath(); ctx.moveTo(0, y(v)); ctx.lineTo(w, y(v)); ctx.stroke(); }
  }
  ctx.setLineDash([]);
  ctx.lineWidth = 2.5;
  const pts = state.history;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if (b.t - a.t > 250) continue;          // the stream stopped here: leave the gap visible
    const key = b.saturated ? "saturated" : (LEVEL_NAME[b.level] || "nodata");
    ctx.strokeStyle = "#" + COLORS[key].toString(16).padStart(6, "0");
    ctx.beginPath();
    ctx.moveTo(w * (1 - (now - a.t) / HISTORY_MS), y(a.norm));
    ctx.lineTo(w * (1 - (now - b.t) / HISTORY_MS), y(b.norm));
    ctx.stroke();
  }
}

// Two-core timeline (last TIMELINE_MS, newest at the right edge).
//   core 1  top strip: one tick per tension message as it arrived here (a gap = the stream stopped);
//           bars: the device's largest frame-interval deviation per second, log scale 10 us .. 10 s,
//           red when the sampler was blocked or frames were late.
//   core 0  band = the coach is thinking; ticks = commands sent, replies and acks.
const timeline = $("timeline");
const tctx = timeline.getContext("2d");
const EVENT_COLOR = { cmd: "#8FA8DC", params: "#00A087", ack: "#EDEDED", llm: "#4DBBD5" };
const EVENT_LEGEND = [["cmd", "segment / mode"], ["llm", "reply"], ["params", "set_params"], ["ack", "ack"]];
function drawTimeline(now) {
  const w = timeline.width, h = timeline.height, left = 112, right = w - 8;
  const x = (t) => right - ((now - t) / TIMELINE_MS) * (right - left);
  const rows = { c1: [34, 150], c0: [186, 270] };       // [top, bottom] of each track
  tctx.clearRect(0, 0, w, h);
  tctx.font = "22px Arial";
  tctx.textBaseline = "middle";
  tctx.fillStyle = "#EDEDED";
  tctx.fillText("core 1", 4, 58);
  tctx.fillText("core 0", 4, 208);
  tctx.fillStyle = "#9A9A9A";
  tctx.font = "17px Arial";
  tctx.fillText("sampler", 4, 84);
  tctx.fillText("1 kHz + DSP", 4, 106);
  tctx.fillText("output,", 4, 234);
  tctx.fillText("cmd_rx", 4, 256);
  for (const [top, bottom] of Object.values(rows)) {
    tctx.fillStyle = "rgba(255,255,255,0.04)";
    tctx.fillRect(left, top, right - left, bottom - top);
  }
  // core 1: message arrivals
  tctx.fillStyle = "#8C8C8C";
  for (const t of state.arrivals) {
    const px = x(t);
    if (px >= left) tctx.fillRect(px, rows.c1[0], 1.5, 12);
  }
  // core 1: deviation bars (log scale)
  const [top1, bottom1] = [rows.c1[0] + 18, rows.c1[1]];
  const barW = Math.max(3, (right - left) / (TIMELINE_MS / 1000) - 3);
  for (const { t, msg } of state.cores) {
    const px = x(t);
    if (px < left) continue;
    const c1 = msg.core1;
    const bad = c1.blocked_ms > 0 || c1.late > 0;
    const frac = Math.min(1, Math.max(0.03, (Math.log10(Math.max(c1.max_dev_us, 1)) - 1) / 6));   // 10 us .. 10 s
    tctx.fillStyle = bad ? "#E64B35" : "#5f6f8f";
    tctx.fillRect(px - barW, bottom1 - frac * (bottom1 - top1), barW, frac * (bottom1 - top1));
  }
  // core 0: thinking spans, then events
  for (const span of state.thinking) {
    const x0 = Math.max(left, x(span.t0)), x1 = x(span.t1 === null ? now : span.t1);
    if (x1 < left) continue;
    tctx.fillStyle = "rgba(77,187,213,0.28)";
    tctx.fillRect(x0, rows.c0[0], x1 - x0, rows.c0[1] - rows.c0[0]);
    tctx.fillStyle = "#4DBBD5";
    tctx.font = "16px Arial";
    if (x1 - x0 > 70) tctx.fillText("LLM thinking", x0 + 5, rows.c0[0] + 14);
  }
  while (state.thinking.length && state.thinking[0].t1 !== null && state.thinking[0].t1 < now - TIMELINE_MS) state.thinking.shift();
  for (const ev of state.events) {
    const px = x(ev.t);
    if (px < left) continue;
    tctx.fillStyle = EVENT_COLOR[ev.kind] || "#fff";
    const tall = ev.kind === "params" || ev.kind === "ack";
    tctx.fillRect(px - 1.5, rows.c0[tall ? 0 : 0] + (tall ? 26 : 44), 3, rows.c0[1] - rows.c0[0] - (tall ? 26 : 44));
  }
  // legend between the tracks
  let lx = left;
  tctx.font = "15px Arial";
  for (const [kind, label] of EVENT_LEGEND) {
    tctx.fillStyle = EVENT_COLOR[kind];
    tctx.fillRect(lx, 162, 4, 14);
    tctx.fillStyle = "#9A9A9A";
    tctx.fillText(label, lx + 9, 170);
    lx += 9 + tctx.measureText(label).width + 22;
  }
  // time axis
  tctx.fillStyle = "#777";
  tctx.font = "15px Arial";
  for (let sec = 0; sec <= TIMELINE_MS / 1000; sec += 10) {
    const px = right - (sec * 1000 / TIMELINE_MS) * (right - left);
    tctx.fillText(sec === 0 ? "now" : `-${sec} s`, Math.max(left, px - (sec === 0 ? 30 : 18)), h - 10);
  }
}

function drawCoach(now) {
  const seg = state.segment;
  const chip = $("seg-state");
  chip.className = "chip " + seg.state;
  chip.textContent = seg.state;
  const secs = seg.since ? ((now - seg.since) / 1000).toFixed(1) : "";
  $("seg-info").textContent = seg.state === "recording" ? `segment ${seg.id} · ${secs} s`
    : seg.state === "thinking" ? `segment ${seg.id} · waiting for the coach ${secs} s`
    : seg.id ? `segment ${seg.id}` : "press space to start a segment";
  const button = $("btn-segment");
  button.textContent = seg.state === "recording" ? "end segment" : "start segment";
  button.classList.toggle("recording", seg.state === "recording");
  button.disabled = seg.state === "thinking";

  const text = $("coach-text"), line = $("loop-line");
  const c = state.coach;
  const visible = c && seg.state !== "recording" && now - state.coachAt < COACH_SHOW_MS;
  if (c) {
    text.textContent = c.feedback;
    text.classList.toggle("fallback", c.fallback);
  }
  text.classList.toggle("show", !!visible);
  line.classList.toggle("show", !!visible);
  if (!c) return;
  const who = c.llm === "none" ? "no LLM call" : `LLM <b>${c.llm}${c.model && c.model !== "rule" ? " · " + c.model : ""}</b> ${Math.round(c.latency_ms)} ms`;
  let cmd, ack = "";
  if (c.fallback) cmd = `<span class="bad">fallback: last good feedback, no command</span>`;
  else if (c.command_error) cmd = `<span class="bad">command dropped (${c.command_error})</span>`;
  else if (!c.command) cmd = "no command";
  else {
    cmd = `command <b>hard_scale ${c.command.hard_scale.toFixed(2)}</b>${c.clamped ? " (clamped)" : ""}`;
    const a = state.loop && state.loop.ack;
    ack = !c.sent ? ` → <span class="bad">not sent (no downlink)</span>`
      : a ? ` → <span class="ok">ack #${a.seq} at sample ${a.sample_index}</span>`
      : ` → <span class="bad">no ack</span>`;
  }
  line.innerHTML = `${who} → ${cmd}${ack}`;
}

function drawCores() {
  const c = state.lastCores;
  const modePill = $("rt-mode");
  modePill.textContent = `mode ${state.rtMode || "—"}`;
  modePill.className = "pill " + (state.rtMode === "naive" ? "bad" : state.rtMode ? "ok" : "");
  $("btn-mode").textContent = state.rtMode === "naive" ? "switch to designed" : "switch to naive";
  $("sim-tag").hidden = !state.simulated;
  $("cores-note").textContent = state.simulated ? "simulated device · timing from a model" : "";
  if (!c) {
    $("v-core1").textContent = "no cores message (firmware 10 / replay)";
    $("v-core0").textContent = "—";
    return;
  }
  const c1 = c.core1, c0 = c.core0;
  const dev = c1.max_dev_us >= 1000 ? `${(c1.max_dev_us / 1000).toFixed(0)} ms` : `${c1.max_dev_us} µs`;
  $("v-core1").textContent = `max deviation ${dev} · late ${c1.late} · ovf ${c1.ovf}` + (c1.blocked_ms ? ` · BLOCKED ${c1.blocked_ms} ms` : "");
  $("v-core0").textContent = `commands ${c0.cmd_rx} · rejected ${c0.parse_fail} · applied ${c0.applied}`;
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
  drawTimeline(now);
  drawCoach(now);
  drawCores();
}
renderer.setAnimationLoop(frame);

setMode(["A", "B", "C"].includes(state.mode) ? state.mode : "C");
connect();
