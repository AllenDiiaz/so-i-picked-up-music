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

# Pinch / fist phases are shaded in the condition's own colour; rest phases are left white.

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
    # gray = baseline, red = failure (output stuck near 0), teal = working
    ("no_lead", "no_lead.log", "1. No lead cable", style.GRAY, NO_CABLE_PHASES),
    ("lead", "lead_no_electrodes.log", "2. Lead cable, no electrodes (fingers on snaps)", style.RED, PINCH_PHASES),
    ("electrodes", "electrodes.log", "3. Three electrodes on the skin", style.TEAL, FIST_PHASES),
]

# Notes on sampling (about 5 Hz, not a waveform) and electrode placement are in the figure
# captions in docs/experiments/05_ad8232_bringup.md.


def phase_stats(t, mv, start, end):
    inside = (t >= start) & (t < end)
    v = mv[inside]
    # Mean absolute change between consecutive readings that are both inside the phase.
    pairs = inside[1:] & inside[:-1]
    step = np.abs(np.diff(mv))[pairs]
    return dict(n=v.size, mean=v.mean(), min=v.min(), max=v.max(), sd=v.std(), step=step.mean())


def draw_limits(ax, label=True):
    for y, text in ((0, "0 mV"), (SATURATION_MV, f"{SATURATION_MV} mV (saturation)")):
        style.ref_line(ax, y, zorder=2)
        if label:
            ax.text(1.0, y, " " + text, transform=ax.get_yaxis_transform(), ha="left", va="center",
                    fontsize=style.NOTE_PT, color=style.REF_COLOR)


def plot_timeseries(data):
    fig, axes = plt.subplots(3, 1, sharex=True, sharey=True, figsize=(style.WIDTH_IN, 5.6),
                             gridspec_kw={"hspace": 0.35})
    for ax, letter, (key, _, title, color, phases) in zip(axes, "abc", CONDITIONS):
        t, mv = data[key]
        for start, end, label, _, action in phases:
            if action:
                style.shade(ax, start, end, color)
            ax.text((start + end) / 2, YLIM[1] - 60, label, ha="center", va="top", fontsize=style.NOTE_PT,
                    color=color if action else style.REF_COLOR)
        draw_limits(ax)
        ax.plot(t, mv, color=color, linewidth=0.6, zorder=2)
        ax.plot(t, mv, "o", color=color, markersize=1.8, zorder=3)
        ax.set_title(title, loc="left", color=color)
        ax.set_ylabel("ADC reading (mV)")
        style.panel_label(ax, letter, y=1.04)
    axes[0].set_ylim(*YLIM)
    axes[0].set_xlim(0, DURATION_S)
    axes[-1].set_xlabel("Time since start of recording (s)")
    style.save(fig, "05_bringup_timeseries.png")


def plot_summary(stats):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 3.4))
    draw_limits(ax)
    x = 0
    ticks, ticklabels = [], []
    for key, _, title, color, phases in CONDITIONS:
        group_start = x
        for start, end, _, short, action in phases:
            s = stats[key][(start, end)]
            ax.errorbar(x, s["mean"], yerr=s["sd"], fmt="s" if action else "o", markersize=4.5,
                        color=color, ecolor=color, elinewidth=0.9, capsize=2.5,
                        markerfacecolor=color if action else "white", markeredgewidth=0.9, zorder=3)
            ax.text(x + 0.12, s["mean"], f"sd {s['sd']:.0f}", fontsize=style.NOTE_PT, va="center",
                    color=style.REF_COLOR)
            ticks.append(x)
            ticklabels.append(f"{start}–{end} s\n{short}")
            x += 1
        ax.text((group_start + x - 1) / 2, YLIM[1] - 60, title.split(" (")[0].replace(", ", ",\n"),
                ha="center", va="top", fontsize=style.LABEL_PT, color=color)
        x += 0.8
    ax.set_xticks(ticks)
    ax.set_xticklabels(ticklabels, fontsize=style.NOTE_PT)
    ax.set_ylim(*YLIM)
    ax.set_xlim(-0.6, x - 0.5)
    ax.set_ylabel("ADC reading, mean ± SD (mV)")
    legend = [Line2D([], [], marker="o", linestyle="", color=style.REF_COLOR, markerfacecolor="white",
                     label="rest phase"),
              Line2D([], [], marker="s", linestyle="", color=style.REF_COLOR, label="pinch / fist phase")]
    ax.legend(handles=legend, loc="center left", bbox_to_anchor=(0.0, 0.62))
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
