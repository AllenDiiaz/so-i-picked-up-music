"""Demo signal for the README GIF: two real segments of exp. 06 recording A (light grip, then hard grip),
spliced end to end. Same filters and thresholds as the firmware. Not synced to the guitar video."""
import sys
sys.path.insert(0, "/home/claude/allendiiaz/so-i-picked-up-music/analysis")
import numpy as np, emg
R = "A"; SEGS = [(39.0, 45.5), (54.0, 58.5)]
t, mv = emg.load_recording(R)
s1 = emg.notched(mv, band=(20, 450)); s2 = emg.notched(mv); env = emg.moving_rms(s2, 0.2)
relax = np.zeros_like(t, bool)
for a, b, k in emg.RECORDINGS[R]["phases"]:
    if k == "relax" and a > 14: relax |= emg.window(t, a, b)
base = emg.rms(s2[relax])
lvl = np.where(env >= 2.72 * base, 2, np.where(env >= 1.49 * base, 1, 0))
parts = {k: [] for k in ("t", "mv", "s1", "s2", "env", "lvl")}; off = 0.0; SPLICE = []
for a, b in SEGS:
    w = (t >= a) & (t < b)
    parts["t"].append(t[w] - a + off)
    for k, v in (("mv", mv), ("s1", s1), ("s2", s2), ("env", env), ("lvl", lvl)): parts[k].append(v[w])
    off += b - a; SPLICE.append(off)
DT, DMV, DS1, DS2, DENV, DLVL = (np.concatenate(parts[k]) for k in ("t", "mv", "s1", "s2", "env", "lvl"))
SPLICE = SPLICE[:-1]; DUR = off
def at(arr, tt): return arr[min(np.searchsorted(DT, tt), len(DT) - 1)]
if __name__ == "__main__":
    print("dur", DUR, "splice", SPLICE, "base", base)
    print("lvl frac", [round(float(np.mean(DLVL == k)), 2) for k in (0, 1, 2)])
    for p in (1, 50, 99, 99.9): print(p, [round(float(np.percentile(x, p)), 1) for x in (DMV, DS1, DS2, DENV)])
    print("".join(str(int(at(DLVL, x))) for x in np.arange(0, DUR, 0.25)))
