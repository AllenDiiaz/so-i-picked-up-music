# MVP: definition of done and status

The MVP is done when a guitarist wearing the electrodes sees their forearm tension (relax / medium / hard) change in the browser while playing, reliably enough to practise with. Architecture: [architecture.md](architecture.md).

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

## Current status (2026-10-13, after hardware session 1)

| Part | Status | Evidence |
|---|---|---|
| On-board DSP, calibration with retry, hysteresis (07) | Done; validated on recordings (host) | C vs float64 reference identical in levels; [07 README](../firmware/experiments/07_onboard_tension/README.md) |
| Three levels on recordings | Partly met on recordings: A relax 91.2 %, medium 78.0 %, hard 100 %; B (guitar chords) relax 67.2 %, medium 30.2 % | Thresholds are provisional and in-sample; B misses criterion 1 |
| Protocol v1 | Done | [protocol.md](protocol.md), `bridge/protocol.py` |
| Replayer, bridge, front end (three designs) | Done, tested with replayed data | `tests/test_e2e_replay.py` passes for A and B: every message received, seq continuous, levels identical to the host test |
| Wi-Fi firmware (08) | **Partly tested on the board** (session 1, 2026-10-13): Wi-Fi streaming, LED, button, no MAC in logs. Open defect: Wi-Fi stalls while `wifi=up` are not detected | [Session 1 notes](experiments/08_hardware_session_1.md) |
| Session summary, letter prompt | Done (prompt printed only, no model call) | Run on a replay session log |
| Criterion 1 on the board, on the guitar | Not done: blocked by an AD8232 module whose output stays near 0 V (session 1) | Replace the module |
| Criterion 2 (latency) | Algorithm part measured offline; device-to-screen part needs hardware | |
| Criteria 3, 4 (5 min, loss) | Replay: 0 lost. Wi-Fi on the board: long stretches with 0 lost, but two multi-minute stalls brought the evening's total to 7.7 % lost | Fix stall detection, then the 5 min run |
| WebXR AR on Quest | Written, untested | |

Known weakness: with the baseline taken before each recording, normalized values in B are inflated (baseline 5.82 mV vs 7.36 mV relax during the recording), so relax after a chord sits near the medium threshold. New recordings with the real calibration flow are needed before the thresholds can be fixed ([checklist](hardware_session_checklist.md#7-recordings-to-validate-the-thresholds)).
