"""Build the "letter to my future self" prompt from a session summary (dry run: print only).

    .venv/bin/python tools/letter_prompt.py [SESSION.jsonl | SUMMARY.json] [--lang zh|en]

Without a path, the newest session in sessions/ is summarised first. The prompt is printed; no
language model is called and no API key is needed. A later step can send this text to a model.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

INSTRUCTIONS = {
    "zh": (
        "你是一位溫和、具體的吉他練習教練。請根據下面這次練習的肌肉緊繃數據,"
        "用第一人稱寫一封給「未來的自己」的短信(繁體中文,150–250 字)。\n"
        "要求:\n"
        "1. 只根據數據說話,引用一兩個具體數字(例如用力時間比例、最長連續用力秒數)。\n"
        "2. 指出一件做得好的事,和一件下次可以注意的事(例如按和弦時放鬆前臂)。\n"
        "3. 語氣鼓勵,不要誇大;不要做任何醫療或傷害相關的判斷。\n"
        "4. 提醒自己:等級門檻是暫定值,這只是單次練習的紀錄。\n"
    ),
    "en": (
        "You are a kind, concrete guitar practice coach. From the muscle-tension data of this practice "
        "session below, write a short letter (120-200 words) in the first person to my future self.\n"
        "Requirements:\n"
        "1. Stay with the data and quote one or two concrete numbers (for example the share of hard time "
        "or the longest continuous hard period).\n"
        "2. Name one thing that went well and one thing to watch next time (for example relaxing the "
        "forearm while holding chords).\n"
        "3. Be encouraging without exaggerating; make no medical or injury-related claims.\n"
        "4. Note that the level thresholds are provisional and this is a single session.\n"
    ),
}

LABELS = {
    "zh": {"duration": "練習時長", "relax": "放鬆", "medium": "中等", "hard": "用力", "none": "無等級(校正中/無基準)",
           "changes": "等級切換次數", "hard_entries": "進入用力的次數", "longest_hard": "最長連續用力",
           "longest_mh": "最長連續中等以上", "saturated": "訊號飽和時間", "norm": "緊繃倍數(相對放鬆基準)",
           "loss": "資料遺失率", "data": "練習數據"},
    "en": {"duration": "Duration", "relax": "relax", "medium": "medium", "hard": "hard",
           "none": "no level (calibrating / no baseline)", "changes": "Level changes",
           "hard_entries": "Entries into hard", "longest_hard": "Longest continuous hard",
           "longest_mh": "Longest continuous medium or hard", "saturated": "Saturated time",
           "norm": "Tension (multiple of the relax baseline)", "loss": "Data loss rate", "data": "Session data"},
}


def load_summary(path):
    if path and path.suffix == ".json":
        return json.loads(path.read_text())
    cmd = [sys.executable, str(REPO / "tools/session_summary.py")] + ([str(path)] if path else [])
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)


def describe(summary, lang):
    L = LABELS[lang]
    seg = summary["segments"][-1] if len(summary["segments"]) == 1 else None
    s = seg or summary["total"]
    share = s["level_share"]
    lines = [f"{L['data']} ({summary['session']}):",
             f"- {L['duration']}: {s['duration_s']:.0f} s",
             "- " + ", ".join(f"{L[k]} {100 * share[k]:.0f}%" for k in ("relax", "medium", "hard", "none"))]
    if seg:
        lines += [f"- {L['changes']}: {seg['level_changes']}; {L['hard_entries']}: {seg['hard_entries']}",
                  f"- {L['longest_hard']}: {seg['longest_hard_s']:.1f} s; {L['longest_mh']}: "
                  f"{seg['longest_medium_or_hard_s']:.1f} s",
                  f"- {L['norm']}: mean {seg['norm']['mean']}, p90 {seg['norm']['p90']}, max {seg['norm']['max']}",
                  f"- {L['saturated']}: {seg['saturated_s']:.1f} s; {L['loss']}: {100 * seg['loss_rate']:.2f}%"]
    else:
        lines.append(f"- {L['longest_hard']}: {s['longest_hard_s']:.1f} s; {L['saturated']}: {s['saturated_s']:.1f} s")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", type=Path, help="session JSONL or summary JSON (default: newest session)")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    summary = load_summary(args.path)
    print("=== DRY RUN: prompt only, no model is called ===\n")
    print(INSTRUCTIONS[args.lang])
    print(describe(summary, args.lang))


if __name__ == "__main__":
    main()
