# MVP: definition of done and status

The MVP is done when a guitarist wearing the electrodes sees their forearm tension (relax / medium / hard) change in the browser while playing, reliably enough to practise with. Architecture: [architecture.md](architecture.md).

The coach loop (a local language model commenting on each practice segment and adjusting one threshold on the board) is an extension on top of the MVP; its status is in the second table below. It does not change the completion criteria.

## Completion criteria

| # | Criterion | Target | How it is checked |
|---|---|---|---|
| 1 | Three levels shown correctly | During cued relax, medium (light grip / chord) and hard phases on the guitar, the shown level matches the cue in most of each phase's analysis window (first 1.5 s after the cue skipped, as in experiment 06). Concrete bar: >= 80 % correct for relax and hard, >= 60 % for medium | New recordings with the 08 firmware, scored with `analysis/validate_07_tension.py`-style phase tables |
| 2 | End-to-end latency | < 300 ms from a change in muscle tension to the change on screen, median over at least 20 level changes | Offline algorithm delay (measured) + device-to-screen delay (LED and phone slow motion, see the checklist) |
| 3 | Stability | 5 min continuous streaming without a disconnect, device restart or browser reload | Bridge log: one `boot` value, `sources` never empty for more than 1 s; front end never shows "no data" |
| 4 | Packet loss | < 1 % lost over the 5 min run, no gap longer than 0.5 s (10 messages) | Bridge `lost / (received + lost)`; `tools/session_summary.py` (`loss_rate`) |

### Why 300 ms

- The level is a judgement about sustained muscle state ("am I squeezing too hard while holding this chord?"), not about note timing, so the feedback does not need to be as fast as audio. It must be fast enough that the player links the colour change to what they just did.
- The algorithm alone takes 122-193 ms to show an onset (measured offline, [architecture.md](architecture.md#latency-sources)). That delay comes from the 200 ms RMS window, which a stable EMG level needs; a shorter window would make the level flicker.
- 300 ms leaves about 100 ms for the board's frame collection, Wi-Fi, bridge, browser smoothing and display, which is several times their expected sum (tens of ms).
- That roughly 300 ms is still felt as "right after" an action is a working assumption for this project, not a value taken from a study. If the hardware session shows the feedback feels late, the window length and smoothing are the knobs.

## Current status (2026-11-16; last hardware session: session 2, 2026-10-18)

| Part | Status | Evidence |
|---|---|---|
| On-board DSP, calibration with retry, hysteresis (07) | Done; validated on recordings (host) | C vs float64 reference identical in levels; [07 README](../firmware/experiments/07_onboard_tension/README.md) |
| Three levels on recordings | Partly met on recordings: A relax 91.2 %, medium 78.0 %, hard 100 %; B (guitar chords) relax 67.2 %, medium 30.2 % | Thresholds are provisional and in-sample; B misses criterion 1 |
| Protocol v1 | Done | [protocol.md](protocol.md), `bridge/protocol.py` |
| Replayer, bridge, front end (three designs) | Done, tested with replayed data | `tests/test_e2e_replay.py` passes for A and B: every message received, seq continuous, levels identical to the host test |
| Wi-Fi firmware (08) | **Partly tested on the board**: streaming, LED, button, no MAC in logs. **Not usable for EMG yet:** with Wi-Fi on, the relaxed-forearm RMS is 15.5 mV instead of 6.5 mV (07), so calibration fails (session 2). Open defect: Wi-Fi stalls while `wifi=up` are not detected (session 1) | [Session 1](experiments/08_hardware_session_1.md), [session 2](experiments/09_hardware_session_2.md#2-07-vs-08-wi-fi-raises-the-noise) |
| USB firmware (10) + `bridge.py --serial` | **Tested on the board** (session 2): arm -> ESP32 -> USB -> bridge -> browser, 16516 messages, 0 lost; bridge reconnects after RST. This is the MVP transport for now | [10 README](../firmware/experiments/10_usb_stream/README.md) |
| Session summary, letter prompt | Done (prompt printed only, no model call) | Run on a replay session log |
| Criterion 1 on the board | **First run done** (session 2, forearm flat on the table, fists instead of chords, one run): relax 99-100 % in all four phases, hard 72 % and 100 %, light 66 % and 14 % (the second light grip was too weak). Bar (relax and hard >= 80 %, medium >= 60 %) not yet met reliably. The module fault of session 1 was a solder joint, fixed | [Session 2](experiments/09_hardware_session_2.md#6-three-level-test-run-2-baseline-642-mv) |
| Criterion 2 (latency) | Algorithm part measured offline; device-to-screen part needs hardware | |
| Criteria 3, 4 (5 min, loss) | USB: 0 lost over about 14 min of streaming (session 2), but no dedicated 5 min run yet. Wi-Fi (session 1): two multi-minute stalls, 7.7 % lost | 5 min run over USB next |
| Front end | Desktop browser, design C (edge glow) is the default. **Browser view, WebXR-ready**: the `immersive-ar` session code is in `web/app.js` but has never been run on a headset. No AR is claimed | `tests/screenshot_frontend.py` passes for all three designs |
| Wi-Fi transport | **Known problem, not in use.** Relaxed-forearm RMS 6.5 mV -> 15.5 mV with Wi-Fi on, calibration fails | [Session 2](experiments/09_hardware_session_2.md#2-07-vs-08-wi-fi-raises-the-noise) |

### Coach loop (added 2026-11-16, no hardware session yet)

"Tested" below means against the simulated device (`tools/fake_device.py`: experiment 06 recordings through the firmware's own C code behind a pseudo-terminal; timing is simulated).

| Part | Status | Evidence |
|---|---|---|
| Firmware `11_coach_loop`: downlink commands, `cmd_rx` task on core 0, parameter hand-over to the sampler, acks, per-second `cores` message, naive mode | **Built, not yet run on the board.** `idf.py build` passes | [11 README](../firmware/experiments/11_coach_loop/README.md) |
| Command parser and scaled hard threshold (`components/coach`) | Tested on the host: 32 malformed lines rejected, clamping, level identical to `emg_dsp` at `hard_scale` 1.00 on both experiment 06 recordings (1495 and 1295 hops) | `make -C firmware/experiments/11_coach_loop/host_test test` |
| Bridge: one serial handle for both directions, segments from keyboard / browser / board button, coach call in a worker thread (10 s timeout), validation and clamping, fallback, everything logged | Tested (board button: code path only, no simulated button) | `tests/test_e2e_coach.py` |
| Coach, mock rule | Tested | Same test |
| Coach, local Ollama (`llama3.2:3b`) with a JSON schema | One real round trip run and saved: reply in 0.7 s warm (7.2 s from cold, hence the warm-up at start), command acked. The model's judgement is weak: with 82 % relax it raised `hard_scale` to 1.10, against the prompt's rule, and its sentence is generic | [`docs/data/11_coach_loop/ollama_round_trip.json`](data/11_coach_loop/ollama_round_trip.json) |
| Designed vs naive | Tested in simulation: designed, longest pause between tension messages 20 ms while the coach thought for 1 s; naive, a 1 s hole after every segment and lost samples reported. **Not measured on the board** | Same test |
| Front end: coach sentence, segment state, command round trip line, two-core timeline, sync flash | Tested by eye on headless Chrome screenshots with the simulated device; no automated check of these elements | |
| `hard_scale` range 0.80-1.50 and what the coach should do with it | **Provisional design choice**, not validated with a player | |

Known weakness: with the baseline taken before each recording, normalized values in B are inflated (baseline 5.82 mV vs 7.36 mV relax during the recording), so relax after a chord sits near the medium threshold. New recordings with the real calibration flow are needed before the thresholds can be fixed ([checklist](hardware_session_checklist.md#7-recordings-to-validate-the-thresholds)).
