"""Experiment 06 (draft) retest: left-hand hard grips vs relax, compared with the first recording.

    python analysis/analyze_06_retest.py [RETEST_LOG FIRST_LOG] [--figs DIR]

Logs default to docs/data/06_forearm_emg/; figures and summary.md only with --figs.
Same method as analyze_06_emg.py: newest board run, time from the
sample index, zero-phase FFT band-pass 20-450 Hz, 100 ms moving RMS, Welch PSD, and the
first 0.5 s after each cue skipped in the statistics.
"""
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

import style
from analyze_06_emg import DURATION_S, PHASES as FIRST_PHASES, SPLIT_HZ, save
from emg import (BAND, MAINS_HZ, RECORDINGS, RMS_WINDOW_S, SAT_HIGH_MV, SAT_LOW_MV, SATURATION_MV, band_power,
                 bandpass, load, moving_rms, rms, welch, window as skip_window)

REACTION_S = 0.5    # the method used when this run was first analysed


def window(t, start, end):
    return skip_window(t, start, end, REACTION_S)

# (start s, end s, label); the first relax cue was spoken at 0.5 s
RETEST_PHASES = [(0.5, 10, "relax"), (10, 15, "hard 1"), (15, 25, "relax"), (25, 30, "hard 2"),
                 (30, 40, "relax"), (40, 45, "hard 3"), (45, 60, "relax")]
HARD_COLOR = style.COLORS["B"]
RELAX_COLOR = style.COLORS["A"]
HARD_SHADE = "#fde0d6"
BANDS = [(20, 40), (40, 100), (100, 200), (200, 450)]
RETEST_FOOTNOTE = ("Real data, retest: left-hand grips, wrist and palm free over the table edge.\n"
                   "1 kHz ADC on GPIO4 (AD8232 OUTPUT); left forearm flexors, red/yellow 2-3 cm apart "
                   "along the muscle, green on the elbow.")


def mask(t, phases, keep):
    m = np.zeros_like(t, dtype=bool)
    for start, end, label in phases:
        if keep(label):
            m |= window(t, start, end)
    return m


def shade_hard(ax, label_y=None):
    for start, end, label in RETEST_PHASES:
        if label.startswith("hard"):
            ax.axvspan(start, end, color=HARD_SHADE, linewidth=0, zorder=0)
        if label_y is not None:
            ax.text((start + end) / 2, label_y, label, ha="center", va="top", fontsize=7.5,
                    color=HARD_COLOR if label.startswith("hard") else RELAX_COLOR,
                    fontweight="bold" if label.startswith("hard") else "normal")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("retest_log", nargs="?", default=RECORDINGS["retest"]["file"])
    parser.add_argument("first_log", nargs="?", default=RECORDINGS["first"]["file"])
    parser.add_argument("--figs", type=Path, help="write figures and summary.md into this directory")
    args = parser.parse_args()
    retest_log, first_log, out_dir = args.retest_log, args.first_log, args.figs
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    style.apply()

    t, mv = load(retest_log)
    bp = bandpass(mv, *BAND)
    env = moving_rms(bp, RMS_WINDOW_S)
    saturated = (mv <= SAT_LOW_MV) | (mv >= SAT_HIGH_MV)

    # --- 1. raw signal ---
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 3.6))
    shade_hard(ax, label_y=3420)
    for y, text in ((0, "0 mV"), (SATURATION_MV, f"{SATURATION_MV} mV (saturation)")):
        ax.axhline(y, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
        ax.text(1.0, y, " " + text, transform=ax.get_yaxis_transform(), ha="left", va="center",
                fontsize=7.5, color=style.REF_COLOR)
    ax.plot(t, mv, color="#333333", linewidth=0.3, zorder=3)
    ax.set_xlim(0, DURATION_S)
    ax.set_ylim(-100, 3500)
    ax.set_xlabel("Time since start of recording (s)")
    ax.set_ylabel("ADC reading (mV)")
    ax.set_title("Experiment 06 retest (draft): raw AD8232 output, left-hand grips", loc="left")
    fig.text(0.01, -0.02, RETEST_FOOTNOTE + f"\nSaturated (<= {SAT_LOW_MV} or >= {SAT_HIGH_MV} mV): "
             f"{saturated.sum()} of {saturated.size} samples.", fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_retest_raw.png")

    # --- 2. band-passed signal and envelope, hard phases marked ---
    fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(style.WIDTH_IN, 5.4),
                                 gridspec_kw={"hspace": 0.12})
    lim = np.percentile(np.abs(bp), 99.9) * 1.15
    shade_hard(a1, label_y=lim * 0.97)
    a1.plot(t, bp, color="#333333", linewidth=0.3, zorder=3)
    a1.set_ylim(-lim, lim)
    a1.set_ylabel(f"Band-passed {BAND[0]}-{BAND[1]} Hz (mV)")
    shade_hard(a2)
    a2.plot(t, env, color=style.COLORS["D"], linewidth=1.0, zorder=3)
    relax_level = rms(bp[mask(t, RETEST_PHASES, lambda l: l == "relax")])
    a2.axhline(relax_level, color=RELAX_COLOR, linewidth=0.9, linestyle=(0, (4, 3)), zorder=4)
    a2.text(0.01, 0.95, f"dashed: RMS over all relax phases = {relax_level:.1f} mV", transform=a2.transAxes,
            ha="left", va="top", fontsize=7.5, color=RELAX_COLOR)
    a2.set_ylim(0, None)
    a2.set_ylabel(f"Moving RMS, {RMS_WINDOW_S * 1000:.0f} ms (mV)")
    a2.set_xlabel("Time since start of recording (s)")
    a2.set_xlim(0, DURATION_S)
    a1.set_title("Experiment 06 retest (draft): band-passed signal and RMS envelope", loc="left")
    fig.text(0.01, -0.01, RETEST_FOOTNOTE + "\nShaded: the three hard-grip phases.", fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_retest_bandpass_envelope.png")

    # --- 3. PSD: retest relax / hard, first recording relax / hard ---
    t1, mv1 = load(first_log)
    first_relax = [mv1[window(t1, s, e)] for s, e, _, k in FIRST_PHASES if k == "relax"]
    first_hard = [mv1[window(t1, s, e)] for s, e, _, k in FIRST_PHASES if k == "hard"]
    spectra = {
        "retest relax": (welch([mv[window(t, s, e)] for s, e, l in RETEST_PHASES if l == "relax"]), RELAX_COLOR, "-"),
        "retest hard": (welch([mv[window(t, s, e)] for s, e, l in RETEST_PHASES if l.startswith("hard")]), HARD_COLOR, "-"),
        "first relax": (welch(first_relax), RELAX_COLOR, (0, (3, 2))),
        "first hard": (welch(first_hard), HARD_COLOR, (0, (3, 2))),
    }
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.4))
    for name, ((f, p, count), color, ls) in spectra.items():
        ax.semilogy(f, p, color=color, linestyle=ls, linewidth=1.2, label=f"{name} ({count} segments)")
    ax.axvline(SPLIT_HZ, color=style.REF_COLOR, linewidth=1.0, linestyle=(0, (4, 3)))
    ax.text(SPLIT_HZ + 3, 0.98, f"{SPLIT_HZ} Hz (typical AD8232\nmodule low-pass, not measured)",
            transform=ax.get_xaxis_transform(), va="top", fontsize=7.5, color=style.REF_COLOR)
    for h in range(MAINS_HZ, 500, MAINS_HZ):
        ax.axvline(h, color="#bbbbbb", linewidth=0.6, linestyle=":", zorder=0)
    ax.set_xlim(0, 500)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (mV²/Hz, log scale)")
    ax.set_title("Experiment 06 (draft): spectrum, retest vs first recording (Welch)", loc="left")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.86))
    fig.text(0.01, -0.02, "Solid: retest (left-hand grips, hand free). Dashed: first recording "
             "(grip hand not confirmed). Dotted: 60 Hz mains harmonics.\nWelch: Hann, 512 samples, 50% "
             "overlap; first 0.5 s after each cue skipped.", fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_retest_psd.png")

    # --- report ---
    lines = ["Per-phase statistics (retest)", "",
             "| Phase | n | Raw mean (mV) | Raw SD (mV) | Saturated | Band-passed RMS (mV) |", "|---|---|---|---|---|---|"]
    phase_rms = []
    for start, end, label in RETEST_PHASES:
        w = window(t, start, end)
        r = rms(bp[w])
        phase_rms.append(r)
        lines.append(f"| {start:g}-{end:g} s {label} | {w.sum()} | {mv[w].mean():.1f} | {mv[w].std():.1f} | "
                     f"{saturated[w].sum()} | {r:.1f} |")

    lines += ["", "Each hard grip vs the relax phases before and after it", "",
              "| Grip | RMS (mV) | relax before (mV) | relax after (mV) | / before | / after | / mean of both |",
              "|---|---|---|---|---|---|---|"]
    for i, (_, _, label) in enumerate(RETEST_PHASES):
        if label.startswith("hard"):
            h, before, after = phase_rms[i], phase_rms[i - 1], phase_rms[i + 1]
            lines.append(f"| {label} | {h:.1f} | {before:.1f} | {after:.1f} | {h / before:.2f} | "
                         f"{h / after:.2f} | {h / ((before + after) / 2):.2f} |")

    first_bp = bandpass(mv1, *BAND)
    first_relax_rms = rms(first_bp[np.concatenate([window(t1, s, e)[None] for s, e, _, k in FIRST_PHASES
                                                    if k == "relax"]).any(axis=0)])
    first_hard_rms = rms(first_bp[np.concatenate([window(t1, s, e)[None] for s, e, _, k in FIRST_PHASES
                                                   if k == "hard"]).any(axis=0)])
    retest_hard_rms = rms(bp[mask(t, RETEST_PHASES, lambda l: l.startswith("hard"))])
    lines += ["", "Hard / relax, both recordings (all relax phases as the baseline)", "",
              "| Recording | Hard RMS (mV) | Relax RMS (mV) | Hard / relax |", "|---|---|---|---|",
              f"| First attempt (01_first_attempt.log, 25-30 s, grip hand not confirmed) | {first_hard_rms:.1f} | "
              f"{first_relax_rms:.1f} | {first_hard_rms / first_relax_rms:.2f} |",
              f"| Retest (three grips, left hand) | {retest_hard_rms:.1f} | {relax_level:.1f} | "
              f"{retest_hard_rms / relax_level:.2f} |"]

    f, p_relax, _ = spectra["retest relax"][0]
    lines += ["", "Band power of each hard grip relative to all retest relax phases", "",
              "| Grip | " + " | ".join(f"{lo}-{hi} Hz" for lo, hi in BANDS) + " |", "|---|---|---|---|---|"]
    for start, end, label in RETEST_PHASES:
        if label.startswith("hard"):
            _, p, _ = welch([mv[window(t, start, end)]])
            lines.append(f"| {label} | " + " | ".join(
                f"{band_power(f, p, lo, hi) / band_power(f, p_relax, lo, hi):.2f}x" for lo, hi in BANDS) + " |")
    _, p_fr, _ = spectra["first relax"][0]
    _, p_fh, _ = spectra["first hard"][0]
    lines.append("| first recording hard (vs its relax) | " + " | ".join(
        f"{band_power(f, p_fh, lo, hi) / band_power(f, p_fr, lo, hi):.2f}x" for lo, hi in BANDS) + " |")

    lines += ["", f"Share of {BAND[0]}-{BAND[1]} Hz power above {SPLIT_HZ} Hz", "",
              "| Spectrum | >40 Hz share | mains ±3 Hz excluded | >40 Hz share of power above relax |",
              "|---|---|---|---|"]
    for name, ((f, p, _), _, _) in spectra.items():
        base = p_relax if name.startswith("retest") else p_fr
        excess = np.clip(p - base, 0, None)
        ex_total = band_power(f, excess, *BAND)
        ex = f"{100 * band_power(f, excess, SPLIT_HZ, BAND[1]) / ex_total:.1f}%" if "hard" in name and ex_total > 0 else "-"
        lines.append(f"| {name} | {100 * band_power(f, p, SPLIT_HZ, BAND[1]) / band_power(f, p, *BAND):.1f}% | "
                     f"{100 * band_power(f, p, SPLIT_HZ, BAND[1], True) / band_power(f, p, *BAND, True):.1f}% | {ex} |")

    report = "\n".join(lines)
    if out_dir:
        (out_dir / "summary.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
