#!/usr/bin/env bash
# One-command demo without hardware: bridge + static web server + looping replay.
#
#   scripts/run_replay_demo.sh [LOG] [SPEED]      e.g. scripts/run_replay_demo.sh 04_B_chord.log 1
#
# LOG: a file in docs/data/06_forearm_emg/ (default 03_A_light_hard.log); SPEED: 1 = real time.
# Open the printed URL; Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="${1:-03_A_light_hard.log}"
SPEED="${2:-1}"
HTTP_PORT="${HTTP_PORT:-8000}"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "missing .venv: python3 -m venv .venv && .venv/bin/pip install -r analysis/requirements.txt"; exit 1; }

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; echo "demo stopped"; }
trap cleanup EXIT INT TERM

"$PY" bridge/bridge.py & pids+=($!)
"$PY" -m http.server "$HTTP_PORT" --bind 127.0.0.1 --directory web >/dev/null 2>&1 & pids+=($!)
sleep 1.5
"$PY" tools/replay_stream.py --log "$LOG" --speed "$SPEED" --loop --quiet & pids+=($!)

echo
echo "  Open http://localhost:${HTTP_PORT}/   (keys 1 / 2 / 3 switch the feedback design)"
echo "  Replaying ${LOG} at ${SPEED}x in a loop. Ctrl-C to stop."
echo
wait
