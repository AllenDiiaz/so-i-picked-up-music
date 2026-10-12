"""Headless screenshots of the front end while a replay is running.

    .venv/bin/python tests/screenshot_frontend.py [OUT_DIR]      (default /tmp/mvp_screens)

Needs Playwright (tests/requirements.txt) and Google Chrome (used through channel="chrome", so
no browser download). Starts the bridge, a static HTTP server for web/ and a replay of segment A
at 2x, opens one page per feedback design (A, B, C) and saves screenshots while the display is
calibrating, at relax, at medium and at hard (the replay is paused with SIGSTOP so all three
pages show the same message). Checks that the display actually changed between them (state read
from window.__mvp).
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mvp_screens")
    out.mkdir(parents=True, exist_ok=True)
    udp, ws, http = free_port(socket.SOCK_DGRAM), free_port(), free_port()
    procs = [
        subprocess.Popen([PY, str(REPO / "bridge/bridge.py"), "--udp-port", str(udp), "--ws-port", str(ws),
                          "--sessions", str(out / "sessions"), "--quiet"], stdout=subprocess.DEVNULL),
        subprocess.Popen([PY, "-m", "http.server", str(http), "--bind", "127.0.0.1", "--directory", str(REPO / "web")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    time.sleep(1.5)
    shots = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True,
                                        args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            pages = {}
            for mode in "ABC":
                page = browser.new_page(viewport={"width": 1280, "height": 760})
                page.goto(f"http://127.0.0.1:{http}/index.html?mode={mode}&ws=ws://127.0.0.1:{ws}&nodata_ms=10000")
                pages[mode] = page
            pages["A"].wait_for_function("window.__mvp && window.__mvp.wsOpen", timeout=20000)
            replay = subprocess.Popen([PY, str(REPO / "tools/replay_stream.py"), "--log", "03_A_light_hard.log",
                                       "--speed", "2", "--port", str(udp), "--quiet"], stdout=subprocess.DEVNULL)
            procs.append(replay)
            # Each state must hold for a few messages, so the screenshot shows it and not a blip.
            steady = "(n, lv) => { const h = window.__mvp.history.slice(-n); return h.length === n && h.every(e => e.level === lv); }"
            wanted = {"calibrating": "m.calibrating", "relax": f"!m.calibrating && ({steady})(10, 0)",
                      "medium": f"({steady})(6, 1)", "hard": f"({steady})(4, 2) && m.norm > 4"}
            for name, cond in wanted.items():
                pages["A"].wait_for_function(f"(() => {{ const m = window.__mvp.last; return m && ({cond}); }})()",
                                             timeout=60000, polling=20)
                # Freeze the stream so all three pages show the same message, then let the
                # smoothing settle before capturing.
                os.kill(replay.pid, signal.SIGSTOP)
                time.sleep(0.4)
                for mode, page in pages.items():
                    path = out / f"{mode}_{name}.png"
                    page.screenshot(path=str(path))
                    st = page.evaluate("(() => { const s = window.__mvp; return {level: s.last.level, norm: s.last.norm,"
                                       " intensity: s.display.intensity, color: s.display.color.getHexString(),"
                                       " net: s.netLat.slice(-1)[0], render: s.renderLat.slice(-1)[0], frames: s.frames}; })()")
                    shots[f"{mode}_{name}"] = st
                    print(f"{path}: {json.dumps(st)}")
                os.kill(replay.pid, signal.SIGCONT)
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
    # The display must differ between states (colour or intensity).
    for mode in "ABC":
        states = [(shots[f"{mode}_{n}"]["color"], round(shots[f"{mode}_{n}"]["intensity"], 2)) for n in wanted]
        assert len(set(states)) == len(states), f"design {mode}: display did not change between states {states}"
    print("ok: the display changed between calibrating, relax, medium and hard in all three designs")


if __name__ == "__main__":
    main()
