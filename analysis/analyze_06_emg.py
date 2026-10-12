"""Experiment 06, first attempt: raw-stream analysis as first done (0.5 s reaction skip).

    python analysis/analyze_06_emg.py [LOG] [--figs DIR]

LOG defaults to docs/data/06_forearm_emg/01_first_attempt.log. Tables are printed; figures
and summary.md are written only with --figs. Shared loading and filters live in emg.py.
"""
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

import style
from emg import (BAND, MAINS_HZ, RECORDINGS, RMS_WINDOW_S, SAT_HIGH_MV, SAT_LOW_MV, SATURATION_MV, WELCH_N,
                 band_power, bandpass, load, moving_rms, welch)

SPLIT_HZ = 40                         # common AD8232 reference-design low-pass (not measured here)
DURATION_S = 60
REACTION_S = 0.5                      # skip this long after each cue (the method used for this run)

# (start s, end s, label, kind); the first relax cue was spoken at 0.5 s
PHASES = [(0.5, 10, "relax", "relax"), (10, 15, "light", "light"), (15, 25, "relax", "relax"),
          (25, 30, "hard", "hard"), (30, 40, "relax", "relax"), (40, 50, "chord", "chord"),
          (50, 60, "relax", "relax")]
KIND_COLORS = {"relax": style.COLORS["A"], "light": style.COLORS["C"],
               "hard": style.COLORS["B"], "chord": style.COLORS["D"]}
ACTION_SHADE = {"light": "#d5efeb", "hard": "#fde0d6", "chord": "#dbe6f6"}
FOOTNOTE = ("Real data, one run. 1 kHz ADC on GPIO4 (AD8232 OUTPUT); left forearm flexors, "
            "red/yellow 2-3 cm apart along the muscle, green on the elbow.")


def save(fig, out_dir, name):
    """Write the figure into out_dir, or just discard it when no --figs directory was given."""
    if out_dir is None:
        plt.close(fig)
        return
    path = out_dir / name
    fig.savefig(path, dpi=style.DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def shade(ax, show_labels=True, y=None):
    for start, end, label, kind in PHASES:
        if kind != "relax":
            ax.axvspan(start, end, color=ACTION_SHADE[kind], linewidth=0, zorder=0)
        if show_labels:
            ax.text((start + end) / 2, y, label, ha="center", va="top", fontsize=7.5,
                    color=KIND_COLORS[kind], fontweight="bold" if kind != "relax" else "normal")


def window(t, start, end):
    return (t >= start + REACTION_S) & (t < end)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", nargs="?", default=RECORDINGS["first"]["file"],
                        help="log in docs/data/06_forearm_emg/ or a path")
    parser.add_argument("--figs", type=Path, help="write figures and summary.md into this directory")
    args = parser.parse_args()
    log, out_dir = args.log, args.figs
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    style.apply()

    t, mv = load(log)
    bp = bandpass(mv, *BAND)
    env = moving_rms(bp, RMS_WINDOW_S)
    saturated = (mv <= SAT_LOW_MV) | (mv >= SAT_HIGH_MV)

    # --- 1. raw signal ---
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 3.6))
    shade(ax, y=3420)
    for y, text in ((0, "0 mV"), (SATURATION_MV, f"{SATURATION_MV} mV (saturation)")):
        ax.axhline(y, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)), zorder=2)
        ax.text(1.0, y, " " + text, transform=ax.get_yaxis_transform(), ha="left", va="center",
                fontsize=7.5, color=style.REF_COLOR)
    ax.plot(t, mv, color="#333333", linewidth=0.3, zorder=3)
    ax.set_xlim(0, DURATION_S)
    ax.set_ylim(-100, 3500)
    ax.set_xlabel("Time since start of recording (s)")
    ax.set_ylabel("ADC reading (mV)")
    ax.set_title("Experiment 06 (draft): raw AD8232 output at 1 kHz, left forearm", loc="left")
    fig.text(0.01, -0.02, FOOTNOTE + f"\nSaturated (<= {SAT_LOW_MV} or >= {SAT_HIGH_MV} mV): "
             f"{saturated.sum()} of {saturated.size} samples.", fontsize=7.5, color=style.REF_COLOR,
             va="top")
    save(fig, out_dir, "emg06_raw.png")

    # --- 2. band-passed signal and RMS envelope ---
    fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(style.WIDTH_IN, 5.4),
                                 gridspec_kw={"hspace": 0.12})
    lim = np.percentile(np.abs(bp), 99.9) * 1.15
    shade(a1, y=lim * 0.97)
    a1.plot(t, bp, color="#333333", linewidth=0.3, zorder=3)
    a1.set_ylim(-lim, lim)
    a1.set_ylabel(f"Band-passed {BAND[0]}-{BAND[1]} Hz (mV)")
    shade(a2, show_labels=False)
    a2.plot(t, env, color=style.COLORS["D"], linewidth=1.0, zorder=3)
    a2.set_ylim(0, None)
    a2.set_ylabel(f"Moving RMS, {RMS_WINDOW_S * 1000:.0f} ms (mV)")
    a2.set_xlabel("Time since start of recording (s)")
    a2.set_xlim(0, DURATION_S)
    a1.set_title("Experiment 06 (draft): band-passed signal and RMS envelope", loc="left")
    fig.text(0.01, -0.01, FOOTNOTE + "\nZero-phase FFT band-pass (numpy), raised-cosine edges ±2 Hz. "
             "Shaded: light / hard / chord phases.", fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_bandpass_envelope.png")

    # --- statistics per phase ---
    relax_bp = np.concatenate([bp[window(t, s, e)] for s, e, _, k in PHASES if k == "relax"])
    relax_rms = np.sqrt(np.mean(relax_bp ** 2))
    rows = []
    for start, end, label, kind in PHASES:
        w = window(t, start, end)
        rms = np.sqrt(np.mean(bp[w] ** 2))
        rows.append(dict(label=f"{start:g}-{end:g} s {label}", kind=kind, n=int(w.sum()),
                         mean=mv[w].mean(), sd=mv[w].std(), sat=saturated[w].mean() * 100,
                         sat_low=int((mv[w] <= SAT_LOW_MV).sum()), sat_high=int((mv[w] >= SAT_HIGH_MV).sum()),
                         rms=rms, ratio=rms / relax_rms))

    # --- 3. PSD per kind ---
    psd = {}
    for kind in ("relax", "light", "hard", "chord"):
        segs = [mv[window(t, s, e)] for s, e, _, k in PHASES if k == kind]
        psd[kind] = welch(segs)
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.4))
    for kind, (f, p, count) in psd.items():
        ax.semilogy(f, p, color=KIND_COLORS[kind], linewidth=1.2, label=f"{kind} ({count} segments)")
    ax.axvline(SPLIT_HZ, color=style.REF_COLOR, linewidth=1.0, linestyle=(0, (4, 3)))
    ax.text(SPLIT_HZ + 3, 0.98, f"{SPLIT_HZ} Hz (typical AD8232\nmodule low-pass, not measured)",
            transform=ax.get_xaxis_transform(), va="top", fontsize=7.5, color=style.REF_COLOR)
    for h in range(MAINS_HZ, 500, MAINS_HZ):
        ax.axvline(h, color="#bbbbbb", linewidth=0.6, linestyle=":", zorder=0)
    ax.text(MAINS_HZ * 2 + 2, 0.02, "dotted: 60 Hz mains harmonics", transform=ax.get_xaxis_transform(),
            fontsize=7, color="#888888")
    ax.set_xlim(0, 500)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (mV²/Hz, log scale)")
    ax.set_title("Experiment 06 (draft): power spectrum per phase type (Welch)", loc="left")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.86))
    fig.text(0.01, -0.02, FOOTNOTE + f"\nWelch: Hann window, {WELCH_N} samples, 50% overlap; "
             f"first {REACTION_S} s after each cue skipped; raw mV with each segment's mean removed.",
             fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_psd.png")

    # --- report ---
    lines = ["| Phase | n | Raw mean (mV) | Raw SD (mV) | Saturated % (low/high samples) | "
             "Band-passed RMS (mV) | RMS / relax |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['label']} | {r['n']} | {r['mean']:.1f} | {r['sd']:.1f} | "
                     f"{r['sat']:.2f} ({r['sat_low']}/{r['sat_high']}) | {r['rms']:.1f} | {r['ratio']:.2f} |")
    lines.append(f"\nRelax baseline (all relax windows): band-passed RMS {relax_rms:.1f} mV")
    for kind in ("light", "hard", "chord"):
        w = np.zeros_like(t, dtype=bool)
        for s, e, _, k in PHASES:
            if k == kind:
                w |= window(t, s, e)
        lines.append(f"{kind} / relax RMS ratio: {np.sqrt(np.mean(bp[w] ** 2)) / relax_rms:.2f}")
    lines.append(f"\nShare of {BAND[0]}-{BAND[1]} Hz power above {SPLIT_HZ} Hz (from the PSD):")
    lines.append("| Kind | total 20-450 (mV²) | >40 Hz share | >40 Hz share, mains ±3 Hz excluded | "
                 ">40 Hz share of power above relax |")
    lines.append("|---|---|---|---|---|")
    f, p_relax, _ = psd["relax"]
    for kind, (f, p, _) in psd.items():
        total = band_power(f, p, *BAND)
        above = band_power(f, p, SPLIT_HZ, BAND[1])
        total_nm = band_power(f, p, *BAND, exclude_mains=True)
        above_nm = band_power(f, p, SPLIT_HZ, BAND[1], exclude_mains=True)
        excess = np.clip(p - p_relax, 0, None)
        ex_total, ex_above = band_power(f, excess, *BAND), band_power(f, excess, SPLIT_HZ, BAND[1])
        ex_share = f"{100 * ex_above / ex_total:.1f}%" if kind != "relax" and ex_total > 0 else "-"
        lines.append(f"| {kind} | {total:.1f} | {100 * above / total:.1f}% | "
                     f"{100 * above_nm / total_nm:.1f}% | {ex_share} |")
    sat_idx = np.flatnonzero(saturated)
    if sat_idx.size:
        runs = np.split(sat_idx, np.flatnonzero(np.diff(sat_idx) > 1) + 1)
        lines.append(f"\nSaturated runs: {len(runs)}; " + ", ".join(
            f"{t[r[0]]:.2f}-{t[r[-1]]:.2f} s ({r.size}, {'low' if mv[r[0]] <= SAT_LOW_MV else 'high'})"
            for r in runs[:40]))
    report = "\n".join(lines)
    if out_dir:
        (out_dir / "summary.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
