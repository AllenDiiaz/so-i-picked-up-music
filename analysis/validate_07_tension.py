"""Experiment 07: validate the on-board tension DSP (emg_dsp.c) on experiment 06 recordings.

    python analysis/validate_07_tension.py [OUT_DIR]     (default /tmp/tension07)

1. Builds and runs the host test (the same emg_dsp.c as the firmware, float32) on segments A
   and B of experiment 06.
2. Runs a float64 Python reference of the same causal algorithm and compares every hop.
3. Plots normalized RMS and level against the cued effort phases.
4. Checks the level in each phase's analysis window and measures the algorithm delay against a
   zero-phase (offline) version of the same metric.
"""
import io
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy import signal

import style
from design_emg_filters import design
from emg import CORE, EMG_DIR, RECORDINGS, SKIP_S, notched

REPO = Path(__file__).resolve().parent.parent
HOST_DIR = REPO / "firmware/experiments/07_onboard_tension/host_test"
HEADER = REPO / "firmware/experiments/07_onboard_tension/components/emg_dsp/include/emg_dsp.h"


def constants():
    """Read the tunable constants from emg_dsp.h so the reference cannot drift from the C code."""
    text = HEADER.read_text()
    get = lambda name: float(re.search(rf"#define {name}\s+([\d.]+)f?", text).group(1))  # noqa: E731
    return dict(window=int(get("EMG_WINDOW_SAMPLES")), hop=int(get("EMG_HOP_SAMPLES")),
                cal=int(get("EMG_CAL_SAMPLES")), settle=int(get("EMG_SETTLE_SAMPLES")),
                cal_min=int(get("EMG_CAL_MIN_VALID")),
                level1=get("EMG_LEVEL1_RATIO"), level2=get("EMG_LEVEL2_RATIO"),
                sat_low=get("EMG_SAT_LOW_MV"), sat_high=get("EMG_SAT_HIGH_MV"))


def load_run(log):
    """Newest board run from sample index 0: (mv, offset) with recording time = index / 1000 - offset."""
    rows = []
    for line in (EMG_DIR / log).read_text().splitlines():
        m = re.match(r"^\s*([\d.]+)\t(\d+),(\d+)$", line)
        if m:
            rows.append((float(m.group(1)), int(m.group(2)), int(m.group(3))))
    start = max(i for i, r in enumerate(rows) if r[1] == 0)
    run = rows[start:]
    host, idx, mv = (np.array(c, dtype=float) for c in zip(*run))
    assert np.all(np.diff(idx) == 1), "sample indices are not continuous"
    live = host > 1
    offset = (idx[live] / 1000 - host[live]).max()
    return mv, offset


def reference(mv, c):
    """float64 version of emg_dsp_process(), hop by hop."""
    rows, _ = design()
    sos = np.column_stack([rows[:, :3], np.ones(len(rows)), rows[:, 3:]])
    y = signal.sosfilt(sos, mv - mv[0])
    y2 = y * y
    sat = (mv <= c["sat_low"]) | (mv >= c["sat_high"])
    cal = slice(c["settle"], c["settle"] + c["cal"])
    good = ~sat[cal]
    baseline = np.sqrt(y2[cal][good].mean()) if good.sum() >= c["cal_min"] else 0.0
    out = []
    last_rms, last_norm, last_level, have = 0.0, 0.0, -1, False
    for n in range(c["window"], len(mv) + 1, c["hop"]):
        w = slice(n - c["window"], n)
        calibrating = n < c["settle"] + c["cal"]
        s = bool(sat[w].any())
        if not s:
            last_rms = np.sqrt(y2[w].mean())
            if baseline > 0 and not calibrating:
                last_norm = last_rms / baseline
                last_level = 2 if last_norm >= c["level2"] else (1 if last_norm >= c["level1"] else 0)
            else:
                last_norm, last_level = 0.0, -1
            have = True
        elif calibrating or baseline <= 0:
            last_norm, last_level = 0.0, -1
        out.append((n - 1, last_rms if have else 0.0, last_norm, last_level, int(s), int(calibrating)))
    return np.array(out), baseline


def run_c(log):
    subprocess.run(["make", "-s", "-C", str(HOST_DIR)], check=True)
    res = subprocess.run([str(HOST_DIR / "emg_host"), str(EMG_DIR / log)], check=True, capture_output=True, text=True)
    baseline = float(re.search(r"baseline ([\d.]+) mV", res.stderr).group(1))
    return np.loadtxt(io.StringIO(res.stdout), delimiter=",", skiprows=1), baseline


def offline_normalized(mv, offset, baseline, c):
    """Zero-phase counterpart: experiment 06's FFT filters and a centred 200 ms RMS (recording time)."""
    core = notched(mv, CORE)
    k = np.ones(c["window"]) / c["window"]
    rms = np.sqrt(np.convolve(core ** 2, k, mode="same"))
    t = np.arange(len(mv)) / 1000 - offset
    return t, rms / baseline


EXPECTED = {"relax": 0, "light": 1, "chord": 1, "hard": 2}


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tension07")
    out_dir.mkdir(parents=True, exist_ok=True)
    style.apply()
    c = constants()
    report = [f"Constants from emg_dsp.h: {c}", ""]

    fig, axes = plt.subplots(4, 1, figsize=(style.WIDTH_IN, 7.2), gridspec_kw={"hspace": 0.55,
                             "height_ratios": [1.6, 0.7, 1.6, 0.7]})
    for seg_i, name in enumerate(("A", "B")):
        rec = RECORDINGS[name]
        mv, offset = load_run(rec["file"])
        c_out, c_base = run_c(rec["file"])
        ref, ref_base = reference(mv, c)

        # --- 1. C vs Python reference ---
        assert c_out.shape == ref.shape and np.all(c_out[:, 0] == ref[:, 0]), "hop indices differ"
        d_rms = np.abs(c_out[:, 1] - ref[:, 1])
        d_norm = np.abs(c_out[:, 2] - ref[:, 2])
        rel = d_rms / np.maximum(ref[:, 1], 1e-9)
        report += [f"== {name} ({rec['file']}): {len(mv)} samples, {len(ref)} hops, board time offset {offset:.3f} s",
                   f"baseline C {c_base:.6f} mV, reference {ref_base:.6f} mV (diff {abs(c_base - ref_base):.2e})",
                   f"max |RMS diff| {d_rms.max():.3e} mV (max relative {rel.max():.3e}); "
                   f"max |normalized diff| {d_norm.max():.3e}",
                   f"level mismatches {int((c_out[:, 3] != ref[:, 3]).sum())}, saturated mismatches "
                   f"{int((c_out[:, 4] != ref[:, 4]).sum())}, calibrating mismatches {int((c_out[:, 5] != ref[:, 5]).sum())}"]

        t = c_out[:, 0] / 1000 - offset          # recording time of the window's last sample
        norm, level, sat = c_out[:, 2], c_out[:, 3].astype(int), c_out[:, 4].astype(bool)

        # --- 3. level per phase analysis window ---
        report.append("| phase | window (s) | hops | expected | level 0 / 1 / 2 / -1 | correct | saturated hops |")
        report.append("|---|---|---|---|---|---|---|")
        counts = {}
        for start, end, kind in rec["phases"]:
            counts[kind] = counts.get(kind, 0) + 1
            w = (t - 0.2 >= start + SKIP_S) & (t < end)        # whole RMS window inside the analysis window
            lv = level[w]
            dist = " / ".join(str(int((lv == k).sum())) for k in (0, 1, 2, -1))
            report.append(f"| {kind} {counts[kind]} | {start + SKIP_S:g}-{end:g} | {w.sum()} | {EXPECTED[kind]} | "
                          f"{dist} | {int((lv == EXPECTED[kind]).sum())}/{w.sum()} | {int(sat[w].sum())} |")

        # --- 4. algorithm delay vs zero-phase offline metric (onset and release, level 1 crossing) ---
        t_off, n_off = offline_normalized(mv, offset, c_base, c)
        report.append("| effort | offline crosses 1.49x up (s) | causal level >=1 (s) | delay (ms) | "
                      "offline last above (s) | causal back to 0 (s) | delay (ms) |")
        report.append("|---|---|---|---|---|---|---|")
        counts = {}
        for start, end, kind in rec["phases"]:
            if kind == "relax":
                continue
            counts[kind] = counts.get(kind, 0) + 1
            span = (t_off >= start) & (t_off < end + 3)
            above = span & (n_off >= c["level1"])
            hop_span = (t >= start) & (t < end + 3) & ~sat
            hop_up = hop_span & (level >= 1)
            if not above.any() or not hop_up.any():
                report.append(f"| {kind} {counts[kind]} | - | - | - | - | - | - |")
                continue
            on_off = t_off[above][0]
            on_c = t[hop_up][0]
            # Release: first time after the last crossing that the signal stays below threshold.
            last_off = t_off[above][-1]
            last_c = t[hop_up][-1]
            later = hop_span & (t > last_c)
            off_c = t[later][0] if later.any() else np.nan
            report.append(f"| {kind} {counts[kind]} | {on_off:.3f} | {on_c:.3f} | {(on_c - on_off) * 1000:.0f} | "
                          f"{last_off:.3f} | {off_c:.3f} | {(off_c - last_off) * 1000:.0f} |")
        report.append("")

        # --- plot ---
        ax, lax = axes[2 * seg_i], axes[2 * seg_i + 1]
        for a in (ax, lax):
            for start, end, kind in rec["phases"]:
                if kind != "relax":
                    style.shade(a, start, end, {"light": style.TEAL, "chord": style.BLUE, "hard": style.RED}[kind])
            a.set_xlim(0, rec["duration"])
        ax.plot(t_off, n_off, color=style.GRAY, linewidth=0.5, label="zero-phase (offline) 200 ms RMS")
        ax.plot(t, np.where(c_out[:, 5] == 1, np.nan, norm), color=style.RAW, linewidth=0.8,
                label="on-board (causal) normalized")
        if sat.any():
            ax.plot(t[sat], np.full(sat.sum(), 0.2), "|", color=style.RED, markersize=4, label="saturated hop")
        for r in (c["level1"], c["level2"]):
            style.ref_line(ax, r)
        ax.set_ylim(0, max(8, np.nanpercentile(norm, 99.5) * 1.1))
        ax.set_ylabel("RMS / baseline")
        ax.set_title(f"{rec['title']} (baseline {c_base:.2f} mV from the first 0.5-5.5 s after boot)", loc="left")
        ax.legend(loc="upper right", ncol=3)
        lax.step(t, level, where="post", color=style.RAW, linewidth=0.8)
        lax.set_yticks([-1, 0, 1, 2])
        lax.set_yticklabels(["cal", "relax", "medium", "hard"])
        lax.set_ylim(-1.5, 2.5)
        style.panel_label(ax, "ab"[seg_i] if seg_i == 0 else "c")
        style.panel_label(lax, "b" if seg_i == 0 else "d")
    axes[-1].set_xlabel("Time since start of recording (s)")
    fig.savefig(out_dir / "tension07_validation.png", dpi=style.DPI, bbox_inches="tight")
    plt.close(fig)

    text = "\n".join(report)
    (out_dir / "summary.md").write_text(text + "\n")
    print(text)
    print(f"wrote {out_dir / 'tension07_validation.png'}")


if __name__ == "__main__":
    main()
