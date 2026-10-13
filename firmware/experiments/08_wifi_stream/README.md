# 08_wifi_stream

MVP step 2: send the on-board EMG tension of experiment 07 to the Mac bridge over Wi-Fi UDP, one [protocol v1](../../../docs/protocol.md) message every 50 ms.

**Status: written and built without warnings, never flashed. Untested on hardware.**

Why a new project instead of extending 07: 07 stays the Wi-Fi-free reference for the DSP and the sampling (experiment 03 showed that Wi-Fi activity disturbs core 0), so the two can be compared. The DSP is not copied: `CMakeLists.txt` adds `../07_onboard_tension/components` to `EXTRA_COMPONENT_DIRS`, so 07, 08, the host test and the replayer all build the same `emg_dsp.c`.

| Core | Work |
|---|---|
| 1 | 1 kHz ADC (DMA) on GPIO4 -> `emg_dsp` -> a hop record every 50 ms into a queue, never waiting. Toggles the LED on GPIO5 at every level change. Polls the calibration button on GPIO6 |
| 0 | Wi-Fi station with reconnect (backoff 0.5-10 s, power save off); network task formats JSON and sends with a non-blocking `sendto()`; status task prints one line per second over USB |

`seq` counts every message, including those produced while Wi-Fi is down, so the bridge reports them as lost.

## Setup

1. Copy the template and fill it in (the real file is git-ignored; never commit it):

   ```sh
   cp firmware/experiments/08_wifi_stream/main/wifi_config.h.example \
      firmware/experiments/08_wifi_stream/main/wifi_config.h
   ```

   Set `WIFI_SSID`, `WIFI_PASSWORD`, `BRIDGE_HOST` (the Mac's IPv4 address on the same network, e.g. from `ipconfig getifaddr en0`) and delete the `WIFI_CONFIG_IS_EXAMPLE` line. `git status` must not list `wifi_config.h`.

2. Build and flash:

   ```sh
   cd firmware/experiments/08_wifi_stream
   . ~/esp/esp-idf-v6.0.3/export.sh
   idf.py build
   idf.py -p /dev/cu.usbmodem1101 flash
   ```

3. On the Mac: `.venv/bin/python bridge/bridge.py` (listens on UDP 9750 on all interfaces). macOS may ask to allow incoming connections for Python.

Without `wifi_config.h` the build uses the template and logs a warning at boot.

## USB status line (once per second)

```
# samples= ovf= queue_drop= bad= wifi=up|down rssi= sent= send_fail= offline= reconnects= dsp_us_frame_avg= dsp_us_frame_max= button= button_low_frames=
```

plus `calibration attempt N: ...` and `# button: calibration started` lines. `button` is the GPIO6 level right now (1 = released, 0 = pressed) and `button_low_frames` counts the 16 ms frames in which it read low since boot: if it stays 0 while the button is pressed, the button is not wired to GPIO6 (check that both wires share a breadboard row with a button leg, on diagonal legs). No MAC address is printed: the Wi-Fi driver's INFO logs (station MAC, AP BSSID) are set to warnings only before `esp_wifi_init()`, and the device identifies itself with `DEVICE_NAME` and a random `boot` number.

## Pins

| GPIO | Use |
|---|---|
| 4 | AD8232 OUTPUT (ADC1 channel 3) |
| 5 | Latency LED (through a resistor to GND), toggled at every level change; its state is sent as `led_state` |
| 6 | Calibration button to GND (internal pull-up) |
