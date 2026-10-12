"""End-to-end test without hardware: replay -> UDP -> bridge -> WebSocket -> checks.

    .venv/bin/python tests/test_e2e_replay.py        (also runs under pytest)

For segments A and B of experiment 06: starts the bridge on free ports, connects a WebSocket
client, replays the recording at 10x and checks that
  - every message is valid protocol v1 as forwarded by the bridge (docs/protocol.md),
  - seq starts at 0 and is continuous, nothing is lost,
  - sample_index and the level sequence equal the host test output of the 07 firmware DSP,
  - the bridge's session log holds every message.
"""
import asyncio
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))
from protocol import validate_bridge_message  # noqa: E402

PY = sys.executable
HOST_DIR = REPO / "firmware/experiments/07_onboard_tension/host_test"
LOGS = ["03_A_light_hard.log", "04_B_chord.log"]
SPEED = 10


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def host_reference(log):
    subprocess.run(["make", "-s", "-C", str(HOST_DIR)], check=True)
    res = subprocess.run([str(HOST_DIR / "emg_host"), str(REPO / "docs/data/06_forearm_emg" / log)],
                         check=True, capture_output=True, text=True)
    return np.loadtxt(io.StringIO(res.stdout), delimiter=",", skiprows=1)


async def run_one(log, sessions):
    udp, ws = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
    bridge = subprocess.Popen([PY, str(REPO / "bridge/bridge.py"), "--udp-host", "127.0.0.1", "--udp-port", str(udp),
                               "--ws-port", str(ws), "--sessions", str(sessions), "--quiet"],
                              stdout=subprocess.DEVNULL)
    try:
        for _ in range(50):                      # wait for the WebSocket server
            try:
                client = await connect(f"ws://localhost:{ws}")
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("bridge did not start")
        replay = subprocess.Popen([PY, str(REPO / "tools/replay_stream.py"), "--log", log, "--speed", str(SPEED),
                                   "--port", str(udp), "--quiet"], stdout=subprocess.DEVNULL)
        messages = []
        start = last_emg = time.monotonic()
        async with client:
            # Status messages arrive every second, so stop on "replay finished and no device
            # message for 2 s" rather than on a receive timeout.
            while not (replay.poll() is not None and time.monotonic() - last_emg > 2.0):
                if time.monotonic() - start > 300:
                    raise RuntimeError("timed out")
                try:
                    msg = json.loads(await asyncio.wait_for(client.recv(), timeout=0.5))
                except asyncio.TimeoutError:
                    continue
                validate_bridge_message(msg)
                if msg["type"] == "emg":
                    messages.append(msg)
                    last_emg = time.monotonic()
        replay.wait()
        return messages, time.monotonic() - start
    finally:
        bridge.terminate()
        bridge.wait()


def check(log, messages, sessions):
    ref = host_reference(log)
    seqs = [m["seq"] for m in messages]
    assert seqs == list(range(len(messages))), f"{log}: seq not continuous from 0"
    assert len({m["boot"] for m in messages}) == 1, f"{log}: more than one boot id"
    assert len(messages) == len(ref), f"{log}: {len(messages)} messages, host test has {len(ref)} hops"
    assert [m["sample_index"] for m in messages] == ref[:, 0].astype(int).tolist(), f"{log}: sample_index differs"
    assert [m["level"] for m in messages] == ref[:, 3].astype(int).tolist(), f"{log}: level sequence differs"
    rms_diff = max(abs(m["rms_mV"] - r) for m, r in zip(messages, ref[:, 1]))
    assert rms_diff <= 0.0005 + 1e-9, f"{log}: rms differs by {rms_diff}"
    logged = sum(1 for f in sessions.glob("*.jsonl") for _ in f.open())
    assert logged == len(messages), f"{log}: session log has {logged} lines, {len(messages)} received"
    return rms_diff


def test_e2e_replay():
    for log in LOGS:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            messages, seconds = asyncio.run(run_one(log, sessions))
            rms_diff = check(log, messages, sessions)
            levels = {lv: sum(1 for m in messages if m["level"] == lv) for lv in (-1, 0, 1, 2)}
            print(f"ok {log}: {len(messages)} messages in {seconds:.1f} s at {SPEED}x, seq 0..{len(messages) - 1} "
                  f"continuous, levels identical to the host test {levels}, max |rms diff| {rms_diff:.4f} mV "
                  f"(3-decimal JSON), session log complete")


if __name__ == "__main__":
    test_e2e_replay()
    print("end-to-end replay test passed")
