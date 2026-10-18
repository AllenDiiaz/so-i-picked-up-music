# Data: hardware session 2 (2026-10-18)

Logs behind [docs/experiments/09_hardware_session_2.md](../../experiments/09_hardware_session_2.md). One subject, left forearm, adhesive electrodes, forearm flat on the table. Times are local wall-clock time of the Mac.

Privacy: LAN IP addresses are replaced by `[LAN IP]` (the Mac's address in the 08 boot line, the board's address and gateway, and `src` in the 08 bridge log). No MAC address, Wi-Fi name or password appears.

| File | Firmware | What |
|---|---|---|
| `07_relax.serial.log` | 07 (no Wi-Fi) | USB output from boot: per-hop CSV `<sample index>,<rms mV>,<normalized>,<level>,<saturated>`, status and `raw_mV` lines, calibration. Relax window analysed: 17:21:04-17:21:34 |
| `08_relax.serial.log` | 08 (Wi-Fi) | USB output from boot: status, `raw_mV` and calibration lines. Relax window analysed: 17:23:12-17:23:42 |
| `08_relax.bridge.jsonl` | 08 | Bridge session log (protocol v1 + `bridge_rx_ms`, `src`) for 17:22:40-17:24:00 |
| `usb_three_level_run1.{jsonl,serial.log,cues.json}` | 10 (USB) | Three-level test with the 10.64 mV baseline |
| `usb_squeeze_check.{jsonl,serial.log,cues.json}` | 10 | Squeeze hard 3 s / relax 3 s, twice |
| `usb_three_level_run2.{jsonl,serial.log,cues.json}` | 10 | Recalibration (6.42 mV) and the three-level test |

- `*.jsonl`: one bridge message per line ([protocol v1](../../protocol.md)); `bridge_rx_ms` is the Mac's Unix time in ms.
- `*.serial.log`: `HH:MM:SS.mmm <line>`; lines starting `##` are notes from the logger or bridge (port opened or lost).
- `*.cues.json`: the spoken cues, `{"cues": [{"t": s, "cue": word, "epoch_ms": Mac Unix time in ms}]}`. Phase windows in the notes start 1.5 s (or 2.5 s) after `epoch_ms`.

The USB segments are cut from one bridge session (17:29-17:43) with margins around each test; the full session log stayed local.
