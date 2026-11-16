"""Mac bridge: UDP tension messages from the ESP32 (or the replayer) -> WebSocket for the browser.

    .venv/bin/python bridge/bridge.py [--udp-port 9750] [--ws-port 8765] [--sessions sessions]
    .venv/bin/python bridge/bridge.py --serial /dev/cu.usbmodem1101      (10_usb_stream over USB)

- Receives protocol v1 messages (docs/protocol.md) on UDP, adds bridge_rx_ms and src, and
  broadcasts them to every WebSocket client on ws://localhost:<ws-port>.
- Sends a status message to the clients every second.
- Prints statistics every 5 s: received, lost and out-of-order (from seq), restarts, senders.
- Writes every forwarded message to sessions/<YYYYmmdd-HHMMSS>.jsonl (git-ignored); these logs
  are the input of tools/session_summary.py.
- A restarted ESP32 (new boot id, seq from 0) and browsers that disconnect and reconnect are
  handled without restarting the bridge. Malformed datagrams are counted and dropped.
- --serial PORT additionally reads the board's USB serial output (10_usb_stream): lines starting
  with '@' are protocol v1 messages and are handled exactly like datagrams (src "serial:PORT");
  every other line goes to sessions/<same name>.serial.log with a timestamp (MAC addresses
  redacted). The port is reopened after it disappears or stays silent for 3 s (e.g. after the RST
  button, when the old handle can go quiet without an error). Only one program can read the port.

Coach loop (firmware 11_coach_loop or tools/fake_device.py on the serial port):
- The serial port is opened once and the same handle is used for reading and for writing the
  downlink commands ('!' lines, docs/protocol.md); opening it again would reset the board.
- A practice segment is started and ended from the keyboard (Enter in this terminal), from the
  browser's button, or from the board's button. When it ends, the segment's statistics
  (tools/session_summary.py) go to the coach (--llm mock|ollama, bridge/coach.py) in a worker
  thread with a 10 s timeout; the stream keeps flowing meanwhile. The reply is validated and
  clamped (protocol.check_llm_reply); only then a set_params command is sent, and its ack awaited.
- If the model is unreachable, too slow or returns nonsense, the last good feedback is shown
  again, marked as fallback, and no command is sent.
- Request, reply, command and ack are all written to the session log next to the stream.
- Keys (then Enter): Enter = segment start/end, n / d = naive / designed mode, f = sync flash.
"""
import argparse
import asyncio
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coach as coach_mod  # noqa: E402
from protocol import (HARD_SCALE_DEFAULT, MODES, UDP_PORT, VERSION, WS_PORT, SeqTracker, check_llm_reply,  # noqa: E402
                      command_line, validate_device_line)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from session_summary import summarise  # noqa: E402

ACK_TIMEOUT_S = 3.0        # designed mode: the board acks within one hop (50 ms)
MIN_SEGMENT_MESSAGES = 20  # under 1 s of levels there is nothing to coach
SERIAL_SILENT_S = 3.0      # the board prints at least every 50 ms; silence means a stale handle
_MAC = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")


def now_ms():
    return time.time() * 1000.0


class Bridge:
    def __init__(self, session_path, quiet=False, coach=None):
        self.coach = coach or coach_mod.Coach("mock")
        self.serial = None          # SerialReader when --serial is used: the only downlink
        self.mode = "designed"
        self.segment_id = 0
        self.segment_state = "idle"
        self.segment_msgs = []      # emg messages of the segment being recorded
        self.cmd_seq = 0
        self.acks = {}              # command seq -> Future resolved by the device's ack
        self.hard_scale = HARD_SCALE_DEFAULT
        self.last_good = None       # last validated coach reply, for the fallback
        self.sync_id = 0
        self.tasks = set()
        self.clients = set()
        self.trackers = {}          # sender "ip:port" -> SeqTracker (a restart may change the port)
        self.sources_seen = {}      # sender -> last bridge_rx_ms
        self.malformed = 0
        self.last_rx_ms = None
        self.quiet = quiet
        self.session_path = session_path
        self.session = open(session_path, "a", buffering=1, encoding="utf-8")
        self.window = dict(received=0, lost=0, out_of_order=0)

    # --- UDP side ---------------------------------------------------------------------------
    def on_datagram(self, data, addr):
        # Track per device address (ip) and boot, so a restart that changes the source port is
        # seen as a restart rather than a second device.
        self.on_message(data, f"{addr[0]}:{addr[1]}", addr[0], now_ms())

    def on_message(self, data, src, device_key, rx_ms):
        try:
            msg = json.loads(data)
            kind = validate_device_line(msg)
        except (ValueError, UnicodeDecodeError) as e:
            self.malformed += 1
            if self.malformed <= 5 and not self.quiet:
                print(f"malformed message from {src}: {e}")
            return
        msg["bridge_rx_ms"] = rx_ms
        msg["src"] = src
        if kind == "emg":
            tracker = self.trackers.setdefault(device_key, SeqTracker())
            before_lost, before_ooo = tracker.lost, tracker.out_of_order
            state = tracker.update(msg["boot"], msg["seq"])
            if state == "reboot" and not self.quiet:
                print(f"{src}: device restarted (boot {msg['boot']}), seq restarts at {msg['seq']}")
            self.window["received"] += 1
            self.window["lost"] += tracker.lost - before_lost
            self.window["out_of_order"] += tracker.out_of_order - before_ooo
            self.sources_seen[src] = rx_ms
            self.last_rx_ms = rx_ms
            if self.segment_state == "recording":
                self.segment_msgs.append(msg)
        elif kind == "ack":
            if "hard_scale" in msg["applied"]:
                self.hard_scale = msg["applied"]["hard_scale"]
            if "mode" in msg["applied"]:
                self.mode = msg["applied"]["mode"]
            future = self.acks.pop(msg["seq"], None)
            if future and not future.done():
                future.set_result(msg)
        elif kind == "cores":
            self.mode = msg["mode"]
            self.hard_scale = msg["hard_scale"]
        elif kind == "button":
            self.segment_toggle("board")
        self.emit(msg)

    def emit(self, msg):
        """Write one message to the session log and send it to every browser."""
        text = json.dumps(msg, separators=(",", ":"))
        self.session.write(text + "\n")
        broadcast(self.clients, text)

    def log_only(self, msg):
        self.session.write(json.dumps(msg, separators=(",", ":")) + "\n")

    # --- downlink and coach loop ------------------------------------------------------------
    def send_command(self, cmd, **fields):
        """Send one '!' command on the serial handle. Returns (seq, sent)."""
        self.cmd_seq += 1
        seq = self.cmd_seq
        sent = bool(self.serial and self.serial.write(command_line(cmd, seq, **fields)))
        if sent:
            self.acks[seq] = asyncio.get_running_loop().create_future()
        self.emit({"type": "command", "v": VERSION, "seq": seq, "cmd": cmd, **fields, "sent": sent,
                   "bridge_ms": now_ms()})
        return seq, sent

    async def wait_ack(self, seq, timeout=ACK_TIMEOUT_S):
        future = self.acks.get(seq)
        if future is None:
            return None
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self.acks.pop(seq, None)
            self.log_only({"type": "ack_timeout", "v": VERSION, "seq": seq, "bridge_ms": now_ms()})
            if not self.quiet:
                print(f"no ack for command {seq} within {timeout:.0f} s")
            return None

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def set_segment(self, state, trigger):
        self.segment_state = state
        self.emit({"type": "segment", "v": VERSION, "id": self.segment_id, "state": state, "trigger": trigger,
                   "bridge_ms": now_ms()})
        if not self.quiet:
            print(f"segment {self.segment_id}: {state} ({trigger})")

    def segment_toggle(self, trigger):
        if self.segment_state == "recording":
            self.segment_end(trigger)
        elif self.segment_state in ("idle", "feedback"):
            self.segment_start(trigger)
        # "thinking": a reply is on its way; ignore the press

    def segment_start(self, trigger):
        if self.segment_state not in ("idle", "feedback"):
            return
        self.segment_id += 1
        self.segment_msgs = []
        self.set_segment("recording", trigger)
        self.send_command("segment", state="start")

    def segment_end(self, trigger):
        if self.segment_state != "recording":
            return
        msgs, self.segment_msgs = self.segment_msgs, []
        self.set_segment("thinking", trigger)
        self.send_command("segment", state="end")
        self.spawn(self.coach_segment(self.segment_id, msgs))

    def set_mode(self, mode):
        if mode in MODES:
            self.send_command("mode", mode=mode)

    def sync(self, trigger):
        """Ask every page for a full-screen flash and a beep, to line a screen recording up with the log."""
        self.sync_id += 1
        self.emit({"type": "sync", "v": VERSION, "id": self.sync_id, "trigger": trigger, "bridge_ms": now_ms()})

    async def coach_segment(self, segment_id, msgs):
        """Segment statistics -> LLM (worker thread) -> validated reply -> command -> ack."""
        started = now_ms()
        coach, info = self.coach, self.coach.describe()
        result = {"type": "coach", "v": VERSION, "id": segment_id, "feedback": "", "command": None, **info,
                  "fallback": False, "clamped": False, "truncated": False, "command_error": None, "sent": False,
                  "acked": False, "reason": None}
        usable = [m for m in msgs if m["level"] >= 0]
        if len(usable) < MIN_SEGMENT_MESSAGES:
            result.update(feedback="Segment too short to judge; play a little longer.", llm="none", model="none",
                          reason="segment too short")
        else:
            summary = summarise(msgs)
            prompt = coach_mod.build_prompt(summary, self.hard_scale)
            self.log_only({"type": "llm_request", "v": VERSION, "id": segment_id, **info, "summary": summary,
                           "hard_scale": self.hard_scale, "request": coach.request(prompt), "bridge_ms": started})
            raw = error = None
            try:
                raw = await asyncio.wait_for(asyncio.to_thread(coach.call, prompt, summary, self.hard_scale),
                                             coach.timeout)
                checked = check_llm_reply(raw)
            except asyncio.TimeoutError:
                error = f"no reply within {coach.timeout:.0f} s"
            except Exception as e:      # connection refused, bad JSON, missing feedback, ...
                error = f"{type(e).__name__}: {e}"
            self.log_only({"type": "llm_response", "v": VERSION, "id": segment_id, **info, "raw": raw, "error": error,
                           "latency_ms": round(now_ms() - started, 1), "bridge_ms": now_ms()})
            if error is None:
                self.last_good = checked
                result.update(checked)
            else:       # fallback: repeat the last good feedback, marked, and send nothing
                result.update(fallback=True, reason=error,
                              feedback=self.last_good["feedback"] if self.last_good
                              else "Coach unavailable; no feedback for this segment.")
        command = result["command"]
        seq = None
        if command is not None:
            seq, result["sent"] = self.send_command("set_params", **command)
        elif self.mode == "naive":
            # Nothing to apply, but a naive device is blocked waiting for a reply: release it.
            seq, _ = self.send_command("set_params")
        if seq is not None:
            ack = await self.wait_ack(seq, 20.0 if self.mode == "naive" else ACK_TIMEOUT_S)
            result["acked"] = ack is not None and command is not None
            if ack is not None:
                result["ack_seq"] = seq
        result["latency_ms"] = round(now_ms() - started, 1)
        result["bridge_ms"] = now_ms()
        self.emit(result)
        if not self.quiet:
            tag = " [fallback]" if result["fallback"] else ""
            print(f"coach{tag}: {result['feedback']} | command {command} sent={result['sent']} acked={result['acked']}"
                  + (f" | dropped: {result['command_error']}" if result["command_error"] else ""))
        if self.segment_id == segment_id:
            self.set_segment("feedback", "coach")

    def on_client_message(self, text):
        """Requests from a browser page: segment button, mode switch, sync flash."""
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("type") == "segment" and msg.get("action") in ("toggle", "start", "end"):
            {"toggle": self.segment_toggle, "start": self.segment_start, "end": self.segment_end}[msg["action"]]("browser")
        elif msg.get("type") == "mode":
            self.set_mode(msg.get("mode"))
        elif msg.get("type") == "sync":
            self.sync("browser")
        elif msg.get("type") == "sync_shown" and isinstance(msg.get("browser_ms"), (int, float)):
            self.log_only({"type": "sync_shown", "v": VERSION, "id": msg.get("id"), "browser_ms": msg["browser_ms"],
                           "bridge_ms": now_ms()})

    def on_key(self, line):
        key = line.strip().lower()
        if key == "":
            self.segment_toggle("keyboard")
        elif key in ("n", "d"):
            self.set_mode("naive" if key == "n" else "designed")
        elif key == "f":
            self.sync("keyboard")

    # --- WebSocket side ---------------------------------------------------------------------
    async def handler(self, websocket):
        self.clients.add(websocket)
        if not self.quiet:
            print(f"browser connected ({len(self.clients)} open)")
        try:
            await websocket.send(json.dumps(self.status()))
            async for text in websocket:
                self.on_client_message(text)
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            if not self.quiet:
                print(f"browser disconnected ({len(self.clients)} open)")

    def totals(self):
        t = dict(received=0, lost=0, out_of_order=0, reboots=0)
        for tr in self.trackers.values():
            t["received"] += tr.received
            t["lost"] += tr.lost
            t["out_of_order"] += tr.out_of_order
            t["reboots"] += tr.reboots
        return t

    def status(self):
        cutoff = now_ms() - 5000
        return {"type": "status", "v": VERSION, "bridge_ms": now_ms(), **self.totals(),
                "last_rx_ms": self.last_rx_ms,
                "sources": sorted(s for s, t in self.sources_seen.items() if t >= cutoff),
                "mode": self.mode, "hard_scale": self.hard_scale, "downlink": self.serial is not None,
                "segment": {"id": self.segment_id, "state": self.segment_state}, **self.coach.describe()}

    async def status_loop(self):
        while True:
            await asyncio.sleep(1.0)
            broadcast(self.clients, json.dumps(self.status()))

    async def stats_loop(self):
        while True:
            await asyncio.sleep(5.0)
            t = self.totals()
            w, self.window = self.window, dict(received=0, lost=0, out_of_order=0)
            total = t["received"] + t["lost"]
            rate = 100.0 * t["lost"] / total if total else 0.0
            print(f"[{datetime.now():%H:%M:%S}] last 5 s: {w['received']} received, {w['lost']} lost, "
                  f"{w['out_of_order']} out of order | total {t['received']} received, {t['lost']} lost "
                  f"({rate:.2f} %), {t['reboots']} restarts, {self.malformed} malformed | "
                  f"senders {', '.join(self.status()['sources']) or '-'} | browsers {len(self.clients)}")


class SerialReader:
    """Reads the board's USB serial port in a thread and hands lines to the event loop."""

    def __init__(self, bridge, port, loop, log_path, quiet=False):
        self.bridge, self.port, self.loop, self.quiet = bridge, port, loop, quiet
        self.src = f"serial:{port}"
        self.log = open(log_path, "a", buffering=1, encoding="utf-8")
        self.reconnects = 0
        self.stop = threading.Event()
        self.ser = None                 # the one open handle, shared by run() and write()
        self.lock = threading.Lock()

    def write(self, data):
        """Write a downlink command on the handle the reader thread opened. Returns False if closed."""
        with self.lock:
            ser = self.ser
            if ser is None or not ser.is_open:
                return False
            try:
                ser.write(data)
                return True
            except Exception as e:      # port vanished between the check and the write
                self.note(f"write failed ({e})")
                return False

    def note(self, text):
        self.log.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" ## {text}\n")
        if not self.quiet:
            print(f"serial: {text}")

    def handle_line(self, raw, rx_ms):
        line = raw.decode(errors="replace").rstrip("\r\n")
        if line.startswith("@"):
            self.bridge.on_message(line[1:], self.src, "serial", rx_ms)
            return
        line = _MAC.sub("[MAC REDACTED]", line)
        self.log.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" {line}\n")
        if not self.quiet and ("calibration" in line or "button:" in line or "rst:" in line or "cmd_rx" in line):
            print(f"serial: {line}")

    def run(self):
        import serial   # pyserial; only needed in serial mode
        while not self.stop.is_set():
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = self.port, 115200, 0.2
            ser.dtr = ser.rts = False          # do not reset the board on open
            try:
                ser.open()
                with self.lock:
                    self.ser = ser
                self.note(f"port {self.port} open")
                last = time.monotonic()
                while not self.stop.is_set():
                    raw = ser.readline()
                    if raw:
                        last = time.monotonic()
                        self.loop.call_soon_threadsafe(self.handle_line, raw, now_ms())
                    elif time.monotonic() - last > SERIAL_SILENT_S:
                        raise serial.SerialException(f"no data for {SERIAL_SILENT_S:.0f} s")
            except (serial.SerialException, OSError) as e:
                self.reconnects += 1
                self.note(f"port lost ({e}); reconnecting")
                time.sleep(0.5)
            finally:
                with self.lock:
                    self.ser = None
                try:
                    ser.close()
                except Exception:
                    pass


class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge):
        self.bridge = bridge

    def datagram_received(self, data, addr):
        self.bridge.on_datagram(data, addr)


async def run(args):
    sessions = Path(args.sessions)
    sessions.mkdir(parents=True, exist_ok=True)
    session_path = sessions / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    replies = json.loads(Path(args.mock_replies).read_text()) if args.mock_replies else None
    coach = coach_mod.Coach(args.llm, model=args.model, url=args.ollama_url, timeout=args.llm_timeout,
                            mock_delay=args.mock_delay, mock_replies=replies)
    bridge = Bridge(session_path, quiet=args.quiet, coach=coach)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: UdpProtocol(bridge),
                                                       local_addr=(args.udp_host, args.udp_port))
    reader = None
    if args.serial:
        reader = SerialReader(bridge, args.serial, loop, session_path.with_suffix(".serial.log"), quiet=args.quiet)
        bridge.serial = reader
        threading.Thread(target=reader.run, name="serial", daemon=True).start()
    if sys.stdin and sys.stdin.isatty():
        loop.add_reader(sys.stdin, lambda: bridge.on_key(sys.stdin.readline()))
    async with serve(bridge.handler, args.ws_host, args.ws_port):
        shown = session_path.relative_to(REPO) if session_path.is_relative_to(REPO) else session_path
        inputs = f"UDP {args.udp_host}:{args.udp_port}" + (f" + serial {args.serial}" if args.serial else "")
        info = coach.describe()
        print(f"bridge: {inputs} -> ws://{args.ws_host}:{args.ws_port} | session log {shown} | "
              f"coach {info['llm']} ({info['model']})", flush=True)
        if sys.stdin and sys.stdin.isatty():
            print("keys + Enter: [Enter] segment start/end, n naive, d designed, f sync flash", flush=True)
        try:
            await asyncio.gather(bridge.status_loop(), bridge.stats_loop())
        finally:
            if reader:
                reader.stop.set()
            transport.close()
            bridge.session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--udp-host", default="0.0.0.0", help="UDP bind address (0.0.0.0: accept the ESP32 on Wi-Fi)")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT)
    parser.add_argument("--ws-host", default="localhost")
    parser.add_argument("--ws-port", type=int, default=WS_PORT)
    parser.add_argument("--sessions", default=str(REPO / "sessions"), help="directory for the JSONL session logs")
    parser.add_argument("--serial", metavar="PORT", help="also read '@' messages from the board's USB serial port "
                        "(10_usb_stream), e.g. /dev/cu.usbmodem1101")
    parser.add_argument("--llm", choices=("mock", "ollama"), default="mock",
                        help="coach back end: a fixed rule, or a local model through Ollama (no API key either way)")
    parser.add_argument("--model", default=coach_mod.DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--ollama-url", default=coach_mod.OLLAMA_URL)
    parser.add_argument("--llm-timeout", type=float, default=coach_mod.TIMEOUT_S, help="seconds before the fallback")
    parser.add_argument("--mock-delay", type=float, default=0.8, help="thinking time of the mock coach in s")
    parser.add_argument("--mock-replies", metavar="FILE", help="JSON list of raw reply texts the mock returns "
                        "in order (tests: illegal and out-of-range commands)")
    parser.add_argument("--quiet", action="store_true", help="only the 5 s statistics")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # statistics show up promptly even when piped
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("bridge stopped")


if __name__ == "__main__":
    main()
