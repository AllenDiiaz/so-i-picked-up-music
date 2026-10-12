"""Record a serial log with spoken cues, prefixing each line with time since the start.

Used for experiment 05: the person at the board follows spoken cues (macOS `say`)
instead of watching the terminal.

    python analysis/record_serial.py PORT OUTPUT [--seconds 30] [--cues "10:pinch,20:release"]

Each output line is "<seconds since start>\\t<serial line>". The time is when the line
arrived on the host; lines buffered on the board before the start arrive together near
t = 0, so use the board's own log timestamps for timing (see data.load_05).

Needs pyserial (for example the ESP-IDF Python environment, which includes it).
"""
import argparse
import subprocess
import time

import serial


def say(text):
    subprocess.Popen(["say", text])   # non-blocking so timing is not delayed


def parse_cues(text):
    """Parse "10:pinch,20:release" into {10.0: "pinch", 20.0: "release"}."""
    if not text:
        return {}
    return {float(t): word for t, word in (c.split(":", 1) for c in text.split(","))}


def open_port(port, timeout_s=10):
    # The USB serial port can be briefly missing after a flash or reset; retry until it is back.
    deadline = time.monotonic() + timeout_s
    while True:
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = port, 115200, 0.1
        ser.dtr = False   # set before open() so the lines are not asserted
        ser.rts = False
        try:
            ser.open()
            return ser
        except serial.SerialException:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("port", help="serial port, for example /dev/cu.usbmodem1101")
    parser.add_argument("output", help="log file to write")
    parser.add_argument("--seconds", type=float, default=30, help="recording length (default 30)")
    parser.add_argument("--cues", default="10:pinch,20:release",
                        help='spoken cues as "seconds:word,..." (default "10:pinch,20:release", "" for none)')
    parser.add_argument("--countdown", type=int, default=5, help="spoken countdown before t = 0 (default 5)")
    args = parser.parse_args()

    cues = parse_cues(args.cues)
    ser = open_port(args.port)
    print("Spoken cues: " + ", ".join(f"{t:g} s {w}" for t, w in sorted(cues.items()))
          + f", {args.seconds:g} s done", flush=True)
    for n in range(args.countdown, 0, -1):
        print(f"starting in {n}...", flush=True)
        say(str(n))
        time.sleep(1)
    ser.reset_input_buffer()   # host side only; the board may still hold older lines
    say("start")
    start = time.monotonic()
    pending_cues = sorted(cues)
    pending = b""
    lines = 0
    with ser, open(args.output, "w", encoding="utf-8") as out:
        while time.monotonic() - start < args.seconds:
            t = time.monotonic() - start
            if pending_cues and t >= pending_cues[0]:
                cue = pending_cues.pop(0)
                say(cues[cue])
                print(f"[{t:6.3f}] cue: {cues[cue]}", flush=True)
            pending += ser.read(ser.in_waiting or 1)
            *complete, pending = pending.split(b"\n")
            t = time.monotonic() - start   # arrival time of these lines
            for raw in complete:
                out.write(f"{t:7.3f}\t{raw.decode('utf-8', errors='replace').rstrip()}\n")
                lines += 1
    say("done")
    print(f"recorded {lines} lines in {args.seconds:g} s -> {args.output}", flush=True)


if __name__ == "__main__":
    main()
