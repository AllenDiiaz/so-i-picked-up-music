#!/usr/bin/env bash
# Coach loop without hardware: simulated device + bridge + static web server.
#
#   scripts/run_coach_demo.sh                 mock coach, designed mode
#   LLM=ollama scripts/run_coach_demo.sh      local Ollama model (llama3.2:3b; MODEL=... to change)
#   MODE=naive scripts/run_coach_demo.sh      the sampler waits for the coach (counter-example)
#
# Open the printed URL. Space (in the page) or Enter (here) starts and ends a segment.
# The device is SIMULATED: tools/fake_device.py plays an experiment 06 recording through the
# firmware's C code; its timing numbers come from a model. Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

LOG="${LOG:-03_A_light_hard.log}"
MODE="${MODE:-designed}"
LLM="${LLM:-mock}"
MODEL="${MODEL:-llama3.2:3b}"
HTTP_PORT="${HTTP_PORT:-8000}"
LINK="${TMPDIR:-/tmp}/fake_emg"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "missing .venv: python3 -m venv .venv && .venv/bin/pip install -r analysis/requirements.txt"; exit 1; }

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; wait 2>/dev/null || true; echo "demo stopped"; }
trap cleanup EXIT INT TERM

"$PY" tools/fake_device.py --log "$LOG" --mode "$MODE" --loop --link "$LINK" & pids+=($!)
"$PY" -m http.server "$HTTP_PORT" --bind 127.0.0.1 --directory web >/dev/null 2>&1 & pids+=($!)
sleep 1.5
echo
echo "  Open http://localhost:${HTTP_PORT}/   (space: segment start / end, m: designed / naive, f: sync flash)"
echo "  Simulated device, mode ${MODE}, coach ${LLM}. Ctrl-C to stop."
echo
"$PY" bridge/bridge.py --serial "$LINK" --llm "$LLM" --model "$MODEL"
