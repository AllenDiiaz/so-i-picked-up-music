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
from protocol import UDP_PORT, VERSION, WS_PORT, SeqTracker, validate_device_message  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SERIAL_SILENT_S = 3.0      # the board prints at least every 50 ms; silence means a stale handle
_MAC = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")


def now_ms():
    return time.time() * 1000.0


class Bridge:
    def __init__(self, session_path, quiet=False):
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
            validate_device_message(msg)
        except (ValueError, UnicodeDecodeError) as e:
            self.malformed += 1
            if self.malformed <= 5 and not self.quiet:
                print(f"malformed message from {src}: {e}")
            return
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
        msg["bridge_rx_ms"] = rx_ms
        msg["src"] = src
        text = json.dumps(msg, separators=(",", ":"))
        self.session.write(text + "\n")
        broadcast(self.clients, text)

    # --- WebSocket side ---------------------------------------------------------------------
    async def handler(self, websocket):
        self.clients.add(websocket)
        if not self.quiet:
            print(f"browser connected ({len(self.clients)} open)")
        try:
            await websocket.send(json.dumps(self.status()))
            async for _ in websocket:   # clients do not send anything; just wait for the close
                pass
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
                "sources": sorted(s for s, t in self.sources_seen.items() if t >= cutoff)}

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
        if not self.quiet and ("calibration" in line or "button:" in line or "rst:" in line):
            print(f"serial: {line}")

    def run(self):
        import serial   # pyserial; only needed in serial mode
        while not self.stop.is_set():
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = self.port, 115200, 0.2
            ser.dtr = ser.rts = False          # do not reset the board on open
            try:
                ser.open()
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
    bridge = Bridge(session_path, quiet=args.quiet)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: UdpProtocol(bridge),
                                                       local_addr=(args.udp_host, args.udp_port))
    reader = None
    if args.serial:
        reader = SerialReader(bridge, args.serial, loop, session_path.with_suffix(".serial.log"), quiet=args.quiet)
        threading.Thread(target=reader.run, name="serial", daemon=True).start()
    async with serve(bridge.handler, args.ws_host, args.ws_port):
        shown = session_path.relative_to(REPO) if session_path.is_relative_to(REPO) else session_path
        inputs = f"UDP {args.udp_host}:{args.udp_port}" + (f" + serial {args.serial}" if args.serial else "")
        print(f"bridge: {inputs} -> ws://{args.ws_host}:{args.ws_port} | session log {shown}", flush=True)
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
    parser.add_argument("--quiet", action="store_true", help="only the 5 s statistics")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # statistics show up promptly even when piped
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("bridge stopped")


if __name__ == "__main__":
    main()
