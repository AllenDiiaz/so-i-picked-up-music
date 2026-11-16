"""v5 architecture (1600x900): a Sensing | b On-device processing | c Feedback, closed loop back to the player.
Arm = Allen's licensed BioRender illustration (cleaned + mirrored by arm_extract.py)."""
import sys, base64, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import v3_layers as V
W, H, T, route = V.W, V.H, V.T, V.route
OUT = Path(__file__).parent / "v5"; OUT.mkdir(exist_ok=True)
INK, MUTED = V.INK, V.MUTED
TEAL, ORANGE, LAV, LINE = "#00A087", "#F08A24", "#9C8BE8", "#3C4656"
PLAN = "#8A93A1"
L, GEO = {}, {}
def path_d(pts): return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
def head(p, q, col, w=2.2):                     # small open chevron at q, pointing along p->q
    import numpy as np
    p, q = np.array(p, float), np.array(q, float); u = (q - p) / np.linalg.norm(q - p); n = np.array([-u[1], u[0]])
    a, b = q - u * 9 + n * 5.5, q - u * 9 - n * 5.5
    return f'<path d="M{a[0]:.1f},{a[1]:.1f} L{q[0]:.1f},{q[1]:.1f} L{b[0]:.1f},{b[1]:.1f}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'
def wire(pts, col=LINE, dash=False, w=2.0, r=14):
    d = route(pts, r); s = f'<path d="{path_d(d)}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"{" stroke-dasharray=\'5 6\'" if dash else ""}/>'
    return s + head(d[-6], d[-1], col, w), d

cy = 420
L["panel"] = f'<rect x="40" y="172" width="{W-80}" height="636" rx="22" fill="#FBF8F1"/>'
# ---------- section letters (Nature-style panel labels) ----------
def sec(x, letter, name):
    return T(x, 214, letter, 22, 800, INK) + T(x + 22, 213, name, 12, 700, "#6B7280", extra="letter-spacing:2.4px")
L["sec"] = sec(72, "a", "SENSING") + sec(520, "b", "ON-DEVICE PROCESSING") + sec(1264, "c", "FEEDBACK")

# ---------- a · arm (licensed BioRender art) + electrodes + leads ----------
arm_b64 = base64.b64encode((Path(__file__).parent / "arm" / "bio_arm_cream.png").read_bytes()).decode()
ax0, ay0, sc = 52, 236, 0.47
P = lambda x, y: (ax0 + x * sc, ay0 + y * sc)
EP, EM, ER = P(598, 386), P(676, 302), P(524, 536)
def el(c, col):
    x, y = c
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="#fff" stroke="#CFC9BF" stroke-width="1.2"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.4" fill="#D7DEE3"/><circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{col}"/>')
adx, ady = 540, cy - 50
leads = ""
for c, col, yy in [(EM, "#E3B23C", cy - 22), (EP, "#D1495B", cy), (ER, "#3A8F6B", cy + 22)]:
    d = route([c, (c[0], c[1]) if False else (c[0] + 0.01, yy) if abs(c[1] - yy) > 1 else c, (adx, yy)], 12) if False else None
    mx = 500 + (0 if col == "#E3B23C" else 8 if col == "#D1495B" else 16)
    pts = route([c, (mx, c[1]), (mx, yy), (adx, yy)], 10)
    leads += f'<path d="{path_d(pts)}" fill="none" stroke="{col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.9"/>'
L["arm"] = (f'<image href="data:image/png;base64,{arm_b64}" x="{ax0}" y="{ay0}" width="{880*sc:.0f}" height="{750*sc:.0f}"/>'
            + leads + el(EM, "#E3B23C") + el(EP, "#D1495B") + el(ER, "#3A8F6B")
            + T(EP[0] - 4, EP[1] - 15, "+", 14, 700, "#B8394A", "middle") + T(EM[0] - 4, EM[1] - 15, "−", 15, 700, "#B9821C", "middle")
            + T(ER[0] - 18, ER[1] + 28, "REF", 11, 700, "#3A8F6B", "middle")
            + T(250, 616, "Surface EMG", 16, 700, INK, "middle") + T(250, 636, "forearm flexors · reference at the elbow", 12, 500, MUTED, "middle"))

def lab(x, a, b, y=cy + 118): return T(x, y, a, 16, 700, INK, "middle") + T(x, y + 20, b, 12, 500, MUTED, "middle")
# ---------- b · AD8232, ESP32 DSP chain, bridge ----------
L["ad"] = (f'<rect x="{adx}" y="{ady}" width="120" height="100" rx="10" fill="#5B4A7A"/><rect x="{adx+14}" y="{cy-14}" width="30" height="30" rx="3" fill="#232026"/>'
           + "".join(f'<rect x="{adx+56+i*10}" y="{ady+10}" width="6" height="6" fill="#C8A96A"/>' for i in range(5))
           + T(adx + 84, cy + 6, "AD8232", 12, 700, "#EDE7F6", "middle") + lab(adx + 60, "Analog front end", "gain ≈ 1000"))
ex = 720
esp = (f'<rect x="{ex}" y="{cy-118}" width="340" height="236" rx="16" fill="#E6F4EF"/>'
       + T(ex + 170, cy - 92, "ESP32-S3 · FreeRTOS, core 1", 12, 700, "#0F6E56", "middle")
       + f'<rect x="{ex+16}" y="{cy-70}" width="98" height="160" rx="9" fill="#1F2328"/><rect x="{ex+27}" y="{cy-56}" width="76" height="56" rx="5" fill="#C9CCD1"/>'
       + T(ex + 65, cy - 23, "ESP32-S3", 11, 700, "#2B2D31", "middle"))
for i, s_ in enumerate(["ADC 1 kHz · DMA", "① 60 Hz notch", "② 45–200 Hz band-pass", "③ RMS → level"]):
    y = cy - 66 + i * 46
    esp += f'<rect x="{ex+130}" y="{y}" width="196" height="34" rx="17" fill="#fff" stroke="#7BC8B4" stroke-width="1.4"/>' + T(ex + 228, y + 22, s_, 12.5, 600, "#0F4F40", "middle")
    if i: esp += f'<path d="M{ex+228},{y-12} L{ex+228},{y-1}" stroke="#7BC8B4" stroke-width="2"/>'
L["esp"] = esp + lab(ex + 170, "On-device DSP", "tension level every 50 ms", cy + 148)
lx = 1112
L["lap"] = (f'<rect x="{lx}" y="{cy-40}" width="96" height="64" rx="6" fill="#2B2F36"/><rect x="{lx+6}" y="{cy-34}" width="84" height="52" rx="3" fill="#DDE6F2"/>'
            f'<path d="M{lx-10},{cy+26} L{lx+106},{cy+26} L{lx+97},{cy+34} L{lx-1},{cy+34} Z" fill="#9AA1AB"/>'
            + "".join(f'<rect x="{lx+13}" y="{cy-25+k*11}" width="{54-k*11}" height="5" rx="2.5" fill="#8FA3BF"/>' for k in range(4))
            + lab(lx + 48, "Bridge", "USB → WebSocket"))

# ---------- c · feedback cards ----------
cx0, cw, ch = 1290, 238, 96
CARDS = {"live": cy - 128, "xr": cy, "ai": cy + 128}
def card(y, planned):
    st = f'stroke="{PLAN}" stroke-dasharray="5 5"' if planned else 'stroke="#C9CED6"'
    s = f'<rect x="{cx0}" y="{y-ch/2}" width="{cw}" height="{ch}" rx="14" fill="#fff" {st} stroke-width="1.4"/>'
    if planned: s += T(cx0 + cw - 12, y - ch / 2 + 18, "planned", 10.5, 700, PLAN, "end", extra="letter-spacing:1px")
    return s
tx = cx0 + 92
y = CARDS["live"]
L["live"] = (card(y, False) + f'<rect x="{cx0+16}" y="{y-26}" width="62" height="50" rx="7" fill="#fff" stroke="#C9CED6" stroke-width="1.4"/>'
             f'<rect x="{cx0+16}" y="{y-26}" width="62" height="12" rx="6" fill="#EEF1F5"/>'
             + "".join(f'<circle cx="{cx0+24+k*7}" cy="{y-20}" r="2.2" fill="{c}"/>' for k, c in enumerate(["#E6A19A", "#E8C77D", "#9CCB9E"]))
             + T(tx, y - 6, "Live view", 15, 700, INK) + T(tx, y + 14, "browser · Three.js", 12, 500, MUTED))
GEO["ring"] = [cx0 + 47, y + 5]
y = CARDS["xr"]; hx = cx0 + 47
L["xr"] = (card(y, True)
           + f'<defs><filter id="glw" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="5"/></filter></defs>'
           + f'<rect x="{hx-30}" y="{y-16}" width="60" height="32" rx="14" fill="none" stroke="{TEAL}" stroke-width="5" stroke-opacity="0.5" filter="url(#glw)"/>'
           + f'<path d="M{hx-30},{y-2} C{hx-40},{y-2} {hx-42},{y+10} {hx-35},{y+13}" fill="none" stroke="#3A3F47" stroke-width="3" stroke-linecap="round"/>'
           + f'<path d="M{hx+30},{y-2} C{hx+40},{y-2} {hx+42},{y+10} {hx+35},{y+13}" fill="none" stroke="#3A3F47" stroke-width="3" stroke-linecap="round"/>'
           + f'<rect x="{hx-29}" y="{y-15}" width="58" height="30" rx="13" fill="#2B2F36"/><rect x="{hx-24}" y="{y-10}" width="48" height="16" rx="8" fill="#3A404A"/>'
           + T(tx, y - 6, "Quest · WebXR", 15, 700, INK) + T(tx, y + 14, "edge-glow feedback", 12, 500, MUTED))
y = CARDS["ai"]
L["ai"] = (card(y, True) + "".join(f'<rect x="{cx0+18}" y="{y-18+k*11}" width="{[50,40,28][k]}" height="4.5" rx="2.2" fill="#D9D2F4"/>' for k in range(3))
           + f'<path d="M{cx0+66},{y+8} l6,-8 l6,8 l-6,8 Z" fill="{LAV}"/>'
           + T(tx, y - 12, "AI coach", 15, 700, INK) + T(tx, y + 8, "session stats →", 12, 500, MUTED) + T(tx, y + 24, "Claude Sonnet 5.5", 12, 500, MUTED))

# ---------- wires ----------
ws, GEO["wires"] = "", []
for pts in [[(500, cy), (adx - 2, cy)] if False else None]: pass
s_, d = wire([(adx + 120, cy), (ex - 4, cy)]); ws += s_; GEO["wires"].append(d)
s_, d = wire([(ex + 340, cy), (lx - 14, cy)]); ws += s_; GEO["wires"].append(d)
s_, d = wire([(lx + 108, cy), (1250, cy), (1250, CARDS["live"]), (cx0 - 4, CARDS["live"])]); ws += s_; GEO["wires"].append(d)
L["wires"] = ws
pl = ""
s_, d = wire([(1250, cy), (cx0 - 4, cy)], PLAN, True, 1.8); pl += s_
s_, d = wire([(1250, cy), (1250, CARDS["ai"]), (cx0 - 4, CARDS["ai"])], PLAN, True, 1.8); pl += s_
s_, d = wire([(cx0 + cw - 30, CARDS["ai"] - ch / 2 - 2), (cx0 + cw - 30, CARDS["xr"] + ch / 2 + 4)], LAV, True, 1.6); pl += s_
pl += T(cx0 + cw - 38, (CARDS["ai"] + CARDS["xr"]) / 2 + 4, "markers", 10.5, 600, LAV, "end")
L["planned"] = pl
# ---------- closed loop back to the player ----------
s_, d = wire([(cx0 + cw / 2, CARDS["ai"] + ch / 2), (cx0 + cw / 2, 736), (250, 736), (250, 652)], "#B7A9EE", False, 1.8, 18)
GEO["loop"] = d
L["loop"] = s_ + (f'<rect x="{720-210}" y="{736-13}" width="420" height="26" rx="13" fill="#FBF8F1"/>'
                  + T(720, 741, "closed loop · the player sees the glow and relaxes the hand", 12.5, 600, "#7A6BC9", "middle", extra="font-style:italic"))
L["legend"] = (f'<line x1="72" y1="776" x2="100" y2="776" stroke="{LINE}" stroke-width="2"/>' + T(108, 780, "built", 11.5, 500, MUTED)
               + f'<line x1="160" y1="776" x2="188" y2="776" stroke="{PLAN}" stroke-width="1.8" stroke-dasharray="5 6"/>' + T(196, 780, "planned", 11.5, 500, MUTED))

def svg(body): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{body}</svg>'
if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": W, "height": H})
        for name, body in L.items():
            pg.set_content(f'<html><body style="margin:0;background:transparent">{svg(body)}</body></html>'); pg.wait_for_timeout(150)
            pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
        pg.set_content(f'<html><body style="margin:0;background:#fff">{svg("".join(L.values()))}</body></html>'); pg.wait_for_timeout(200)
        pg.screenshot(path=str(OUT / "_all.png")); b.close()
    (OUT / "geom.json").write_text(json.dumps(GEO))
    print("v5 ok")
