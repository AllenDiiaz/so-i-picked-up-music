"""End-to-end test of the coach loop without hardware.

    .venv/bin/python tests/test_e2e_coach.py [--ollama] [--save-ollama FILE]     (also runs under pytest)

    simulated device (tools/fake_device.py on a pty, experiment 06 recording, firmware C code)
      <-> bridge (--serial, one handle for both directions) <-> WebSocket client (this test)

For both device modes it runs four practice segments against a scripted mock coach:
  1. a valid command           -> sent, acked by the device, hard_scale changes
  2. an illegal command        -> stopped by the bridge, the feedback is still shown
  3. an out-of-range command   -> clamped to the limit, then sent and acked
  4. a reply that is not JSON  -> fallback: the previous feedback, marked, nothing applied
and checks
  designed  the tension stream never pauses while the coach thinks; seq is continuous; the
            device reports no blocking and no overflow
  naive     the stream stops for about the thinking time after every segment end, and the
            device reports the blocking and the lost samples (the hole the design avoids)
plus: every message is valid protocol v1, each ack matches its command, the session log holds
request, reply, command and ack, and the sync flash round trip is logged.

--ollama (or OLLAMA=1) adds one designed-mode segment against the local Ollama model, if it is
running; --save-ollama FILE stores that real request / reply / result as JSON.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))
from protocol import HARD_SCALE_MAX, validate_bridge_message  # noqa: E402

PY = sys.executable
SPEED = 4                    # device time runs 4x: one hop every 12.5 ms
MOCK_DELAY = 1.0             # s the mock coach "thinks" (wall clock)
REPLIES = [
    '{"feedback": "Mostly relaxed. Tightening the hard threshold.", "command": {"hard_scale": 0.9}}',
    '{"feedback": "Second segment, same grip.", "command": {"hard_scale": "lots"}}',
    '{"feedback": "Hard nearly all the time; loosening the threshold a lot.", "command": {"hard_scale": 9}}',
    "this is not JSON",
]


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/version", timeout=1) as res:
            return res.status == 200
    except OSError:
        return False


class Session:
    """Fake device + bridge + one WebSocket client, collecting every message with its arrival time."""

    def __init__(self, tmp, mode, bridge_args):
        self.tmp, self.mode, self.bridge_args = Path(tmp), mode, bridge_args
        self.msgs = []           # (monotonic arrival, message)

    async def __aenter__(self):
        link = self.tmp / "port"
        udp, ws = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
        self.device = subprocess.Popen([PY, str(REPO / "tools/fake_device.py"), "--mode", self.mode, "--speed",
                                        str(SPEED), "--loop", "--link", str(link)], stdout=subprocess.DEVNULL)
        for _ in range(100):
            if link.is_symlink():
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("fake device did not start")
        self.bridge = subprocess.Popen([PY, str(REPO / "bridge/bridge.py"), "--serial", str(link), "--udp-host",
                                        "127.0.0.1", "--udp-port", str(udp), "--ws-port", str(ws), "--sessions",
                                        str(self.tmp), "--quiet", *self.bridge_args], stdout=subprocess.DEVNULL)
        for _ in range(50):
            try:
                self.ws = await connect(f"ws://localhost:{ws}")
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            raise RuntimeError("bridge did not start")
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()
        for proc in (self.bridge, self.device):
            proc.terminate()
            proc.wait()

    async def pump(self, until, timeout):
        """Receive until until(message) is true; returns that message."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=0.2))
            except asyncio.TimeoutError:
                continue
            validate_bridge_message(msg)
            self.msgs.append((time.monotonic(), msg))
            if until(msg):
                return msg
        raise RuntimeError(f"{self.mode}: timed out waiting")

    async def idle(self, seconds):
        end = time.monotonic() + seconds
        try:
            await self.pump(lambda m: time.monotonic() >= end, seconds + 1)
        except RuntimeError:
            pass

    async def segment(self, seconds):
        """One practice segment; returns the coach message."""
        await self.ws.send(json.dumps({"type": "segment", "action": "start"}))
        await self.pump(lambda m: m["type"] == "segment" and m["state"] == "recording", 5)
        await self.idle(seconds)
        await self.ws.send(json.dumps({"type": "segment", "action": "end"}))
        coach = await self.pump(lambda m: m["type"] == "coach", 30)
        await self.pump(lambda m: m["type"] == "segment" and m["state"] == "feedback", 5)
        return coach

    def of(self, kind):
        return [(t, m) for t, m in self.msgs if m["type"] == kind]

    def log_lines(self):
        return [json.loads(line) for f in self.tmp.glob("*.jsonl") for line in f.open()]


async def run_scripted(mode, tmp):
    replies = Path(tmp) / "replies.json"
    replies.write_text(json.dumps(REPLIES))
    args = ["--llm", "mock", "--mock-delay", str(MOCK_DELAY), "--mock-replies", str(replies)]
    async with Session(tmp, mode, args) as s:
        await s.pump(lambda m: m["type"] == "emg" and m["level"] >= 0, 30)      # calibrated
        coaches, ends = [], []
        for _ in REPLIES:
            coaches.append(await s.segment(1.5))
            ends.append(next(t for t, m in reversed(s.msgs) if m["type"] == "segment" and m["state"] == "thinking"))
            await s.idle(0.5)
        await s.ws.send(json.dumps({"type": "sync"}))
        sync = await s.pump(lambda m: m["type"] == "sync", 5)
        await s.ws.send(json.dumps({"type": "sync_shown", "id": sync["id"], "browser_ms": time.time() * 1000}))
        await s.idle(1.5)
        check(mode, s, coaches, ends)
        return s


def check(mode, s, coaches, ends):
    emg = s.of("emg")
    seqs = [m["seq"] for _, m in emg]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), f"{mode}: seq not continuous"
    assert len({m["boot"] for _, m in emg}) == 1, f"{mode}: more than one boot id"
    commands = {m["seq"]: m for _, m in s.of("command")}
    acks = {m["seq"]: m for _, m in s.of("ack")}
    assert all(c["sent"] for c in commands.values()), f"{mode}: a command was not written to the serial port"
    assert set(acks) == set(commands), f"{mode}: acks {sorted(acks)} do not match commands {sorted(commands)}"
    for seq, ack in acks.items():
        assert ack["cmd"] == commands[seq]["cmd"], f"{mode}: ack {seq} is for another command"
    params = [c for c in commands.values() if c["cmd"] == "set_params"]
    with_value = [c for c in params if "hard_scale" in c]

    c1, c2, c3, c4 = coaches
    # 1. valid command: sent, acked, applied
    assert c1["command"] == {"hard_scale": 0.9} and c1["sent"] and c1["acked"] and not c1["fallback"], c1
    assert acks[c1["ack_seq"]]["applied"] == {"hard_scale": 0.9} and not acks[c1["ack_seq"]]["clamped"]
    # 2. illegal command: never reaches the device, feedback kept
    assert c2["command"] is None and c2["command_error"] and not c2["sent"] and not c2["fallback"], c2
    assert c2["feedback"] == "Second segment, same grip."
    # 3. out of range: clamped by the bridge before sending
    assert c3["command"] == {"hard_scale": HARD_SCALE_MAX} and c3["clamped"] and c3["sent"] and c3["acked"], c3
    assert acks[c3["ack_seq"]]["applied"] == {"hard_scale": HARD_SCALE_MAX}
    # 4. unusable reply: fallback to the last good feedback, marked, nothing applied
    assert c4["fallback"] and c4["command"] is None and not c4["sent"] and c4["feedback"] == c3["feedback"], c4
    assert [c["hard_scale"] for c in with_value] == [0.9, HARD_SCALE_MAX], f"{mode}: unexpected set_params {with_value}"
    cores = [m for _, m in s.of("cores")]
    assert cores and all(m["simulated"] and m["mode"] == mode for m in cores)
    assert cores[-1]["hard_scale"] == HARD_SCALE_MAX, f"{mode}: device ended at hard_scale {cores[-1]['hard_scale']}"
    assert cores[-1]["core0"]["parse_fail"] == 0, f"{mode}: the device rejected a line from the bridge"
    assert cores[-1]["core0"]["cmd_rx"] == len(commands)

    # The stream around each segment end: longest pause between two tension messages in the
    # window from the segment end to the coach's reply (plus a little).
    times = [t for t, _ in emg]
    pauses = []
    for end in ends:
        window = [t for t in times if end - 0.2 <= t <= end + MOCK_DELAY + 1.0]
        pauses.append(max(b - a for a, b in zip(window, window[1:])))
    blocked = [m["core1"]["blocked_ms"] for m in cores if m["core1"]["blocked_ms"] > 0]
    if mode == "designed":
        assert max(pauses) < 0.25, f"designed: the stream paused for {max(pauses):.2f} s while the coach was thinking"
        assert not blocked and cores[-1]["core1"]["ovf"] == 0, "designed: the device reports blocking or overflow"
        assert len(params) == 2, "designed: nothing may be sent when there is no valid command"
        assert all("waited_ms" not in a for a in acks.values())
    else:
        assert min(pauses) > 0.8 * MOCK_DELAY, f"naive: expected a hole of about {MOCK_DELAY} s, pauses {pauses}"
        assert blocked and cores[-1]["core1"]["ovf"] > 0, "naive: the device did not report the blocking"
        assert len(params) == 4, "naive: every segment end needs a set_params to release the device"
        waits = [acks[c["seq"]].get("waited_ms", 0) for c in params]
        assert all(w > 0.8 * MOCK_DELAY * 1000 * SPEED for w in waits), f"naive: waits {waits} (device ms)"

    log = s.log_lines()
    kinds = [m["type"] for m in log]
    for kind, n in (("llm_request", 4), ("llm_response", 4), ("coach", 4), ("sync", 1), ("sync_shown", 1)):
        assert kinds.count(kind) == n, f"{mode}: session log has {kinds.count(kind)} {kind} lines, expected {n}"
    assert kinds.count("command") == len(commands) and kinds.count("ack") == len(acks)
    logged = {m["seq"] for m in log if m["type"] == "emg"}      # the bridge is still logging: superset
    assert set(seqs) <= logged, f"{mode}: {len(set(seqs) - logged)} tension messages missing from the session log"
    assert [m["error"] is None for m in log if m["type"] == "llm_response"] == [True, True, True, False]
    print(f"ok {mode}: {len(emg)} tension messages, seq continuous; 4 segments: command acked, illegal command "
          f"stopped, out-of-range clamped to {HARD_SCALE_MAX}, fallback marked; longest pause while thinking "
          f"{max(pauses) * 1000:.0f} ms (shortest {min(pauses) * 1000:.0f} ms); device blocked_ms "
          f"{max(blocked) if blocked else 0}, ovf {cores[-1]['core1']['ovf']}; session log complete")


async def run_ollama(tmp, save):
    async with Session(tmp, "designed", ["--llm", "ollama"]) as s:
        await s.pump(lambda m: m["type"] == "emg" and m["level"] >= 0, 30)
        coach = await s.segment(3.0)
        await s.idle(0.5)
        log = s.log_lines()
        request = next(m for m in log if m["type"] == "llm_request")
        response = next(m for m in log if m["type"] == "llm_response")
        acks = [m for m in log if m["type"] == "ack" and m["cmd"] == "set_params"]
        assert coach["llm"] == "ollama"
        assert not coach["fallback"], f"ollama: fell back ({coach['reason']})"
        assert response["error"] is None and json.loads(response["raw"])["feedback"]
        if coach["command"]:
            assert coach["sent"] and coach["acked"] and acks, "ollama: command was not acked"
        print(f"ok ollama ({coach['model']}): reply in {coach['latency_ms']:.0f} ms: {coach['feedback']!r}, "
              f"command {coach['command']}, acked {coach['acked']}")
        if save:
            for m in (request, response, coach, *acks):
                m.pop("src", None)
            Path(save).parent.mkdir(parents=True, exist_ok=True)
            Path(save).write_text(json.dumps({"note": "One real round trip: simulated device (experiment 06 recording), "
                                              "local Ollama model. Times are epoch ms.", "llm_request": request,
                                              "llm_response": response, "coach": coach, "acks": acks}, indent=1) + "\n")
            print(f"saved {save}")


def test_host_parser():
    """The device's own rejection of bad lines is covered by the C host test."""
    res = subprocess.run(["make", "-s", "-C", str(REPO / "firmware/experiments/11_coach_loop/host_test"), "test"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    print("ok host test: " + res.stdout.strip().splitlines()[0])


def test_e2e_coach():
    for mode in ("designed", "naive"):
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(run_scripted(mode, tmp))


def test_e2e_ollama(save=None):
    if not ollama_running():
        print("skipped ollama: no server on localhost:11434")
        return
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(run_ollama(tmp, save))


if __name__ == "__main__":
    test_host_parser()
    test_e2e_coach()
    if "--ollama" in sys.argv or "--save-ollama" in sys.argv or os.environ.get("OLLAMA") == "1":
        save = sys.argv[sys.argv.index("--save-ollama") + 1] if "--save-ollama" in sys.argv else None
        test_e2e_ollama(save)
    print("coach loop end-to-end test passed")
