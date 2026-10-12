"""Shared helpers for experiment 06 (forearm EMG): loading the 1 kHz stream, filters, spectra.

The captures are record_serial.py logs of firmware/experiments/06_raw_emg_stream:
"<host seconds>\\t<sample index>,<mV>" per sample. Only numpy is used: band-pass and
mains notches are zero-phase FFT masks, and the PSD is a plain Welch estimate.
"""
import re
from pathlib import Path

import numpy as np

from data import DATA_DIR

EMG_DIR = DATA_DIR / "06_forearm_emg"

FS = 1000
SATURATION_MV = 3108                  # largest calibrated reading (12 dB attenuation)
SAT_LOW_MV, SAT_HIGH_MV = 5, 3100     # a reading at or beyond these counts as saturated
BAND = (20, 450)                      # conventional surface-EMG band
CORE = (45, 200)                      # main metric: above most motion artefact, below the flat noise floor
MAINS_HZ = 60
NOTCH_HALF_HZ = 2.0
RMS_WINDOW_S = 0.1
WELCH_N = 512
SKIP_S = 1.5                          # skipped after every cue (grip onset/release lagged the cue by 1-1.65 s)

# Phases as (start s, end s, kind). The first relax cue was spoken at 0.5 s in every recording.
RECORDINGS = {
    "first": dict(file="01_first_attempt.log", duration=60,
                  title="First attempt: hand on the table, grip hand not confirmed",
                  phases=[(0.5, 10, "relax"), (10, 15, "light"), (15, 25, "relax"), (25, 30, "hard"),
                          (30, 40, "relax"), (40, 50, "chord"), (50, 60, "relax")]),
    "retest": dict(file="02_retest_hard.log", duration=60,
                   title="Retest: left hand, hand free over the table edge",
                   phases=[(0.5, 10, "relax"), (10, 15, "hard"), (15, 25, "relax"), (25, 30, "hard"),
                           (30, 40, "relax"), (40, 45, "hard"), (45, 60, "relax")]),
    "A": dict(file="03_A_light_hard.log", duration=70,
              title="A: left hand free over the table edge",
              phases=[(0.5, 10, "relax"), (10, 15, "light"), (15, 25, "relax"), (25, 30, "hard"),
                      (30, 40, "relax"), (40, 45, "light"), (45, 55, "relax"), (55, 60, "hard"),
                      (60, 70, "relax")]),
    "B": dict(file="04_B_chord.log", duration=60,
              title="B: holding the guitar (relax = fingers resting on the strings)",
              phases=[(0.5, 10, "relax"), (10, 15, "chord"), (15, 25, "relax"), (25, 30, "chord"),
                      (30, 40, "relax"), (40, 45, "chord"), (45, 60, "relax")]),
}


def load(log, duration_s=60):
    """Samples of the newest board run, on the recording's time axis: (t_s, mv).

    log is a file name inside docs/data/06_forearm_emg/ or a path. Lines buffered on the
    board before the recording started arrive together near t = 0, so time comes from
    the sample index (the ADC clock). Its offset to the recording clock is taken from
    lines that arrived live (smallest transfer delay).
    """
    path = Path(log) if Path(log).is_absolute() else EMG_DIR / log
    rows = []
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([\d.]+)\t(\d+),(\d+)$", line)
        if m:
            rows.append((float(m.group(1)), int(m.group(2)), int(m.group(3))))
    host, idx, mv = (np.array(c, dtype=float) for c in zip(*rows))
    restart = np.flatnonzero(np.diff(idx) < 0)
    if restart.size:                           # keep only the run after the last board restart
        host, idx, mv = host[restart[-1] + 1:], idx[restart[-1] + 1:], mv[restart[-1] + 1:]
    assert np.all(np.diff(idx) == 1), "sample indices are not continuous"
    live = host > 1
    offset = (idx[live] / FS - host[live]).max()
    t = idx / FS - offset
    keep = (t >= 0) & (t < duration_s)
    return t[keep], mv[keep]


def load_recording(name):
    rec = RECORDINGS[name]
    return load(rec["file"], rec["duration"])


def bandpass(x, low, high, ramp=2.0):
    """Zero-phase FFT band-pass with raised-cosine edges of +/- ramp Hz."""
    f = np.fft.rfftfreq(x.size, 1 / FS)

    def edge(f0):
        return np.clip((f - (f0 - ramp)) / (2 * ramp), 0, 1)

    gain = 0.5 - 0.5 * np.cos(np.pi * edge(low))
    gain *= 0.5 + 0.5 * np.cos(np.pi * edge(high))
    return np.fft.irfft(np.fft.rfft(x - x.mean()) * gain, n=x.size)


def notched(x, band=CORE):
    """Band-pass with every 60 Hz mains harmonic (+/- 2 Hz) removed as well."""
    f = np.fft.rfftfreq(x.size, 1 / FS)
    spec = np.fft.rfft(bandpass(x, *band))
    for h in range(MAINS_HZ, FS // 2, MAINS_HZ):
        spec[np.abs(f - h) <= NOTCH_HALF_HZ] = 0
    return np.fft.irfft(spec, n=x.size)


def moving_rms(x, window_s=RMS_WINDOW_S):
    n = int(window_s * FS)
    return np.sqrt(np.convolve(x ** 2, np.ones(n) / n, mode="same"))


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)))


def window(t, start, end, skip=SKIP_S):
    return (t >= start + skip) & (t < end)


def welch(segments):
    """Welch PSD in mV^2/Hz, averaged over every 50 %-overlapped Hann segment: (f, psd, n_segments)."""
    win = np.hanning(WELCH_N)
    scale = 1 / (FS * (win ** 2).sum())
    acc, count = 0, 0
    for x in segments:
        for s in range(0, x.size - WELCH_N + 1, WELCH_N // 2):
            seg = x[s:s + WELCH_N]
            spec = np.abs(np.fft.rfft((seg - seg.mean()) * win)) ** 2 * scale
            spec[1:-1] *= 2
            acc, count = acc + spec, count + 1
    return np.fft.rfftfreq(WELCH_N, 1 / FS), acc / count, count


def band_power(f, p, lo, hi, exclude_mains=False):
    sel = (f >= lo) & (f < hi)
    if exclude_mains:
        for h in range(MAINS_HZ, hi + MAINS_HZ, MAINS_HZ):
            sel &= np.abs(f - h) > 3
    return p[sel].sum() * (f[1] - f[0])


def saturated(mv):
    return (mv <= SAT_LOW_MV) | (mv >= SAT_HIGH_MV)


def efforts(name, skip=SKIP_S):
    """Per-phase statistics of one recording.

    Returns (relax, active): lists of dicts. Each active phase is compared with the relax
    phases right before and after it. 'core' is the main metric (45-200 Hz, mains notched),
    'plain' the 20-450 Hz band-pass without notches.
    """
    rec = RECORDINGS[name]
    t, mv = load_recording(name)
    core, plain = notched(mv, CORE), bandpass(mv, *BAND)
    sat = saturated(mv)
    phases = rec["phases"]
    relax, active, counts = [], [], {}
    for i, (start, end, kind) in enumerate(phases):
        w = window(t, start, end, skip)
        item = dict(recording=name, kind=kind, start=start, end=end, n=int(w.sum()),
                    rms_core=rms(core[w]), rms_plain=rms(plain[w]), saturated=int(sat[w].sum()))
        if kind == "relax":
            relax.append(item)
            continue
        counts[kind] = counts.get(kind, 0) + 1
        nb = window(t, *phases[i - 1][:2], skip) | window(t, *phases[i + 1][:2], skip)
        item.update(number=counts[kind], ratio_core=item["rms_core"] / rms(core[nb]),
                    ratio_plain=item["rms_plain"] / rms(plain[nb]))
        active.append(item)
    return relax, active
