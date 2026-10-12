"""README animation: replay of experiment 06, segment A (light and hard grips) then segment B (G chord).

Three tracks (raw ADC reading, 45-200 Hz with mains removed, its RMS envelope), each
coloured by cued phase, and a
"Tension" bar. The bar's levels are set per segment, relative to that segment's own relax
RMS, using effort/relax ratios measured in experiment 06. The first GIF frame is the
finished picture of B; the replay runs A, pauses, then runs B at 4x speed and ends on
that first picture.
"""
import numpy as np
import matplotlib.pyplot as plt

import style
from emg import CORE, RECORDINGS, efforts, load_recording, moving_rms, notched, rms, saturated, window
from plot_06_forearm_emg import phase_spans

FPS = 10                 # GIF frame times are stored in 10 ms units, so keep 1000/FPS whole
SPEED = 4
HOLD_MS = 1500           # first (= final) frame
PAUSE_MS = 1000          # between segment A and segment B
BAR_WINDOW_S = 0.5       # the bar uses a slower RMS than the 100 ms envelope so it does not flicker
SEGMENTS = [("A", "Segment A: left hand free over the table edge, light and hard grips"),
            ("B", "Segment B: holding the guitar, G chord")]
KIND_COLOR = {"relax": style.GRAY, "light": style.TEAL, "chord": style.BLUE, "hard": style.RED}
LEVEL_COLOR = {"relax": style.GRAY, "medium": style.BLUE, "hard": style.RED}


def level_factors():
    """Level splits as multiples of a segment's relax RMS.

    medium starts halfway between relax (1x) and the weakest medium effort; hard starts
    halfway between the strongest medium effort and the weakest hard effort. Ratios are the
    main metric vs neighbouring relax, from the retest, A and B; saturated windows excluded.
    """
    ratios = {"medium": [], "hard": []}
    for name in ("retest", "A", "B"):
        for a in efforts(name)[1]:
            if a["saturated"] == 0:
                ratios["hard" if a["kind"] == "hard" else "medium"].append(a["ratio_core"])
    low = (1 + min(ratios["medium"])) / 2
    high = (max(ratios["medium"]) + min(ratios["hard"])) / 2
    return low, high


def prepare(name, k_low, k_high):
    rec = RECORDINGS[name]
    t, mv = load_recording(name)
    core = notched(mv, CORE)
    relax = np.zeros_like(t, dtype=bool)
    for start, end, kind in rec["phases"]:
        if kind == "relax":
            relax |= window(t, start, end)
    base = rms(core[relax])
    sat = saturated(mv)
    sat_span = (t[sat][0], t[sat][-1]) if sat.any() else None
    return dict(name=name, rec=rec, t=t, mv=mv, core=core, env=moving_rms(core),
                bar=moving_rms(core, BAR_WINDOW_S), base=base, low=k_low * base, high=k_high * base,
                sat_span=sat_span)


def level_of(value, seg):
    return "relax" if value < seg["low"] else ("medium" if value < seg["high"] else "hard")


class Replay:
    def __init__(self, fig, k_low, k_high):
        self.fig, self.k_low, self.k_high = fig, k_low, k_high

    def build(self, seg, subtitle):
        fig = self.fig
        fig.clear()
        rec, t, mv, core, env = seg["rec"], seg["t"], seg["mv"], seg["core"], seg["env"]
        duration = rec["duration"]
        left, width, top, height, gap = 0.09, 0.70, 0.845, 0.175, 0.07
        axes = [fig.add_axes([left, top - (i + 1) * height - i * gap, width, height]) for i in range(3)]
        bar_ax = fig.add_axes([0.85, top - 3 * height - 2 * gap, 0.035, 3 * height + 2 * gap])

        core_lim = np.percentile(np.abs(core), 99.95) * 1.4
        tracks = [
            (mv, "Raw ADC reading", (min(mv.min(), 1000) - 80, max(mv.max(), 2200) + 80), 0.3),
            (core, f"{CORE[0]}-{CORE[1]} Hz, 60 Hz harmonics removed", (-core_lim, core_lim), 0.3),
            (env, "Envelope (100 ms RMS)", (0, np.percentile(env, 99.95) * 1.3), 0.7),
        ]
        self.lines = []
        counts = {}
        labels = []
        for start, end, kind in rec["phases"]:
            if kind != "relax":
                counts[kind] = counts.get(kind, 0) + 1
                labels.append((start, end, kind, f"{kind} {counts[kind]}"))
        spans = phase_spans(t, rec["phases"])
        for ax, (y, title, ylim, lw) in zip(axes, tracks):
            for start, end, kind, label in labels:
                style.shade(ax, start, end, KIND_COLOR[kind])
                if ax is axes[0]:
                    ax.text((start + end) / 2, ylim[1], label, ha="center", va="bottom", fontsize=style.TICK_PT,
                            color=KIND_COLOR[kind])
            if seg["sat_span"]:
                ax.axvspan(*seg["sat_span"], facecolor="none", edgecolor=style.REF_COLOR, hatch="////",
                           linewidth=0, zorder=1)
                if ax is axes[0]:
                    ax.text(seg["sat_span"][1] + 0.5, ylim[0] + 0.12 * (ylim[1] - ylim[0]), "saturated",
                            fontsize=style.TICK_PT, color=style.REF_COLOR, ha="left", va="center")
            # One line per phase, coloured like the phase (relax gray, light teal, chord blue, hard red).
            for i0, i1, kind in spans:
                line, = ax.plot([], [], color=KIND_COLOR[kind], linewidth=lw, zorder=3)
                self.lines.append((line, y, i0, i1))
            ax.set_xlim(0, duration)
            ax.set_ylim(*ylim)
            ax.set_ylabel("mV")
            ax.set_title(title, loc="left", pad=12 if ax is axes[0] else 3)
            if ax is not axes[-1]:
                ax.tick_params(labelbottom=False)
        for value in (seg["low"], seg["high"]):
            style.ref_line(axes[2], value, zorder=2)
        axes[-1].set_xlabel("Time since start of recording (s)")
        self.cursors = [ax.axvline(0, color=style.BLUE, linewidth=0.8, alpha=0.6, zorder=4) for ax in axes]

        # Tension bar: level bands, current value, horizontal level names to the right.
        bar_top = max(np.percentile(seg["bar"], 99.9) * 1.15, seg["high"] * 1.6)
        for level, lo, hi in (("relax", 0, seg["low"]), ("medium", seg["low"], seg["high"]),
                              ("hard", seg["high"], bar_top)):
            bar_ax.axhspan(lo, hi, color=LEVEL_COLOR[level], alpha=style.SHADE_ALPHA, linewidth=0)
            bar_ax.text(1.25, (lo + hi) / 2, level, transform=bar_ax.get_yaxis_transform(), ha="left",
                        va="center", fontsize=style.TICK_PT, color=LEVEL_COLOR[level])
        self.bar_patch = bar_ax.bar([0], [0], width=0.8, color=LEVEL_COLOR["relax"])[0]
        bar_ax.set_xlim(-0.5, 0.5)
        bar_ax.set_ylim(0, bar_top)
        bar_ax.set_xticks([])
        bar_ax.set_ylabel("mV")
        bar_ax.set_title("Tension", pad=4)
        self.bar_value = bar_ax.text(0.5, -0.03, "", transform=bar_ax.transAxes, ha="center", va="top",
                                     fontsize=style.TICK_PT)

        fig.text(left, 0.965, "Forearm EMG through the AD8232 (experiment 06)", fontsize=style.LABEL_PT + 1,
                 fontweight="bold", va="top")
        fig.text(left, 0.93, subtitle, fontsize=style.LABEL_PT, color=style.REF_COLOR, va="top")
        self.clock = fig.text(0.97, 0.965, "", ha="right", va="top", fontsize=style.LABEL_PT, fontweight="bold")
        fig.text(0.97, 0.93, f"Playback {SPEED}x", ha="right", va="top", fontsize=style.TICK_PT,
                 color=style.REF_COLOR)
        fig.text(0.01, 0.038,
                 f"Tension bar: {BAR_WINDOW_S * 1000:.0f} ms RMS. Levels relative to this segment's relax RMS "
                 f"({seg['base']:.1f} mV): medium from {self.k_low:.2f}x ({seg['low']:.1f} mV), "
                 f"hard from {self.k_high:.2f}x ({seg['high']:.1f} mV);\nthe factors lie halfway between the "
                 "effort/relax ratios measured in experiment 06. Dashed lines in the envelope: the same levels.",
                 fontsize=style.TICK_PT, color=style.REF_COLOR, ha="left", va="bottom", linespacing=1.3)
        fig.text(0.01, 0.008, "Real data · 1 kHz · mains removed · single subject", fontsize=style.TICK_PT,
                 color=style.REF_COLOR, ha="left", va="bottom")
        self.seg = seg

    def render(self, t_now):
        seg = self.seg
        t = seg["t"]
        shown = t <= t_now
        n = int(shown.sum())
        for line, y, i0, i1 in self.lines:
            end = min(i1, n)
            line.set_data(t[i0:end], y[i0:end]) if end > i0 else line.set_data([], [])
        for c in self.cursors:
            c.set_xdata([t_now, t_now])
            c.set_visible(t_now < seg["rec"]["duration"] - 0.05)
        value = seg["bar"][shown][-1] if shown.any() else 0.0
        level = level_of(value, seg)
        self.bar_patch.set_height(value)
        self.bar_patch.set_color(LEVEL_COLOR[level])
        self.bar_value.set_text(f"{value:.1f} mV\n{level}")
        self.bar_value.set_color(LEVEL_COLOR[level])
        self.clock.set_text(f"t = {t_now:4.1f} s")
        return style.fig_to_image(self.fig)


def main():
    style.apply()
    k_low, k_high = level_factors()
    fig = plt.figure(figsize=(style.WIDTH_IN, style.WIDTH_IN * 0.9), dpi=style.GIF_DPI)
    replay = Replay(fig, k_low, k_high)

    clips = []
    for name, subtitle in SEGMENTS:
        seg = prepare(name, k_low, k_high)
        replay.build(seg, subtitle)
        duration = seg["rec"]["duration"]
        n = int(duration / SPEED * FPS)
        clips.append([replay.render(duration * k / n) for k in range(1, n + 1)])
        print(f"{name}: relax RMS {seg['base']:.2f} mV, levels {seg['low']:.2f} / {seg['high']:.2f} mV "
              f"({k_low:.3f}x / {k_high:.3f}x)")
    plt.close(fig)

    a_frames, b_frames = clips
    frames = [b_frames[-1]] + a_frames + b_frames                      # first frame: finished picture of B
    durations = [HOLD_MS] + [1000 // FPS] * (len(a_frames) - 1) + [PAUSE_MS] + [1000 // FPS] * len(b_frames)
    style.save_gif(frames, durations, "06_emg_replay.gif", colors=192)


if __name__ == "__main__":
    main()
