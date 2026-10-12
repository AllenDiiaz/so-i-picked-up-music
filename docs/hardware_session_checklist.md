# Hardware session checklist

Everything that could be done without the board is done and tested with replayed data ([mvp.md](mvp.md)). This list is for the next session with the ESP32-S3, the AD8232 module and electrodes. Work top to bottom; each step says what to write down.

Before starting: `git pull`, `.venv` set up (`.venv/bin/pip install -r analysis/requirements.txt`), ESP-IDF v6.0.3 installed, phone with slow-motion video (240 fps if available), fresh electrode pads.

## 1. Button and LED wiring

| GPIO | Connect | Notes |
|---|---|---|
| 4 | AD8232 OUTPUT | As in experiments 05-07 |
| 6 | Push button to **GND** | No resistor needed: the internal pull-up is enabled; pressed = low. Two consecutive low 16 ms frames count as a press |
| 5 | LED anode through a 220-470 Ω resistor, cathode to GND | Toggles at every level change; used for the latency measurement (step 6) |

AD8232: 3.3v -> 3V3, GND -> GND; LO+, LO- and SDN not connected.

- [ ] Button wired GPIO6 <-> GND
- [ ] LED with resistor on GPIO5
- [ ] Board on USB, port is `/dev/cu.usbmodem1101` (`ls /dev/cu.usb*`)

## 2. Electrodes

Placement as in experiment 06 ([notes](experiments/06_forearm_emg.md#2-setup)), left forearm (fretting hand):

- red and yellow pads 2-3 cm apart along the forearm flexors (inner forearm, a third of the way from elbow to wrist), along the muscle;
- green (reference) on the bony point of the elbow.

- [ ] Skin clean and dry, pads pressed on firmly, lead cable clipped
- [ ] **Wait 30 s** after the pads are on before calibrating: the skin-electrode contact and the AD8232's high-pass filter need time to settle (how long exactly has not been measured; a calibration on an unsettled signal is rejected as `saturated` or `unstable`, or gives a wrong baseline)
- [ ] Sit in the playing posture with the guitar, fingers resting on the strings

## 3. Flash 08 and set up Wi-Fi

Details in the [08 README](../firmware/experiments/08_wifi_stream/README.md).

```sh
cp firmware/experiments/08_wifi_stream/main/wifi_config.h.example \
   firmware/experiments/08_wifi_stream/main/wifi_config.h
# edit: WIFI_SSID, WIFI_PASSWORD, BRIDGE_HOST = output of `ipconfig getifaddr en0`; delete the WIFI_CONFIG_IS_EXAMPLE line
git status --short          # wifi_config.h must NOT appear
cd firmware/experiments/08_wifi_stream
. ~/esp/esp-idf-v6.0.3/export.sh
idf.py build
idf.py -p /dev/cu.usbmodem1101 flash monitor
```

- [ ] `git status` does not list `wifi_config.h`
- [ ] Boot log: no "using the template" warning; `wifi=up` in the status line within a few seconds
- [ ] **No MAC address or BSSID anywhere in the monitor output** (search for `:` groups like `aa:bb:...`). If one appears, do not paste the log anywhere; note which line printed it
- [ ] Status line: `ovf=0`, `queue_drop=0`, `bad=0`, `dsp_us_frame_max` well below 16000
- [ ] Press the button: `# button: calibration started`, then a `calibration attempt` line
- [ ] LED toggles when the level changes (squeeze the fist)

Untested parts of 08 to watch: reconnect after turning the access point off and on (`reconnects=` should rise and `wifi=up` return), `send_fail=` staying at 0.

## 4. Calibration

The board calibrates by itself 0.5 s after boot; a rejected attempt is retried every 2 s. The button starts a new attempt at any time.

1. Wait the 30 s from step 2, guitar in hand, fingers resting on the strings, forearm relaxed.
2. Press the button, stay still for 5 s.
3. Read the result: `# calibration attempt N: accepted ... baseline_mv=...` (or in the browser, the `cal` result).
4. If rejected:
   - `saturated`: signal at the rails, usually a loose pad or the 30 s not over; press the pads, wait, retry;
   - `too_high` (RMS >= 15 mV): the arm was not relaxed, or noise; relax and retry;
   - `unstable` (CV >= 0.5): movement during the 5 s; stay still and retry.

- [ ] Write down: attempts until accepted, and `baseline_mv` (experiment 06: 4.5-8.1 mV relax)

## 5. Switch from replay to the real board

The bridge and front end do not change; only the sender does.

```sh
.venv/bin/python bridge/bridge.py                                     # terminal 1: listens on UDP 9750, all interfaces
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory web  # terminal 2
```

Open http://localhost:8000/. Do **not** run `tools/replay_stream.py` or `scripts/run_replay_demo.sh` at the same time (both would send to port 9750).

- [ ] Bridge prints the board's address as a new source, `dev` = `esp32s3-emg`; macOS may ask to allow incoming connections for Python: allow
- [ ] Front end leaves "no data", shows "calibrating" and then levels
- [ ] Bridge's 5 s stats line: `lost` near 0

If nothing arrives: same Wi-Fi network for Mac and board? `BRIDGE_HOST` is the Mac's current address? macOS firewall? `nc -ul 9750` (with the bridge stopped) shows whether datagrams reach the Mac.

## 6. Latency with the phone's slow motion

What is measured: from the board deciding a level change (LED toggles in the same step that produces the message) to the screen changing colour. The algorithm delay before that (122-193 ms, measured offline) is added afterwards.

1. Put the board's LED next to the screen so both are in one frame; film in slow motion (240 fps = 4.2 ms per frame; 120 fps = 8.3 ms).
2. Use design B or C (large colour change), screen brightness at maximum.
3. Squeeze and release the fist about 20 times, 2 s each, filming the whole time.
4. Step through the video frame by frame: for each LED change, count frames until the screen colour starts to change.
5. Device-to-screen delay = frames x (1000 / fps) ms. Write down median and maximum.
6. End-to-end estimate = algorithm delay (median ~150 ms) + device-to-screen median. Target < 300 ms ([mvp.md](mvp.md#completion-criteria)).

Also write down the front end's live readouts (`bridge -> browser`, `browser -> render`) during the run. The front end's smoothing (TAU 60 ms) starts the colour change in the first frame, so count the first visible change, not the end.

- [ ] Device-to-screen median / max: ____ / ____ ms (fps: ___)

## 7. Recordings to validate the thresholds

The thresholds (enter 1.49x / 2.72x, exit 1.35x / 2.45x) are in-sample from experiment 06 and the calibration baseline in the replays came from before each recording. New data, all with the guitar, after the 30 s wait and an accepted calibration:

| # | Recording | Firmware | Cues |
|---|---|---|---|
| R1 | Raw guitar session for offline analysis | `06_raw_emg_stream` (raw 1 kHz samples, so the DSP and thresholds can be re-run offline) | 0 relax (fingers on strings, 10 s), then 3x: chord light 5 s, relax 10 s, chord hard 5 s, relax 10 s |
| R2 | Same protocol live | `08_wifi_stream` + bridge (session log in `sessions/`) | Same cues, while watching the front end |
| R3 | Playing | `08_wifi_stream` + bridge | 2-3 min of normal playing (simple chord changes), then 5 min continuous for criteria 3 and 4 |
| R4 (optional) | Second day or new pads | `06_raw_emg_stream` | R1 again: is the baseline and threshold scaling repeatable? |

For R1 (raw):

```sh
cd firmware/experiments/06_raw_emg_stream && idf.py -p /dev/cu.usbmodem1101 flash && cd -
.venv/bin/python analysis/record_serial.py /dev/cu.usbmodem1101 docs/data/<new folder>/R1_guitar.log \
    --seconds 100 --cues "0:relax,10:light,15:relax,25:hard,30:relax,40:light,45:relax,55:hard,60:relax,70:light,75:relax,85:hard,90:relax"
```

(New recordings go in a new folder; existing data in `docs/data/` stays unchanged.) Then flash 08 again for R2 and R3.

What to check afterwards:

- [ ] Relax RMS during the recording vs the calibration baseline: is the baseline taken in playing posture closer than in experiment 06?
- [ ] Phase table (correct share per phase) with the current thresholds; criterion 1 in [mvp.md](mvp.md)
- [ ] Calibration CV in relax: still 0.24-0.44, i.e. is the 0.5 limit right?
- [ ] R3: `tools/session_summary.py` on the session log: `loss_rate`, `restarts` = 0, longest gap
- [ ] Any saturation during chords (B's first hard chord was at the ADC rails for 1.7 s): if so, note posture and pad placement

## 8. Quest (optional, after the above)

WebXR needs HTTPS or localhost on the headset. Not set up yet; the AR button in the front end is written but untested.

## After the session

- [ ] Fill in the measured values in [mvp.md](mvp.md) and the 08 README; change "untested" only for what was actually tested
- [ ] Commit new data (no MAC addresses in logs; `wifi_config.h` not tracked)
