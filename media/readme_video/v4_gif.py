"""15 s README GIF: guitar demo (video + TAB + signals) -> architecture."""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import v3_gif as G                      # comet(), helpers, header layer, circuit scene
G.LEVEL[2] = (240, 138, 36)             # orange = over-effort, everywhere
import demo_data as DD
W, H, FPS = G.W, G.H, 12
LAY4 = {p.stem: Image.open(p).convert("RGBA") for p in (HERE / "v5").glob("*.png") if not p.stem.startswith("_")}
GEO4 = json.loads((HERE / "v5" / "geom.json").read_text())
VID = "/root/.claude/uploads/4f0045de-265e-50a4-a7ff-ee284bf0416f/a18910c6-814115789.158804.mp4"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/out"); SNAP = sys.argv[2] if len(sys.argv) > 2 else None
D_LEN, A_LEN, C_LEN = 11.0, 5.0, 4.0
VW, VH = 600, 540                                  # video panel
# fretting-hand side of the frame (aspect 600:540)
cw = int(720 * VW / VH); cx0 = 1280 - cw
raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-t", str(D_LEN), "-i", VID, "-vf",
                      f"fps={FPS},crop={cw}:720:{cx0}:0,scale={VW}:{VH}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                     capture_output=True, check=True).stdout
FR = np.frombuffer(raw, np.uint8).reshape(-1, VH, VW, 3)

def lay4(img, n, a):
    if a <= 0: return img
    l = LAY4[n]
    if a < 1: l = l.copy(); l.putalpha(l.getchannel("A").point(lambda v: int(v * a)))
    return Image.alpha_composite(img, l)

D_T0 = 0.0
def disp_level(arr, hold=0.35):                             # same idea as firmware hysteresis: a level must persist
    out = np.zeros_like(arr); cur = int(arr[0]); cand, since = cur, 0
    for i, v in enumerate(arr):
        if v != cand: cand, since = int(v), i
        if cand != cur and (i - since) >= hold * 1000: cur = cand
        out[i] = cur
    return out
DL = disp_level(DD.DLVL)
lev = lambda tt: int(DD.at(DL, tt))
# ---- edge glow: soft inner light at the frame edges (green = medium, orange = high) ----
yy, xx = np.mgrid[0:VH, 0:VW].astype(np.float32)
_d = np.minimum.reduce([xx, VW - 1 - xx, yy, VH - 1 - yy])
EDGE = np.exp(-_d / 70.0)[..., None]
_tt = np.arange(int(D_LEN * FPS) + 2) / FPS
_raw = np.array([(0.0, 0.6, 1.1)[lev(x)] for x in _tt])
GLOW = np.zeros_like(_raw); _g = 0.0
for i, v in enumerate(_raw):
    _g += (v - _g) * (0.28 if v > _g else 0.10); GLOW[i] = _g
TEAL, ORANGE = np.array(G.LEVEL[1], np.float32), np.array(G.LEVEL[2], np.float32)
def edge_glow(frame, g):
    if g < 0.02: return frame
    w = float(np.clip((g - 0.85) / 0.25, 0, 1))
    col = TEAL * (1 - w) + ORANGE * w
    a = EDGE * (0.8 * min(1.0, g) ** 0.8)
    f = frame.astype(np.float32)
    f = f + (255 - f) * (col / 255) * a
    return np.clip(f, 0, 255).astype(np.uint8)

SPAN = 7.0
def scene_demo(t, img):
    cur = t; lv = lev(cur)
    k = min(int(t * FPS), len(FR) - 1)
    fr = Image.fromarray(edge_glow(FR[k], float(GLOW[min(k, len(GLOW) - 1)])))
    m = Image.new("L", (VW, VH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, VW - 1, VH - 1], 16, fill=255)
    img.paste(fr, (40, 186), m); d = ImageDraw.Draw(img)
    d.rounded_rectangle([56, 202, 236, 234], 16, fill=(25, 25, 25)); G.text(d, (146, 218), "practice video", G.font("SemiBold", 14), (240, 240, 240), "mm")
    d.rounded_rectangle([56, 186 + VH - 52, 256, 186 + VH - 16], 18, fill=G.LEVEL[lv])
    G.text(d, (156, 186 + VH - 34), "tension: " + G.LNAME[lv], G.font("Bold", 16), (255, 255, 255), "mm")
    gx, gw = 836, 714; sweep = (0, D_LEN); X = lambda tt: gx + tt / D_LEN * gw
    rows = [("Bars", "4/4 · 110 BPM", 186), ("raw", "1 kHz ADC", 306), ("① notch", "60 Hz mains removed", 412),
            ("② band-pass", "45–200 Hz", 518), ("③ RMS", "→ tension level", 624)]
    for name, sub, y in rows:
        G.text(d, (668, y + 28), name, G.font("Bold", 20), G.INK); G.text(d, (668, y + 52), sub, G.font("Regular", 13), G.MUTED)
        if name != "Bars": G.grid(d, (gx, y + 4, gx + gw, y + (122 if name == "③ RMS" else 92)), 25, (240, 240, 240))
    # ---- sections · bars · beats · current bar (no notes) ----
    BAR = 60 / 110 * 4; B0 = 0.25; LAV, LAVB = (150, 130, 240), (238, 234, 252)
    nb = int((D_LEN - B0) / BAR) + 1
    for i in range(nb):
        s0, s1_ = B0 + i * BAR, B0 + (i + 1) * BAR
        if s0 <= cur < s1_: d.rectangle([max(gx, X(s0)), 232, min(gx + gw, X(s1_)), 290], fill=(246, 244, 253))
    for name, b0, b1 in [("Section A", 0, 3), ("Section B", 3, 6)]:
        x0, x1 = max(gx, X(B0 + b0 * BAR)) + 3, min(gx + gw, X(B0 + b1 * BAR)) - 3
        on = B0 + b0 * BAR <= cur < B0 + b1 * BAR
        d.rounded_rectangle([x0, 194, x1, 220], 13, fill=LAVB if on else (244, 244, 246))
        G.text(d, (x0 + 14, 207), name, G.font("SemiBold", 13), (95, 75, 190) if on else (165, 165, 172), "lm")
    d.line([(gx, 261), (gx + gw, 261)], fill=(222, 222, 226))
    for i in range(nb + 1):
        bs = B0 + i * BAR
        for kk in range(4):
            bt = bs + kk * BAR / 4; x = X(bt)
            if not gx <= x <= gx + gw: continue
            if kk == 0:
                d.line([(x, 238), (x, 284)], fill=(120, 120, 128), width=2)
                G.text(d, (x + 6, 246), str(i + 1), G.font("Medium", 12), G.MUTED, "lm")
            else:
                past = bt <= cur; near = 0 <= cur - bt < 0.18; r = 5 if near else 3.5
                d.ellipse([x - r, 261 - r, x + r, 261 + r], fill=LAV if near else (G.INK if past else (200, 200, 205)))
    img = G.comet(img, (gx, 310, gx + gw, 398), DD.DT, DD.DMV, cur, SPAN, 1250, 2100, 1, sweep, 0.5)
    img = G.comet(img, (gx, 416, gx + gw, 504), DD.DT, DD.DS1, cur, SPAN, -150, 150, 1, sweep, 0.5)
    img = G.comet(img, (gx, 522, gx + gw, 610), DD.DT, DD.DS2, cur, SPAN, -95, 95, 1, sweep, 0.5)
    img = G.comet(img, (gx, 628, gx + gw, 746), DD.DT, DD.DENV, cur, SPAN, 0, 30, 6, sweep, 0.5)
    d = ImageDraw.Draw(img)
    for th, kk in [(1.49 * DD.base, 1), (2.72 * DD.base, 2)]:
        y = 746 - th / 30 * 118
        for x in range(gx, gx + gw, 12): d.line([(x, y), (x + 6, y)], fill=G.LEVEL[kk])
        G.text(d, (gx + gw - 4, y - 4), "medium" if kk == 1 else "high", G.font("Medium", 12), G.LEVEL[kk], "rs")
    for sp in DD.SPLICE:                                      # mark where the two recording segments meet
        xs = X(sp)
        for y in range(310, 750, 10): d.line([(xs, y), (xs, y + 4)], fill=(200, 200, 206))
    xp = X(cur); d.line([(xp, 182), (xp, 750)], fill=(150, 130, 240), width=2)
    G.text(d, (668, 790), "draft · signal: lab recording (light grip, then hard grip; two segments joined at the dotted line) · not synced to the video · sections are placeholders",
           G.font("Regular", 12), G.MUTED, "ls")
    a = G.ease(t / 0.4) * (1 - G.ease((t - D_LEN + 0.5) / 0.4))
    return G.pill(img, "Forearm EMG while playing  ·  green = medium, orange = over-effort", a)

def scene_arch(t, img):
    for n, t0 in [("panel", 0.0), ("sec", 0.15), ("arm", 0.2), ("ad", 0.7), ("wires", 0.9), ("esp", 1.0), ("lap", 1.4),
                  ("live", 1.7), ("planned", 2.0), ("xr", 2.0), ("ai", 2.25), ("loop", 2.7), ("legend", 2.9)]:
        img = lay4(img, n, G.ease((t - t0) / 0.5))
    for pts, t0 in zip(GEO4["wires"], [1.1, 1.5, 1.9]):
        if t > t0: img = G.dots(img, pts, t, 2, 0.8, G.TAIL, 4.5, 3)
    if t > 1.9:
        d = ImageDraw.Draw(img); lv = lev(min(D_LEN - 0.01, (t - 1.9) * 3.0)); cx, cy = GEO4["ring"]
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], outline=G.LEVEL[lv], width=4)
    a = G.ease((t - 0.2) / 0.4) * (1 - G.ease((t - A_LEN + 0.5) / 0.4))
    return G.pill(img, "Sense → process on the ESP32 → feed back to the player", a)

def scene_circuit(t, img):
    out = G.scene_circuit(t + 0.5, img)
    return out
SCENES = [(scene_demo, D_LEN), (scene_arch, A_LEN), (scene_circuit, C_LEN)]
def render(ft):
    acc = 0
    for fn, dur in SCENES:
        if ft < acc + dur:
            lt = ft - acc
            img = G.layer(G.BASE.copy(), "header", 1.0)
            out = fn(lt, img.copy())
            if lt < 0.35 and acc > 0: out = Image.blend(img, out, G.ease(lt / 0.35))
            return out.convert("RGB")
        acc += dur
    return G.BASE.convert("RGB")

if __name__ == "__main__":
    total = D_LEN + A_LEN + C_LEN
    if SNAP:
        for k, ft in enumerate([3.0, 10.4, 15.6, 18.5]): render(ft).save(f"{SNAP}/v4_{k}.png")
        sys.exit()
    mp4, gif = OUT / "so_i_picked_up_music_20s.mp4", OUT / "so_i_picked_up_music_20s.gif"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    for k in range(int(total * FPS)): p.stdin.write(render(k / FPS).tobytes())
    p.stdin.close(); p.wait()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf",
                    "fps=10,scale=1100:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    "-loop", "0", str(gif)], check=True)
    print("done", total)
