# Data protocol, version 1

How tension data travels from the ESP32-S3 (or the replayer) to the browser:

```
ESP32-S3 (08_wifi_stream) or tools/replay_stream.py
   │  UDP, one JSON object per datagram, 20 Hz          default port 9750
   ▼
bridge/bridge.py (Mac)        adds bridge_rx_ms and src, logs every message to sessions/*.jsonl
   │  WebSocket text frames, one JSON object each        ws://localhost:8765
   ▼
web/ (browser, Three.js)
```

The executable definition is [`bridge/protocol.py`](../bridge/protocol.py): `validate_device_message()` and `validate_bridge_message()` check every field listed here, and the end-to-end test uses them.

## Device message (`type: "emg"`)

Sent once per DSP hop, i.e. every 50 ms. Field order is not significant.

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `type` | string | | Always `"emg"` |
| `v` | integer | | Protocol version, `1` |
| `dev` | string | | Device name, e.g. `"esp32s3-emg"` or `"replay"`. Never a MAC address or serial number |
| `boot` | integer | | Random 32-bit number chosen at every boot (replayer: at every start or loop). A new value means the device restarted |
| `seq` | integer | | Message counter, 0 for the first message after boot, +1 per message |
| `sample_index` | integer | samples | Index of the last ADC sample in the RMS window, counted from the first sample after boot (1 kHz, so it is also ms of sampling time) |
| `device_ms` | integer | ms | Device clock (ms since boot) when the message was built. Only comparable with other `device_ms` values from the same boot |
| `rms_mV` | number | mV | RMS of the band-passed (45-200 Hz, mains removed) signal over the last 200 ms. Held at the last valid value while `saturated` |
| `norm` | number | | `rms_mV / baseline_mV`; `0` while there is no baseline or while calibrating |
| `level` | integer | | `0` relax, `1` medium, `2` hard (with hysteresis), or `-1` (see below) |
| `saturated` | boolean | | A raw sample in the window was at an ADC rail (<= 5 mV or >= 3100 mV); `rms_mV`, `norm` and `level` are the last valid values |
| `calibrating` | boolean | | The filters are settling or a calibration attempt is collecting |
| `baseline_mV` | number | mV | Relax baseline in use; `0` = none yet |
| `led_state` | integer | | `0` or `1`: the state of the latency LED, toggled at every level change (08 firmware; the replayer simulates it) |
| `cal` | object, optional | | Present only in the first message after a calibration attempt finished (see below) |

`level = -1` means "no level available": while `calibrating`, or when no calibration has been accepted yet (for example while every attempt is rejected because the electrodes are off). Displays should show a distinct state for it, not relax.

`cal` object:

| Field | Type | Meaning |
|---|---|---|
| `attempt` | integer | 1, 2, ... since boot or since the last button press |
| `result` | string | `"accepted"`, `"saturated"` (under 90 % unsaturated samples), `"too_high"` (RMS >= 15 mV) or `"unstable"` (CV of 50 ms RMS >= 0.5) |
| `valid` | number | Unsaturated share of the attempt's samples, 0-1 |
| `cv` | number | Coefficient of variation of the attempt's 50 ms RMS values |
| `rms_mV` | number | RMS of the attempt (the new baseline if accepted) |

Example:

```json
{"type":"emg","v":1,"dev":"esp32s3-emg","boot":2846150713,"seq":1834,"sample_index":91749,"device_ms":91752,
 "rms_mV":10.512,"norm":2.342,"level":1,"saturated":false,"calibrating":false,"baseline_mV":4.489,"led_state":1}
```

## Bridge additions (WebSocket)

The bridge forwards every device message unchanged and adds:

| Field | Type | Unit | Meaning |
|---|---|---|---|
| `bridge_rx_ms` | number | ms | Mac wall clock (Unix epoch, ms, sub-ms resolution) when the datagram arrived |
| `src` | string | | Sender `"ip:port"` (a local network address; no MAC) |

Every second the bridge also sends a status message:

| Field | Type | Meaning |
|---|---|---|
| `type` | string | `"status"` |
| `v` | integer | `1` |
| `bridge_ms` | number | Mac wall clock (Unix epoch ms) |
| `received` | integer | Device messages received since the bridge started |
| `lost` | integer | Messages missing according to `seq` (same `boot`) |
| `out_of_order` | integer | Messages whose `seq` was lower than expected (same `boot`) |
| `reboots` | integer | Times a new `boot` value appeared after the first |
| `last_rx_ms` | number or null | `bridge_rx_ms` of the latest device message |
| `sources` | array of strings | Sender addresses seen in the last 5 s |

Browser and bridge run on the same Mac, so `bridge_rx_ms` and the browser's `performance.timeOrigin + performance.now()` share a clock and can be subtracted directly.

## Detecting loss, reordering and restarts

Per sender, the receiver keeps the last `boot` and the next expected `seq`:

- different `boot` (or `seq == 0` after a higher value): the device restarted; reset the expectation, count a reboot, nothing is lost;
- `seq == expected`: in order;
- `seq > expected`: `seq - expected` messages were lost;
- `seq < expected`: out of order or duplicated; forwarded and counted in `out_of_order`. If that `seq` had been counted as lost (one of the last 1000), it is removed from `lost` again: it arrived late, it was not lost.

Loss rate = `lost / (received + lost)`.

## Why JSON over UDP

- **Bandwidth is not a concern.** One message is about 250 bytes; at 20 Hz that is about 5 kB/s (40 kbit/s), a negligible share of Wi-Fi capacity and of the ESP32's CPU (one `snprintf` every 50 ms).
- **Every layer can read it as is.** The bridge forwards and logs the text unchanged, the browser parses it with `JSON.parse`, and captures (`sessions/*.jsonl`, `nc -ul 9750`) are human-readable.
- **Versioning is easy.** New fields can be added without breaking older readers; `v` changes only for incompatible changes.
- A packed binary format would save about 200 bytes per message but would need matching struct layouts, byte order and version handling in C, Python and JavaScript.

UDP rather than TCP: a late message is useless for live feedback, so retransmission would only add delay; loss is visible through `seq`. One datagram per message keeps framing trivial.

## Versioning

`v` is incremented only for incompatible changes (renamed or removed fields, changed units or meanings). Adding an optional field keeps `v = 1`; readers must ignore unknown fields.
