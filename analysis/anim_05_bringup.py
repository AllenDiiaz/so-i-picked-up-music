"""README animation: replay of the experiment 05 ADC readings for the three conditions.

Uses the same conditions, colors, phases and y range as 05_bringup_timeseries.png.
The first GIF frame is the finished picture, so viewers that only show the first frame
still see the result. The replay then runs at 3x speed and ends on that same picture,
which is held before the loop starts again.
"""
import numpy as np
import matplotlib.pyplot as plt

import style
from data import load_05
from plot_05_bringup import CONDITIONS, DURATION_S, SATURATION_MV, YLIM

FPS = 10                # GIF frame times are stored in 10 ms units, so keep 1000/FPS whole
SPEED = 3               # 30 s of data in 10 s
HOLD_MS = 1500          # first (= final) frame is held this long
ACTION_WORD = {"no_lead": "pinch (no cable)", "lead": "pinch", "electrodes": "squeeze"}


def draw(axes, data, t_now):
    for ax, (key, _, title, color, phases) in zip(axes, CONDITIONS):
        ax.clear()
        ax.set_xlim(0, DURATION_S)
        ax.set_ylim(*YLIM)
        ax.set_yticks([0, 1000, 2000, 3000])
        ax.set_ylabel("mV")
        ax.set_title(title, loc="left", color=color, pad=3)

        # Phase backgrounds and labels appear as playback reaches them.
        for start, end, label, _, action in phases:
            if t_now <= start:
                continue
            if action:
                style.shade(ax, start, min(end, t_now), color)
            ax.text(start + 0.3, YLIM[1] - 70, label, ha="left", va="top", fontsize=style.NOTE_PT,
                    color=color if action else style.REF_COLOR)
            if action and start <= t_now < end:
                ax.text(0.99, 0.70, ACTION_WORD[key], transform=ax.transAxes, ha="right", va="center",
                        fontsize=style.LABEL_PT, fontweight="bold", color=color,
                        bbox=dict(boxstyle="square,pad=0.3", fc="white", ec=color, lw=0.6))

        # Labels sit outside the plot (as in the static figure) so data and phase labels stay clear.
        for y, text in ((0, "0 mV"), (SATURATION_MV, f"{SATURATION_MV} mV\nsaturation")):
            style.ref_line(ax, y, zorder=2)
            ax.text(1.01, y, text, transform=ax.get_yaxis_transform(), ha="left", va="center",
                    fontsize=style.NOTE_PT, color=style.REF_COLOR)

        t, mv = data[key]
        shown = t <= t_now
        if shown.any():
            ax.plot(t[shown], mv[shown], color=color, linewidth=0.6, zorder=3)
            ax.plot(t[shown], mv[shown], "o", color=color, markersize=1.8, zorder=4)
            ax.plot(t[shown][-1], mv[shown][-1], "o", color=color, markersize=5,
                    markeredgecolor="white", markeredgewidth=0.8, zorder=5)
        if ax is not axes[-1]:
            ax.tick_params(labelbottom=False)
    axes[-1].set_xlabel("Time since start of recording (s)")


def main():
    style.apply()
    data = {key: load_05(filename) for key, filename, *_ in CONDITIONS}

    fig, axes = plt.subplots(3, 1, figsize=(style.WIDTH_IN, style.WIDTH_IN * 0.8), dpi=style.GIF_DPI,
                             gridspec_kw={"hspace": 0.45})
    fig.subplots_adjust(left=0.09, right=0.86, top=0.86, bottom=0.12)
    fig.text(0.09, 0.955, "AD8232 OUTPUT on GPIO4 (experiment 05)", fontsize=style.LABEL_PT + 1,
             fontweight="bold")
    fig.text(0.09, 0.915, "Three conditions, recorded separately", fontsize=style.TICK_PT, color=style.REF_COLOR)
    clock = fig.text(0.97, 0.955, "", ha="right", fontsize=style.LABEL_PT, fontweight="bold")
    fig.text(0.97, 0.915, f"Playback {SPEED}x", ha="right", fontsize=style.TICK_PT, color=style.REF_COLOR)
    fig.text(0.01, 0.015, "Real data · one-shot ADC ≈ 5 Hz · not a waveform", fontsize=style.NOTE_PT,
             color=style.REF_COLOR, ha="left", va="bottom")

    def render(t_now):
        draw(axes, data, t_now)
        clock.set_text(f"t = {t_now:4.1f} s")
        return style.fig_to_image(fig)

    n_replay = int(DURATION_S / SPEED * FPS)
    frames, durations = [render(DURATION_S)], [HOLD_MS]   # first frame: finished picture
    for k in range(1, n_replay + 1):
        frames.append(render(DURATION_S * k / n_replay))
        durations.append(1000 // FPS)
    plt.close(fig)
    style.save_gif(frames, durations, "05_bringup_replay.gif")


if __name__ == "__main__":
    main()
