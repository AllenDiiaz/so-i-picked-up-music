"""Replay an experiment 06 recording as a live tension stream, exactly as the ESP32 would send it.

    .venv/bin/python tools/replay_stream.py --log 03_A_light_hard.log [--speed 1] [--loop]
        [--calibrate boot|relax] [--host 127.0.0.1] [--port 9750]

The raw 1 kHz samples go through the firmware's own DSP (emg_dsp.c from
firmware/experiments/07_onboard_tension, loaded with ctypes from the host build), so every
number matches the board. Every 50 ms of sample time one protocol v1 message (docs/protocol.md)
is sent over UDP; --speed scales the pace.

Calibration (--calibrate):
  boot   start at the board's first sample after boot. The DSP calibrates on 0.5-5.5 s after
         boot, which in experiment 06 is the countdown before the recording, with the arm at
         rest -- what the firmware itself would do.
  relax  first feed 5.5 s of the recording's first relax phase (from 1.5 s after its cue:
         0.5 s filter settling + 5 s calibration), then the recording from its start. Uses a
         relax period recorded with the same posture as the efforts.
"""
import argparse
import ctypes
import random
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))
sys.path.insert(0, str(REPO / "analysis"))
from protocol import CAL_RESULTS, UDP_PORT, device_message, encode  # noqa: E402

HOST_DIR = REPO / "firmware/experiments/07_onboard_tension/host_test"
LIB = HOST_DIR / "libemg_dsp.dylib"
DATA_DIR = REPO / "docs/data/06_forearm_emg"
HOP_SAMPLES = 50
FS = 1000


class Dsp:
    """ctypes wrapper of the host build of emg_dsp.c (host_test/emg_api.c)."""

    def __init__(self):
        subprocess.run(["make", "-s", "-C", str(HOST_DIR), "libemg_dsp.dylib"], check=True)
        self.lib = ctypes.CDLL(str(LIB))
        self.lib.emg_api_state_size.restype = ctypes.c_size_t
        self.lib.emg_api_process.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.POINTER(ctypes.c_double)]
        self.lib.emg_api_process.restype = ctypes.c_int
        self.state = ctypes.create_string_buffer(self.lib.emg_api_state_size())
        self.out = (ctypes.c_double * 13)()
        self.lib.emg_api_init(self.state)

    def process(self, mv):
        """Feed one sample; returns the hop output as a dict, or None."""
        if not self.lib.emg_api_process(self.state, mv, self.out):
            return None
        o = self.out
        hop = dict(sample_index=int(o[0]), rms=o[1], norm=o[2], level=int(o[3]), saturated=bool(o[4]),
                   calibrating=bool(o[5]), baseline=o[6])
        if o[7]:
            hop["cal"] = {"attempt": int(o[9]), "result": CAL_RESULTS[int(o[8])], "valid": round(o[10], 4),
                          "cv": round(o[11], 4) if o[11] != float("inf") else 1e9, "rms_mV": round(o[12], 3)}
        return hop


def load_run(log):
    """Raw mV of the newest board run (from sample index 0) and its board-time offset in s."""
    path = Path(log) if Path(log).exists() else DATA_DIR / log
    rows = []
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([\d.]+)\t(\d+),(\d+)$", line)
        if m:
            rows.append((float(m.group(1)), int(m.group(2)), int(m.group(3))))
    start = max(i for i, r in enumerate(rows) if r[1] == 0)
    run = rows[start:]
    if any(b[1] != a[1] + 1 for a, b in zip(run, run[1:])):
        raise SystemExit(f"{path.name}: sample indices are not continuous")
    live = [(h, i) for h, i, _ in run if h > 1]
    offset = max(i / FS - h for h, i in live)
    return [float(v) for _, _, v in run], offset, path.name


def relax_prefix(log_name, mv, offset):
    """5.5 s from the recording's first relax phase, starting 1.5 s after its cue."""
    from emg import RECORDINGS, SKIP_S   # noqa: E402  (analysis/emg.py)
    for rec in RECORDINGS.values():
        if rec["file"] == log_name:
            start, end, kind = rec["phases"][0]
            assert kind == "relax"
            i0 = int(round((start + SKIP_S + offset) * FS))
            return mv[i0:i0 + 5500], f"recording {start + SKIP_S:.1f}-{start + SKIP_S + 5.5:.1f} s"
    raise SystemExit(f"--calibrate relax: no phase table for {log_name} in analysis/emg.py")


def replay_once(args, mv, offset, log_name, sock):
    dsp = Dsp()
    boot = random.getrandbits(32)
    seq, led, last_level, sent = 0, 0, None, 0
    samples = mv[int(round(offset * FS)):] if args.calibrate == "relax" else mv
    if args.calibrate == "relax":
        prefix, where = relax_prefix(log_name, mv, offset)
        samples = prefix + samples
        print(f"calibration: {where} first, then the recording from its start")
    else:
        print("calibration: 0.5-5.5 s after board boot (before the recording started)")
    t0 = time.monotonic()
    for n, value in enumerate(samples, start=1):
        hop = dsp.process(value)
        if hop is None:
            continue
        if last_level is not None and hop["level"] != last_level:
            led ^= 1                                  # the 08 firmware toggles its LED here
        last_level = hop["level"]
        msg = device_message(
            dev="replay", boot=boot, seq=seq, sample_index=hop["sample_index"],
            device_ms=hop["sample_index"] + 1,        # simulated device clock: 1 sample = 1 ms
            rms_mv=hop["rms"], norm=hop["norm"], level=hop["level"], saturated=hop["saturated"],
            calibrating=hop["calibrating"], baseline_mv=hop["baseline"], led_state=led, cal=hop.get("cal"))
        due = t0 + n / FS / args.speed
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        sock.sendto(encode(msg), (args.host, args.port))
        seq += 1
        sent += 1
        if "cal" in msg:
            print(f"  calibration attempt {msg['cal']['attempt']}: {msg['cal']['result']} "
                  f"(cv {msg['cal']['cv']}, rms {msg['cal']['rms_mV']} mV)")
        if not args.quiet and sent % (100 if args.speed <= 1 else 400) == 0:
            print(f"  sent {sent} messages, sample time {hop['sample_index'] / FS:6.1f} s, level {hop['level']}")
    return sent


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", default="03_A_light_hard.log",
                        help="file in docs/data/06_forearm_emg/ or a path (default 03_A_light_hard.log)")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed, 1 = real time")
    parser.add_argument("--loop", action="store_true", help="start again at the end (new boot id, seq from 0)")
    parser.add_argument("--calibrate", choices=("boot", "relax"), default="boot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=UDP_PORT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    mv, offset, log_name = load_run(args.log)
    print(f"{log_name}: {len(mv)} samples ({len(mv) / FS:.1f} s, recording starts {offset:.2f} s after boot); "
          f"sending to udp://{args.host}:{args.port} at {args.speed:g}x")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            sent = replay_once(args, mv, offset, log_name, sock)
            print(f"done: {sent} messages")
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
