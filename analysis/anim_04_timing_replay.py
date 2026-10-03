"""README animation: replay of measured per-frame timing for A, B and C (experiment 04).

The first GIF frame is the finished picture (all data, final counters), so viewers that
only show the first frame still see the result. The replay then runs at 8x speed and ends
on that same picture, which makes the loop seamless.
"""
import numpy as np
import matplotlib.pyplot as plt

import style
from data import FRAME_PERIOD_US, load_04

LATE_DEV_US = 100   # late = frame_dt > 16100 us, as in the experiment notes
AC_LIM = 120        # shared scale for A and C
B_LIM = 1200        # B's own scale: 10x, fits B's largest |deviation| (1030 us)

ROWS = [
    # key, file, label, y limit
    ("A", "a_no_wifi_isr_core0.txt", "A: no Wi-Fi", AC_LIM),
    ("B", "b_wifi_sampler_core0.txt", "B: Wi-Fi, sampler on core 0", B_LIM),
    ("C", "c_wifi_isr_core0.txt", "C: Wi-Fi, sampler on core 1", AC_LIM),
]

FPS = 10              # GIF frame times are stored in 10 ms units, so keep 1000/FPS whole
REPLAY_S = 7.5          # 60 s of data in 7.5 s -> 8x
HOLD_MS = 1500          # first (= final) frame is held this long
B_BACKGROUND = "#fdf1ed"


def load_rows():
    rows = []
    for key, filename, label, lim in ROWS:
        dt = load_04(filename)
        dev = dt - FRAME_PERIOD_US
        assert np.abs(dev).max() < lim, f"{key} has points beyond its scale"
        rows.append(dict(key=key, label=label, lim=lim, t=np.cumsum(dt) / 1e6, dev=dev))
    return rows


def build_figure(rows, duration_s):
    fig = plt.figure(figsize=(8.0, 5.6), dpi=100)
    left, width, top, height, gap = 0.10, 0.60, 0.86, 0.215, 0.03
    artists = []
    for i, r in enumerate(rows):
        ax = fig.add_axes([left, top - (i + 1) * height - i * gap, width, height])
        ax.set_xlim(0, duration_s)
        ax.set_ylim(-r["lim"], r["lim"])
        color = style.COLORS[r["key"]]
        if r["key"] == "B":
            ax.set_facecolor(B_BACKGROUND)
            ax.axhspan(-AC_LIM, AC_LIM, color="#d9d9d9", alpha=0.8, linewidth=0, zorder=0)
            ax.set_yticks([-1000, 0, 1000])
        else:
            ax.set_yticks([-100, 0, 100])
        ax.axhline(LATE_DEV_US, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)))
        ax.axhline(0, color="#bbbbbb", linewidth=0.5)
        ax.text(0.01, 0.93, r["label"], transform=ax.transAxes, ha="left", va="top", fontsize=9,
                color=color, fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85))
        if i < len(rows) - 1:
            ax.tick_params(labelbottom=False)
        scatter = ax.scatter([], [], s=4, color=color, linewidths=0)

        # Counter column to the right of each row.
        x_text = left + width + 0.03
        y_mid = top - (i + 1) * height - i * gap + height / 2
        if r["key"] == "B":
            fig.text(x_text, y_mid + 0.075, f"different scale: ±{r['lim']} µs (10x)", fontsize=8,
                     color=style.COLORS["B"], fontweight="bold")
            fig.text(x_text, y_mid + 0.045, f"gray band = A/C scale (±{AC_LIM} µs)", fontsize=7.5,
                     color=style.REF_COLOR)
        else:
            fig.text(x_text, y_mid + 0.065, f"scale ±{r['lim']} µs", fontsize=8, color=style.REF_COLOR)
        late_txt = fig.text(x_text, y_mid + 0.01, "", fontsize=10, color=color)
        max_txt = fig.text(x_text, y_mid - 0.045, "", fontsize=10, color=color)
        artists.append((r, scatter, late_txt, max_txt))

    axes = fig.axes
    axes[-1].set_xlabel("Time since start of recording (s)")
    fig.text(0.025, top - 1.5 * height - gap, "Deviation from 16000 µs (µs)", rotation=90,
             ha="center", va="center", fontsize=10)
    fig.text(left, 0.955, "Frame timing at 1 kHz on ESP32-S3", fontsize=13, fontweight="bold")
    fig.text(left, 0.915, "Measured data, experiment 04. Each dot is one 16 ms frame.",
             fontsize=9, color=style.REF_COLOR)
    clock = fig.text(0.98, 0.955, "", fontsize=10, ha="right", fontweight="bold")
    fig.text(0.02, 0.03,
             "Dashed line: late threshold (+100 µs). A and C share one scale; B uses its own (10x).\n"
             "B was recorded in a separate run. The ADC interrupt is on core 0 in all three.",
             fontsize=7.5, color=style.REF_COLOR, va="bottom")
    return fig, artists, clock


def update(artists, clock, t_now, duration_s):
    for r, scatter, late_txt, max_txt in artists:
        shown = r["t"] <= t_now
        dev = r["dev"][shown]
        scatter.set_offsets(np.column_stack([r["t"][shown], dev]) if dev.size else np.empty((0, 2)))
        late = int((dev > LATE_DEV_US).sum())
        biggest = int(np.abs(dev).max()) if dev.size else 0
        late_txt.set_text(f"late frames: {late}")
        max_txt.set_text(f"max |dev|: {biggest} µs")
    clock.set_text(f"Playback 8x   t = {min(t_now, duration_s):4.1f} / {duration_s:.0f} s")


def main():
    style.apply()
    plt.rcParams["axes.grid"] = False
    rows = load_rows()
    duration_s = max(r["t"][-1] for r in rows)
    fig, artists, clock = build_figure(rows, duration_s)

    n_replay = int(REPLAY_S * FPS)
    frames, durations = [], []
    update(artists, clock, duration_s, duration_s)          # first frame: finished picture
    frames.append(style.fig_to_image(fig))
    durations.append(HOLD_MS)
    for k in range(1, n_replay + 1):
        update(artists, clock, duration_s * k / n_replay, duration_s)
        frames.append(style.fig_to_image(fig))
        durations.append(round(1000 / FPS))
    plt.close(fig)
    style.save_gif(frames, durations, "04_timing_replay.gif")


if __name__ == "__main__":
    main()
