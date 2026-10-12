"""Experiment 06, segments A and B: graded grips and guitar chords vs relax.

    python analysis/analyze_06_AB.py [A_LOG B_LOG RETEST_LOG] [--figs DIR]

A: hand free over the table edge, light and hard grips. B: holding the guitar,
pressing a G chord. RETEST_LOG is the earlier three-hard-grip retest, re-analysed here
with the same 1.5 s reaction skip so the numbers can be compared. Logs default to
docs/data/06_forearm_emg/; figures and summary.md are written only with --figs.

Shared loading, filters and phase definitions come from emg.py: newest board run, time
from the sample index, zero-phase FFT band-pass, mains notches, 100 ms moving RMS, Welch PSD.
"""
import argparse
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

import style
from analyze_06_emg import save
from emg import (BAND, CORE as EMG_CORE, RECORDINGS, RMS_WINDOW_S, SAT_HIGH_MV, SAT_LOW_MV, SKIP_S, band_power,
                 bandpass, load, moving_rms, notched, rms, welch, window as win)

BANDS = [(20, 40), (40, 100), (100, 200), (200, 450)]
KIND_COLOR = {"relax": style.COLORS["A"], "light": style.COLORS["C"], "hard": style.COLORS["B"],
              "chord": style.COLORS["D"]}
KIND_SHADE = {"light": "#d5efeb", "hard": "#fde0d6", "chord": "#dbe6f6"}
SEGMENTS = {key: RECORDINGS[key] for key in ("A", "B", "retest")}
FOOTNOTE = ("Real data, left forearm flexors (red/yellow 2-3 cm apart along the muscle, green on the elbow), "
            "left hand.\n1 kHz ADC on GPIO4 (AD8232 OUTPUT). Statistics skip the first "
            f"{SKIP_S} s after every cue.")


def analyse(log, seg):
    t, mv = load(log, seg["duration"])
    bp = bandpass(mv, *BAND)
    nb = notched(mv, BAND)
    core = notched(mv, EMG_CORE)
    saturated = (mv <= SAT_LOW_MV) | (mv >= SAT_HIGH_MV)
    phases = seg["phases"]
    events, counts = [], {}
    for i, (start, end, kind) in enumerate(phases):
        if kind == "relax":
            continue
        counts[kind] = counts.get(kind, 0) + 1
        w = win(t, start, end)
        before, after = phases[i - 1], phases[i + 1]
        wb, wa = win(t, *before[:2]), win(t, *after[:2])
        neighbours = wb | wa
        f, p, _ = welch([mv[w]])
        _, p_rel, _ = welch([mv[wb], mv[wa]])
        events.append(dict(
            name=f"{kind} {counts[kind]}", kind=kind, start=start, end=end,
            rms=rms(bp[w]), rms_before=rms(bp[wb]), rms_after=rms(bp[wa]),
            ratio=rms(bp[w]) / rms(bp[neighbours]),
            ratio_notched=rms(nb[w]) / rms(nb[neighbours]),
            rms_core=rms(core[w]), ratio_core=rms(core[w]) / rms(core[neighbours]),
            bands=[band_power(f, p, lo, hi) / band_power(f, p_rel, lo, hi) for lo, hi in BANDS],
            saturated=int(saturated[w].sum()), n=int(w.sum())))
    relax = np.zeros_like(t, dtype=bool)
    for start, end, kind in phases:
        if kind == "relax":
            relax |= win(t, start, end)
    return dict(t=t, mv=mv, bp=bp, env=moving_rms(bp, RMS_WINDOW_S), env_notched=moving_rms(nb, RMS_WINDOW_S),
                events=events, relax_rms=rms(bp[relax]), relax_rms_notched=rms(nb[relax]), relax_rms_core=rms(core[relax]),
                saturated=saturated, relax_mask=relax)


def plot_segment(key, seg, res, out_dir):
    t, bp, env = res["t"], res["bp"], res["env"]
    fig, (a1, a2) = plt.subplots(2, 1, sharex=True, figsize=(style.WIDTH_IN, 5.4),
                                 gridspec_kw={"hspace": 0.12})
    lim = np.percentile(np.abs(bp), 99.9) * 1.15
    for ax, label_y in ((a1, lim * 0.97), (a2, None)):
        counts = {}
        for start, end, kind in seg["phases"]:
            if kind == "relax":
                continue
            counts[kind] = counts.get(kind, 0) + 1
            ax.axvspan(start, end, color=KIND_SHADE[kind], linewidth=0, zorder=0)
            if label_y is not None:
                ax.text((start + end) / 2, label_y, f"{kind} {counts[kind]}", ha="center", va="top",
                        fontsize=7.5, color=KIND_COLOR[kind], fontweight="bold")
    a1.plot(t, bp, color="#333333", linewidth=0.3, zorder=3)
    a1.set_ylim(-lim, lim)
    a1.set_ylabel(f"Band-passed {BAND[0]}-{BAND[1]} Hz (mV)")
    a2.plot(t, env, color=style.COLORS["D"], linewidth=1.0, zorder=3, label="20-450 Hz")
    a2.plot(t, res["env_notched"], color="#222222", linewidth=0.9, zorder=4,
            label="20-450 Hz, 60 Hz harmonics notched")
    a2.legend(loc="upper right", fontsize=7.5)
    a2.text(0.01, 0.95, f"relax RMS: {res['relax_rms']:.1f} mV, notched {res['relax_rms_notched']:.1f} mV",
            transform=a2.transAxes, ha="left", va="top", fontsize=7.5, color=KIND_COLOR["relax"])
    a2.set_ylim(0, None)
    a2.set_ylabel(f"Moving RMS, {RMS_WINDOW_S * 1000:.0f} ms (mV)")
    a2.set_xlabel("Time since start of recording (s)")
    a2.set_xlim(0, seg["duration"])
    a1.set_title(f"Experiment 06 (draft) {seg['title']}", loc="left", fontsize=10)
    note = ""
    sat = res["saturated"]
    if sat.any():
        idx = np.flatnonzero(sat)
        note = (f"\nSaturated samples (<= {SAT_LOW_MV} or >= {SAT_HIGH_MV} mV): {sat.sum()}, "
                f"between {t[idx[0]]:.1f} and {t[idx[-1]]:.1f} s.")
    fig.text(0.01, -0.01, FOOTNOTE + note, fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, f"emg06_{key}_envelope.png")


def plot_ratios(results, out_dir):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.2))
    groups = [("A", "light"), ("A", "hard"), ("retest", "hard"), ("B", "chord")]
    labels = ["A light", "A hard", "Retest hard", "B chord"]
    for gx, (key, kind) in enumerate(groups):
        evs = [e for e in results[key]["events"] if e["kind"] == kind]
        for j, e in enumerate(evs):
            x = gx + (j - (len(evs) - 1) / 2) * 0.16
            sat = e["saturated"] > 0
            ax.plot(x, e["ratio"], "x", markersize=6, color=KIND_COLOR[kind], zorder=3)
            ax.plot(x, e["ratio_core"], "o", markersize=8, color=KIND_COLOR[kind],
                    markerfacecolor="white" if sat else KIND_COLOR[kind], markeredgewidth=1.5, zorder=4)
            ax.text(x, e["ratio_core"] + 0.15, f"{e['ratio_core']:.2f}", fontsize=7, ha="center", va="bottom",
                    color=style.REF_COLOR)
    ax.axhline(1, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)))
    ax.text(-0.45, 1.0, "relax level", fontsize=7.5, va="bottom", ha="left", color=style.REF_COLOR)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(labels)
    ax.set_xlim(-0.5, len(groups) - 0.5)
    ax.set_ylim(0, None)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Band-passed RMS / neighbouring relax RMS")
    ax.set_title("Experiment 06 (draft): each effort vs the relax phases before and after it", loc="left",
                 fontsize=10)
    fig.text(0.01, -0.02, FOOTNOTE + "\nDot: 45-200 Hz with 60 Hz harmonics notched (number shown). Cross: plain 20-450 Hz. "
             "Open dot: the window contains saturated samples.",
             fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_AB_ratios.png")


def plot_psd(results, out_dir):
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(style.WIDTH_IN, 3.8), gridspec_kw={"wspace": 0.08})
    for ax, key, kinds in ((axes[0], "A", ("relax", "light", "hard")), (axes[1], "B", ("relax", "chord"))):
        res, seg = results[key], SEGMENTS[key]
        for kind in kinds:
            segs = [res["mv"][win(res["t"], s, e)] for s, e, k in seg["phases"] if k == kind]
            f, p, n = welch(segs)
            ax.semilogy(f, p, color=KIND_COLOR[kind], linewidth=1.1, label=f"{kind} ({n} segments)")
        ax.axvline(40, color=style.REF_COLOR, linewidth=0.9, linestyle=(0, (4, 3)))
        ax.set_xlim(0, 500)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_title(f"Segment {key}", loc="left", fontsize=10)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylabel("PSD (mV²/Hz, log scale)")
    fig.text(0.01, -0.03, FOOTNOTE + "\nWelch: Hann, 512 samples, 50% overlap. Dashed: 40 Hz.",
             fontsize=7.5, color=style.REF_COLOR, va="top")
    save(fig, out_dir, "emg06_AB_psd.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for key in ("A", "B", "retest"):
        parser.add_argument(f"{key}_log", nargs="?", default=RECORDINGS[key]["file"])
    parser.add_argument("--figs", type=Path, help="write figures and summary.md into this directory")
    args = parser.parse_args()
    logs = dict(A=args.A_log, B=args.B_log, retest=args.retest_log)
    out_dir = args.figs
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    style.apply()
    results = {key: analyse(logs[key], SEGMENTS[key]) for key in ("A", "B", "retest")}
    for key in ("A", "B"):
        plot_segment(key, SEGMENTS[key], results[key], out_dir)
    plot_ratios(results, out_dir)
    plot_psd(results, out_dir)

    lines = [f"Skip after each cue: {SKIP_S} s. Ratios use the relax phases right before and after each effort.", "",
             "| Segment | Effort | n | Saturated | RMS (mV) | Relax before | Relax after | RMS / relax | "
             "RMS / relax, mains notched | 45-200 Hz notched RMS (mV) | 45-200 Hz notched / relax | "
             + " | ".join(f"{lo}-{hi} Hz" for lo, hi in BANDS) + " |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in ("A", "retest", "B"):
        for e in results[key]["events"]:
            lines.append(f"| {key} | {e['name']} ({e['start']:g}-{e['end']:g} s) | {e['n']} | {e['saturated']} | "
                         f"{e['rms']:.1f} | {e['rms_before']:.1f} | {e['rms_after']:.1f} | {e['ratio']:.2f} | "
                         f"{e['ratio_notched']:.2f} | {e['rms_core']:.1f} | {e['ratio_core']:.2f} | "
                         + " | ".join(f"{b:.2f}x" for b in e["bands"]) + " |")
    lines += ["", "| Segment | Relax RMS, all relax phases (mV) | mains notched (mV) | 45-200 Hz notched (mV) |",
              "|---|---|---|---|"]
    for key in ("A", "B", "retest"):
        r = results[key]
        lines.append(f"| {key} | {r['relax_rms']:.1f} | {r['relax_rms_notched']:.1f} | {r['relax_rms_core']:.1f} |")
    lines += ["", "Mean RMS / relax per effort type:"]
    for key, kind in (("A", "light"), ("A", "hard"), ("retest", "hard"), ("B", "chord")):
        r = [e["ratio"] for e in results[key]["events"] if e["kind"] == kind]
        clean = [e["ratio"] for e in results[key]["events"] if e["kind"] == kind and e["saturated"] == 0]
        rn = [e["ratio_notched"] for e in results[key]["events"] if e["kind"] == kind]
        cn = [e["ratio_notched"] for e in results[key]["events"] if e["kind"] == kind and e["saturated"] == 0]
        lines.append(f"- {key} {kind}: mean {np.mean(r):.2f} (each: {', '.join(f'{x:.2f}' for x in r)}); "
                     f"without saturated windows: {np.mean(clean):.2f} | mains notched: mean {np.mean(rn):.2f} "
                     f"(each: {', '.join(f'{x:.2f}' for x in rn)}), without saturated: {np.mean(cn):.2f}")
    report = "\n".join(lines)
    if out_dir:
        (out_dir / "summary.md").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
