"""Figures for experiment 04: per-frame interval deviation for A, C and D.

Captions (until docs/experiments/04 exists): sampler task on core 1 in all runs; 3750
frames per run; deviation = frame_dt - 16000 us. Histogram: 1 us bins, empty bins not drawn
on the log axis. CCDF: p99 / p99.9 are nearest-rank percentiles of |deviation| (both
directions); dot = largest |deviation|. Time series: one dot per frame, time = running sum
of frame_dt, recording starts about 2.4 s after boot, Wi-Fi scan times were not logged.
"""
import math

import numpy as np
import matplotlib.pyplot as plt

import style
from data import FRAME_PERIOD_US, load_04

SCENARIOS = {
    "A": ("a_no_wifi_isr_core0.txt", "A: no Wi-Fi, ADC ISR on core 0"),
    "C": ("c_wifi_isr_core0.txt", "C: Wi-Fi, ADC ISR on core 0"),
    "D": ("d_wifi_isr_core1.txt", "D: Wi-Fi, ADC ISR on core 1"),
}
SUBTITLE = "sampler task on core 1 in all runs"


def deviations():
    return {key: load_04(f) - FRAME_PERIOD_US for key, (f, _) in SCENARIOS.items()}


def nearest_rank(sorted_values, pct):
    return sorted_values[max(0, math.ceil(pct / 100 * len(sorted_values)) - 1)]


def plot_histogram(dev):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 3.0))
    lo = min(dev["C"].min(), dev["D"].min())
    hi = max(dev["C"].max(), dev["D"].max())
    edges = np.arange(lo - 0.5, hi + 1.5, 1.0)   # 1 us bins centered on integers
    for key in ("C", "D"):
        ax.hist(dev[key], bins=edges, histtype="step", linewidth=0.9,
                color=style.COLORS[key], label=SCENARIOS[key][1])

    n_a = len(dev["A"])
    assert np.all(dev["A"] == 0)
    ax.axvline(0, color=style.COLORS["A"], linewidth=0.9, linestyle=(0, (4, 3)),
               label=f"A: all {n_a} frames at 0 µs")

    ax.set_yscale("log")
    ax.set_xlabel("Deviation from 16000 µs (µs)")
    ax.set_ylabel("Frames per 1 µs bin (log scale)")
    ax.legend(loc="upper right", title=SUBTITLE, title_fontsize=style.LEGEND_PT, alignment="left")
    style.save(fig, "04_deviation_histogram.png")


def plot_ccdf(dev):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 3.2))
    n = len(dev["C"])
    for key in ("C", "D"):
        a = np.sort(np.abs(dev[key]))
        top = int(a[-1])
        x = np.arange(0, top + 1)
        frac = np.array([(a > t).sum() / n for t in x])
        # Fraction is 0 at x = max, which a log axis cannot show; end the line at max instead.
        frac[-1] = frac[-2]
        p99, p999 = nearest_rank(a, 99), nearest_rank(a, 99.9)
        label = f"{SCENARIOS[key][1]}  (|dev| p99 {p99}, p99.9 {p999}, max {top} µs)"
        ax.step(x, frac, where="post", color=style.COLORS[key], linewidth=1.0, label=label)
        ax.plot([top], [frac[-1]], marker="o", markersize=3, color=style.COLORS[key])

    for y, text in ((1e-2, "1% (p99)"), (1e-3, "0.1% (p99.9)")):
        style.ref_line(ax, y)
        ax.text(0.99, y, text, transform=ax.get_yaxis_transform(), ha="right", va="bottom",
                fontsize=style.NOTE_PT, color=style.REF_COLOR)
    floor = 1 / n
    style.ref_line(ax, floor, linestyle=":")
    ax.text(0.01, floor, f"1 frame of {n} ({floor:.1e})", transform=ax.get_yaxis_transform(),
            ha="left", va="bottom", fontsize=style.NOTE_PT, color=style.REF_COLOR)

    assert np.all(dev["A"] == 0)
    ax.text(0.99, 0.97, f"A: no frame deviates from 16000 µs ({len(dev['A'])} of {len(dev['A'])} at 0 µs),\n"
            "so its fraction is 0 everywhere and cannot be drawn on a log axis.",
            transform=ax.transAxes, ha="right", va="top", fontsize=style.NOTE_PT, color=style.REF_COLOR)

    ax.set_yscale("log")
    ax.set_ylim(floor / 2, 1.5)
    ax.set_xlim(0, None)
    ax.set_xlabel("|Deviation from 16000 µs| (µs)")
    ax.set_ylabel("Fraction of frames with larger |deviation|")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.80), title=SUBTITLE, title_fontsize=style.LEGEND_PT,
              alignment="left")
    style.save(fig, "04_abs_deviation_ccdf.png")


def plot_timeseries(dev):
    fig, axes = plt.subplots(2, 1, sharex=True, sharey=True, figsize=(style.WIDTH_IN, 4.2),
                             gridspec_kw={"hspace": 0.15})
    for ax, key in zip(axes, ("C", "D")):
        f = SCENARIOS[key][0]
        t = np.cumsum(load_04(f)) / 1e6
        style.ref_line(ax, 0)
        ax.scatter(t, dev[key], s=1.2, color=style.COLORS[key], linewidths=0)
        ax.set_ylabel("Deviation from\n16000 µs (µs)")
        ax.text(0.01, 0.95, SCENARIOS[key][1], transform=ax.transAxes, ha="left", va="top",
                color=style.COLORS[key], fontsize=style.LABEL_PT,
                bbox=dict(boxstyle="square,pad=0.2", fc="white", ec="none"))
    lim = max(np.abs(dev["C"]).max(), np.abs(dev["D"]).max()) + 7
    axes[0].set_ylim(-lim, lim)
    axes[0].set_xlim(0, None)
    axes[-1].set_xlabel("Time since start of recording (s)")
    style.panel_label(axes[0], "a")
    style.panel_label(axes[1], "b")
    style.save(fig, "04_deviation_timeseries.png")


def main():
    style.apply()
    dev = deviations()
    plot_histogram(dev)
    plot_ccdf(dev)
    plot_timeseries(dev)


if __name__ == "__main__":
    main()
