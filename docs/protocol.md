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

Over USB (firmware `10_usb_stream` and `11_coach_loop`), the same device messages are printed on the board's USB serial port, one per line with an `@` prefix (`@{"type":"emg",...}`), and `bridge/bridge.py --serial PORT` handles each line exactly like a datagram (`src` is then `serial:<port>`). Lines without `@` are diagnostics.

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

## Downlink commands

Firmware `11_coach_loop` (and its simulation, `tools/fake_device.py`) also reads the USB serial port. The bridge writes commands on the same handle it reads from (opening the port a second time would reset the board). Over UDP there is no downlink.

```
bridge/bridge.py --serial PORT
   │  one line per command, prefixed with '!'              host -> device
   ▼
device: cmd_rx task (core 0) -> one 32-bit word -> sampler (core 1), effective on the next hop
   │  @{"type":"ack",...}                                   device -> host
   ▼
bridge: logs it, forwards it to the browsers
```

| Command | Fields besides `v`, `cmd`, `seq` | Effect |
|---|---|---|
| `set_params` | `hard_scale` (number, optional) | Multiplies the hard entry and exit ratios (2.72 / 2.45). Allowed 0.80-1.50, default 1.00; a value outside is clamped. Without `hard_scale` nothing changes (used to release a naive device) |
| `segment` | `state`: `"start"` or `"end"` | Marks a practice segment. In naive mode, `end` makes the sampler wait for the next `set_params` |
| `mode` | `mode`: `"designed"` or `"naive"` | Switches how the device waits for the coach ([11 README](../firmware/experiments/11_coach_loop/README.md#naive-mode-the-counter-example)) |

```
!{"v":1,"cmd":"set_params","hard_scale":1.10,"seq":7}
```

`seq` is chosen by the sender (the bridge counts up from 1) and comes back in the ack. The device's parser is strict: a flat JSON object with only these keys, string or number values, no escapes, no duplicate keys, at most 160 characters. A line that does not fit is dropped and counted in `core0.parse_fail`; it gets no ack.

### Ack (`type: "ack"`)

| Field | Type | Meaning |
|---|---|---|
| `type`, `v`, `dev`, `boot` | | As in the device message |
| `seq` | integer | `seq` of the command |
| `cmd` | string | `"set_params"`, `"segment"` or `"mode"` |
| `applied` | object | What is now in effect: `{"hard_scale":1.1}`, `{}` (a `set_params` without a value), `{"state":"end"}`, `{"mode":"naive"}` |
| `clamped` | boolean | The requested value was outside the allowed range; `applied` holds the limit |
| `sample_index` | integer | For `set_params`: last sample of the first hop computed with the new value. Otherwise the newest hop sent |
| `device_ms` | integer | Device clock when the ack was built |
| `waited_ms` | integer, optional | Naive mode only: how long the sampler was blocked before this reply arrived |

### Core statistics (`type: "cores"`)

Sent once per second by the device.

| Field | Type | Meaning |
|---|---|---|
| `type`, `v`, `dev`, `boot`, `device_ms` | | As above |
| `mode` | string | `"designed"` or `"naive"` |
| `simulated` | boolean | `true` from `tools/fake_device.py`: the core 1 numbers then come from a model (0 when the sampler never waits, the wait length when it blocks), not from a measurement |
| `hard_scale` | number | Value in use |
| `segment` | boolean, optional | A segment is being recorded (firmware only) |
| `core1.frames` | integer | Frame wake-ups of the sampler in the last second (62-63 at 1 kHz with 16-sample frames) |
| `core1.max_dev_us` | integer | Largest deviation of a wake-up interval from 16000 µs in the last second; while blocked, the length of the wait so far |
| `core1.late` | integer | Wake-ups more than 100 µs late in the last second (as in experiments 03 / 04) |
| `core1.blocked_ms` | integer | Naive mode: length of the wait in progress or just finished; otherwise 0 |
| `core1.ovf`, `core1.drop` | integer | Since boot: DMA pool overflows (samples lost) and hop outputs that did not fit in the queue |
| `core0.cmd_rx`, `core0.parse_fail`, `core0.applied` | integer | Since boot: command lines received, dropped by the parser, carried out |
| `core0.sent` | integer | Since boot: messages sent |

### Button (`type: "button"`)

`{"type":"button","v":1,"dev":...,"boot":...,"event":"segment","device_ms":...}`: a short press of the board's button. The bridge starts or ends a segment.

## Coach loop messages from the bridge

The bridge adds `bridge_rx_ms` and `src` to acks, core statistics and button messages like to any device message, and sends these of its own (all with `v` and `bridge_ms`):

| `type` | Fields | Meaning |
|---|---|---|
| `segment` | `id`, `state`, `trigger` | `state`: `recording` (started), `thinking` (ended, the coach is working), `feedback` (reply shown), `idle`. `trigger`: `keyboard`, `browser`, `board` or `coach` |
| `command` | `seq`, `cmd`, the command's fields, `sent` | A downlink command. `sent` is false when there is no serial port (UDP sources) |
| `coach` | `id`, `feedback`, `command`, `llm`, `model`, `fallback`, `clamped`, `truncated`, `command_error`, `sent`, `acked`, `ack_seq`, `reason`, `latency_ms` | Result of one segment. `feedback`: at most 20 words. `command`: `{"hard_scale": x}` after validation and clamping, or null. `command_error`: why a command was dropped. `fallback`: the model was unreachable, late or unusable, so `feedback` repeats the last good one and no command was sent |
| `sync` | `id`, `trigger` | Every page shows a white flash and plays a beep; used to line a screen recording up with the log |

The session log additionally holds `llm_request` (segment statistics and the exact request), `llm_response` (the raw reply text or the error, and the latency), `llm_warm_up`, `ack_timeout` and `sync_shown` (the page's clock when it flashed). These are not sent to browsers.

Browser pages may send: `{"type":"segment","action":"toggle"|"start"|"end"}`, `{"type":"mode","mode":"naive"|"designed"}`, `{"type":"sync"}` and `{"type":"sync_shown","id":n,"browser_ms":t}`.

The status message additionally carries `mode`, `hard_scale`, `downlink` (a serial port is in use), `segment` (`id`, `state`), `llm` and `model`.

### What the model may and may not do

The model's reply must be `{"feedback": string, "command": {"hard_scale": number} | null}` (enforced as a JSON schema through Ollama's `format`, then checked again by `protocol.check_llm_reply`). The only thing it can change on the device is `hard_scale`, inside 0.80-1.50; the bridge clamps before sending and the device clamps again. A command of any other shape is dropped and never sent. The model cannot start a calibration, change the mode, or touch sampling and filtering.

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
