"""Figures for experiment 06: forearm EMG with the AD8232 module (three tension levels).

Also prints the tables used in docs/experiments/06_forearm_emg.md.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import style
from emg import (BAND, CORE, MAINS_HZ, RECORDINGS, SKIP_S, bandpass, efforts, load_recording, moving_rms,
                 notched, rms, saturated, welch, window)

KIND_COLOR = {"relax": style.COLORS["A"], "light": style.COLORS["C"], "chord": style.COLORS["D"],
              "hard": style.COLORS["B"]}
KIND_SHADE = {"light": "#d5efeb", "chord": "#dbe6f6", "hard": "#fde0d6"}
MARKER = {"A": "o", "B": "s", "retest": "^"}
REC_LABEL = {"A": "A: table, hand free", "B": "B: holding the guitar", "retest": "Retest: hard grips only"}
LEVELS = [("relax", ("relax",), "#ececec"), ("medium", ("light", "chord"), "#dff1ee"),
          ("hard", ("hard",), "#fde6de")]
KINDS = ["relax", "light", "chord", "hard"]
SUBJECT = ("Real data, one subject, one day. Left forearm flexors (red/yellow 2-3 cm apart along the muscle, "
           "green on the elbow), left hand.")
METRIC = (f"Main metric: RMS of the {CORE[0]}-{CORE[1]} Hz band with every {MAINS_HZ} Hz harmonic (±2 Hz) "
          f"removed; first {SKIP_S} s after each cue skipped.")


def footnote(fig, text, y=-0.01):
    fig.text(0.01, y, text, fontsize=7.5, color=style.REF_COLOR, ha="left", va="top")


def collect():
    data = {name: efforts(name) for name in ("first", "retest", "A", "B")}
    return data


def level_ranges(data):
    values = {kind: [] for kind in KINDS}
    for name in ("retest", "A", "B"):
        relax, active = data[name]
        values["relax"] += [r["rms_core"] for r in relax]
        values.update({k: values[k] + [a["rms_core"] for a in active if a["kind"] == k]
                       for k in ("light", "chord", "hard")})
    return {level: (min(v for k in kinds for v in values[k]), max(v for k in kinds for v in values[k]))
            for level, kinds, _ in LEVELS}


def plot_tension_levels(data, ranges):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.8))
    for level, _, shade in LEVELS:
        lo, hi = ranges[level]
        ax.axhspan(lo, hi, color=shade, linewidth=0, zorder=0)
        ax.text(1.0, (lo + hi) / 2, f" {level}\n {lo:.1f}-{hi:.1f} mV", transform=ax.get_yaxis_transform(),
                ha="left", va="center", fontsize=8, color=style.REF_COLOR)
    for name in ("A", "B", "retest"):
        relax, active = data[name]
        offset = {"A": -0.25, "B": 0.0, "retest": 0.25}[name]
        seen = {}
        for item in relax + active:
            j = seen[item["kind"]] = seen.get(item["kind"], -1) + 1   # spread repeats side by side
            x = KINDS.index(item["kind"]) + offset + (j - 1.5) * 0.045
            sat = item["saturated"] > 0
            color = KIND_COLOR[item["kind"]]
            ax.plot(x, item["rms_core"], MARKER[name], markersize=7, color=color, markeredgewidth=1.4,
                    markerfacecolor="white" if sat else color, zorder=3)
            if sat:
                ax.annotate("saturated", xy=(x, item["rms_core"]), xytext=(x - 0.6, item["rms_core"] + 4),
                            fontsize=7.5, color=color, arrowprops=dict(arrowstyle="->", color=color, lw=0.9))
    ax.set_xticks(range(len(KINDS)))
    ax.set_xticklabels(["relax", "light grip", "G chord", "hard grip"])
    ax.set_xlim(-0.5, len(KINDS) - 0.5)
    ax.set_ylim(0, None)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel(f"RMS, {CORE[0]}-{CORE[1]} Hz, mains removed (mV)")
    ax.set_title("Experiment 06: forearm EMG falls into three tension levels", loc="left")
    handles = [Line2D([], [], marker=MARKER[n], linestyle="", color="#555555", label=REC_LABEL[n])
               for n in ("A", "B", "retest")]
    handles.append(Line2D([], [], marker="o", linestyle="", color="#555555", markerfacecolor="white",
                          label="window contains saturated samples"))
    ax.legend(handles=handles, loc="upper left", fontsize=8)
    footnote(fig, SUBJECT + "\n" + METRIC + "\nOne point per phase. Bands: range of the observed values "
             "per level. The first attempt is excluded (grip hand not confirmed).")
    style.save(fig, "06_tension_levels.png")


def plot_metric_comparison(data):
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(style.WIDTH_IN, 4.2), gridspec_kw={"wspace": 0.08})
    order = [("A", "light"), ("B", "chord"), ("A", "hard"), ("retest", "hard")]
    for ax, key, title in ((axes[0], "ratio_plain", f"{BAND[0]}-{BAND[1]} Hz, no mains removal"),
                           (axes[1], "ratio_core", f"{CORE[0]}-{CORE[1]} Hz, mains removed (main metric)")):
        ticks, labels = [], []
        for gx, (name, kind) in enumerate(order):
            items = [a for a in data[name][1] if a["kind"] == kind]
            for j, a in enumerate(items):
                x = gx + (j - (len(items) - 1) / 2) * 0.18
                sat = a["saturated"] > 0
                ax.plot(x, a[key], MARKER[name], markersize=7, color=KIND_COLOR[kind], markeredgewidth=1.4,
                        markerfacecolor="white" if sat else KIND_COLOR[kind], zorder=3)
            ticks.append(gx)
            labels.append(f"{name}\n{kind}")
        ax.axhline(1, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)))
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_xlim(-0.5, len(order) - 0.5)
        ax.grid(axis="x", visible=False)
        ax.set_title(title, loc="left", fontsize=9)
    axes[0].text(-0.4, 1.05, "relax level", fontsize=7.5, color=style.REF_COLOR, va="bottom")
    axes[0].set_ylim(0, None)
    axes[0].set_ylabel("RMS / relax phases before and after")
    fig.suptitle("Experiment 06: removing mains interference reveals the EMG", x=0.125, ha="left", y=1.0,
                 fontsize=11)
    footnote(fig, SUBJECT + f"\nSame efforts in both panels; first {SKIP_S} s after each cue skipped. "
             "Open marker: window contains saturated samples.\nIn A, 60 Hz mains made up most of the relax "
             "RMS, so without removing it light grips look like relax.", y=-0.03)
    style.save(fig, "06_metric_comparison.png")


def plot_envelopes():
    fig, axes = plt.subplots(2, 1, figsize=(style.WIDTH_IN, 6.0), gridspec_kw={"hspace": 0.42})
    for ax, name in zip(axes, ("A", "B")):
        rec = RECORDINGS[name]
        t, mv = load_recording(name)
        env_core = moving_rms(notched(mv, CORE))
        env_plain = moving_rms(bandpass(mv, *BAND))
        ymax = max(np.percentile(env_core, 99.9), np.percentile(env_plain, 99.9)) * 1.25
        counts = {}
        for start, end, kind in rec["phases"]:
            if kind == "relax":
                continue
            counts[kind] = counts.get(kind, 0) + 1
            ax.axvspan(start, end, color=KIND_SHADE[kind], linewidth=0, zorder=0)
            ax.text((start + end) / 2, ymax * 0.98, f"{kind} {counts[kind]}", ha="center", va="top",
                    fontsize=7.5, color=KIND_COLOR[kind], fontweight="bold")
        ax.plot(t, env_plain, color="#9db8e3", linewidth=0.8, zorder=2,
                label=f"{BAND[0]}-{BAND[1]} Hz, no mains removal")
        ax.plot(t, env_core, color="#222222", linewidth=0.9, zorder=3,
                label=f"{CORE[0]}-{CORE[1]} Hz, mains removed")
        sat = saturated(mv)
        if sat.any():
            idx = np.flatnonzero(sat)
            ax.annotate(f"saturated {t[idx[0]]:.1f}-{t[idx[-1]]:.1f} s", xy=(t[idx[0]], 2),
                        xytext=(t[idx[0]] + 3, ymax * 0.55), fontsize=7.5, color=KIND_COLOR["chord"],
                        arrowprops=dict(arrowstyle="->", color=KIND_COLOR["chord"], lw=0.9))
        ax.set_xlim(0, rec["duration"])
        ax.set_ylim(0, ymax)
        ax.set_ylabel("Moving RMS, 100 ms (mV)")
        ax.set_title(rec["title"], loc="left", fontsize=9.5)
        ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.86), fontsize=7.5)
    axes[-1].set_xlabel("Time since start of recording (s)")
    footnote(fig, SUBJECT + "\nShaded: effort phases as cued (grip onset lagged the cue by about 1-1.6 s).")
    style.save(fig, "06_envelopes.png")


def plot_psd():
    rec = RECORDINGS["A"]
    t, mv = load_recording("A")
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.2))
    ax.axvspan(*CORE, color="#f3f3f3", linewidth=0, zorder=0)
    for h in range(MAINS_HZ, 500, MAINS_HZ):
        ax.axvline(h, color="#bbbbbb", linewidth=0.7, linestyle=":", zorder=1)
    for x in CORE:
        ax.axvline(x, color=style.REF_COLOR, linewidth=0.9, linestyle=(0, (4, 3)), zorder=1)
    for kind in ("relax", "hard"):
        f, p, n = welch([mv[window(t, s, e)] for s, e, k in rec["phases"] if k == kind])
        ax.semilogy(f, p, color=KIND_COLOR[kind], linewidth=1.2, label=f"A {kind} ({n} segments)", zorder=3)
    ax.text(CORE[0] + 3, 0.97, f"{CORE[0]} Hz", transform=ax.get_xaxis_transform(), fontsize=7.5,
            va="top", color=style.REF_COLOR)
    ax.text(CORE[1] + 3, 0.97, f"{CORE[1]} Hz", transform=ax.get_xaxis_transform(), fontsize=7.5,
            va="top", color=style.REF_COLOR)
    ax.text(242, 0.04, f"dotted: {MAINS_HZ} Hz mains harmonics", transform=ax.get_xaxis_transform(),
            fontsize=7.5, color="#888888")
    ax.set_xlim(0, 500)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("PSD (mV²/Hz, log scale)")
    ax.set_title("Experiment 06: spectrum of A, relax vs hard grip (Welch)", loc="left")
    ax.legend(loc="upper right")
    footnote(fig, SUBJECT + f"\nWelch: Hann, 512 samples, 50% overlap; first {SKIP_S} s after each cue skipped. "
             f"Gray band: {CORE[0]}-{CORE[1]} Hz used for the main metric.")
    style.save(fig, "06_psd.png")


def first_vs_retest_values():
    """Hard (and first-attempt chord) vs all relax phases, 0.5 s skip: the method used when recorded."""
    out = {}
    for name, kind in (("first", "hard"), ("first", "chord"), ("retest", "hard")):
        rec = RECORDINGS[name]
        t, mv = load_recording(name)
        relax = np.zeros_like(t, dtype=bool)
        act = np.zeros_like(t, dtype=bool)
        for s, e, k in rec["phases"]:
            if k == "relax":
                relax |= window(t, s, e, 0.5)
            elif k == kind:
                act |= window(t, s, e, 0.5)
        plain, core = bandpass(mv, *BAND), notched(mv, CORE)
        out[(name, kind)] = (rms(plain[act]) / rms(plain[relax]), rms(core[act]) / rms(core[relax]))
    return out


def plot_first_vs_retest(values):
    fig, ax = plt.subplots(figsize=(style.WIDTH_IN, 4.2))
    groups = [(("first", "hard"), "First attempt\nhard grip\n(grip hand not confirmed)"),
              (("retest", "hard"), "Retest\nhard grip\n(left hand, hand free)"),
              (("first", "chord"), "First attempt\nchord phase\n(left hand, as instructed)")]
    width = 0.34
    for gx, (key, _) in enumerate(groups):
        plain, core = values[key]
        color = KIND_COLOR[key[1]]
        for dx, value, alpha, hatch in ((-width / 2, plain, 0.45, None), (width / 2, core, 1.0, None)):
            ax.bar(gx + dx, value, width, color=color, alpha=alpha, hatch=hatch, zorder=2)
            ax.text(gx + dx, value + 0.05, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    ax.axhline(1, color=style.REF_COLOR, linewidth=0.8, linestyle=(0, (4, 3)), zorder=3)
    ax.annotate("", xy=(1 - width / 2, values[("retest", "hard")][0] + 0.25),
                xytext=(0 - width / 2, values[("first", "hard")][0] + 0.25),
                arrowprops=dict(arrowstyle="->", color=style.REF_COLOR, lw=1.0, connectionstyle="arc3,rad=-0.25"))
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[1] for g in groups], fontsize=8)
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, None)
    ax.set_ylabel("Effort RMS / RMS over all relax phases")
    ax.set_title("Experiment 06: first attempt vs retest, effort / relax", loc="left", fontsize=10)
    legend = [plt.Rectangle((0, 0), 1, 1, color="#999999", alpha=0.45, label=f"{BAND[0]}-{BAND[1]} Hz"),
              plt.Rectangle((0, 0), 1, 1, color="#999999", label=f"{CORE[0]}-{CORE[1]} Hz, mains removed")]
    ax.legend(handles=legend, loc="upper right", fontsize=8)
    footnote(fig, SUBJECT.replace(", left hand.", ".") + "\nComputed as when the runs were first analysed: "
             "first 0.5 s after each cue skipped, baseline = all relax phases.\nWhich hand gripped in the first "
             "attempt was not recorded; the chord phase was explicitly done with the left hand.", y=-0.1)
    style.save(fig, "06_first_vs_retest.png")


def print_tables(data, ranges, values):
    print("| Recording | Effort | Window (s) | n | Saturated | RMS 45-200 notched (mV) | / relax | "
          "RMS 20-450 / relax |")
    print("|---|---|---|---|---|---|---|---|")
    for name in ("first", "retest", "A", "B"):
        for a in data[name][1]:
            print(f"| {name} | {a['kind']} {a['number']} | {a['start'] + SKIP_S:g}-{a['end']:g} | {a['n']} | "
                  f"{a['saturated']} | {a['rms_core']:.1f} | {a['ratio_core']:.2f} | {a['ratio_plain']:.2f} |")
    print("\n| Recording | Relax phases, RMS 45-200 notched (mV) | Relax phases, RMS 20-450 (mV) |")
    print("|---|---|---|")
    for name in ("first", "retest", "A", "B"):
        relax = data[name][0]
        print(f"| {name} | " + ", ".join(f"{r['rms_core']:.1f}" for r in relax) + " | "
              + ", ".join(f"{r['rms_plain']:.1f}" for r in relax) + " |")
    print("\nLevels (retest, A, B):", ", ".join(f"{k} {lo:.1f}-{hi:.1f} mV" for k, (lo, hi) in ranges.items()))
    print("First vs retest (0.5 s skip, all-relax baseline): " + ", ".join(
        f"{n} {k}: plain {p:.2f}, core {c:.2f}" for (n, k), (p, c) in values.items()))


def main():
    style.apply()
    data = collect()
    ranges = level_ranges(data)
    values = first_vs_retest_values()
    plot_tension_levels(data, ranges)
    plot_metric_comparison(data)
    plot_envelopes()
    plot_psd()
    plot_first_vs_retest(values)
    print_tables(data, ranges, values)


if __name__ == "__main__":
    main()
