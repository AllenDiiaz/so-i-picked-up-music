"""Figures for experiment 05: AD8232 bring-up, ADC readings on GPIO4 under three conditions.

Also prints the per-phase statistics table used in docs/experiments/05_ad8232_bringup.md.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import style
from data import load_05

SATURATION_MV = 3108   # largest calibrated reading (ADC_ATTEN_DB_12)
YLIM = (-100, 3500)   # headroom above saturation for the phase labels
DURATION_S = 30

REST_SHADE = "#f2f2f2"
ACTION_SHADE = "#fde3a7"

# phase: (start s, end s, label, short label, is the action phase)
PINCH_PHASES = [(0, 10, "hands off", "hands off", False),
                (10, 20, "pinch red + yellow snaps", "pinch", True),
                (20, 30, "release", "release", False)]
NO_CABLE_PHASES = [(0, 10, "hands off", "hands off", False),
                   (10, 20, "pinch phase (no cable plugged in)", "(pinch)", True),
                   (20, 30, "release", "release", False)]
FIST_PHASES = [(0, 15, "relaxed", "relaxed", False),
               (15, 25, "right fist squeeze", "fist", True),
               (25, 30, "relaxed", "relaxed", False)]

CONDITIONS = [
    # key, file, title, color, phases
    ("no_lead", "no_lead.log", "1. No lead cable", style.COLORS["A"], NO_CABLE_PHASES),
    ("lead", "lead_no_electrodes.log", "2. Lead cable, no electrodes (fingers on snaps)",
     style.COLORS["B"], PINCH_PHASES),
    ("electrodes", "electrodes.log", "3. Three electrodes on the skin", style.COLORS["D"], FIST_PHASES),
]

FOOTNOTE = ("Sampling ≈ 5 Hz (one-shot ADC read every 200 ms): individual readings, not a waveform.\n"
            "Electrodes: red right wrist, yellow left wrist, green right forearm near the elbow "
            "(wrist-to-wrist, ECG-style), not a forearm EMG placement.")


def phase_stats(t, mv, start, end):
    inside = (t >= start) & (t < end)
    v = mv[inside]
    # Mean absolute change between consecutive readings that are both inside the phase.
    pairs = inside[1:] & inside[:-1]
    step = np.abs(np.diff(mv))[pairs]
    return dict(n=v.size, mean=v.mean(), min=v.min(), max=v.max(), sd=v.std(), step=step.mean())


def draw_limits(ax, label=True):
    for y, text in ((0, "0 mV"), (SATURATION_MV, f"{SATURATION_MV} mV (saturation)")):
        ax.axhline(y, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
        if label:
            ax.text(1.0, y, " " + text, transform=ax.get_yaxis_transform(), ha="left", va="center",
                    fontsize=7.5, color=style.REF_COLOR)


def plot_timeseries(data):
    fig, axes = plt.subplots(3, 1, sharex=True, sharey=True, figsize=(style.WIDTH_IN, 7.4),
                             gridspec_kw={"hspace": 0.32})
    for ax, (key, _, title, color, phases) in zip(axes, CONDITIONS):
        t, mv = data[key]
        for start, end, label, _, action in phases:
            ax.axvspan(start, end, color=ACTION_SHADE if action else REST_SHADE, linewidth=0, zorder=0)
            ax.text((start + end) / 2, YLIM[1] - 60, label, ha="center", va="top", fontsize=7.5,
                    color="#7a5a00" if action else style.REF_COLOR)
        draw_limits(ax)
        ax.plot(t, mv, color=color, linewidth=0.6, zorder=2)
        ax.plot(t, mv, "o", color=color, markersize=2.5, zorder=3)
        ax.set_title(title, loc="left", fontsize=10, color=color, fontweight="bold")
        ax.set_ylabel("ADC reading (mV)")
    axes[0].set_ylim(*YLIM)
    axes[0].set_xlim(0, DURATION_S)
    axes[-1].set_xlabel("Time since start of recording (s)")
    fig.suptitle("Experiment 05: AD8232 OUTPUT on GPIO4, three conditions", x=0.125, ha="left",
                 fontsize=11.5, y=0.955)
    fig.text(0.01, 0.0, FOOTNOTE + "\nShaded: phases of the spoken-cue schedule (yellow = pinch / fist).",
             fontsize=7.5, color=style.REF_COLOR, ha="left", va="top")
    style.save(fig, "05_bringup_timeseries.png")


def plot_summary(stats):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.8))
    draw_limits(ax)
    x = 0
    ticks, ticklabels = [], []
    for key, _, title, color, phases in CONDITIONS:
        group_start = x
        for start, end, _, short, action in phases:
            s = stats[key][(start, end)]
            ax.errorbar(x, s["mean"], yerr=s["sd"], fmt="s" if action else "o", markersize=6,
                        color=color, ecolor=color, elinewidth=1.4, capsize=4,
                        markerfacecolor=color if action else "white", markeredgewidth=1.4, zorder=3)
            ax.text(x + 0.12, s["mean"], f"sd {s['sd']:.0f}", fontsize=7, va="center",
                    color=style.REF_COLOR)
            ticks.append(x)
            ticklabels.append(f"{start}–{end} s\n{short}")
            x += 1
        ax.text((group_start + x - 1) / 2, YLIM[1] - 60, title.split(" (")[0].replace(", ", ",\n"),
                ha="center", va="top", fontsize=8.5, color=color, fontweight="bold")
        x += 0.8
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticklabels, fontsize=7)
    ax.set_ylim(*YLIM)
    ax.set_xlim(-0.6, x - 0.5)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("ADC reading, mean ± SD (mV)")
    ax.set_title("Experiment 05: mean ± standard deviation per condition and phase", loc="left")
    legend = [Line2D([], [], marker="o", linestyle="", color="#555555", markerfacecolor="white",
                     label="rest phase"),
              Line2D([], [], marker="s", linestyle="", color="#555555", label="pinch / fist phase")]
    ax.legend(handles=legend, loc="center left", bbox_to_anchor=(0.0, 0.62))
    fig.text(0.01, -0.02, FOOTNOTE, fontsize=7.5, color=style.REF_COLOR, ha="left", va="top")
    style.save(fig, "05_bringup_summary.png")


def print_table(stats):
    print("| Condition | Phase | n | Mean (mV) | Min | Max | SD | Mean step (mV) |")
    print("|---|---|---|---|---|---|---|---|")
    for key, _, title, _, phases in CONDITIONS:
        for start, end, label, _, _ in phases:
            s = stats[key][(start, end)]
            print(f"| {title} | {start}-{end} s {label} | {s['n']} | {s['mean']:.1f} | {s['min']} | "
                  f"{s['max']} | {s['sd']:.1f} | {s['step']:.1f} |")


def main():
    style.apply()
    data = {key: load_05(filename) for key, filename, *_ in CONDITIONS}
    stats = {key: {(a, b): phase_stats(*data[key], a, b) for a, b, *_ in phases}
             for key, _, _, _, phases in CONDITIONS}
    plot_timeseries(data)
    plot_summary(stats)
    print_table(stats)


if __name__ == "__main__":
    main()
