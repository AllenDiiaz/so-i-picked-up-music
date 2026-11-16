"""25 s README video, 2026-11 architecture: demo -> architecture -> A/B (naive vs designed) -> circuit.

    .venv/bin/python media/readme_video/v6_gif.py [OUT_DIR] [SNAP_DIR]

OUT_DIR defaults to docs/figures (so_i_picked_up_music_25s.mp4 / .gif). With SNAP_DIR, only still
frames of every scene are written there, for checking the layout.

Inputs: build/v6 (v6_layers.py), build/ab (v6_capture_ab.py) and the previous render in private/.

  demo          frames 0-8.5 s of the previous render, unchanged: practice video + lab EMG, with its
                own "draft ... placeholders" note. Replaced once the real take exists.
  architecture  new: two cores on the board, bridge, browser view (WebXR-ready), local AI coach,
                the command downlink (dashed: built, not yet run on the board).
  A/B           new: the real front end recorded in headless Chrome, driven by the simulated device,
                naive (left) against designed (right), lined up on the end of the segment.
  circuit       frames 16.5-19.5 s of the previous render, unchanged.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
V6, ABDIR = HERE / "build" / "v6", HERE / "build" / "ab"
OLD = HERE / "private" / "so_i_picked_up_music_20s.mp4"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "figures"
SNAP = Path(sys.argv[2]) if len(sys.argv) > 2 else None
W, H, FPS = 1600, 900, 12
D_LEN, A_LEN, B_LEN, C_LEN = 8.5, 6.5, 7.0, 3.0
C_FROM = 16.5                                   # circuit: start in the previous render
TAIL, LAVD = np.array([10, 155, 255]), np.array([122, 107, 201])     # kit colours: blue dots, lavender

LAY = {p.stem: Image.open(p).convert("RGBA") for p in V6.glob("*.png") if not p.stem.startswith("_")}
GEO = json.loads((V6 / "geom.json").read_text())
AB = GEO["ab"]


def old_frames(start, seconds):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(seconds), "-i", str(OLD), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


DEMO, CIRC = old_frames(0, D_LEN), old_frames(C_FROM, C_LEN)
ABF = {m: [Image.open(p).convert("RGB") for p in sorted((ABDIR / m).glob("*.png"))] for m in ("naive", "designed")}
META = json.loads((ABDIR / "meta.json").read_text())


def ease(x): x = min(max(x, 0.0), 1.0); return x * x * (3 - 2 * x)


def layer(img, name, a):
    if a <= 0: return img
    lay = LAY[name]
    if a < 1:
        lay = lay.copy(); lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
    return Image.alpha_composite(img, lay)


def arc_pos(pts, frac):
    p = np.array(pts, float); c = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    s = c[-1] * (frac % 1); i = int(np.clip(np.searchsorted(c, s), 1, len(c) - 1))
    a = (s - c[i - 1]) / max(c[i] - c[i - 1], 1e-6); return p[i - 1] + (p[i] - p[i - 1]) * a


def dots(img, pts, t, n, speed, col, r, trail=4):
    """Moving dots along a wire (kit style)."""
    ov = Image.new("RGBA", (W * 2, H * 2)); d = ImageDraw.Draw(ov)
    for j in range(n):
        for k in range(trail):
            x, y = arc_pos(pts, t * speed + j / n - k * 0.012); rr = (r - k * 1.0) * 2; al = int(230 * (1 - k / trail))
            d.ellipse([x * 2 - rr, y * 2 - rr, x * 2 + rr, y * 2 + rr], fill=tuple(int(c) for c in col) + (al,))
    return Image.alpha_composite(img, ov.resize((W, H), Image.LANCZOS))


BASE = layer(Image.new("RGBA", (W, H), (255, 255, 255, 255)), "header", 1.0)


def scene_demo(t):
    return Image.fromarray(DEMO[min(int(t * FPS), len(DEMO) - 1)]).convert("RGBA")


ARCH_ORDER = [("panel", 0.0), ("sec", 0.15), ("arm", 0.2), ("ad", 0.6), ("wires", 0.9), ("esp", 0.9), ("lap", 1.4), ("view", 1.7),
              ("ai", 2.3), ("ai_wires", 2.5), ("cmd", 3.2), ("loop", 4.0), ("legend", 4.2)]
ARCH_DOTS = [("ad_esp", 1.0, TAIL, 2, 0.9), ("hop", 1.2, TAIL, 1, 1.4), ("esp_bridge", 1.5, TAIL, 2, 0.8), ("bridge_view", 1.9, TAIL, 2, 0.8),
             ("bridge_ai", 2.6, TAIL, 1, 0.7), ("ai_bridge", 2.9, LAVD, 1, 0.7), ("cmd", 3.4, LAVD, 2, 0.5), ("param", 3.7, LAVD, 1, 1.4)]


def scene_arch(t):
    img = BASE.copy()
    for name, t0 in ARCH_ORDER:
        img = layer(img, name, ease((t - t0) / 0.5))
    for name, t0, col, n, speed in ARCH_DOTS:
        if t > t0: img = dots(img, GEO["wires"][name], t - t0, n, speed, col, 4.5, 3)
    img = layer(img, "cmd_label", ease((t - 3.2) / 0.5))
    return layer(img, "pill_arch", ease((t - 0.3) / 0.4) * (1 - ease((t - A_LEN + 0.5) / 0.4)))


def rounded(im, r=12):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], r, fill=255)
    return m


def scene_ab(t):
    img = layer(BASE.copy(), "ab", 1.0)
    k = min(int(t * FPS), META["naive"]["frames"] - 1)
    for mode, x in (("naive", AB["left"]), ("designed", AB["right"])):
        fr = ABF[mode][k]
        img.paste(fr, (x, AB["y"]), rounded(fr))
    return layer(img, "pill_ab", ease((t - 0.3) / 0.4) * (1 - ease((t - B_LEN + 0.5) / 0.4)))


def scene_circuit(t):
    return Image.fromarray(CIRC[min(int(t * FPS), len(CIRC) - 1)]).convert("RGBA")


SCENES = [(scene_demo, D_LEN), (scene_arch, A_LEN), (scene_ab, B_LEN), (scene_circuit, C_LEN)]
TOTAL = sum(d for _, d in SCENES)


def render(ft):
    acc = 0
    for fn, dur in SCENES:
        if ft < acc + dur:
            lt = ft - acc
            out = fn(lt)
            if lt < 0.35 and acc > 0:           # cross-fade in from the header-only frame
                out = Image.blend(BASE, out, ease(lt / 0.35))
            return out.convert("RGB")
        acc += dur
    return BASE.convert("RGB")


if __name__ == "__main__":
    if SNAP:
        SNAP.mkdir(parents=True, exist_ok=True)
        for ft in [1.0, 8.0, 9.2, 10.5, 12.0, 14.6, 15.4, 17.2, 19.0, 21.5, 22.5, 24.5]:
            render(ft).save(SNAP / f"v6_{ft:05.1f}.png")
        sys.exit(f"stills in {SNAP}")
    OUT.mkdir(parents=True, exist_ok=True)
    mp4, gif = OUT / "so_i_picked_up_music_25s.mp4", OUT / "so_i_picked_up_music_25s.gif"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4)], stdin=subprocess.PIPE)
    for k in range(int(TOTAL * FPS)): p.stdin.write(render(k / FPS).tobytes())
    p.stdin.close(); p.wait()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf",
                    "fps=10,scale=1100:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    "-loop", "0", str(gif)], check=True)
    print(f"done: {TOTAL:.1f} s, {mp4.name} {mp4.stat().st_size / 1e6:.1f} MB, {gif.name} {gif.stat().st_size / 1e6:.1f} MB")
