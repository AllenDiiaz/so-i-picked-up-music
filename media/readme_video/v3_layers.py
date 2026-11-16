"""Vector layers for the README GIF (1600x900): header, architecture groups, circuit base. Exports PNG layers + geometry."""
import json
from pathlib import Path
import numpy as np

OUT = Path(__file__).parent / "v3"; OUT.mkdir(exist_ok=True)
W, H = 1600, 900
INK, MUTED, RULE = "#1E2430", "#7A7F87", "#D9D6CE"
SERIF = "font-family:Lora,serif"; SANS = "font-family:Inter,sans-serif"
C_3V3, C_GND, C_SIG, C_LED, C_BTN = "#D1495B", "#2B2D31", "#00A087", "#3C5488", "#4DBBD5"
L_RED, L_YEL, L_GRN = "#D1495B", "#E3B23C", "#3A8F6B"
GOLD = "#C8A96A"
GEOM = {}

def T(x, y, t, size=16, w=400, fill=INK, anchor="start", fam=SANS, extra=""):
    return f'<text x="{x}" y="{y}" style="{fam};font-size:{size}px;font-weight:{w};{extra}" fill="{fill}" text-anchor="{anchor}">{t}</text>'

def route(pts, r=16, n=10):
    """Orthogonal polyline with rounded corners -> dense point list."""
    pts = [np.array(p, float) for p in pts]; out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        u = (b - a) / np.linalg.norm(b - a); v = (c - b) / np.linalg.norm(c - b)
        rr = min(r, np.linalg.norm(b - a) / 2, np.linalg.norm(c - b) / 2)
        p0, p2 = b - u * rr, b + v * rr
        for t in np.linspace(0, 1, n):
            out.append((1 - t) ** 2 * p0 + 2 * (1 - t) * t * b + t ** 2 * p2)
    out.append(pts[-1])
    dense = []
    for p, q in zip(out[:-1], out[1:]):
        k = max(2, int(np.linalg.norm(q - p) / 4))
        for t in np.linspace(0, 1, k, endpoint=False): dense.append((p + (q - p) * t).tolist())
    dense.append(out[-1].tolist()); return dense

def wire_svg(pts, col, w=6):
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity="0.3" stroke-width="1.6" stroke-linecap="round"/>')

def pin(x, y, used=False):
    return (f'<rect x="{x-6}" y="{y-6}" width="12" height="12" rx="2" fill="{GOLD if used else "#8E8E8E"}"/>'
            f'<circle cx="{x}" cy="{y}" r="2.6" fill="#3A3A3A"/>')

# ======================= header =======================
header = (T(W / 2, 66, "So I Picked Up Music", 46, 700, INK, "middle", SERIF)
          + T(W / 2, 100, "Seeing forearm muscle tension while learning guitar", 20, 500, "#3C4656", "middle")
          + T(W / 2, 128, "ESP32-S3  ·  SURFACE EMG  ·  ON-DEVICE DSP  ·  LIVE FEEDBACK", 12, 600, MUTED, "middle", SANS, "letter-spacing:2.5px")
          + f'<line x1="{W/2-170}" y1="146" x2="{W/2+170}" y2="146" stroke="{RULE}" stroke-width="1.2"/>'
          + f'<rect x="{W/2-4}" y="142" width="8" height="8" transform="rotate(45 {W/2} 146)" fill="#8FA3BF"/>')

# ======================= architecture =======================
A = {}
panel = f'<rect x="40" y="172" width="{W-80}" height="636" rx="22" fill="#FBF8F1"/>'
A["panel"] = panel
cy = 430
# 1 forearm illustration (BioRender-style, see arm_svg.py)
import sys as _s; _s.path.insert(0, str(Path(__file__).parent))
from arm_svg import forearm
arm = forearm(66, cy, 0.84)
arm += T(210, cy + 140, "Surface EMG", 19, 700, INK, "middle") + T(210, cy + 164, "3 snap electrodes, left forearm", 14, 500, MUTED, "middle")
A["arm"] = arm
# 2 AD8232
ax = 440
ad = (f'<rect x="{ax}" y="{cy-62}" width="150" height="124" rx="10" fill="#5B4A7A"/>'
      f'<rect x="{ax+20}" y="{cy-18}" width="38" height="38" rx="3" fill="#232026"/>'
      + "".join(f'<rect x="{ax+72+i*12}" y="{cy-52}" width="7" height="7" fill="{GOLD}"/>' for i in range(6))
      + T(ax + 108, cy + 8, "AD8232", 15, 700, "#EDE7F6", "middle")
      + T(ax + 75, cy + 140, "Analog front end", 19, 700, INK, "middle") + T(ax + 75, cy + 164, "gain ≈ 1000, band-limit", 14, 500, MUTED, "middle"))
A["ad"] = ad
# 3 ESP32 + DSP chain
ex = 690
esp = (f'<rect x="{ex-16}" y="{cy-128}" width="420" height="262" rx="16" fill="#E6F4EF"/>'
       + T(ex + 194, cy - 102, "ESP32-S3  ·  FreeRTOS, core 1", 14, 700, "#0F6E56", "middle")
       + f'<rect x="{ex}" y="{cy-78}" width="132" height="190" rx="10" fill="#1F2328"/>'
       f'<rect x="{ex+14}" y="{cy-62}" width="104" height="70" rx="5" fill="#C9CCD1"/>'
       + T(ex + 66, cy - 22, "ESP32-S3", 13, 700, "#2B2D31", "middle")
       + "".join(f'<rect x="{ex+10+i*14}" y="{cy+92}" width="7" height="7" fill="{GOLD}"/>' for i in range(8)))
steps = ["ADC 1 kHz · DMA", "60 Hz notch", "45–200 Hz band-pass", "RMS → level"]
for i, s in enumerate(steps):
    y = cy - 74 + i * 52
    esp += f'<rect x="{ex+156}" y="{y}" width="222" height="38" rx="19" fill="#FFFFFF" stroke="#7BC8B4" stroke-width="1.5"/>'
    esp += T(ex + 267, y + 25, s, 15, 600, "#0F4F40", "middle")
    if i: esp += f'<path d="M{ex+267},{y-12} L{ex+267},{y-2}" stroke="#7BC8B4" stroke-width="2"/>'
esp += T(ex + 194, cy + 160, "On-device signal processing", 19, 700, INK, "middle") + T(ex + 194, cy + 184, "every 50 ms: tension level 0 / 1 / 2", 14, 500, MUTED, "middle")
A["esp"] = esp
# 4 laptop
lx = 1172
lap = (f'<rect x="{lx}" y="{cy-50}" width="120" height="80" rx="6" fill="#2B2F36"/><rect x="{lx+7}" y="{cy-43}" width="106" height="66" rx="3" fill="#DDE6F2"/>'
       f'<path d="M{lx-14},{cy+36} L{lx+134},{cy+36} L{lx+124},{cy+46} L{lx-4},{cy+46} Z" fill="#9AA1AB"/>'
       + "".join(f'<rect x="{lx+16}" y="{cy-34+k*14}" width="{70-k*14}" height="6" rx="3" fill="#8FA3BF"/>' for k in range(4))
       + T(lx + 60, cy + 140, "Bridge", 19, 700, INK, "middle") + T(lx + 60, cy + 164, "USB serial → WebSocket", 14, 500, MUTED, "middle"))
A["lap"] = lap
# 5 browser
bx = 1372
br = (f'<rect x="{bx}" y="{cy-62}" width="156" height="124" rx="10" fill="#fff" stroke="#C9CED6" stroke-width="2"/>'
      f'<rect x="{bx}" y="{cy-62}" width="156" height="24" rx="10" fill="#EEF1F5"/>'
      + "".join(f'<circle cx="{bx+16+k*14}" cy="{cy-50}" r="4" fill="{c}"/>' for k, c in enumerate(["#E6A19A", "#E8C77D", "#9CCB9E"]))
      + f'<circle cx="{bx+78}" cy="{cy+12}" r="30" fill="none" stroke="#00A087" stroke-width="7"/>'
      + T(bx + 78, cy + 140, "Live view", 19, 700, INK, "middle") + T(bx + 78, cy + 164, "browser 3D (Three.js)", 14, 500, MUTED, "middle"))
A["br"] = br
nxt = (f'<rect x="{bx-6}" y="{cy+272}" width="168" height="54" rx="27" fill="none" stroke="#9AA3B0" stroke-width="1.6" stroke-dasharray="5 5"/>'
       + T(bx + 78, cy + 295, "Next", 13, 700, MUTED, "middle") + T(bx + 78, cy + 315, "WebXR · AI feedback", 13, 500, MUTED, "middle"))
A["next"] = nxt
# arrows (geometry for pulses) + tiny labels
ARROWS = [((380, cy), (432, cy), "~1 mV"), ((598, cy), (668, cy), "0–3.3 V"), ((1112, cy), (1158, cy), "level"), ((1306, cy), (1362, cy), "")]
arr = ""
for (p, q, lab) in ARROWS:
    arr += f'<line x1="{p[0]}" y1="{p[1]}" x2="{q[0]-8}" y2="{q[1]}" stroke="#3C4656" stroke-width="2.4"/>'
    arr += f'<path d="M{q[0]-12},{q[1]-7} L{q[0]},{q[1]} L{q[0]-12},{q[1]+7} Z" fill="#3C4656"/>'
    if lab: arr += T((p[0] + q[0]) / 2, cy - 14, lab, 12, 600, MUTED, "middle")
A["arrows"] = arr
GEOM["arch_arrows"] = [[p, q] for p, q, _ in ARROWS]
# layer bracket
br_ = ""
for x0, x1, lab in [(60, 600, "body + analog"), (674, 1094, "real-time firmware · 1 kHz"), (1150, 1540, "computer")]:
    br_ += f'<path d="M{x0},{cy+212} L{x0},{cy+222} L{x1},{cy+222} L{x1},{cy+212}" fill="none" stroke="#B8B4AA" stroke-width="1.5"/>'
    br_ += T((x0 + x1) / 2, cy + 246, lab, 13, 600, MUTED, "middle", SANS, "letter-spacing:1.5px;text-transform:uppercase")
A["brackets"] = br_.replace(f'{1150}, {1540}', '')

# ======================= circuit (orthogonal, rounded) =======================
C = ""
ex0, ey0, ew, eh = 640, 214, 720, 196
C += f'<rect x="{ex0}" y="{ey0}" width="{ew}" height="{eh}" rx="14" fill="#1F2328"/>'
C += f'<rect x="{ex0+14}" y="{ey0+40}" width="150" height="116" rx="6" fill="#C9CCD1"/><rect x="{ex0+14}" y="{ey0+40}" width="30" height="116" rx="4" fill="#2C3036"/>'
C += T(ex0 + 104, ey0 + 96, "ESP32-S3", 18, 700, "#2B2D31", "middle") + T(ex0 + 104, ey0 + 118, "N16R8", 12, 500, "#5A5E66", "middle")
for k in range(2): C += f'<rect x="{ex0+ew-20}" y="{ey0+46+k*76}" width="28" height="40" rx="5" fill="#B8BCC2"/>'
C += T(ex0 + ew - 120, ey0 + 98, "BOOT   RST", 11, 600, "#9AA0A8", "middle")
J1 = ["3V3", "3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46", "9", "10", "11", "12", "13", "14", "5V", "GND"]
p0x, pitch = 862, 22
P = {}
for i, lab in enumerate(J1):
    x = p0x + i * pitch; used = i in (0, 3, 4, 5, 21)
    C += pin(x, ey0 + eh - 16, used) + pin(x, ey0 + 16, i == 0)
    C += f'<text x="{x+4}" y="{ey0+eh-30}" transform="rotate(-90 {x+4} {ey0+eh-30})" style="{SANS};font-size:10px;font-weight:{700 if used else 400}" fill="{"#F2F2F2" if used else "#7D838C"}">{("GPIO"+lab) if lab.isdigit() else lab}</text>'
    P[i] = (x, ey0 + eh - 16)
PT = (p0x, ey0 + 16)
C += T(PT[0], ey0 + 44, "GND", 10, 700, "#F2F2F2", "middle")
C += T(ex0 + ew - 10, ey0 - 12, "ESP32-S3-DevKitC-1", 16, 700, INK, "end")
# AD8232
ax0, ay0, aw, ah = 300, 500, 250, 170
C += f'<rect x="{ax0}" y="{ay0}" width="{aw}" height="{ah}" rx="12" fill="#5B4A7A"/>'
C += f'<rect x="{ax0+40}" y="{ay0+82}" width="46" height="46" rx="4" fill="#232026"/>'
C += T(ax0 + 168, ay0 + 112, "AD8232", 17, 700, "#EDE7F6", "middle") + T(ax0 + 168, ay0 + 132, "EMG front end", 11, 500, "#CFC4E3", "middle")
APIN = ["GND", "3.3v", "OUTPUT", "LO-", "LO+", "SDN"]; AP = {}
for i, lab in enumerate(APIN):
    x = ax0 + 34 + i * 38; y = ay0 + 18; used = i < 3
    C += pin(x, y, used); AP[lab] = (x, y)
    C += f'<text x="{x+4}" y="{y+18}" transform="rotate(90 {x+4} {y+18})" style="{SANS};font-size:10px;font-weight:{700 if used else 400}" fill="{"#F4EFFA" if used else "#B9AED0"}">{lab}</text>'
jack = (ax0 - 4, ay0 + 104)
C += f'<rect x="{ax0-28}" y="{ay0+86}" width="52" height="36" rx="5" fill="#2A2730"/>'
C += T(ax0 + aw / 2, ay0 + ah + 26, "AD8232 module", 16, 700, INK, "middle")
W_ = {}
W_["w_gnd"] = (route([AP["GND"], (AP["GND"][0], 190), (PT[0], 190), PT]), C_GND)
W_["w_3v3"] = (route([AP["3.3v"], (AP["3.3v"][0], 452), (P[0][0], 452), P[0]]), C_3V3)
W_["w_sig"] = (route([AP["OUTPUT"], (AP["OUTPUT"][0], 478), (P[3][0], 478), P[3]]), C_SIG)
yb, yl = 560, 690; gx = P[21][0]; BTN = (1150, yb); rx0 = 1060; LED = (rx0 + 150, yl)
W_["w_btn"] = (route([P[5], (P[5][0], yb), (BTN[0] - 30, yb)]), C_BTN)
W_["w_led"] = (route([P[4], (P[4][0], yl), (rx0, yl)]), C_LED)
W_["g_btn"] = (route([(BTN[0] + 30, yb), (gx, yb)]), C_GND)
W_["g_led"] = (route([(LED[0] + 22, yl), (gx, yl), P[21]]), C_GND)
EL = [(90, 330, L_RED, "+", "flexor"), (90, 480, L_YEL, "−", "flexor, 2–3 cm"), (90, 630, L_GRN, "REF", "elbow")]
for k, (x, y, col, sym, wh) in enumerate(EL):
    xk = 214 - k * 22; jy = jack[1] - 10 + k * 10
    W_[f"w_lead{k}"] = (route([(x + 34, y), (xk, y), (xk, jy), (jack[0] - 24, jy)], 14), col)
for name, (pts, col) in W_.items():
    C += wire_svg(pts, col, 5 if name.startswith("w_lead") else 6)
for k, (x, y, col, sym, wh) in enumerate(EL):
    C += f'<circle cx="{x}" cy="{y}" r="34" fill="#fff" stroke="#D8D4CC" stroke-width="2"/><circle cx="{x}" cy="{y}" r="14" fill="#B9C4CC"/><circle cx="{x}" cy="{y}" r="7" fill="{col}"/>'
    C += T(x - 46, y + 6, sym, 16, 700, col, "end") + T(x, y + 54, wh, 12, 500, MUTED, "middle")
C += T(90, 278, "left forearm", 14, 700, INK, "middle")
C += f'<rect x="{BTN[0]-30}" y="{yb-30}" width="60" height="60" rx="6" fill="#2F3338"/><circle cx="{BTN[0]}" cy="{yb}" r="16" fill="#15181C"/>'
C += T(BTN[0], yb + 52, "recalibrate", 12, 600, MUTED, "middle")
C += f'<line x1="{rx0}" y1="{yl}" x2="{rx0+12}" y2="{yl}" stroke="#9A9A9A" stroke-width="3"/><rect x="{rx0+12}" y="{yl-10}" width="96" height="20" rx="10" fill="#E8DCC4"/>'
C += "".join(f'<rect x="{rx0+28+k*17}" y="{yl-10}" width="7" height="20" fill="{c}"/>' for k, c in enumerate(["#6B4E2E", "#6B4E2E", "#7A4A1F", "#C8A96A"]))
C += f'<line x1="{rx0+108}" y1="{yl}" x2="{LED[0]-22}" y2="{yl}" stroke="#9A9A9A" stroke-width="3"/>'
C += T(rx0 + 60, yl - 20, "330 Ω", 12, 600, MUTED, "middle")
C += f'<circle cx="{LED[0]}" cy="{LED[1]}" r="22" fill="#E9A3A0" stroke="#C9504A" stroke-width="2"/>' + T(LED[0], yl + 46, "LED", 12, 600, MUTED, "middle")
lg = [(C_3V3, "3V3"), (C_GND, "ground"), (C_SIG, "EMG → GPIO4"), (C_LED, "GPIO5 → LED"), (C_BTN, "GPIO6 ← button")]
for k, (c, t) in enumerate(lg):
    y = 470 + k * 34
    C += f'<path d="M1372,{y} L1406,{y}" stroke="{c}" stroke-width="6" stroke-linecap="round"/>' + T(1418, y + 5, t, 13, 500, INK)
GEOM["wires"] = {k: v[0] for k, v in W_.items()}
GEOM["wire_colors"] = {k: v[1] for k, v in W_.items()}
GEOM["led"] = LED; GEOM["module"] = [ex0 + 14, ey0 + 40, ex0 + 164, ey0 + 156]
GEOM["scope"] = [590, 560, 900, 790]

# ======================= render layers =======================
def svg(body): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{body}</svg>'
layers = {"header": header, "circuit": C, **{"arch_" + k: v for k, v in A.items()}}
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    for name, body in layers.items():
        pg.set_content(f'<html><body style="margin:0;background:transparent">{svg(body)}</body></html>'); pg.wait_for_timeout(150)
        pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
    b.close()
(OUT / "geom.json").write_text(json.dumps(GEOM))
print("layers:", list(layers))
