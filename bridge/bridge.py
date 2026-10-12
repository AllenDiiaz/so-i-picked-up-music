"""Mac bridge: UDP tension messages from the ESP32 (or the replayer) -> WebSocket for the browser.

    .venv/bin/python bridge/bridge.py [--udp-port 9750] [--ws-port 8765] [--sessions sessions]

- Receives protocol v1 messages (docs/protocol.md) on UDP, adds bridge_rx_ms and src, and
  broadcasts them to every WebSocket client on ws://localhost:<ws-port>.
- Sends a status message to the clients every second.
- Prints statistics every 5 s: received, lost and out-of-order (from seq), restarts, senders.
- Writes every forwarded message to sessions/<YYYYmmdd-HHMMSS>.jsonl (git-ignored); these logs
  are the input of tools/session_summary.py.
- A restarted ESP32 (new boot id, seq from 0) and browsers that disconnect and reconnect are
  handled without restarting the bridge. Malformed datagrams are counted and dropped.
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import UDP_PORT, VERSION, WS_PORT, SeqTracker, validate_device_message  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


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
        rx_ms = now_ms()
        src = f"{addr[0]}:{addr[1]}"
        try:
            msg = json.loads(data)
            validate_device_message(msg)
        except (ValueError, UnicodeDecodeError) as e:
            self.malformed += 1
            if self.malformed <= 5 and not self.quiet:
                print(f"malformed datagram from {src}: {e}")
            return
        # Track per device address (ip) and boot, so a restart that changes the source port is
        # seen as a restart rather than a second device.
        tracker = self.trackers.setdefault(addr[0], SeqTracker())
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
    async with serve(bridge.handler, args.ws_host, args.ws_port):
        print(f"bridge: UDP {args.udp_host}:{args.udp_port} -> ws://{args.ws_host}:{args.ws_port} | "
              f"session log {session_path.relative_to(REPO) if session_path.is_relative_to(REPO) else session_path}",
              flush=True)
        try:
            await asyncio.gather(bridge.status_loop(), bridge.stats_loop())
        finally:
            transport.close()
            bridge.session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--udp-host", default="0.0.0.0", help="UDP bind address (0.0.0.0: accept the ESP32 on Wi-Fi)")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT)
    parser.add_argument("--ws-host", default="localhost")
    parser.add_argument("--ws-port", type=int, default=WS_PORT)
    parser.add_argument("--sessions", default=str(REPO / "sessions"), help="directory for the JSONL session logs")
    parser.add_argument("--quiet", action="store_true", help="only the 5 s statistics")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)   # statistics show up promptly even when piped
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("bridge stopped")


if __name__ == "__main__":
    main()
