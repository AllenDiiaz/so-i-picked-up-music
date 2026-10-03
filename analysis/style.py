"""Shared figure style: fixed colors, font and white background for every plot."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIG_DIR = REPO / "docs" / "figures"

# One color per scenario, used in every figure.
COLORS = {
    "A": "#7f7f7f",  # gray
    "B": "#f08060",  # coral (experiment 03 only)
    "C": "#1a9e8f",  # teal
    "D": "#2b6cc4",  # blue
}
WARMUP_COLOR = "#e6e6e6"
REF_COLOR = "#555555"

DPI = 200
WIDTH_IN = 7.5


def apply():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.transparent": False,
        "axes.grid": True,
        "grid.color": "#dddddd",
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def fig_to_image(fig):
    """Render a figure to an RGB Pillow image (one GIF frame)."""
    import numpy as np
    from PIL import Image

    fig.canvas.draw()
    return Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")


def save_gif(frames, durations_ms, name, colors=64):
    """Write frames as a looping GIF with one shared palette, then compress with gifsicle.

    The palette comes from the first and the middle frame together, so colors that only
    appear while animating (cursor, dimmed elements) are included.
    """
    import shutil
    import subprocess
    from PIL import Image

    if shutil.which("gifsicle") is None:
        raise SystemExit("gifsicle not found (macOS: brew install gifsicle)")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    first, middle = frames[0], frames[len(frames) // 2]
    sample = Image.new("RGB", (first.width * 2, first.height))
    sample.paste(first, (0, 0))
    sample.paste(middle, (first.width, 0))
    palette = sample.quantize(colors=colors, dither=Image.Dither.NONE)
    # Quantizing averages the background slightly off white; snap near-white entries back.
    entries = palette.getpalette()
    for i in range(0, len(entries), 3):
        if min(entries[i:i + 3]) >= 248:
            entries[i:i + 3] = [255, 255, 255]
    palette.putpalette(entries)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    quantized[0].save(path, save_all=True, append_images=quantized[1:],
                      duration=durations_ms, loop=0, disposal=1, optimize=False)
    subprocess.run(["gifsicle", "-O3", "--batch", str(path)], check=True)
    print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size / 1e6:.2f} MB, {len(frames)} frames)")


def save(fig, name):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path.relative_to(REPO)}")
