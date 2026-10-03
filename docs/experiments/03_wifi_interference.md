# Experiment 03: Wi-Fi interference on 1 kHz DMA sampling

## 1. Question

Does Wi-Fi activity disturb 1 kHz DMA sampling on the ESP32-S3, and does pinning the sampler task to core 1 help?

## 2. Setup

| Item | Value |
|---|---|
| Board | ESP32-S3 N16R8 (firmware uses the default 2 MB flash setting; PSRAM not enabled) |
| Framework | ESP-IDF v6.0.3 |
| CPU clock | 160 MHz |
| Input | Potentiometer on GPIO4 (ADC1 channel 3) |
| Sample rate | 1000 Hz |
| Frame size | 16 samples per frame (16 ms) |
| DMA buffer | 4 frames (64 ms) |
| Sampler task | Priority 10, pinned to the core under test |
| Wi-Fi load | Continuous blocking scans in STA mode (load task on core 0) |
| Capture | 40 s per scenario, one run per scenario |
| Firmware | `firmware/experiments/03_wifi_interference` at commit `6aee619`; only `WIFI_LOAD` and `SAMPLER_CORE` changed between scenarios |

Scenarios:

| | `WIFI_LOAD` | `SAMPLER_CORE` | Data |
|---|---|---|---|
| A: no Wi-Fi | 0 | 1 | [a_no_wifi_core1.txt](../data/03_wifi_interference/a_no_wifi_core1.txt) |
| B: Wi-Fi, sampler on core 0 | 1 | 0 | [b_wifi_core0.txt](../data/03_wifi_interference/b_wifi_core0.txt) |
| C: Wi-Fi, sampler on core 1 | 1 | 1 | [c_wifi_core1.txt](../data/03_wifi_interference/c_wifi_core1.txt) |

## 3. Method

- `frame_dt` is the interval between the moments the CPU receives consecutive frames, measured with `esp_timer` in the sampler task. It is not the time at which individual samples were taken; that is set by the ADC hardware clock.
- The firmware prints one statistics line per second: sample rate, `frame_dt` min/avg/max, late frames, and overflow count.
- A frame is `late` if its `frame_dt` exceeds 16100 us (16000 us period + 100 us margin).
- `ovf` is the cumulative number of DMA buffer overflows (data lost because the CPU did not read in time).
- The first 2 statistics lines of each run (about 1.4 s and 2.4 s after boot) overlap Wi-Fi initialization and are reported separately as warm-up. The remaining 37 lines are the stable period.

## 4. Results

| | A: no Wi-Fi, core 1 | C: Wi-Fi, core 1 | B: Wi-Fi, core 0 |
|---|---|---|---|
| Statistics lines | 39 | 39 | 39 |
| **Warm-up (first 2 lines)** | | | |
| Rate (Hz) | 999.034 - 1000.000 | 998.976 - 1000.004 | 999.107 - 1000.011 |
| `frame_dt` lowest min (us) | 15987 (-13) | 15864 (-136) | 13432 (-2568) |
| `frame_dt` avg range (us) | 15999 - 16000 | 15997 - 15999 | 15999 - 16849 |
| `frame_dt` highest max (us) | 16000 (+0) | 16020 (+20) | 66569 (+50569) |
| Late / frames | 0/125 | 0/125 | 2/119 |
| **Stable (lines 3-39)** | | | |
| Rate (Hz) | 1000.000 - 1000.000 | 999.980 - 1000.019 | 999.869 - 1000.131 |
| `frame_dt` lowest min (us) | 16000 (+0) | 15970 (-30) | 14802 (-1198) |
| `frame_dt` avg range (us) | 16000 - 16000 | 15999 - 16000 | 15997 - 16002 |
| `frame_dt` highest max (us) | 16000 (+0) | 16029 (+29) | 17207 (+1207) |
| Late / frames | 0/2331 | 0/2331 | 31/2331 (1.33%) |
| Windows with late frames | 0/37 | 0/37 | 23/37 |
| **Whole run** | | | |
| Late / frames | 0/2456 | 0/2456 | 33/2450 |
| Final `ovf` | 0 | 0 | 0 |
| Wi-Fi scans logged | - (Wi-Fi off) | 1 line: 10 scans at 25.5 s | 1 line: 10 scans at 25.5 s |

## 5. Observations

- In the stable period all three scenarios average 1000 Hz, and `ovf` is 0 in all three runs. No samples were lost.
- Without Wi-Fi (A), every stable-period `frame_dt` is exactly 16000 us.
- With Wi-Fi and the sampler on core 0 (B), stable-period `frame_dt` ranges from -1198 us to +1207 us around 16000 us, and 1.33% of frames are late (31/2331).
- With Wi-Fi and the sampler on core 1 (C), stable-period `frame_dt` stays within -30 us to +29 us, with no late frames.
- In B, 22 of the 23 stable windows that contain a late frame also have a minimum below 16000 us by a similar amount (for example 14802 / 17207); the exception is -8 / +133 us. The window average stays at 15997-16002 us. This is consistent with a late frame being followed by an early one: the samples keep arriving on the hardware clock, and what varies is when the CPU collects them.
- In B's warm-up, one interval reached 66.6 ms (66569 us), close to the 64 ms the 4-frame DMA buffer can hold. `ovf` stayed 0.
- The boot log shows the Wi-Fi driver task running on core 0 at priority 23 (`wifi driver task: ... prio:23, ... core=0`). The sampler task runs at priority 10.

## 6. Design implications

- Sample timestamps should be derived from the sample index (index / 1000 Hz), not from the time the CPU receives the frame.
- Pin the sampler task to core 1. If it has to run on core 0, the DMA buffer needs to be larger than 4 frames to cover delays like the 66.6 ms seen during Wi-Fi start-up.

## 7. Open question (unverified hypothesis)

The ADC continuous driver and its conversion-done interrupt are set up in `app_main`, which runs on core 0 (`CONFIG_ESP_MAIN_TASK_AFFINITY_CPU0=y`). The interrupt may therefore still be affected by Wi-Fi interrupts on core 0, which could explain the remaining jitter of about +/-30 us in scenario C (scenario A shows none). This has not been tested. The next experiment will move ADC initialization to a task on core 1 to check it.

## 8. Limitations

- Each scenario was run once, for 40 s.
- The Wi-Fi load task logs only every 10 scans, so the amount of Wi-Fi load in B and C cannot be compared precisely (both logged 10 scans at 25.5 s and had not reached 20 by the end of the capture).
- All timing was measured with the chip's own clock (`esp_timer`) and has not been checked against an external logic analyzer.
