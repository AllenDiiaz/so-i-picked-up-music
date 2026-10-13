# Hardware session 1: first run of 08_wifi_stream (2026-10-13)

First session with the board after the replay-only MVP work, following [hardware_session_checklist.md](../hardware_session_checklist.md). Goal: flash 08, check Wi-Fi, LED and button, then measure the three levels on the guitar. The first part worked; the level test could not be done because the AD8232 module's output stayed near 0 V.

Data: the bridge session log and the board's USB log stayed local (not committed); the numbers below are taken from them. No MAC address appeared in any log.

## 1. Front-end design

Design **C** (edge glow) was chosen for the hardware tests after watching the replay of segment B: it needs no AR alignment and is visible while looking at the fretboard. A and B use fixed arm and neck positions without tracking.

## 2. 08 firmware on the board

| Check | Result |
|---|---|
| Build with the real `wifi_config.h` | **Bug found and fixed** (`b68add0`): the first flash ran the template settings because `wifi_config.h`, created after the first build, did not trigger a recompile (`__has_include` is invisible to the build system). CMake now re-checks for the file at every build |
| `wifi_config.h` tracked by git | No (ignored; checked with `git check-ignore` and `git status`) |
| Wi-Fi association | About 4.5 s after boot; RSSI -64 to -75 dBm, dips to -83 dBm (2.4 GHz network; the Mac was on the same router's 5 GHz network) |
| Stream to the bridge | 20 Hz; long stretches with 0 lost; ping to the board 6-10 ms |
| Sampling | `ovf=0`, `queue_drop=0`, `bad=0`, `send_fail=0` throughout |
| DSP time | 135-185 µs average per 16-sample frame; max 1.2-1.7 ms (first frames after boot), far below the 16 ms frame |
| MAC address in logs | None (every USB line and the bridge output were scanned) |
| LED on GPIO5 | Toggles on level changes |
| Button on GPIO6 | Works after rewiring (below); one press starts one calibration, holding does not repeat |

Button wiring fault: GPIO6 never read low, neither from the button nor from a wire touched to GND. A `button=` / `button_low_frames=` field was added to the status line (`368ae68`): it stayed 0 until a wire from the GPIO6 row was touched to GND directly (then counted up and triggered a calibration), so the board and firmware were fine. The cause was the button's wires not sharing breadboard rows with its legs. After moving them to diagonal legs, presses were detected.

Calibration with the button: pressing it with the left (measured) hand gave a baseline of 12.1 mV; pressing with the right hand while the left arm stayed relaxed gave 7.86 mV, inside the experiment 06 relax range (4.5-8.1 mV). Use the right hand.

## 3. Wi-Fi stalls (open defect)

Twice the board reported `wifi=up`, kept sending without errors, but almost nothing reached the Mac and ping to the board failed:

| Period | Duration | Received / 5 s (normal 100) |
|---|---|---|
| 21:42:50-21:44:15 | ~1.5 min | mostly 1-67 |
| 21:56:56-22:00:26 | ~3.5 min, intermittent | mostly 1-85 |

The first ended when the board was reset; the second recovered by itself. RSSI on the board stayed around -70 dBm with dips to -80 dBm. Both happened while the person was handling the board or the guitar next to it; whether the body blocking the antenna, the router or something else caused it is **not known**. Over the whole evening the bridge counted 4492 lost of 58674 (7.7 %), almost all in these two periods.

The firmware reconnects only on a disconnect event, so it cannot detect this state. **To fix:** a liveness check (for example the bridge echoing a small UDP reply every second, and the board reconnecting after several seconds without one), and counting the stall time in the status line.

## 4. AD8232 output stuck near 0 V (blocks the level test)

Symptom: levels frozen at "medium" and calibration rejected as `saturated`. A raw-input line was added to the status output (`31ed192`, `# raw_mV min= avg= max= at_low= at_high=` per 1000 samples). It showed the module's output sitting at 30-160 mV with many samples at 0 mV, instead of the ~1650 mV mean seen in the experiment 06 recordings (computed from `03_A_light_hard.log` and `04_B_chord.log`).

Fault isolation, using GPIO4 as a voltmeter (the yellow GPIO4 -> OUTPUT wire unplugged for the measurements on the module's rows):

| Test | Reading | Conclusion |
|---|---|---|
| New electrodes, skin cleaned with alcohol | 30 -> ~150 mV, falls back to ~30 mV after moving | Helped a little, not the cause |
| Lead cable unplugged from the module | ~60 mV (experiment 05: ~1600 mV without the cable) | Not the electrodes or the cable |
| GPIO4 to the module's 3.3v row | 3107 mV (ADC limit) | Supply reaches the module's row |
| GPIO4 to the module's GND row | 0 mV | Ground is connected |
| GPIO4 directly to the module's OUTPUT row | ~160 mV, same as through the yellow wire | The wire to GPIO4 is fine; the low level comes from the module |
| Pressing and bending the module's 3.3v / GND header pins | No change | No obvious loose solder joint |
| LO-, LO+, SDN rows | Empty | Not shut down by SDN |
| Heart LED on the module | Lit on hard grips the day before, never lit today | Consistent with an output that cannot swing |

Once, for about 3 s, the output went to 1600-1900 mV and fell back below 200 mV within about 2 s, so the chip can still drive its output.

Conclusion (inference, not proven): the AD8232 module is no longer working as it did in experiment 06, and nothing in the wiring explains it. Possible causes are damage during today's rewiring (for example plugging wires with power on) or a fault not visible from the header rows (a solder joint between a header pin and the board). The 3.3v and GND checks measured the breadboard rows, not the module's pads.

## 5. Not done (needs a working module)

- Three-level test on the guitar (one cued run was made, but the module was saturated throughout and no calibration was accepted, so it has no usable result)
- Latency with the phone's slow motion
- 5 min stability run (also blocked by the Wi-Fi stall defect)
- Recordings R1-R4 for the thresholds

## 6. Next session

1. Replace the AD8232 module (or reflow its header pins). Before the electrodes: with the lead cable unplugged, `raw_mV avg` should be around 1600 mV; with three electrodes on relaxed skin, around 1300-1650 mV with no `at_low` / `at_high`.
2. Fix the Wi-Fi stall detection in 08 first, so the 5 min run is meaningful.
3. Then continue the checklist from step 4 (calibration, right hand on the button).
