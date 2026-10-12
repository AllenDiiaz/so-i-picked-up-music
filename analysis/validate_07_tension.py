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
    names = ["EMG_WINDOW_SAMPLES", "EMG_HOP_SAMPLES", "EMG_SETTLE_SAMPLES", "EMG_CAL_SAMPLES",
             "EMG_CAL_RETRY_SAMPLES", "EMG_CAL_MIN_VALID", "EMG_CAL_MAX_BASELINE_MV", "EMG_CAL_MAX_CV",
             "EMG_CAL_CHUNK_SAMPLES", "EMG_CAL_CHUNK_MIN", "EMG_LEVEL1_ENTER", "EMG_LEVEL1_EXIT",
             "EMG_LEVEL2_ENTER", "EMG_LEVEL2_EXIT", "EMG_SAT_LOW_MV", "EMG_SAT_HIGH_MV"]
    c = {n[4:].lower(): get(n) for n in names}
    for k in ("window_samples", "hop_samples", "settle_samples", "cal_samples", "cal_retry_samples",
              "cal_min_valid", "cal_chunk_samples", "cal_chunk_min"):
        c[k] = int(c[k])
    return c


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


def next_level(prev, r, c):
    if r >= c["level2_enter"] or (prev == 2 and r >= c["level2_exit"]):
        return 2
    if r >= c["level1_enter"] or (prev >= 1 and r >= c["level1_exit"]):
        return 1
    return 0


def reference(mv, c, max_cv=None):
    """float64 version of emg_dsp_process(), sample by sample (calibration state machine included).

    Returns (hops, events): hops rows = sample_index, rms, normalized, level, saturated, calibrating,
    baseline; events = (sample_index, result, valid_fraction, cv, rms).
    """
    max_cv = c["cal_max_cv"] if max_cv is None else max_cv
    rows, _ = design()
    sos = np.column_stack([rows[:, :3], np.ones(len(rows)), rows[:, 3:]])
    y2 = signal.sosfilt(sos, mv - mv[0]) ** 2
    sat = (mv <= c["sat_low_mv"]) | (mv >= c["sat_high_mv"])
    W, H = c["window_samples"], c["hop_samples"]
    csum = np.concatenate([[0.0], np.cumsum(y2)])
    satsum = np.concatenate([[0], np.cumsum(sat)])

    phase, left, baseline = "settle", c["settle_samples"], 0.0
    hops, events = [], []
    last_rms, last_norm, last_level, have = 0.0, 0.0, -1, False
    att_start = 0
    n = 0
    total = len(mv)
    while n < total:
        # Advance to the next event: end of the current calibration phase or the next hop.
        next_hop = max(W, (n // H + 1) * H)
        phase_end = n + left if phase != "idle" else total + 1
        step_to = min(next_hop, phase_end, total)
        n_new = step_to
        left -= (n_new - n) if phase != "idle" else 0
        n = n_new
        if phase != "idle" and left == 0:
            if phase in ("settle", "wait"):
                phase, left, att_start = "collect", c["cal_samples"], n
            elif phase == "collect":
                seg = slice(att_start, n)
                good = ~sat[seg]
                count = int(good.sum())
                rms = np.sqrt(y2[seg][good].mean()) if count else 0.0
                chunks = []
                for k in range(att_start, n, c["cal_chunk_samples"]):
                    g = ~sat[k:k + c["cal_chunk_samples"]]
                    if g.sum() >= c["cal_chunk_min"]:
                        chunks.append(np.sqrt(y2[k:k + c["cal_chunk_samples"]][g].mean()))
                chunks = np.array(chunks)
                cv = chunks.std() / chunks.mean() if len(chunks) > 1 and chunks.mean() > 0 else np.inf
                if count < c["cal_min_valid"]:
                    result = 2
                elif rms >= c["cal_max_baseline_mv"]:
                    result = 3
                elif not cv < max_cv:
                    result = 4
                else:
                    result = 1
                events.append((n - 1, result, count / c["cal_samples"], cv, rms))
                if result == 1:
                    baseline, phase = rms, "idle"
                else:
                    phase, left = "wait", c["cal_retry_samples"]
        if n >= W and n % H == 0 and n == step_to:
            calibrating = phase in ("settle", "collect")
            s = satsum[n] - satsum[n - W] > 0
            if not s:
                last_rms = np.sqrt((csum[n] - csum[n - W]) / W)
                if baseline > 0 and not calibrating:
                    last_norm = last_rms / baseline
                    last_level = next_level(last_level, last_norm, c)
                else:
                    last_norm, last_level = 0.0, -1
                have = True
            elif calibrating or baseline <= 0:
                last_norm, last_level = 0.0, -1
            hops.append((n - 1, last_rms if have else 0.0, last_norm, last_level, int(s), int(calibrating), baseline))
    return np.array(hops), events


def run_c(log, max_cv=None):
    """Run the host test; with max_cv, a copy built with -DEMG_CAL_MAX_CV=<max_cv>f."""
    subprocess.run(["make", "-s", "-C", str(HOST_DIR)], check=True)
    exe = HOST_DIR / "emg_host"
    if max_cv is not None:
        exe = HOST_DIR / "emg_host_cv"
        subprocess.run(["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-I../components/emg_dsp/include",
                        f"-DEMG_CAL_MAX_CV={max_cv}f", "-o", exe.name, "main.c", "../components/emg_dsp/emg_dsp.c",
                        "-lm"], check=True, cwd=HOST_DIR)
    res = subprocess.run([str(exe), str(EMG_DIR / log)], check=True, capture_output=True, text=True)
    events = re.findall(r"attempt (\d+): ([^(]+) \(valid ([\d.]+) %, cv ([\d.]+|inf), rms ([\d.]+) mV\)", res.stderr)
    return np.loadtxt(io.StringIO(res.stdout), delimiter=",", skiprows=1), events


def offline_normalized(mv, offset, baseline, c):
    """Zero-phase counterpart: experiment 06's FFT filters and a centred 200 ms RMS (recording time)."""
    core = notched(mv, CORE)
    k = np.ones(c["window_samples"]) / c["window_samples"]
    rms = np.sqrt(np.convolve(core ** 2, k, mode="same"))
    t = np.arange(len(mv)) / 1000 - offset
    return t, rms / baseline if baseline > 0 else rms * 0


EXPECTED = {"relax": 0, "light": 1, "chord": 1, "hard": 2}


def phase_table(rec, t, level, sat):
    """Rows per phase analysis window and totals (correct, total) per kind (unsaturated hops only)."""
    rows, totals, counts = [], {}, {}
    for start, end, kind in rec["phases"]:
        counts[kind] = counts.get(kind, 0) + 1
        w = (t - 0.2 >= start + SKIP_S) & (t < end)
        ok = w & ~sat
        lv = level[ok]
        dist = " / ".join(str(int((lv == k).sum())) for k in (0, 1, 2, -1))
        correct = int((lv == EXPECTED[kind]).sum())
        rows.append(f"| {kind} {counts[kind]} | {start + SKIP_S:g}-{end:g} | {ok.sum()} | {EXPECTED[kind]} | {dist} | "
                    f"{correct}/{ok.sum()} | {int((w & sat).sum())} |")
        group = "relax" if kind == "relax" else ("medium" if kind in ("light", "chord") else "hard")
        a, b = totals.get(group, (0, 0))
        totals[group] = (a + correct, b + int(ok.sum()))
    return rows, totals


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tension07")
    out_dir.mkdir(parents=True, exist_ok=True)
    style.apply()
    c = constants()
    report = [f"Constants from emg_dsp.h: {c}", ""]
    summary = {}

    fig, axes = plt.subplots(4, 1, figsize=(style.WIDTH_IN, 7.2), gridspec_kw={"hspace": 0.55,
                             "height_ratios": [1.6, 0.7, 1.6, 0.7]})
    for seg_i, name in enumerate(("A", "B")):
        rec = RECORDINGS[name]
        mv, offset = load_run(rec["file"])
        c_out, c_events = run_c(rec["file"])
        ref, ref_events = reference(mv, c)

        # --- 1. C vs Python reference ---
        assert c_out.shape[0] == ref.shape[0] and np.all(c_out[:, 0] == ref[:, 0]), "hop indices differ"
        d_rms = np.abs(c_out[:, 1] - ref[:, 1])
        d_norm = np.abs(c_out[:, 2] - ref[:, 2])
        rel = d_rms / np.maximum(ref[:, 1], 1e-9)
        report += [f"== {name} ({rec['file']}): {len(mv)} samples, {len(ref)} hops, board time offset {offset:.3f} s",
                   "calibration attempts C:   " + "; ".join(f"#{a} {r.strip()} cv {cv} rms {m}" for a, r, v, cv, m in c_events),
                   "calibration attempts ref: " + "; ".join(f"t={e[0] / 1000:.2f} result {e[1]} cv {e[3]:.3f} rms {e[4]:.3f}"
                                                         for e in ref_events),
                   f"max |RMS diff| {d_rms.max():.3e} mV (max relative {rel.max():.3e}); "
                   f"max |normalized diff| {d_norm.max():.3e}; max |baseline diff| {np.abs(c_out[:, 6] - ref[:, 6]).max():.3e} mV",
                   f"level mismatches {int((c_out[:, 3] != ref[:, 3]).sum())}, saturated mismatches "
                   f"{int((c_out[:, 4] != ref[:, 4]).sum())}, calibrating mismatches {int((c_out[:, 5] != ref[:, 5]).sum())}"]

        t = c_out[:, 0] / 1000 - offset          # recording time of the window's last sample
        norm, level, sat = c_out[:, 2], c_out[:, 3].astype(int), c_out[:, 4].astype(bool)
        baseline = c_out[-1, 6]

        # --- 3. level per phase analysis window ---
        report.append("| phase | window (s) | unsaturated hops | expected | level 0 / 1 / 2 / -1 | correct | saturated hops |")
        report.append("|---|---|---|---|---|---|---|")
        rows, totals = phase_table(rec, t, level, sat)
        report += rows
        summary[name] = totals
        for cv in (0.3,):
            c_cv, ev_cv = run_c(rec["file"], max_cv=cv)
            _, tot_cv = phase_table(rec, c_cv[:, 0] / 1000 - offset, c_cv[:, 3].astype(int), c_cv[:, 4].astype(bool))
            report.append(f"with EMG_CAL_MAX_CV={cv}: attempts " + "; ".join(f"#{a} {r.strip()} (cv {cv_})"
                                                                            for a, r, v, cv_, m in ev_cv)
                          + " | correct " + ", ".join(f"{k} {a}/{b}" for k, (a, b) in tot_cv.items()))

        # --- 4. algorithm delay vs zero-phase offline metric (onset and release, level 1 crossing) ---
        t_off, n_off = offline_normalized(mv, offset, baseline, c)
        report.append("| effort | offline crosses 1.49x up (s) | causal level >=1 (s) | delay (ms) | "
                      "offline last above 1.35x (s) | causal back to 0 (s) | delay (ms) |")
        report.append("|---|---|---|---|---|---|---|")
        counts = {}
        for start, end, kind in rec["phases"]:
            if kind == "relax":
                continue
            counts[kind] = counts.get(kind, 0) + 1
            span = (t_off >= start) & (t_off < end + 3)
            above = span & (n_off >= c["level1_enter"])
            hop_span = (t >= start) & (t < end + 3) & ~sat
            hop_up = hop_span & (level >= 1)
            if not above.any() or not hop_up.any():
                report.append(f"| {kind} {counts[kind]} | - | - | - | - | - | - |")
                continue
            on_off, on_c = t_off[above][0], t[hop_up][0]
            last_off = t_off[span & (n_off >= c["level1_exit"])][-1]
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
        for r in (c["level1_enter"], c["level2_enter"]):
            style.ref_line(ax, r)
        for r in (c["level1_exit"], c["level2_exit"]):
            style.ref_line(ax, r, linestyle=":")
        ax.set_ylim(0, max(8, np.nanpercentile(norm, 99.5) * 1.1))
        ax.set_ylabel("RMS / baseline")
        ax.set_title(f"{rec['title']} (baseline {baseline:.2f} mV)", loc="left")
        ax.legend(loc="upper right", ncol=3)
        lax.step(t, level, where="post", color=style.RAW, linewidth=0.8)
        lax.set_yticks([-1, 0, 1, 2])
        lax.set_yticklabels(["cal", "relax", "medium", "hard"])
        lax.set_ylim(-1.5, 2.5)
        style.panel_label(ax, "ac"[seg_i])
        style.panel_label(lax, "bd"[seg_i])
    axes[-1].set_xlabel("Time since start of recording (s)")
    fig.savefig(out_dir / "tension07_validation.png", dpi=style.DPI, bbox_inches="tight")
    plt.close(fig)

    report.append("Correct share per group (unsaturated hops in the analysis windows):")
    for name, totals in summary.items():
        report.append(f"  {name}: " + ", ".join(f"{k} {a}/{b} ({100 * a / b:.1f} %)" for k, (a, b) in totals.items()))
    text = "\n".join(report)
    (out_dir / "summary.md").write_text(text + "\n")
    print(text)
    print(f"wrote {out_dir / 'tension07_validation.png'}")


if __name__ == "__main__":
    main()
