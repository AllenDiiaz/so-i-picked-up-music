"""Simulated 11_coach_loop board on a pseudo-terminal, for developing and testing without hardware.

    .venv/bin/python tools/fake_device.py [--log 03_A_light_hard.log] [--mode designed|naive]
        [--speed 1] [--loop] [--link /tmp/fake_emg]
    .venv/bin/python bridge/bridge.py --serial /tmp/fake_emg        (in a second terminal)

It opens a pty and prints its path (and creates the --link symlink); bridge.py --serial reads
and writes it like the board's USB serial port.

What is real and what is simulated:
- Real: the EMG samples are an experiment 06 recording; they go through the same compiled
  emg_dsp.c as on the board; '!' commands are parsed by the firmware's own coach.c (ctypes
  build in firmware/experiments/11_coach_loop/host_test), which also decides the level with the
  commanded hard_scale. The messages have the firmware's format (docs/protocol.md).
- Simulated: time (a Python loop, not a 1 kHz ADC with DMA) and the two cores. The "cores"
  message carries "simulated": true. Its core 1 numbers come from a model, not a measurement:
  0 us deviation while the sampler never waits, and the length of the wait when it blocks.
  The tens of microseconds of real jitter (experiment 04) are not modelled.

Modes (as in the firmware):
  designed  commands are handled next to the sampler (core 0); a set_params takes effect on the
            next hop and is acked; the stream never stops.
  naive     after "segment end" the sampler itself waits for the reply (up to 15 s). No hops
            are produced meanwhile; the samples that arrive during the wait are lost, except
            the 64 that fit in the DMA pool, and counted as overflow.
"""
import argparse
import ctypes
import json
import os
import random
import select
import subprocess
import sys
import time
import tty
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))
sys.path.insert(0, str(REPO / "tools"))
from protocol import CAL_RESULTS, HARD_SCALE_DEFAULT, VERSION, device_message  # noqa: E402
from replay_stream import FS, load_run  # noqa: E402

HOST_DIR = REPO / "firmware/experiments/11_coach_loop/host_test"
LIB = HOST_DIR / "libcoach.dylib"
DEVICE_NAME = "fake-esp32s3-emg"
FRAME_US = 16000
POOL_SAMPLES = 64               # the firmware's DMA pool: 4 frames of 16 samples
NAIVE_TIMEOUT_S = 15.0
CMD_SET_PARAMS, CMD_SEGMENT, CMD_MODE = 1, 2, 3


class Firmware:
    """The board's C code (emg_dsp.c + coach.c), loaded from the host build."""

    def __init__(self):
        subprocess.run(["make", "-s", "-C", str(HOST_DIR), "libcoach.dylib"], check=True)
        lib = self.lib = ctypes.CDLL(str(LIB))
        lib.emg_api_state_size.restype = ctypes.c_size_t
        lib.emg_api_process.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.POINTER(ctypes.c_double)]
        lib.emg_api_process.restype = ctypes.c_int
        lib.coach_api_parse.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_double)]
        lib.coach_api_parse.restype = ctypes.c_int
        lib.coach_api_level.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int, ctypes.c_double,
                                        ctypes.c_double]
        lib.coach_api_level.restype = ctypes.c_int
        self.state = ctypes.create_string_buffer(lib.emg_api_state_size())
        self.out = (ctypes.c_double * 13)()
        self.cmd = (ctypes.c_double * 7)()
        self.level = ctypes.c_int(-1)
        lib.emg_api_init(self.state)

    def process(self, mv, hard_scale):
        if not self.lib.emg_api_process(self.state, mv, self.out):
            return None
        o = self.out
        hop = dict(sample_index=int(o[0]), rms=o[1], norm=o[2], saturated=bool(o[4]), calibrating=bool(o[5]),
                   baseline=o[6])
        hop["level"] = self.lib.coach_api_level(ctypes.byref(self.level), int(o[3]), int(o[4]), o[2], hard_scale)
        if o[7]:
            hop["cal"] = {"attempt": int(o[9]), "result": CAL_RESULTS[int(o[8])], "valid": round(o[10], 4),
                          "cv": round(o[11], 4) if o[11] != float("inf") else 1e9, "rms_mV": round(o[12], 3)}
        return hop

    def parse(self, line):
        """A '!' line -> dict, or None if the firmware's parser rejects it."""
        if not self.lib.coach_api_parse(line, self.cmd):
            return None
        c = self.cmd
        return dict(kind=int(c[0]), seq=int(c[1]), has_hard_scale=bool(c[2]), hard_scale=round(c[3], 4),
                    clamped=bool(c[4]), segment_start=bool(c[5]), naive=bool(c[6]))


class FakeDevice:
    def __init__(self, args, mv):
        self.args, self.mv = args, mv
        self.fw = Firmware()
        self.master, slave = os.openpty()
        tty.setraw(slave)                       # no echo, no line editing: bytes pass through unchanged
        self.path = os.ttyname(slave)
        self.slave = slave                      # kept open so the pty survives the bridge reconnecting
        os.set_blocking(self.master, False)
        self.boot = random.getrandbits(32)
        self.naive = args.mode == "naive"
        self.hard_scale = HARD_SCALE_DEFAULT    # in use by the "sampler"
        self.pending = None                     # (command dict) set_params waiting for the next hop
        self.rx = b""
        self.seq = 0
        self.sample_index = 0
        self.led, self.last_level = 0, None
        self.t0 = time.monotonic()
        self.c1 = dict(frames=0, max_dev_us=0, late=0, blocked_ms=0, ovf=0, drop=0)
        self.c0 = dict(cmd_rx=0, parse_fail=0, applied=0, sent=0)

    # --- output ---------------------------------------------------------------------------
    def device_ms(self):
        return int((time.monotonic() - self.t0) * 1000 * self.args.speed)

    def send(self, msg):
        data = b"@" + json.dumps(msg, separators=(",", ":")).encode() + b"\n"
        try:
            os.write(self.master, data)
            self.c0["sent"] += 1
        except BlockingIOError:                 # nobody reads the pty: like the board's full queue
            self.c1["drop"] += 1

    def ack(self, cmd, name, applied, sample_index=None, waited_ms=None):
        msg = {"type": "ack", "v": VERSION, "dev": DEVICE_NAME, "boot": self.boot, "seq": cmd["seq"], "cmd": name,
               "applied": applied, "clamped": cmd["clamped"],
               "sample_index": self.sample_index if sample_index is None else sample_index,
               "device_ms": self.device_ms()}
        if waited_ms is not None:
            msg["waited_ms"] = waited_ms
        self.send(msg)

    def send_cores(self):
        c1 = self.c1
        self.send({"type": "cores", "v": VERSION, "dev": DEVICE_NAME, "boot": self.boot, "device_ms": self.device_ms(),
                   "mode": "naive" if self.naive else "designed", "simulated": True, "hard_scale": self.hard_scale,
                   "core1": dict(c1), "core0": dict(self.c0)})
        c1.update(frames=0, max_dev_us=0, late=0, blocked_ms=0)     # per-second values; ovf and drop accumulate

    # --- commands -------------------------------------------------------------------------
    def read_commands(self, timeout=0.0):
        """Complete '!' lines received from the host, parsed by the firmware's parser."""
        if timeout > 0:
            select.select([self.master], [], [], timeout)
        try:
            self.rx += os.read(self.master, 4096)
        except (BlockingIOError, OSError):
            pass
        commands = []
        while b"\n" in self.rx:
            line, self.rx = self.rx.split(b"\n", 1)
            if not line.strip():
                continue
            self.c0["cmd_rx"] += 1
            cmd = self.fw.parse(line)
            if cmd is None:
                self.c0["parse_fail"] += 1      # dropped and counted, no ack
            else:
                commands.append(cmd)
        return commands

    def handle(self, cmd):
        """The cmd_rx task's work (core 0). Returns True if the sampler must now block (naive)."""
        if cmd["kind"] == CMD_SET_PARAMS:
            self.pending = cmd                  # single hand-over point; the sampler applies it at a hop
        elif cmd["kind"] == CMD_MODE:
            self.naive = cmd["naive"]
            self.c0["applied"] += 1
            self.ack(cmd, "mode", {"mode": "naive" if self.naive else "designed"})
        elif cmd["kind"] == CMD_SEGMENT:
            self.c0["applied"] += 1
            self.ack(cmd, "segment", {"state": "start" if cmd["segment_start"] else "end"})
            return self.naive and not cmd["segment_start"]
        return False

    def apply_pending(self, sample_index, waited_ms=None):
        cmd, self.pending = self.pending, None
        applied = {}
        if cmd["has_hard_scale"]:
            self.hard_scale = cmd["hard_scale"]
            applied["hard_scale"] = cmd["hard_scale"]
        self.c0["applied"] += 1
        self.ack(cmd, "set_params", applied, sample_index=sample_index, waited_ms=waited_ms)

    def naive_wait(self, cores_due):
        """Naive mode: the sampler waits for the reply itself. Returns (seconds waited, next cores time)."""
        start = time.monotonic()
        while time.monotonic() - start < NAIVE_TIMEOUT_S / self.args.speed:
            for cmd in self.read_commands(timeout=0.02):
                if cmd["kind"] == CMD_SET_PARAMS:
                    self.pending = cmd
                    return time.monotonic() - start, cores_due
                self.handle(cmd)
            if time.monotonic() >= cores_due:   # the output task (core 0) is not blocked
                self.c1["blocked_ms"] = int((time.monotonic() - start) * 1000 * self.args.speed)
                self.c1["max_dev_us"] = self.c1["blocked_ms"] * 1000
                self.send_cores()
                cores_due += 1.0 / self.args.speed
        return time.monotonic() - start, cores_due

    # --- main loop ------------------------------------------------------------------------
    def run(self):
        args, n = self.args, 0                  # n: samples of device time elapsed (consumed + lost)
        cores_due = time.monotonic() + 1.0 / args.speed
        pos = 0
        while True:
            if pos >= len(self.mv):
                if not args.loop:
                    return
                pos = self.loop_from            # play the recording again, same boot, DSP state kept
            value = self.mv[pos]
            pos += 1
            n += 1
            if n % 16 == 0:
                self.c1["frames"] += 1
            hop = self.fw.process(value, self.hard_scale)
            if hop is None:
                continue
            delay = self.t0 + n / FS / args.speed - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            block = False
            for cmd in self.read_commands():
                block |= self.handle(cmd)
            if self.pending:                    # applied at a hop boundary: the next hop uses it
                self.apply_pending(hop["sample_index"])
            if self.last_level is not None and hop["level"] != self.last_level:
                self.led ^= 1
            self.last_level = hop["level"]
            self.sample_index = hop["sample_index"]
            self.send(device_message(
                dev=DEVICE_NAME, boot=self.boot, seq=self.seq, sample_index=hop["sample_index"],
                device_ms=self.device_ms(), rms_mv=hop["rms"], norm=hop["norm"], level=hop["level"],
                saturated=hop["saturated"], calibrating=hop["calibrating"], baseline_mv=hop["baseline"],
                led_state=self.led, cal=hop.get("cal")))
            self.seq += 1
            if block:
                waited, cores_due = self.naive_wait(cores_due)
                waited_ms = int(waited * 1000 * args.speed)
                lost = max(0, int(waited * FS * args.speed) - POOL_SAMPLES)
                # The ADC kept sampling: those samples never reach the DSP.
                pos = (pos + lost) % len(self.mv) if args.loop else min(len(self.mv), pos + lost)
                n += lost
                self.c1["ovf"] += lost // 16
                self.c1["late"] += 1
                self.c1["blocked_ms"] = waited_ms
                self.c1["max_dev_us"] = max(self.c1["max_dev_us"], waited_ms * 1000)
                if self.pending:
                    self.apply_pending(self.sample_index, waited_ms=waited_ms)
            if time.monotonic() >= cores_due:
                self.send_cores()
                cores_due += 1.0 / args.speed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", default="03_A_light_hard.log", help="file in docs/data/06_forearm_emg/ or a path")
    parser.add_argument("--mode", choices=("designed", "naive"), default="designed")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed, 1 = real time")
    parser.add_argument("--loop", action="store_true", help="repeat the recording (same boot, seq continues)")
    parser.add_argument("--link", metavar="PATH", help="create this symlink to the pty, e.g. /tmp/fake_emg")
    args = parser.parse_args()

    mv, offset, log_name = load_run(args.log)
    dev = FakeDevice(args, mv)
    dev.loop_from = int(round(offset * FS))     # loops restart where the recording proper begins
    if args.link:
        link = Path(args.link)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(dev.path)
    print(f"fake device (SIMULATED board): {log_name}, mode {args.mode}, {args.speed:g}x, serial port "
          f"{args.link or dev.path}", flush=True)
    print(f"PTY {dev.path}", flush=True)
    try:
        dev.run()
    except KeyboardInterrupt:
        pass
    finally:
        if args.link and Path(args.link).is_symlink():
            Path(args.link).unlink()


if __name__ == "__main__":
    main()
