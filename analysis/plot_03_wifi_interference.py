"""Figure for experiment 03: per-second frame_dt range over time for A, B and C."""
import numpy as np
import matplotlib.pyplot as plt

import style
from data import FRAME_PERIOD_US, load_03

# The first 2 statistics windows overlap Wi-Fi start-up (see the experiment notes);
# the second window of B and C ends at 2.401 s.
WARMUP_END_S = 2.40

TOP_YLIM = 60      # A and C
BOTTOM_YLIM = 1500  # B

SCENARIOS = {
    "A": ("a_no_wifi_core1.txt", "A: no Wi-Fi, sampler on core 1"),
    "B": ("b_wifi_core0.txt", "B: Wi-Fi, sampler on core 0"),
    "C": ("c_wifi_core1.txt", "C: Wi-Fi, sampler on core 1"),
}


def draw_band(ax, key):
    filename, label = SCENARIOS[key]
    starts, ends, mins, maxs = load_03(filename)
    lo, hi = mins - FRAME_PERIOD_US, maxs - FRAME_PERIOD_US
    # Each window spans [start, end]; draw it as a flat step over that span.
    x = np.column_stack([starts, ends]).ravel()
    ylo, yhi = np.repeat(lo, 2), np.repeat(hi, 2)
    color = style.COLORS[key]
    ax.fill_between(x, ylo, yhi, color=color, alpha=0.35, linewidth=0, label=label)
    # Outlines keep a zero-height band (A) visible.
    ax.plot(x, ylo, color=color, linewidth=1.4, zorder=3)
    ax.plot(x, yhi, color=color, linewidth=1.4, zorder=3)
    return starts, ends, lo, hi


def mark_clipped(ax, starts, ends, lo, hi, limit, color, text_for, text_y):
    """Point at values beyond the axis limit and print their actual value.

    text_y is the label height as a fraction of the limit, chosen so the label
    sits in empty space above or below the bands.
    """
    for s, e, a, b in zip(starts, ends, lo, hi):
        for value, sign in ((b, 1), (a, -1)):
            if sign * value > limit:
                x = (s + e) / 2
                ax.annotate(text_for(value), xy=(x, sign * limit * 0.98),
                            xytext=(WARMUP_END_S + 0.6, sign * limit * text_y),
                            color=color, fontsize=8.5, ha="left", va="center",
                            bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"),
                            arrowprops=dict(arrowstyle="->", color=color, lw=1.0,
                                            shrinkA=0, shrinkB=0))


def shade_warmup(ax):
    ax.axvspan(0, WARMUP_END_S, color=style.WARMUP_COLOR, zorder=0, linewidth=0)


def main():
    style.apply()
    fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(style.WIDTH_IN, 6.2),
                                      gridspec_kw={"hspace": 0.12})

    for ax in (top, bottom):
        shade_warmup(ax)
        # Dashed so it is not mistaken for A's band, which sits on 0.
        ax.axhline(0, color=style.REF_COLOR, linewidth=0.6, linestyle=(0, (4, 3)), zorder=1)

    for key in ("A", "C"):
        starts, ends, lo, hi = draw_band(top, key)
        mark_clipped(top, starts, ends, lo, hi, TOP_YLIM, style.COLORS[key],
                     lambda v: f"{v:+d} µs (off scale)", text_y=0.75)
    top.set_ylim(-TOP_YLIM, TOP_YLIM)
    top.set_ylabel("Deviation from 16000 µs (µs)")
    top.text(WARMUP_END_S + 0.6, TOP_YLIM * 0.85, "◀ warm-up (first 2 windows)",
             ha="left", va="center", fontsize=8, color=style.REF_COLOR)
    top.legend(loc="upper right")

    starts, ends, lo, hi = draw_band(bottom, "B")
    mark_clipped(bottom, starts, ends, lo, hi, BOTTOM_YLIM, style.COLORS["B"],
                 lambda v: f"{v:+d} µs (frame_dt {(v + FRAME_PERIOD_US) / 1000:.1f} ms, off scale)",
                 text_y=0.9)
    bottom.set_ylim(-BOTTOM_YLIM, BOTTOM_YLIM)
    bottom.set_ylabel("Deviation from 16000 µs (µs)")
    bottom.set_xlabel("Time since boot (s)")
    bottom.legend(loc="upper right")
    bottom.set_xlim(0, ends[-1] + 0.3)

    top.set_title("Experiment 03: per-second frame_dt range (min to max), deviation from 16000 µs")
    fig.text(0.01, -0.01,
             "Note: the two panels use different y-axis scales (top ±60 µs, bottom ±1500 µs). "
             "Each band spans one ~1 s statistics window.\nGray background: warm-up (first 2 windows). Dashed line: 0 µs.",
             fontsize=8, color=style.REF_COLOR, ha="left", va="top")

    style.save(fig, "03_jitter_range_over_time.png")


if __name__ == "__main__":
    main()
