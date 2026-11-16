"""30 s README animation: architecture -> circuit -> demo. Writes MP4 and GIF."""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent; L = HERE / "v3"
sys.path.insert(0, "/home/claude/allendiiaz/so-i-picked-up-music/analysis")
import emg  # noqa: E402

W, H, FPS = 1600, 900, 12
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/out")
SNAP = sys.argv[2] if len(sys.argv) > 2 else None
U = "/root/.claude/uploads/4f0045de-265e-50a4-a7ff-ee284bf0416f/"
FONT = "/usr/share/fonts/opentype/inter/Inter-"
def font(st, sz): return ImageFont.truetype(FONT + st + ".otf", sz)
INK, MUTED, RULE = (30, 36, 48), (122, 127, 135), (217, 214, 206)
HEAD, TAIL = np.array([182, 156, 255]), np.array([10, 155, 255])     # lavender head -> blue body (reference style)
LEVEL = {-1: (190, 190, 190), 0: (140, 140, 140), 1: (0, 160, 135), 2: (230, 75, 53)}
LNAME = {0: "relaxed", 1: "medium", 2: "high"}
def ease(x): x = min(max(x, 0.0), 1.0); return x * x * (3 - 2 * x)

LAY = {p.stem: Image.open(p).convert("RGBA") for p in L.glob("*.png")}
GEO = json.loads((L / "geom.json").read_text())

# ---------- data (exp. 06, segment B: holding the guitar, G chord) ----------
t_all, mv = emg.load_recording("B")
s1 = emg.notched(mv, band=(20, 450)); s2 = emg.notched(mv); env = emg.moving_rms(s2, 0.2)
relax = np.zeros_like(t_all, bool)
for a, b, k in emg.RECORDINGS["B"]["phases"]:
    if k == "relax" and a > 14: relax |= emg.window(t_all, a, b)
base = emg.rms(s2[relax]); lvl = np.where(env >= 2.72 * base, 2, np.where(env >= 1.49 * base, 1, 0))
chg = np.flatnonzero(np.diff(lvl) != 0)
def at_t(arr, tt): return arr[min(np.searchsorted(t_all, tt), len(t_all) - 1)]

# ---------- drawing helpers ----------
def text(d, xy, s, f, fill=INK, anchor="la", a=1.0, bg=(255, 255, 255)):
    c = tuple(int(bg[i] + (fill[i] - bg[i]) * a) for i in range(3)); d.text(xy, s, font=f, fill=c, anchor=anchor)

def layer(img, name, a):
    if a <= 0: return img
    lay = LAY[name]
    if a < 1:
        lay = lay.copy(); al = lay.getchannel("A").point(lambda v: int(v * a)); lay.putalpha(al)
    return Image.alpha_composite(img, lay)

def pill(img, s, a=1.0, y=846):
    if a <= 0: return img
    ov = Image.new("RGBA", (W, H)); d = ImageDraw.Draw(ov); f = font("Medium", 18)
    w = d.textlength(s, font=f) + 44
    d.rounded_rectangle([W / 2 - w / 2, y - 20, W / 2 + w / 2, y + 20], 20, fill=(241, 238, 230, int(255 * a)))
    d.text((W / 2, y), s, font=f, fill=INK + (int(255 * a),), anchor="mm")
    return Image.alpha_composite(img, ov)

SS = 3
def comet(img, box, tt, yy, head, span, lo, hi, width=6, sweep=None, fade=0.45, solid=None):
    """Reference-style trace: drawn up to `head`, older than `span` gone, tail fades, lavender head."""
    x0, y0, x1, y1 = box; bw, bh = x1 - x0, y1 - y0
    m = (tt <= head) & (tt >= head - span)
    if m.sum() < 2: return img
    t_, y_ = tt[m], yy[m]
    npx = int(bw)
    if sweep is None: sweep = (head - span, head)
    xs = (t_ - sweep[0]) / (sweep[1] - sweep[0]) * bw
    keep = (xs >= 0) & (xs <= bw)
    t_, y_, xs = t_[keep], y_[keep], xs[keep]
    if xs.size < 2: return img
    bins = np.clip(xs.astype(int), 0, npx)
    st = np.flatnonzero(np.r_[True, np.diff(bins) > 0])
    X = xs[st]; Y = np.maximum.reduceat(np.clip(y_, lo, hi), st) if width < 4 else np.add.reduceat(np.clip(y_, lo, hi), st) / np.diff(np.r_[st, len(y_)])
    if width < 4:
        Ymin = np.minimum.reduceat(np.clip(y_, lo, hi), st)
    T_ = t_[st]
    lay = Image.new("RGBA", (bw * SS, bh * SS)); d = ImageDraw.Draw(lay)
    py = lambda v: (bh - (v - lo) / (hi - lo) * bh) * SS
    for i in range(1, len(X)):
        age = (head - T_[i]) / span
        a = 1.0 if age < fade else max(0.0, 1 - (age - fade) / (1 - fade))
        hk = max(0.0, 1 - age / 0.12)
        col = solid if solid is not None else tuple((TAIL * (1 - hk) + HEAD * hk).astype(int))
        c = tuple(col) + (int(255 * a),)
        if width < 4:
            d.line([(X[i] * SS, py(Ymin[i])), (X[i] * SS, py(Y[i]))], fill=c, width=width * SS)
            d.line([(X[i - 1] * SS, py((Y[i - 1] + Ymin[i - 1]) / 2)), (X[i] * SS, py((Y[i] + Ymin[i]) / 2))], fill=c, width=width * SS)
        else:
            d.line([(X[i - 1] * SS, py(Y[i - 1])), (X[i] * SS, py(Y[i]))], fill=c, width=width * SS)
            r = width * SS / 2; d.ellipse([X[i] * SS - r, py(Y[i]) - r, X[i] * SS + r, py(Y[i]) + r], fill=c)
    lay = lay.resize((bw, bh), Image.LANCZOS)
    img.alpha_composite(lay, (int(x0), int(y0))); return img

def grid(d, box, step=24, col=(236, 236, 236)):
    x0, y0, x1, y1 = box
    for x in range(int(x0), int(x1) + 1, step): d.line([(x, y0), (x, y1)], fill=col)
    for y in range(int(y0), int(y1) + 1, step): d.line([(x0, y), (x1, y)], fill=col)

def arc_pos(pts, frac):
    p = np.array(pts, float); c = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    Ls = c[-1] * (frac % 1); i = int(np.clip(np.searchsorted(c, Ls), 1, len(c) - 1))
    a = (Ls - c[i - 1]) / max(c[i] - c[i - 1], 1e-6); return p[i - 1] + (p[i] - p[i - 1]) * a

def dots(img, pts, t, n, speed, col, r, trail=4):
    ov = Image.new("RGBA", (W * 2, H * 2)); d = ImageDraw.Draw(ov)
    for j in range(n):
        for k in range(trail):
            x, y = arc_pos(pts, t * speed + j / n - k * 0.012); rr = (r - k * 1.2) * 2; al = int(230 * (1 - k / trail))
            d.ellipse([x * 2 - rr, y * 2 - rr, x * 2 + rr, y * 2 + rr], fill=tuple(col) + (al,))
    return Image.alpha_composite(img, ov.resize((W, H), Image.LANCZOS))

# ---------- scenes ----------
ARCH_ORDER = [("arch_panel", 0.3), ("arch_arm", 0.8), ("arch_ad", 1.8), ("arch_esp", 2.8), ("arch_lap", 4.4), ("arch_br", 5.2), ("arch_arrows", 1.3), ("arch_brackets", 6.0), ("arch_next", 6.6)]
def scene_arch(t, img):
    for name, t0 in ARCH_ORDER:
        img = layer(img, name, ease((t - t0) / 0.6))
    arrows = GEO["arch_arrows"]; starts = [1.6, 2.4, 4.0, 4.8]
    for (p, q), t0 in zip(arrows, starts):
        if t > t0: img = dots(img, [p, q], t, 2, 0.9, TAIL, 5, 5)
    if t > 5.6:                                          # ring in the browser follows the recorded level
        d = ImageDraw.Draw(img); lv = int(at_t(lvl, 22.5 + t * 1.5))
        d.ellipse([1420, 412, 1480, 472], outline=LEVEL[lv], width=7)
    a = ease((t - 0.2) / 0.5) * (1 - ease((t - 9.4) / 0.5))
    msg = "Three snap electrodes pick up forearm muscle activity" if t < 4.2 else "The ESP32 filters it in real time; only a tension level leaves the board"
    return pill(img, msg, a)

C_T0 = 24.0
CIRC_END = 4.5
def scene_circuit(t, img):
    img = layer(img, "circuit", 1.0)
    cur = C_T0 + t; e = float(at_t(env, cur)); lv = int(at_t(lvl, cur)); k = min(e / 25.0, 1.0)
    for i in range(3):
        img = dots(img, GEO["wires"][f"w_lead{i}"], t, 3, 0.35, np.array(Image.new("RGB", (1, 1), GEO["wire_colors"][f"w_lead{i}"]).getpixel((0, 0))), 4 + 3 * k)
    img = dots(img, GEO["wires"]["w_sig"], t, 5, 0.45, np.array([0, 160, 135]), 4 + 4 * k)
    d = ImageDraw.Draw(img)
    m = GEO["module"]; g = int(120 + 100 * (0.5 + 0.5 * np.sin(t * 5)))
    d.rounded_rectangle([m[0] - 6, m[1] - 6, m[2] + 6, m[3] + 6], 8, outline=(0, 160, 135, g), width=4)
    if ((t_all[chg] <= cur) & (t_all[chg] > cur - 0.3)).any():
        lx, ly = GEO["led"]
        ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
        for rr, al in [(52, 50), (38, 90), (22, 255)]: od.ellipse([lx - rr, ly - rr, lx + rr, ly + rr], fill=(230, 75, 53, al))
        img = Image.alpha_composite(img, ov); d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = GEO["scope"]
    d.rounded_rectangle([x0, y0, x1, y1], 12, fill=(250, 250, 250), outline=(225, 225, 225), width=2)
    grid(d, (x0 + 14, y0 + 40, x1 - 14, y1 - 40), 20)
    text(d, (x0 + 16, y0 + 22), "GPIO4  ·  muscle activity (RMS)", font("SemiBold", 14), INK, "lm")
    img = comet(img, (x0 + 14, y0 + 40, x1 - 14, y1 - 40), t_all, env, cur, 3.0, 0, 30, 5)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0 + 14, y1 - 32, x0 + 150, y1 - 10], 11, fill=LEVEL[lv])
    text(d, (x0 + 82, y1 - 21), LNAME[lv], font("Bold", 13), (255, 255, 255), "mm")
    text(d, (x1 - 16, y1 - 21), f"{e:4.1f} mV", font("Medium", 13), MUTED, "rm")
    a = ease((t - 0.5) / 0.4) * (1 - ease((t - CIRC_END + 0.4) / 0.4))
    return pill(img, "AD8232 → GPIO4, sampled at 1 kHz  ·  the LED flashes when the tension level changes", a)

HAND = Image.open(U + "5580a21e-image.jpg").convert("RGB").crop((430, 697, 870, 1185))
TAB_S = ["e", "B", "G", "D", "A", "E"]; GSH = ["3", "0", "0", "0", "2", "3"]
D_T0, D_LEN = 22.5, 12.0
STRUMS = [26.5 + k for k in range(4)]
def scene_demo(t, img):
    cur = D_T0 + t; lv = int(at_t(lvl, cur))
    d = ImageDraw.Draw(img)
    hs = HAND.resize((600, int(600 * HAND.height / HAND.width)), Image.LANCZOS)
    img.paste(hs, (44, 176)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([60, 192, 300, 226], 17, fill=(25, 25, 25)); text(d, (180, 209), "practice video", font("SemiBold", 15), (240, 240, 240), "mm")
    d.rounded_rectangle([60, 176 + hs.height - 52, 260, 176 + hs.height - 16], 18, fill=LEVEL[lv])
    text(d, (160, 176 + hs.height - 34), "tension: " + LNAME[lv], font("Bold", 16), (255, 255, 255), "mm")
    gx, gw = 860, 690; sweep = (D_T0, D_T0 + D_LEN); X = lambda tt: gx + (tt - D_T0) / D_LEN * gw
    rows = [("TAB", "G chord (draft)", 186, 104), ("raw", "1 kHz ADC", 312, 100), ("① notch", "60 Hz mains removed", 428, 100),
            ("② band-pass", "45–200 Hz", 544, 100), ("③ RMS", "200 ms → tension level", 660, 120)]
    for name, sub, y, h in rows:
        text(d, (690, y + 30), name, font("Bold", 21), INK); text(d, (690, y + 56), sub, font("Regular", 14), MUTED)
        if name != "TAB": grid(d, (gx, y + 4, gx + gw, y + h - 4), 25, (240, 240, 240))
    for k, s in enumerate(TAB_S):
        y = 196 + k * 16; d.line([(gx, y), (gx + gw, y)], fill=(185, 185, 185)); text(d, (gx - 10, y), s, font("Regular", 12), MUTED, "rm")
    for stt in STRUMS:
        x = X(stt); past = stt <= cur
        for k, f in enumerate(GSH):
            y = 196 + k * 16; d.rectangle([x - 7, y - 7, x + 7, y + 7], fill=(255, 255, 255))
            text(d, (x, y), f, font("Bold", 13), INK if past else (175, 175, 175), "mm")
    img = comet(img, (gx, 316, gx + gw, 408), t_all, mv, cur, 6.0, 1150, 2050, 1, sweep, 0.5)
    img = comet(img, (gx, 432, gx + gw, 524), t_all, s1, cur, 6.0, -170, 170, 1, sweep, 0.5)
    img = comet(img, (gx, 548, gx + gw, 640), t_all, s2, cur, 6.0, -100, 100, 1, sweep, 0.5)
    img = comet(img, (gx, 664, gx + gw, 776), t_all, env, cur, 6.0, 0, 32, 6, sweep, 0.5)
    d = ImageDraw.Draw(img)
    for th, nm in [(1.49 * base, "medium"), (2.72 * base, "high")]:
        y = 776 - th / 32 * 112
        for x in range(gx, gx + gw, 12): d.line([(x, y), (x + 6, y)], fill=LEVEL[1 if nm == "medium" else 2])
        text(d, (gx + gw - 4, y - 4), nm, font("Medium", 12), LEVEL[1 if nm == "medium" else 2], "rs")
    xp = X(cur); d.line([(xp, 182), (xp, 780)], fill=(150, 130, 240), width=2)
    text(d, (690, 806), "draft · video not synced with the data · TAB is a placeholder", font("Regular", 12), MUTED, "ls")
    a = ease(t / 0.5) * (1 - ease((t - D_LEN + 0.6) / 0.5))
    return pill(img, "Recorded session: pressing a G chord while holding the guitar  ·  same filters as the firmware", a)

SCENES = [(scene_arch, 10.0), (scene_circuit, 8.0), (scene_demo, D_LEN)]
BASE = Image.new("RGBA", (W, H), (255, 255, 255, 255))
def render(ft):
    acc = 0
    for fn, dur in SCENES:
        if ft < acc + dur:
            lt = ft - acc
            img = layer(BASE.copy(), "header", ease(ft / 0.6))
            img = fn(lt, img)
            if fn is not scene_arch and lt < 0.4:          # cross-fade content in from the header-only frame
                img = Image.blend(layer(BASE.copy(), "header", 1).convert("RGB").convert("RGBA"), img, ease(lt / 0.4))
            return img.convert("RGB")
        acc += dur
    return BASE.convert("RGB")

if __name__ == "__main__":
    total = sum(d for _, d in SCENES)
    if SNAP:
        for k, ft in enumerate([7.5, 14.0, 27.0]): render(ft).save(f"{SNAP}/v3_{k}.png")
        sys.exit()
    OUT.mkdir(exist_ok=True)
    mp4, gif = OUT / "so_i_picked_up_music_readme.mp4", OUT / "so_i_picked_up_music_readme.gif"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    for k in range(int(total * FPS)): p.stdin.write(render(k / FPS).tobytes())
    p.stdin.close(); p.wait()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf",
                    "scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=5",
                    "-loop", "0", str(gif)], check=True)
    print("done", total)
