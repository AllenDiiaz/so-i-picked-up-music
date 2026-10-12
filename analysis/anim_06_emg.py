"""README animation: replay of experiment 06, segment A (light and hard grips, hand free).

Three tracks (raw ADC reading, 45-200 Hz with mains removed, its RMS envelope) and a
"Tension" bar coloured by the three levels found in the experiment. The first GIF frame
is the finished picture; the replay then runs at 4x speed and ends on that picture,
which is held before the loop starts again.
"""
import numpy as np
import matplotlib.pyplot as plt

import style
from emg import CORE, RECORDINGS, load_recording, moving_rms, notched
from plot_06_forearm_emg import KIND_COLOR, KIND_SHADE, collect, level_ranges

FPS = 10                # GIF frame times are stored in 10 ms units, so keep 1000/FPS whole
SPEED = 4
HOLD_MS = 1500          # first (= final) frame is held this long
BAR_WINDOW_S = 0.5      # the bar uses a slower RMS than the 100 ms envelope so it does not flicker
LEVEL_COLOR = {"relax": style.COLORS["A"], "medium": style.COLORS["C"], "hard": style.COLORS["B"]}


def thresholds():
    r = level_ranges(collect())
    return (r["relax"][1] + r["medium"][0]) / 2, (r["medium"][1] + r["hard"][0]) / 2


def level_of(value, low, high):
    return "relax" if value < low else ("medium" if value < high else "hard")


def main():
    style.apply()
    rec = RECORDINGS["A"]
    duration = rec["duration"]
    t, mv = load_recording("A")
    core = notched(mv, CORE)
    env = moving_rms(core)
    bar = moving_rms(core, BAR_WINDOW_S)
    low, high = thresholds()

    fig = plt.figure(figsize=(7.2, 6.0), dpi=100)
    left, width, top, height, gap = 0.10, 0.66, 0.84, 0.215, 0.035
    axes = [fig.add_axes([left, top - (i + 1) * height - i * gap, width, height]) for i in range(3)]
    bar_ax = fig.add_axes([0.85, top - 3 * height - 2 * gap, 0.05, 3 * height + 2 * gap])

    tracks = [
        (mv, "Raw (mV)", (np.percentile(mv, 0.05) - 50, np.percentile(mv, 99.95) + 50)),
        (core, f"{CORE[0]}-{CORE[1]} Hz,\nmains removed (mV)", (-np.abs(core).max() * 1.1, np.abs(core).max() * 1.1)),
        (env, "Envelope,\n100 ms RMS (mV)", (0, env.max() * 1.15)),
    ]
    lines, cursors = [], []
    for ax, (y, label, ylim) in zip(axes, tracks):
        counts = {}
        for start, end, kind in rec["phases"]:
            if kind == "relax":
                continue
            counts[kind] = counts.get(kind, 0) + 1
            ax.axvspan(start, end, color=KIND_SHADE[kind], linewidth=0, zorder=0)
            if ax is axes[0]:
                ax.text((start + end) / 2, ylim[1], f"{kind} {counts[kind]}", ha="center", va="bottom",
                        fontsize=8, color=KIND_COLOR[kind], fontweight="bold")
        line, = ax.plot([], [], color="#333333" if ax is not axes[2] else style.COLORS["D"],
                        linewidth=0.35 if ax is not axes[2] else 0.9, zorder=3)
        lines.append((line, y))
        cursors.append(ax.axvline(0, color=style.COLORS["D"], linewidth=0.8, alpha=0.6, zorder=4))
        ax.set_xlim(0, duration)
        ax.set_ylim(*ylim)
        ax.set_ylabel(label, fontsize=8.5)
        ax.tick_params(labelsize=8)
        if ax is not axes[-1]:
            ax.tick_params(labelbottom=False)
    for value in (low, high):
        axes[2].axhline(value, color=style.REF_COLOR, linewidth=0.7, linestyle=(0, (4, 3)), zorder=2)
    axes[-1].set_xlabel("Time since start of recording (s)", fontsize=9)

    # Tension bar: background bands for the three levels, a filled bar for the current value.
    bar_top = max(bar.max() * 1.1, high * 1.5)
    for name, lo, hi in (("relax", 0, low), ("medium", low, high), ("hard", high, bar_top)):
        bar_ax.axhspan(lo, hi, color=LEVEL_COLOR[name], alpha=0.15, linewidth=0)
        bar_ax.text(1.08, (lo + hi) / 2, name, transform=bar_ax.get_yaxis_transform(), rotation=90,
                    ha="left", va="center", fontsize=7.5, color=LEVEL_COLOR[name])
    bar_patch = bar_ax.bar([0], [0], width=0.8, color=LEVEL_COLOR["relax"])[0]
    bar_ax.set_xlim(-0.5, 0.5)
    bar_ax.set_ylim(0, bar_top)
    bar_ax.set_xticks([])
    bar_ax.tick_params(labelsize=7.5)
    bar_ax.grid(False)
    bar_ax.set_title("Tension", fontsize=9, pad=4)
    bar_value = bar_ax.text(0.5, -0.04, "", transform=bar_ax.transAxes, ha="center", va="top", fontsize=8)

    fig.text(left, 0.955, "Forearm EMG through the AD8232 (experiment 06)", fontsize=11.5, fontweight="bold")
    fig.text(left, 0.918, "Segment A: left hand free over the table edge, light and hard grips", fontsize=8.5,
             color=style.REF_COLOR)
    clock = fig.text(0.97, 0.955, "", ha="right", fontsize=10.5, fontweight="bold")
    fig.text(0.97, 0.918, f"Playback {SPEED}x", ha="right", fontsize=8.5, color=style.REF_COLOR)
    fig.text(0.01, 0.012, "Real data · 1 kHz · mains removed · single subject", fontsize=8,
             color=style.REF_COLOR, ha="left", va="bottom")
    fig.text(0.99, 0.012, f"bar: {BAR_WINDOW_S * 1000:.0f} ms RMS, levels split at {low:.1f} / {high:.1f} mV",
             fontsize=7, color=style.REF_COLOR, ha="right", va="bottom")

    def render(t_now):
        shown = t <= t_now
        for line, y in lines:
            line.set_data(t[shown], y[shown])
        for c in cursors:
            c.set_xdata([t_now, t_now])
            c.set_visible(t_now < duration - 0.05)
        value = bar[shown][-1] if shown.any() else 0.0
        level = level_of(value, low, high)
        bar_patch.set_height(value)
        bar_patch.set_color(LEVEL_COLOR[level])
        bar_value.set_text(f"{value:.1f} mV\n{level}")
        bar_value.set_color(LEVEL_COLOR[level])
        clock.set_text(f"t = {t_now:4.1f} s")
        return style.fig_to_image(fig)

    n_replay = int(duration / SPEED * FPS)
    frames, durations = [render(t[-1])], [HOLD_MS]       # first frame: finished picture
    for k in range(1, n_replay + 1):
        frames.append(render(duration * k / n_replay))
        durations.append(1000 // FPS)
    plt.close(fig)
    # 128 colours: with 64, the coral of the rarer hard-grip frames is mapped to brown.
    style.save_gif(frames, durations, "06_emg_replay.gif", colors=128)


if __name__ == "__main__":
    main()
