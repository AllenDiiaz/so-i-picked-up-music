# Hardware session 2: reflowed AD8232, Wi-Fi interference, MVP over USB (2026-10-18)

Second session with the board, continuing [session 1](08_hardware_session_1.md). Result: the AD8232 fault was a solder problem; Wi-Fi (08) raises the noise so much that relax calibration fails; over USB (new firmware `10_usb_stream`) the whole path arm -> ESP32 -> Mac bridge -> browser (design C) works and the three levels were measured once.

Setup as in session 1: ESP32-S3 on the breadboard, AD8232 module (3.3v, GND, OUTPUT -> GPIO4), new adhesive electrodes on the left forearm (skin cleaned with alcohol), laptop charger unplugged. One subject.

Data: [`docs/data/09_hardware_session_2/`](../data/09_hardware_session_2/) (see its README). LAN IP addresses in the logs are replaced by `[LAN IP]`; no MAC address appeared.

In the tables, **evidence** is what the logs show; **inference** is marked as such.

## 1. Reflowed AD8232 module

The 3.3v and GND header pins of the module were reflowed. With the lead cable unplugged and 08 on the board, `raw_mV avg` over 30 s was 1609-1620 mV per second (min 1538, max 1689 mV), with no samples at either rail. Session 1 measured about 60 mV in the same condition; experiment 05 measured 1624-1678 mV.

Evidence: the module's output is back at its normal operating point after the reflow. The session 1 conclusion is corrected accordingly (3.3v/GND solder joints, not a faulty module).

## 2. 07 vs 08: Wi-Fi raises the noise

With 08 and electrodes on, calibration kept failing. After the RST button (17:15), six boot calibration attempts were rejected as `too_high` (RMS 19.5-27.4 mV). To separate Wi-Fi from everything else, the same electrodes and the same posture (left forearm flat on the table, fully relaxed) were measured with 07 (no Wi-Fi) and then 08 (Wi-Fi streaming), 30 s each, starting 30 s after boot. 07 got the same once-per-second `raw_mV` line as 08 for this (output only, DSP unchanged).

| | 07 (no Wi-Fi) | 08 (Wi-Fi) | Experiment 06 |
|---|---|---|---|
| Calibration | accepted at attempt 1 (CV 0.307) | 8 attempts rejected, `too_high` (RMS 15.4-23.7 mV) | - |
| Baseline | **7.26 mV** | none | 4.5-8.1 mV relax |
| Relax RMS (600 hops) | median **6.51 mV** (p10 5.23, p90 8.17) | median **15.53 mV** (mean 20.0, p10 12.4, p90 35.5) | 4.6-8.1 mV |
| Levels | 600 x relax | 600 x -1 (no baseline) | - |
| Raw peak-to-peak per second | median 797 mV (719-869) | median 1744 mV (950-2303) | 215-287 mV |
| Samples at a rail | 0 | 21 at the low rail | - |
| Transport | - | 0 lost, RSSI -51 dBm, `send_fail=0` | - |

Files: `07_relax.serial.log`, `08_relax.serial.log`, `08_relax.bridge.jsonl`.

Evidence: with Wi-Fi on, the relaxed-forearm RMS is about 2.4 times higher and calibration fails; nothing else changed between the two runs except the firmware.

Inference (not tested): the coupling path is unknown. Candidates are the Wi-Fi transmit current pulses on the shared 3V3 supply of the ESP32 and the AD8232, and radiation from the antenna into the lead cable. The 08 calibration in session 1 (7.86 mV) is not comparable: the module's solder joints were faulty then and its output could not swing.

The raw peak-to-peak value includes components outside 45-200 Hz (baseline drift, ECG, 60 Hz) that the DSP removes, so it is a noise indicator, not an EMG amplitude.

**Decision:** the MVP streams over USB for now; the Wi-Fi interference becomes a separate experiment later (candidate fixes: decoupling capacitors at the module, lower Wi-Fi TX power, more distance between antenna and leads, a separate supply for the AD8232; each can be checked with the same 07-vs-08 relax comparison).

## 3. USB streaming (10_usb_stream)

New firmware [`10_usb_stream`](../../firmware/experiments/10_usb_stream): the 07 DSP printing one protocol v1 message per hop as an `@`-prefixed JSON line, plus the `#` diagnostics; LED on GPIO5 toggles on level changes. `bridge/bridge.py --serial /dev/cu.usbmodem1101` turns the `@` lines into the same messages the UDP path produces, so the front end and session logs are unchanged.

| Check | Result |
|---|---|
| Stream | 20 messages/s; 16516 received, 0 lost over the session (one partial line read when the port was first opened was counted as malformed) |
| Bridge reconnect after RST | Works: the port disappeared ("Device not configured", then "No such file"), the bridge reopened it and picked up the new boot. Opening the port reset the board once more (`rst:0x15 USB_UART_CHIP_RESET`), so one RST shows as two restarts |
| First calibrations | accepted at 9.47 mV and, after RST, 10.64 mV; relax RMS median 11.2-12.5 mV, raw peak-to-peak median 1146-1372 mV, above the 07 run |
| Later in the session | relax RMS 4.3-6.4 mV and raw peak-to-peak median 771-855 mV (runs 1 and 2), close to 07 |

Inference: the high values right after switching to 10 did not last, so the larger USB output (about 5 kB/s of JSON vs about 0.6 kB/s of CSV in 07) is unlikely to be the cause; electrode settling is a possible explanation (the relax RMS also fell from 8.3 to 6.4 mV within run 1). Not tested.

Side findings:
- After the RST button, a plain pyserial reader's open handle went silent without an error (the board kept running); the bridge therefore reopens the port after 3 s without data.
- Once after RST, flashing failed with `No serial data received` until the USB cable was unplugged and replugged.

## 4. Three-level test, run 1 (baseline 10.64 mV)

Spoken cues (macOS `say`), 60 s: 0 relax, 10 light, 15 relax, 25 hard, 30 relax, 40 light, 45 relax, 55 hard. Light = half-strength fist, hard = full fist, forearm flat on the table. Phase windows skip 1.5 s after each cue.

| Phase | relax | medium | hard | norm mean | RMS median |
|---|---|---|---|---|---|
| 0 s relax | 100 % | 0 | 0 | 0.77 | 8.3 mV |
| 10 s light | 96 % | 4 % | 0 | 0.93 | 9.4 mV |
| 15 s relax | 100 % | 0 | 0 | 0.68 | 7.1 mV |
| 25 s hard | 100 % | 0 | 0 | 1.00 | 10.8 mV |
| 30 s relax | 100 % | 0 | 0 | 0.64 | 6.7 mV |
| 40 s light | 100 % | 0 | 0 | 0.77 | 8.2 mV |
| 45 s relax | 100 % | 0 | 0 | 0.61 | 6.4 mV |
| 55 s hard | 91 % | 9 % | 0 | 1.07 | 11.1 mV |

Evidence: the efforts barely raised the signal (per-second RMS maximum 10-14 mV in the hard phases, once 21 mV; raw peak-to-peak unchanged), and the baseline was above the relax level during the test. Light and hard were not detected.

Files: `usb_three_level_run1.*`.

## 5. Squeeze check

Spoken cues: squeeze hard 3 s, relax 3 s, twice.

| | RMS |
|---|---|
| Relax | 4.3-5.3 mV per second (median) |
| Squeeze 1 | median 38-40 mV, max 57 mV -> hard |
| Squeeze 2 | median 33-36 mV, max 69 mV -> hard; 14 saturated hops |

Evidence: the electrodes, the module and the DSP respond strongly to a real full grip (7-8 times relax, more than experiment 06's 20.7-32.3 mV). So the weak efforts in run 1 were in the movement, not in the signal path (inference: the subject gripped much less than in this check during run 1; the cues were the same words).

The rise came about 2 s after the "squeeze hard" cue and the fall about 1.5 s after "relax". This is the time to speak the cue plus the person's reaction, **not system latency**; experiment 06 saw a similar 1.2-1.65 s lag after spoken cues.

Files: `usb_squeeze_check.*`.

## 6. Three-level test, run 2 (baseline 6.42 mV)

Recalibrated after RST (attempt 1 rejected `unstable`, CV 0.505; attempt 2 accepted, 6.415 mV, CV 0.282). Same cues as run 1. 0 lost, no recalibration, no saturation during the test.

| Phase | relax | medium | hard | norm mean | RMS median | Correct (skip 1.5 s) | Correct (skip 2.5 s) |
|---|---|---|---|---|---|---|---|
| 0 s relax | **100 %** | 0 | 0 | 1.01 | 6.4 mV | 100 % | 100 % |
| 10 s light | 21 % | **66 %** | 13 % | 1.79 | 10.7 mV | 66 % | 61 % |
| 15 s relax | **100 %** | 0 | 0 | 0.90 | 5.8 mV | 100 % | 100 % |
| 25 s hard | 4 % | 24 % | **72 %** | 3.12 | 19.6 mV | 72 % | 68 % |
| 30 s relax | **99 %** | 1 % | 0 | 0.70 | 4.3 mV | 99 % | 100 % |
| 40 s light | 86 % | 14 % | 0 | 1.05 | 6.2 mV | 14 % | 0 % |
| 45 s relax | **100 %** | 0 | 0 | 0.89 | 5.8 mV | 100 % | 100 % |
| 55 s hard | 0 | 0 | **100 %** | 4.18 | 24.2 mV | 100 % | 100 % |

First hop at the target level after each cue: 1.4-1.7 s for light and hard (reaction time, see section 5).

Misclassifications:
- **Second light (40 s) almost missed.** Evidence: medium appeared briefly 1.4 s after the cue, then the RMS stayed at 6.2 mV, the relax level. Inference: the grip was too light or released early; the levels follow the signal.
- **First hard (25 s): 24 % medium.** Evidence: norm mean 3.12, just above the hard entry threshold 2.72, so a slightly weaker moment drops to medium (exit at 2.45). Inference: effort varied within the 5 s.
- **First light (10 s): 13 % hard.** Evidence: norm reached the hard range at times. Inference: the half-strength grip overshot.
- **Relax: no misclassification** in four phases (99-100 %).

Front end: the bridge forwarded every message to the open browser page (design C) throughout. Whether the colours matched what the subject did was not reported back, so it is **not confirmed** here.

Files: `usb_three_level_run2.*`.

## 7. Open points

- Wi-Fi interference (section 2): own experiment, then return to 08.
- Wi-Fi stall detection in 08 (session 1) is still open.
- Repeat the three-level test with a steadier light grip and longer phases (the 1.5-2 s reaction lag eats into 5 s effort phases); then latency with the LED and the phone's slow motion (the LED toggles in 10 too), the 5 min run and the R1-R4 recordings.
- The thresholds are still the provisional in-sample values from experiment 06.
