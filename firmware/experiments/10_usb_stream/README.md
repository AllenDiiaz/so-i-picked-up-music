# 10_usb_stream

MVP transport over USB: the on-board EMG tension of experiment 07, sent to the Mac bridge over the USB-Serial-JTAG port as one [protocol v1](../../../docs/protocol.md) message every 50 ms. No Wi-Fi.

Why: in hardware session 2, Wi-Fi (08) raised the relaxed-forearm RMS from 6.5 mV (07, no Wi-Fi) to 15.5 mV, so calibration was rejected ([notes](../../../docs/experiments/09_hardware_session_2.md)). The MVP uses USB until the Wi-Fi interference is solved. (The folder is numbered 10 because experiment 09 is reserved for that Wi-Fi interference work.)

**Status: tested on hardware** (session 2, 2026-10-18): streaming, bridge reconnect after RST, LED, three-level test.

Like 08, `CMakeLists.txt` adds `../07_onboard_tension/components` to `EXTRA_COMPONENT_DIRS`, so 07, 08, 10, the host test and the replayer all build the same `emg_dsp.c`.

| Core | Work |
|---|---|
| 1 | 1 kHz ADC (DMA) on GPIO4 -> `emg_dsp` -> a hop every 50 ms into a queue, never waiting. Toggles the LED on GPIO5 at every level change. Polls the calibration button on GPIO6 |
| 0 | Output task: formats each hop as JSON and writes it to USB-Serial-JTAG, plus the diagnostic lines |

## Output

```
@{"type":"emg","v":1,"dev":"esp32s3-emg-usb","boot":...,"seq":...,"sample_index":...,...}   every 50 ms
# samples= ovf= dropped= bad= dsp_us_frame_avg= dsp_us_frame_max=                        once per second
# raw_mV min= avg= max= at_low= at_high= (of 1000; rails <= 5 / >= 3100 mV)                once per second
# calibration attempt N: accepted | <reason> (valid %, cv, rms); baseline_mv=...
# button: calibration started
```

Lines starting with `@` are protocol v1 messages (same fields as 08 sends over UDP); everything else is diagnostics. `dropped` counts hops that did not fit in the queue, for example while no program reads the port.

## Run

```sh
cd firmware/experiments/10_usb_stream
. ~/esp/esp-idf-v6.0.3/export.sh
idf.py build
idf.py -p /dev/cu.usbmodem1101 flash
cd ../../..
.venv/bin/python bridge/bridge.py --serial /dev/cu.usbmodem1101      # terminal 1
.venv/bin/python -m http.server 8000 --bind 127.0.0.1 --directory web  # terminal 2, then open http://localhost:8000/?mode=C
```

Only one program can read the serial port: stop `idf.py monitor` or other loggers first. The bridge writes the messages to `sessions/<time>.jsonl` and every other line to `sessions/<time>.serial.log`, and reopens the port when it disappears or stays silent for 3 s (after the RST button the old handle can go quiet without an error). Opening the port can reset the board (`rst:0x15 (USB_UART_CHIP_RESET)`), which starts a new calibration.

If flashing fails with `No serial data received` after pressing RST, unplug and replug the USB cable.

## Pins

| GPIO | Use |
|---|---|
| 4 | AD8232 OUTPUT (ADC1 channel 3) |
| 5 | Latency LED (through a resistor to GND), toggled at every level change; its state is sent as `led_state` |
| 6 | Calibration button to GND (internal pull-up). Press it with the right hand: the left forearm is measured |
