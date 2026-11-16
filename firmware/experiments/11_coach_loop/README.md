# 11_coach_loop

The USB tension stream of [`10_usb_stream`](../10_usb_stream/README.md) plus a downlink: between practice segments, a language model on the Mac may adjust one parameter of the level decision on the board. The model is in the loop but outside the hard real-time path.

**Status: built, not yet run on the board.** `idf.py build` passes (ESP-IDF v6.0.3) and the command parser and level logic pass the host test; the same C code runs in the simulated device (`tools/fake_device.py`) and in the end-to-end test. Nothing in this folder has been flashed yet, so task timing, the USB input path, the button and the `cores` numbers are unverified on hardware ([list](../../../docs/autonomous_log.md#to-verify-on-the-board)).

10 is unchanged; 11 is a copy with these additions.

## Tasks

| Core | Task (priority) | Work | Class |
|---|---|---|---|
| 1 | `sampler` (10) | 1 kHz ADC (DMA) -> `emg_dsp` -> level -> hop queue. Waits only for the ADC. Sampling and DSP as in 07 / 10 | hard real-time |
| 0 | `output` (5) | Hop queue -> `@` JSON lines on USB, acks, once per second the `cores` message | soft real-time |
| 0 | `cmd_rx` (3) | Reads `!` command lines from USB, parses them, hands parameters to the sampler | asynchronous |

Parameters cross from core 0 to core 1 through one 32-bit word (generation + `hard_scale` in 1/1000). The sampler reads it once per hop, without a lock; a new value takes effect on the next hop (within 50 ms) and is acked with that hop's sample index.

`emg_dsp.c` is untouched. The level is decided by [`components/coach`](components/coach/include/coach.h) from the DSP's normalized value with the hard thresholds multiplied by `hard_scale` (0.80-1.50, default 1.00). With 1.00 it equals the DSP's own level on every hop of the experiment 06 recordings (host test).

## Downlink commands

One line per command, prefixed with `!` ([protocol.md](../../../docs/protocol.md#downlink-commands)):

```
!{"v":1,"cmd":"set_params","hard_scale":1.10,"seq":7}
!{"v":1,"cmd":"segment","state":"start","seq":8}        state: start | end
!{"v":1,"cmd":"mode","mode":"naive","seq":9}            mode: designed | naive
```

The parser accepts only this shape: a flat object, the keys above, no escapes, no duplicates, at most 160 characters. Anything else is dropped and counted (`parse_fail`), without an ack. A `hard_scale` outside 0.80-1.50 is clamped and the ack says `"clamped":true`.

## Output

```
@{"type":"emg",...}                                         every 50 ms, as in 10 (level uses hard_scale)
@{"type":"ack","seq":7,"cmd":"set_params","applied":{"hard_scale":1.100},"clamped":false,"sample_index":...}
@{"type":"cores","mode":"designed","simulated":false,"hard_scale":1.000,
  "core1":{"frames":62,"max_dev_us":...,"late":0,"blocked_ms":0,"ovf":0,"drop":0},
  "core0":{"cmd_rx":3,"parse_fail":0,"applied":3,"sent":...}}        once per second
@{"type":"button","event":"segment",...}                    short press of the button
# ...                                                       diagnostics, as in 10
```

`core1`: frame wake-ups in the last second, the largest deviation of a wake-up interval from 16000 µs (measured with `esp_timer` as in experiments 03 / 04; integer work only, no printing or locks on the sampling path), wake-ups more than 100 µs late, DMA pool overflows and dropped hops since boot. `core0`: command lines received, dropped by the parser, carried out, and messages sent, since boot.

## Naive mode (the counter-example)

`mode = naive` shows what the two-core design avoids. After `segment end` the sampler task itself waits on USB for the reply (up to 15 s), as a single-loop program would while it waits for a model. No frames are collected meanwhile: the DMA pool (64 ms) overflows, the `emg` stream stops and `core1.blocked_ms` grows. The default is `designed`; the designed path only tests one flag that naive mode sets.

## Button and LED

| GPIO | Use |
|---|---|
| 4 | AD8232 OUTPUT (ADC1 channel 3) |
| 5 | LED, toggled at every level change (`led_state`) |
| 6 | Button to GND. Short press: segment start / end. Held for 1 s: new calibration (in 10 any press calibrates) |

## Build, test, run

```sh
make -C firmware/experiments/11_coach_loop/host_test test      # parser cases + level identity, no board needed
cd firmware/experiments/11_coach_loop
. ../../../scripts/idf_env.sh       # export.sh, also when the default python3 changed
idf.py build
idf.py -p /dev/cu.usbmodem1101 flash
cd ../../..
.venv/bin/python bridge/bridge.py --serial /dev/cu.usbmodem1101 --llm ollama     # or --llm mock
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory web            # http://localhost:8000/
```

Without the board: `.venv/bin/python tools/fake_device.py --link /tmp/fake_emg --loop` and `bridge.py --serial /tmp/fake_emg`.
