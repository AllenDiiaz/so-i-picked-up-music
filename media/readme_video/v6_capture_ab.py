"""Capture the A/B scene of the README video: the real front end, driven by the simulated device,
once in naive and once in designed mode.

    .venv/bin/python media/readme_video/v6_capture_ab.py

For each mode: tools/fake_device.py (experiment 06 recording, firmware C code, SIMULATED timing)
+ bridge.py (mock coach, 2.5 s thinking time) + the page web/?view=cores in headless Chrome.
One short practice segment (2.5 s, forearm relaxed) is recorded; screenshots are taken as fast as Chrome delivers them from
1.5 s before the segment ends to 5.5 s after, and resampled to 12 fps relative to the segment
end, so both modes line up. Output: build/ab/<mode>/NNN.png and build/ab/meta.json.
"""
import io
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "build" / "ab"
PY = sys.executable
FPS, BEFORE, AFTER = 12, 1.5, 5.5
VIEW = {"width": 520, "height": 430}
SCALE = 1.3
THINK_S = 2.5


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def capture(mode):
    out = OUT / mode
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    udp, ws, http = free_port(socket.SOCK_DGRAM), free_port(), free_port()
    link = OUT / f"port_{mode}"
    procs = [subprocess.Popen([PY, str(REPO / "tools/fake_device.py"), "--mode", mode, "--loop", "--link", str(link)],
                              stdout=subprocess.DEVNULL)]
    time.sleep(1.0)
    procs += [
        subprocess.Popen([PY, str(REPO / "bridge/bridge.py"), "--serial", str(link), "--udp-host", "127.0.0.1",
                          "--udp-port", str(udp), "--ws-port", str(ws), "--sessions", str(OUT / "sessions"),
                          "--quiet", "--llm", "mock", "--mock-delay", str(THINK_S)], stdout=subprocess.DEVNULL),
        subprocess.Popen([PY, "-m", "http.server", str(http), "--bind", "127.0.0.1", "--directory", str(REPO / "web")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport=VIEW, device_scale_factor=SCALE)
            page.goto(f"http://127.0.0.1:{http}/?ws=ws://localhost:{ws}&view=cores&timeline_ms=12000")
            page.wait_for_function("window.__mvp.last && window.__mvp.last.level >= 0", timeout=30000)
            # Timing against recording A (board time): calibration ends at 5.5 s, the first effort
            # starts near 15 s. The segment runs from about 6.2 to 8.7 s and the capture ends near
            # 14.2 s, so the forearm is relaxed throughout and the edge glow stays quiet.
            time.sleep(0.6)
            page.keyboard.press(" ")                    # segment start
            time.sleep(1.0)
            shots, t0, ended = [], time.monotonic(), None
            while time.monotonic() - t0 < BEFORE + AFTER + 0.3:
                if ended is None and time.monotonic() - t0 >= BEFORE:
                    page.keyboard.press(" ")            # segment end
                    ended = time.monotonic()
                shots.append((time.monotonic(), page.screenshot()))
            info = page.evaluate("JSON.stringify({coach: window.__mvp.coach, mode: window.__mvp.rtMode, "
                                 "simulated: window.__mvp.simulated})")
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
    times = [t - ended for t, _ in shots]
    n = int((BEFORE + AFTER) * FPS)
    for k in range(n):
        tau = -BEFORE + k / FPS
        i = min(range(len(times)), key=lambda j: abs(times[j] - tau))
        Image.open(io.BytesIO(shots[i][1])).convert("RGB").save(out / f"{k:03d}.png")
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {"frames": n, "screenshots": len(shots), "max_gap_ms": round(1000 * max(gaps)), "state": json.loads(info)}


if __name__ == "__main__":
    meta = {"fps": FPS, "before_s": BEFORE, "after_s": AFTER, "think_s": THINK_S, "view": VIEW, "scale": SCALE}
    for mode in ("naive", "designed"):
        meta[mode] = capture(mode)
        c = meta[mode]["state"]["coach"]
        print(f"{mode}: {meta[mode]['screenshots']} screenshots (max gap {meta[mode]['max_gap_ms']} ms) -> "
              f"{meta[mode]['frames']} frames; coach: {c and c['feedback']!r}, command {c and c['command']}")
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
