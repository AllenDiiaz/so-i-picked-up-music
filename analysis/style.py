"""Shared figure style for every plot and animation in the repo (Nature-like).

Sizes are given at the final output size: figures are 183 mm wide (Nature double
column) and fonts are in points at that width. PNGs are written at 300 dpi; GIF frames
are rendered at GIF_DPI so a 183 mm figure becomes about 1440 px wide.
"""
from pathlib import Path

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIG_DIR = REPO / "docs" / "figures"

# --- colours (NPG palette), chosen by meaning and used the same way in every figure ---
GRAY = "#8C8C8C"        # baseline / relax / no interference
TEAL = "#00A087"        # positive / light / sampler on core 1
BLUE = "#3C5488"        # intermediate / chord
RED = "#E64B35"         # negative / strong / sampler on core 0
LIGHT_BLUE = "#4DBBD5"  # supplementary
SALMON = "#F39B7F"      # supplementary
RAW = "#3B3B3B"         # raw signal traces
ENVELOPE = BLUE         # RMS envelopes
REF_COLOR = "#555555"   # reference lines and secondary text
SHADE_ALPHA = 0.12      # phase backgrounds: the phase colour at this alpha

# Scenario keys used by experiments 03 and 04.
COLORS = {"A": GRAY, "B": RED, "C": TEAL, "D": BLUE}

# --- sizes ---
MM = 1 / 25.4
WIDTH_IN = 183 * MM          # Nature double column
SINGLE_WIDTH_IN = 89 * MM    # Nature single column
DPI = 300
GIF_DPI = 200                # 183 mm -> about 1440 px

LABEL_PT = 8
TICK_PT = 7
LEGEND_PT = 7
TITLE_PT = 8
NOTE_PT = 6.5                # small in-figure notes (annotations, GIF footers)
PANEL_PT = 8


def _font_family():
    for name in ("Arial", "Helvetica", "DejaVu Sans"):
        try:
            font_manager.findfont(font_manager.FontProperties(family=name), fallback_to_default=False)
            return name
        except ValueError:
            continue
    return "DejaVu Sans"


def apply():
    plt.rcParams.update({
        "font.family": _font_family(),
        "font.size": LABEL_PT,
        "axes.titlesize": TITLE_PT,
        "axes.titleweight": "normal",
        "axes.labelsize": LABEL_PT,
        "legend.fontsize": LEGEND_PT,
        "legend.frameon": False,
        "xtick.labelsize": TICK_PT,
        "ytick.labelsize": TICK_PT,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.minor.width": 0.5,
        "ytick.minor.width": 0.5,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "xtick.minor.size": 1.8,
        "ytick.minor.size": 1.8,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "lines.linewidth": 1.0,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.transparent": False,
        "hatch.linewidth": 0.6,
    })


def hgrid(ax):
    """Very faint horizontal lines, only where reading values off the axis matters."""
    ax.yaxis.grid(True, color="#EEEEEE", linewidth=0.5)
    ax.set_axisbelow(True)


def panel_label(ax, letter, x=-0.09, y=1.02):
    """Bold lower-case panel letter at the top left of an axes (axes coordinates)."""
    ax.text(x, y, letter, transform=ax.transAxes, fontsize=PANEL_PT, fontweight="bold",
            ha="right", va="bottom")


def shade(ax, start, end, color, alpha=SHADE_ALPHA, **kwargs):
    return ax.axvspan(start, end, color=color, alpha=alpha, linewidth=0, zorder=0, **kwargs)


def ref_line(ax, y, **kwargs):
    kwargs.setdefault("color", REF_COLOR)
    kwargs.setdefault("linewidth", 0.6)
    kwargs.setdefault("linestyle", (0, (4, 3)))
    return ax.axhline(y, **kwargs)


def illustration_badge(fig, x, y, text="Illustration (not measured data)", **kwargs):
    """Gray-framed small label for conceptual (non-data) figures."""
    return fig.text(x, y, text, fontsize=TITLE_PT, color=REF_COLOR, ha=kwargs.pop("ha", "right"),
                    va=kwargs.pop("va", "center"),
                    bbox=dict(boxstyle="square,pad=0.35", fc="white", ec=GRAY, lw=0.6), **kwargs)


def fig_to_image(fig):
    """Render a figure to an RGB Pillow image (one GIF frame)."""
    import numpy as np
    from PIL import Image

    fig.canvas.draw()
    return Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")


def save_gif(frames, durations_ms, name, colors=128):
    """Write frames as a looping GIF with one shared palette, then compress with gifsicle.

    The palette is built from several frames spread over the animation, so colours that
    only appear while animating are included.
    """
    import shutil
    import subprocess
    from PIL import Image

    if shutil.which("gifsicle") is None:
        raise SystemExit("gifsicle not found (macOS: brew install gifsicle)")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    picks = sorted({0, len(frames) // 4, len(frames) // 2, 3 * len(frames) // 4, len(frames) - 1})
    first = frames[0]
    # A swatch strip of the palette colours (and their phase-background tints) makes sure the
    # quantizer keeps them even when they cover only a few pixels next to many anti-aliased grays.
    swatch_h = first.height // 3
    sample = Image.new("RGB", (first.width * len(picks), first.height + swatch_h), "white")
    for i, k in enumerate(picks):
        sample.paste(frames[k], (first.width * i, 0))
    keys = [GRAY, TEAL, BLUE, RED, LIGHT_BLUE, SALMON, RAW, REF_COLOR]
    block = sample.width // (2 * len(keys))
    for j, c in enumerate(keys):
        rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        tint = tuple(round(255 + (v - 255) * SHADE_ALPHA) for v in rgb)
        sample.paste(Image.new("RGB", (block, swatch_h), rgb), (2 * j * block, first.height))
        sample.paste(Image.new("RGB", (block, swatch_h), tint), ((2 * j + 1) * block, first.height))
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
    print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size / 1e6:.2f} MB, {len(frames)} frames, "
          f"{first.width}x{first.height})")


def save(fig, name, width_in=WIDTH_IN):
    """Save a PNG at DPI, exactly width_in wide, so fonts keep their point size at that width.

    The figure is cropped to its content first (labels outside the axes included) and then
    padded with white on both sides to the target width.
    """
    import io
    from PIL import Image

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / name
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    img = Image.open(buf).convert("RGB")
    target = round(width_in * DPI)
    if img.width < target:
        canvas = Image.new("RGB", (target, img.height), "white")
        canvas.paste(img, ((target - img.width) // 2, 0))
        img = canvas
    elif img.width > target:
        print(f"warning: {name} is {img.width} px wide, more than {target} px ({width_in / MM:.0f} mm)")
    img.save(path, dpi=(DPI, DPI), optimize=True)
    print(f"wrote {path.relative_to(REPO)} ({img.width}x{img.height})")
