"""Summarise a bridge session log (sessions/*.jsonl) as JSON.

    .venv/bin/python tools/session_summary.py [SESSION.jsonl] [--out summary.json]

Without a path, the newest file in sessions/ is used. Each device message stands for 50 ms
(one DSP hop). Per device boot (a restart starts a new segment) and in total:
  - duration, messages, lost messages (from seq), calibrating and saturated time
  - time share per level (relax / medium / hard / none), level changes, entries into hard
  - longest continuous hard and medium-or-hard periods
  - normalized tension: mean, 90th percentile, max (calibrated, unsaturated messages only)
  - calibration attempts and their results
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOP_S = 0.05
LEVELS = {-1: "none", 0: "relax", 1: "medium", 2: "hard"}


def load(path):
    msgs = []
    for line in Path(path).read_text().splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("type") == "emg" and m.get("v") == 1:
            msgs.append(m)
    return msgs


def longest_run(levels, wanted):
    best = run = 0
    for lv in levels:
        run = run + 1 if lv in wanted else 0
        best = max(best, run)
    return round(best * HOP_S, 2)


def percentile(values, q):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q / 100 * (len(s) - 1)))))
    return round(s[k], 3)


def summarise(msgs):
    """Summary of one segment (messages of one boot, in arrival order)."""
    msgs = sorted(msgs, key=lambda m: m["seq"])
    seqs = [m["seq"] for m in msgs]
    lost = (seqs[-1] - seqs[0] + 1 - len(set(seqs))) if seqs else 0
    levels = [m["level"] for m in msgs]
    valid = [m for m in msgs if m["level"] >= 0 and not m["saturated"]]
    shown = [lv for lv in levels if lv >= 0]
    changes = sum(1 for a, b in zip(shown, shown[1:]) if a != b)
    hard_entries = sum(1 for a, b in zip(shown, shown[1:]) if b == 2 and a != 2)
    sat_runs = sum(1 for a, b in zip([False] + [m["saturated"] for m in msgs], [m["saturated"] for m in msgs])
                   if b and not a)
    calibrations = [dict(m["cal"], at_s=round(m["sample_index"] / 1000, 2)) for m in msgs if "cal" in m]
    n = len(msgs)
    return {
        "messages": n,
        "duration_s": round(n * HOP_S, 2),
        "lost_messages": lost,
        "loss_rate": round(lost / (n + lost), 4) if n + lost else 0.0,
        "calibrating_s": round(sum(m["calibrating"] for m in msgs) * HOP_S, 2),
        "saturated_s": round(sum(m["saturated"] for m in msgs) * HOP_S, 2),
        "saturated_episodes": sat_runs,
        "level_time_s": {name: round(levels.count(lv) * HOP_S, 2) for lv, name in LEVELS.items()},
        "level_share": {name: round(levels.count(lv) / n, 4) if n else 0.0 for lv, name in LEVELS.items()},
        "level_changes": changes,
        "hard_entries": hard_entries,
        "longest_hard_s": longest_run(levels, {2}),
        "longest_medium_or_hard_s": longest_run(levels, {1, 2}),
        "norm": {
            "mean": round(sum(m["norm"] for m in valid) / len(valid), 3) if valid else None,
            "p90": percentile([m["norm"] for m in valid], 90),
            "max": round(max(m["norm"] for m in valid), 3) if valid else None,
        },
        "baseline_mV": msgs[-1]["baseline_mV"] if msgs else None,
        "calibrations": calibrations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session", nargs="?", help="session JSONL (default: newest in sessions/)")
    parser.add_argument("--out", help="write the JSON here instead of stdout")
    args = parser.parse_args()
    path = Path(args.session) if args.session else max((REPO / "sessions").glob("*.jsonl"), default=None,
                                                         key=lambda p: p.stat().st_mtime)
    if path is None or not path.exists():
        sys.exit("no session log found (run bridge/bridge.py first)")
    msgs = load(path)
    if not msgs:
        sys.exit(f"{path}: no device messages")

    segments, order = {}, []
    for m in msgs:                       # one segment per (sender, boot)
        key = (m.get("src", "").split(":")[0], m["boot"])
        if key not in segments:
            segments[key] = []
            order.append(key)
        segments[key].append(m)
    seg_summaries = []
    for key in order:
        s = summarise(segments[key])
        s.update(device=segments[key][0]["dev"], boot=key[1])
        seg_summaries.append(s)
    total = summarise(msgs) if len(order) == 1 else None
    rx = [m["bridge_rx_ms"] for m in msgs if "bridge_rx_ms" in m]
    summary = {
        "session": path.name,
        "protocol": 1,
        "hop_s": HOP_S,
        "start_ms": min(rx) if rx else None,
        "end_ms": max(rx) if rx else None,
        "devices": sorted({m["dev"] for m in msgs}),
        "restarts": len(order) - 1,
        "segments": seg_summaries,
        "total": total or {
            "messages": len(msgs),
            "duration_s": round(len(msgs) * HOP_S, 2),
            "level_share": {name: round(sum(1 for m in msgs if m["level"] == lv) / len(msgs), 4)
                            for lv, name in LEVELS.items()},
            "lost_messages": sum(s["lost_messages"] for s in seg_summaries),
            "saturated_s": round(sum(s["saturated_s"] for s in seg_summaries), 2),
            "longest_hard_s": max(s["longest_hard_s"] for s in seg_summaries),
        },
        "notes": "Levels use provisional thresholds (1.49x/1.35x medium, 2.72x/2.45x hard of the relax "
                 "baseline). One message = 50 ms.",
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
