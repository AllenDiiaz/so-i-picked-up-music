"""v6 layers (1600x900) for the README video: the architecture as of 2026-11 and the A/B scene's labels.

    .venv/bin/python media/readme_video/v6_layers.py      -> build/v6/*.png, build/v6/geom.json

Architecture: a Sensing | b On the board: two cores | c On the Mac: bridge, browser view, coach.
Solid = built; dashed lavender = built but not yet run on the board (the command downlink).
The arm (licensed BioRender illustration) and the header are cropped from the previous render in
private/ (see README.md); neither the source illustration nor that render is committed.
Styling follows the kit's v5_layers.py (same palette, fonts and helper code).
"""
import base64
import io
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "v6"
OLD = HERE / "private" / "so_i_picked_up_music_20s.mp4"       # previous 20 s render (kit v4)
W, H = 1600, 900
INK, MUTED = "#1E2430", "#7A7F87"
SANS = "font-family:Inter,sans-serif"
TEAL, ORANGE, LAV, LINE, RED = "#00A087", "#F08A24", "#9C8BE8", "#3C4656", "#E64B35"
LAV_D = "#7A6BC9"
L, GEO = {}, {"wires": {}}


def T(x, y, t, size=16, w=400, fill=INK, anchor="start", fam=SANS, extra=""):
    return f'<text x="{x}" y="{y}" style="{fam};font-size:{size}px;font-weight:{w};{extra}" fill="{fill}" text-anchor="{anchor}">{t}</text>'


def route(pts, r=16, n=10):
    """Orthogonal polyline with rounded corners -> dense point list (from the kit's v3_layers.py)."""
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


def path_d(pts): return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def head(p, q, col, w=2.2):                     # small open chevron at q, pointing along p->q
    p, q = np.array(p, float), np.array(q, float); u = (q - p) / np.linalg.norm(q - p); n = np.array([-u[1], u[0]])
    a, b = q - u * 9 + n * 5.5, q - u * 9 - n * 5.5
    return f'<path d="M{a[0]:.1f},{a[1]:.1f} L{q[0]:.1f},{q[1]:.1f} L{b[0]:.1f},{b[1]:.1f}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'


def wire(name, pts, col=LINE, dash=False, w=2.0, r=12):
    d = route(pts, r)
    s = f'<path d="{path_d(d)}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"{" stroke-dasharray=\'5 6\'" if dash else ""}/>'
    GEO["wires"][name] = d
    return s + head(d[-6], d[-1], col, w)


def old_frame(t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(OLD), "-frames:v", "1", "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(raw)).convert("RGB")


def b64(img):
    buf = io.BytesIO(); img.save(buf, "PNG"); return base64.b64encode(buf.getvalue()).decode()


cy = 420
# ---------- header (pixels of the previous render; Lora + Inter as set by the kit) ----------
full = old_frame(15.8)                          # architecture scene of the previous render, fully built
L["header"] = f'<image href="data:image/png;base64,{b64(full.crop((0, 0, W, 166)))}" x="0" y="0" width="{W}" height="166"/>'
L["panel"] = f'<rect x="40" y="172" width="{W-80}" height="636" rx="22" fill="#FBF8F1"/>'


def sec(x, letter, name):
    return T(x, 214, letter, 22, 800, INK) + T(x + 22, 213, name, 12, 700, "#6B7280", extra="letter-spacing:2.4px")


L["sec"] = sec(72, "a", "SENSING") + sec(520, "b", "ON THE BOARD · FREERTOS, TWO CORES") + sec(1130, "c", "ON THE MAC")

# ---------- a · arm with electrodes and leads: cropped from the previous render ----------
ARM_BOX = (48, 232, 539, 598)
arm_img = full.crop(ARM_BOX)
# Right of x = 522 only the three lead wires belong to the arm picture: clear the rest (it holds
# the edge of a label of the previous layout) with the panel colour sampled from the render.
arm_img.paste(full.getpixel((530, 300)), (522 - ARM_BOX[0], 470 - ARM_BOX[1], ARM_BOX[2] - ARM_BOX[0], ARM_BOX[3] - ARM_BOX[1]))
L["arm"] = (f'<image href="data:image/png;base64,{b64(arm_img)}" x="{ARM_BOX[0]}" y="{ARM_BOX[1]}" '
            f'width="{ARM_BOX[2]-ARM_BOX[0]}" height="{ARM_BOX[3]-ARM_BOX[1]}"/>'
            + T(250, 628, "Surface EMG", 16, 700, INK, "middle") + T(250, 648, "forearm flexors · reference at the elbow", 12, 500, MUTED, "middle"))

# ---------- b · AD8232 ----------
adx, ady = 540, cy - 50
L["ad"] = (f'<rect x="{adx}" y="{ady}" width="120" height="100" rx="10" fill="#5B4A7A"/><rect x="{adx+14}" y="{cy-14}" width="30" height="30" rx="3" fill="#232026"/>'
           + "".join(f'<rect x="{adx+56+i*10}" y="{ady+10}" width="6" height="6" fill="#C8A96A"/>' for i in range(5))
           + T(adx + 84, cy + 6, "AD8232", 12, 700, "#EDE7F6", "middle")
           + T(adx + 60, cy + 78, "Analog front end", 14, 700, INK, "middle") + T(adx + 60, cy + 96, "gain ≈ 1000", 12, 500, MUTED, "middle"))

# ---------- b · ESP32-S3: core 1 (hard real-time) and core 0 (soft real-time + asynchronous) ----------
ex, ew = 700, 400
ey0, ey1 = 252, 580


def pill(x, y, w, text, stroke="#7BC8B4", fill="#fff", col="#0F4F40", dash=False):
    d = ' stroke-dasharray="5 4"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="32" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{d}/>'
            + T(x + w / 2, y + 21, text, 12.5, 600, col, "middle"))


c1y, c0y = 290, 444                               # tops of the two core panels
esp = (f'<rect x="{ex}" y="{ey0}" width="{ew}" height="{ey1-ey0}" rx="16" fill="#E6F4EF"/>'
       + T(ex + 18, ey0 + 25, "ESP32-S3", 13, 800, "#0F6E56") + T(ex + ew - 18, ey0 + 25, "USB only · Wi-Fi off", 11.5, 500, "#5C8F82", "end")
       # core 1
       + f'<rect x="{ex+12}" y="{c1y}" width="{ew-24}" height="118" rx="12" fill="#fff" fill-opacity="0.75"/>'
       + T(ex + 26, c1y + 24, "core 1", 14, 800, INK) + T(ex + 78, c1y + 24, "hard real-time", 12, 700, RED, extra="letter-spacing:0.6px")
       + T(ex + ew - 26, c1y + 24, "sampler · prio 10", 11.5, 500, MUTED, "end")
       + pill(ex + 22, c1y + 40, 120, "ADC 1 kHz · DMA") + pill(ex + 152, c1y + 40, 128, "notch · band-pass") + pill(ex + 290, c1y + 40, 88, "RMS · level")
       + f'<path d="M{ex+142},{c1y+56} L{ex+152},{c1y+56} M{ex+280},{c1y+56} L{ex+290},{c1y+56}" stroke="#7BC8B4" stroke-width="2"/>'
       + T(ex + 26, c1y + 100, "waits only for the ADC · no locks, no printing", 11.5, 500, MUTED)
       # core 0
       + f'<rect x="{ex+12}" y="{c0y}" width="{ew-24}" height="118" rx="12" fill="#fff" fill-opacity="0.75"/>'
       + T(ex + 26, c0y + 24, "core 0", 14, 800, INK) + T(ex + 78, c0y + 24, "soft real-time · async", 12, 700, "#3C5488", extra="letter-spacing:0.6px")
       + pill(ex + 22, c0y + 40, 150, "output → USB", "#9DB1DA", "#fff", "#2C3E66")
       + pill(ex + 200, c0y + 40, 178, "cmd_rx ← USB · prio 3", LAV, "#fff", "#4B3FA0", True)
       + T(ex + 26, c0y + 100, "tension every 50 ms · acks", 11.5, 500, MUTED)
       + T(ex + ew - 26, c0y + 100, "strict parser · clamps", 11.5, 500, MUTED, "end"))
# hop queue (down) and parameter word (up), in the gap between the two core panels
qx, px, g0, g1 = ex + 60, ex + 232, c1y + 118, c0y
esp += (f'<path d="M{qx},{g0-2} L{qx},{g1+2}" stroke="#4FAF98" stroke-width="2.2"/>' + head((qx, g0), (qx, g1 + 3), "#4FAF98", 2.2)
        + f'<path d="M{px},{g1+2} L{px},{g0-2}" stroke="{LAV_D}" stroke-width="2.2" stroke-dasharray="4 4"/>' + head((px, g1), (px, g0 - 3), LAV_D, 2.2)
        + T(qx + 14, g0 + 23, "hop queue", 12, 700, "#0F6E56") + T(px + 14, g0 + 23, "hard_scale · 32-bit word", 12, 700, "#4B3FA0"))
GEO["wires"]["hop"] = route([(qx, g0 - 2), (qx, g1 + 2)])
GEO["wires"]["param"] = route([(px, g1 + 2), (px, g0 - 2)])
L["esp"] = esp + T(ex + ew / 2, 628, "Sampling never waits for the host", 15, 700, INK, "middle") \
               + T(ex + ew / 2, 648, "a new parameter takes effect between two hops", 12, 500, MUTED, "middle")

# ---------- c · bridge (laptop), browser view, coach ----------
lx = 1150
L["lap"] = (f'<rect x="{lx}" y="{cy-40}" width="96" height="64" rx="6" fill="#2B2F36"/><rect x="{lx+6}" y="{cy-34}" width="84" height="52" rx="3" fill="#DDE6F2"/>'
            f'<path d="M{lx-10},{cy+26} L{lx+106},{cy+26} L{lx+97},{cy+34} L{lx-1},{cy+34} Z" fill="#9AA1AB"/>'
            + "".join(f'<rect x="{lx+13}" y="{cy-25+k*11}" width="{54-k*11}" height="5" rx="2.5" fill="#8FA3BF"/>' for k in range(4))
            + T(lx + 48, cy - 72, "Bridge", 15, 700, INK, "middle") + T(lx + 48, cy - 54, "USB ⇄ WebSocket", 12, 500, MUTED, "middle"))
cx0, cw, ch = 1296, 244, 100
VIEW_Y, AI_Y = 318, 482


def card(y):
    return f'<rect x="{cx0}" y="{y-ch/2}" width="{cw}" height="{ch}" rx="14" fill="#fff" stroke="#C9CED6" stroke-width="1.4"/>'


tx = cx0 + 88
y = VIEW_Y
L["view"] = (card(y)
             + f'<defs><filter id="glw" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3"/></filter></defs>'
             + f'<rect x="{cx0+16}" y="{y-27}" width="60" height="52" rx="7" fill="#1B1D21"/>'
             + f'<rect x="{cx0+20}" y="{y-23}" width="52" height="44" rx="5" fill="none" stroke="{TEAL}" stroke-width="5" stroke-opacity="0.9" filter="url(#glw)"/>'
             + f'<rect x="{cx0+30}" y="{y+6}" width="32" height="4" rx="2" fill="#C9CED6"/>'
             + T(tx, y - 16, "Browser view", 15, 700, INK) + T(tx, y + 3, "(WebXR-ready)", 12.5, 600, "#4B5563")
             + T(tx, y + 23, "edge glow · coach text", 12, 500, MUTED))
y = AI_Y
L["ai"] = (card(y) + "".join(f'<rect x="{cx0+18}" y="{y-18+k*11}" width="{[50,40,28][k]}" height="4.5" rx="2.2" fill="#D9D2F4"/>' for k in range(3))
           + f'<path d="M{cx0+62},{y+8} l6,-8 l6,8 l-6,8 Z" fill="{LAV}"/>'
           + T(tx, y - 16, "AI coach", 15, 700, INK) + T(tx, y + 3, "local LLM · Ollama", 12.5, 600, "#4B5563")
           + T(tx, y + 23, "feedback + hard_scale", 12, 500, MUTED))

# ---------- wires: the measurement path (solid) ----------
ws = wire("ad_esp", [(adx + 120, cy), (ex - 4, cy)])
ws += wire("esp_bridge", [(ex + ew, c0y + 56), (1124, c0y + 56), (1124, cy), (lx - 14, cy)])
ws += wire("bridge_view", [(lx + 108, cy - 12), (1272, cy - 12), (1272, VIEW_Y), (cx0 - 4, VIEW_Y)])
L["wires"] = ws
# ---------- the coach round trip ----------
ai = wire("bridge_ai", [(lx + 108, cy + 8), (1272, cy + 8), (1272, AI_Y - 14), (cx0 - 4, AI_Y - 14)])
ai += wire("ai_bridge", [(cx0, AI_Y + 16), (lx + 62, AI_Y + 16), (lx + 62, cy + 42)], LAV_D, False, 2.0)
ai += T(1264, AI_Y - 6, "stats", 11, 600, "#4B5563", "end") + T(lx + 70, AI_Y + 34, "reply", 11, 600, LAV_D)
L["ai_wires"] = ai
# ---------- command downlink: built, not yet run on the board (dashed) ----------
cmd_x = ex + 289
cmd = wire("cmd", [(lx + 22, cy + 42), (lx + 22, 604), (cmd_x, 604), (cmd_x, ey1 + 4)], LAV_D, True, 2.0)
cmd_mid = (cmd_x + lx + 22) / 2
L["cmd"] = cmd
L["cmd_label"] = (f'<rect x="{cmd_mid-66}" y="592" width="132" height="24" rx="12" fill="#FBF8F1"/>'       # drawn over the moving dots
                  + T(cmd_mid, 608, "! set_params · ack", 12, 700, LAV_D, "middle"))
# ---------- closed loop back to the player ----------
loop = wire("loop", [(cx0 + cw, VIEW_Y), (1550, VIEW_Y), (1550, 736), (250, 736), (250, 664)], "#B7A9EE", False, 1.8, 18)
L["loop"] = loop + (f'<rect x="{800-250}" y="{736-13}" width="500" height="26" rx="13" fill="#FBF8F1"/>'
                    + T(800, 741, "closed loop · the player sees the glow, reads the coach, relaxes the hand", 12.5, 600, LAV_D, "middle", extra="font-style:italic"))
L["legend"] = (f'<line x1="72" y1="780" x2="100" y2="780" stroke="{LINE}" stroke-width="2"/>' + T(108, 784, "built", 11.5, 500, MUTED)
               + f'<line x1="156" y1="780" x2="184" y2="780" stroke="{LAV_D}" stroke-width="2" stroke-dasharray="5 6"/>'
               + T(192, 784, "built · not yet run on the board", 11.5, 500, MUTED))

# ---------- A/B scene: labels around the two captured browser panels ----------
AB = {"y": 226, "left": 108, "right": 816, "w": 676, "h": 559}
GEO["ab"] = AB


def ab_label(x, letter, title, sub, col):
    return (f'<rect x="{x}" y="186" width="30" height="30" rx="8" fill="{col}"/>' + T(x + 15, 208, letter, 17, 800, "#fff", "middle")
            + T(x + 42, 200, title, 15, 700, INK) + T(x + 42, 216, sub, 12, 500, MUTED))


L["ab"] = (ab_label(AB["left"], "A", "Naive: the sampler waits for the LLM", "one loop does everything · the 1 kHz stream stops while the coach thinks", RED)
           + ab_label(AB["right"], "B", "Designed: the LLM is outside the real-time path", "core 1 keeps sampling · the reply arrives through core 0", TEAL)
           + "".join(f'<rect x="{x-2}" y="{AB["y"]-2}" width="{AB["w"]+4}" height="{AB["h"]+4}" rx="14" fill="#121212"/>' for x in (AB["left"], AB["right"]))
           + T(W / 2, 806, "simulated device (recorded EMG through the firmware's C code, timing from a model) · mock coach, 2.5 s thinking time · real browser front end",
               12, 500, MUTED, "middle"))


def caption(text):                             # the kit's bottom pill
    w = 9.6 * len(text) + 44
    return (f'<rect x="{W/2-w/2}" y="826" width="{w}" height="40" rx="20" fill="#F1EEE6"/>' + T(W / 2, 852, text, 18, 500, INK, "middle"))


L["pill_arch"] = caption("The LLM is in the loop, but outside the hard real-time path")
L["pill_ab"] = caption("Same segment, same coach reply · only the two-core design keeps the 1 kHz stream alive")


def svg(body): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{body}</svg>'


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    arch = [k for k in L if k not in ("header", "ab", "pill_ab")]
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome"); pg = b.new_page(viewport={"width": W, "height": H})
        for name, body in L.items():
            pg.set_content(f'<html><body style="margin:0;background:transparent">{svg(body)}</body></html>'); pg.wait_for_timeout(150)
            pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
        for name, keys in (("_arch", ["header"] + arch), ("_ab", ["header", "ab", "pill_ab"])):
            pg.set_content(f'<html><body style="margin:0;background:#fff">{svg("".join(L[k] for k in keys))}</body></html>'); pg.wait_for_timeout(200)
            pg.screenshot(path=str(OUT / f"{name}.png"))
        b.close()
    (OUT / "geom.json").write_text(json.dumps(GEO))
    print("v6 layers ok:", ", ".join(L))
