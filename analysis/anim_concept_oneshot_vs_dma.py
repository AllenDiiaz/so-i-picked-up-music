"""README animation: why DMA sampling keeps sample times fixed (illustration, not data).

Top: oneshot reads, where the CPU takes each sample, so a busy CPU delays the sample.
Bottom: DMA, where a hardware clock takes the samples and the CPU only collects frames,
so only the collection time moves.

Every GIF frame shows the complete diagram; a time cursor sweeps across and the part
it has passed is drawn at full strength. The first frame is the complete diagram.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import style

FPS = 10                 # GIF frame times are stored in 10 ms units
SWEEP_S = 6.5
HOLD_MS = 1500
T_END = 12.0             # illustrative time axis, 1 sample per unit

SAMPLE = "#333333"
TICK = "#c8c8c8"
BUSY_FACE = "#eeeeee"
DIM = 0.22               # alpha for the part the cursor has not reached yet

ONESHOT_BUSY = (4.35, 5.75)
ONESHOT_SAMPLES = [0, 1, 2, 3, 4, 5.8, 6, 7, 8, 9, 10, 11]   # sample 5 waits for the CPU
DMA_BUSY = (7.3, 8.9)
DMA_SAMPLES = list(range(12))
FRAME_ENDS = [3.5, 7.5, 11.5]                                  # 4 samples per frame here
FRAME_PICKUP = [3.65, 8.95, 11.65]                             # second pickup waits for the CPU


def draw(ax_top, ax_bottom, cursor):
    """Draw both rows; elements after the cursor are dimmed. cursor=None means all solid."""
    def a(x):
        return 1.0 if cursor is None or x <= cursor else DIM

    coral = style.COLORS["B"]
    for ax in (ax_top, ax_bottom):
        ax.clear()
        ax.set_xlim(-0.6, T_END + 0.4)
        ax.set_ylim(-0.2, 2.3)
        ax.axis("off")
        for t in range(int(T_END)):
            ax.plot([t, t], [0.05, 2.05], color=TICK, linewidth=0.8, linestyle=(0, (2, 2)), zorder=0)

    # --- top: oneshot ---
    ax = ax_top
    ax.text(-0.6, 2.3, "Oneshot read: the CPU decides when each sample is taken",
            fontsize=10.5, fontweight="bold", va="bottom")
    ax.text(-0.55, 1.55, "samples", fontsize=8, ha="right", va="center", color=style.REF_COLOR)
    ax.text(-0.55, 0.55, "CPU", fontsize=8, ha="right", va="center", color=style.REF_COLOR)
    b0, b1 = ONESHOT_BUSY
    ax.add_patch(Rectangle((b0, 0.3), b1 - b0, 0.5, facecolor=BUSY_FACE, edgecolor="#888888",
                           hatch="///", linewidth=0.8, alpha=a(b0)))
    ax.text((b0 + b1) / 2, 0.92, "CPU busy\n(e.g. Wi-Fi)", fontsize=7.5, ha="center", va="bottom",
            color="#555555", alpha=a(b0))
    for s in ONESHOT_SAMPLES:
        delayed = s not in range(12)
        ax.plot(s, 1.55, "o", markersize=7, color=coral if delayed else SAMPLE, alpha=a(s))
    ax.annotate("", xy=(5.8, 1.85), xytext=(5.0, 1.85),
                arrowprops=dict(arrowstyle="->", color=coral, lw=1.4, alpha=a(5.8)))
    ax.text(5.4, 1.95, "sample delayed", fontsize=8, color=coral, ha="center", va="bottom", alpha=a(5.8))
    ax.text(T_END + 0.3, 1.55, "uneven\nspacing", fontsize=8, ha="right", va="center",
            color=coral, alpha=a(T_END - 0.5))

    # --- bottom: DMA ---
    ax = ax_bottom
    ax.text(-0.6, 2.3, "DMA: a hardware clock takes the samples; the CPU only collects frames",
            fontsize=10.5, fontweight="bold", va="bottom")
    ax.text(-0.55, 1.55, "samples", fontsize=8, ha="right", va="center", color=style.REF_COLOR)
    ax.text(-0.55, 0.55, "CPU", fontsize=8, ha="right", va="center", color=style.REF_COLOR)
    for s in DMA_SAMPLES:
        ax.plot(s, 1.55, "o", markersize=7, color=SAMPLE, alpha=a(s))
    for e in FRAME_ENDS:
        ax.plot([e, e], [1.3, 1.8], color="#888888", linewidth=1.0, alpha=a(e))
    ax.text(1.5, 1.95, "frame (4 samples here, 16 in the firmware)", fontsize=7.5, ha="left",
            va="bottom", color=style.REF_COLOR, alpha=a(0))
    b0, b1 = DMA_BUSY
    ax.add_patch(Rectangle((b0, 0.3), b1 - b0, 0.5, facecolor=BUSY_FACE, edgecolor="#888888",
                           hatch="///", linewidth=0.8, alpha=a(b0)))
    ax.text((b0 + b1) / 2, 0.92, "CPU busy\n(e.g. Wi-Fi)", fontsize=7.5, ha="center", va="bottom",
            color="#555555", alpha=a(b0))
    for edge, pickup in zip(FRAME_ENDS, FRAME_PICKUP):
        late = pickup - edge > 0.5
        ax.plot(pickup, 0.1, "^", markersize=8, color=coral if late else SAMPLE, alpha=a(pickup))
    ax.annotate("", xy=(8.95, 0.1), xytext=(7.65, 0.1),
                arrowprops=dict(arrowstyle="->", color=coral, lw=1.4, alpha=a(8.95)))
    ax.text(9.15, 0.55, "frame collected late;\nsample times unchanged", fontsize=8, color=coral,
            ha="left", va="center", alpha=a(8.95))
    ax.text(0.15, 0.1, "▲ CPU collects a frame", fontsize=7.5, color=style.REF_COLOR, ha="left",
            va="center", alpha=a(0))

    if cursor is not None:
        for ax in (ax_top, ax_bottom):
            ax.plot([cursor, cursor], [-0.15, 2.15], color=style.COLORS["D"], linewidth=1.6, zorder=5)


def main():
    style.apply()
    fig = plt.figure(figsize=(8.0, 4.8), dpi=100)
    ax_top = fig.add_axes([0.08, 0.50, 0.90, 0.36])
    ax_bottom = fig.add_axes([0.08, 0.07, 0.90, 0.36])
    fig.text(0.98, 0.955, "Illustration (not measured data)", ha="right", va="center", fontsize=11,
             fontweight="bold", color="#333333",
             bbox=dict(boxstyle="round,pad=0.35", fc="#fff6d6", ec="#333333", lw=1.0))
    fig.text(0.02, 0.955, "Oneshot vs. DMA sampling", ha="left", va="center", fontsize=13,
             fontweight="bold")
    fig.text(0.98, 0.015, "Dashed gray lines: ideal 1 kHz sample times. Not to scale.",
             ha="right", va="bottom", fontsize=7.5, color=style.REF_COLOR)

    frames, durations = [], []
    draw(ax_top, ax_bottom, None)                            # first frame: complete diagram
    frames.append(style.fig_to_image(fig))
    durations.append(HOLD_MS)
    n = int(SWEEP_S * FPS)
    for k in range(n):
        draw(ax_top, ax_bottom, -0.4 + (T_END + 0.4) * k / (n - 1))
        frames.append(style.fig_to_image(fig))
        durations.append(1000 // FPS)
    plt.close(fig)
    style.save_gif(frames, durations, "concept_oneshot_vs_dma.gif")


if __name__ == "__main__":
    main()
