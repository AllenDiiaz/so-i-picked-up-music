# So I Picked Up Music

An ESP32-S3 + FreeRTOS EMG guitar practice device with measured real-time timing.

## Firmware experiments

Early bring-up experiments, each a standalone ESP-IDF project under `firmware/experiments/`:

| Folder | Description |
|---|---|
| `01_adc_oneshot` | Stage 0: read a potentiometer on GPIO4 with the oneshot ADC driver to verify wiring and the ADC path. |
| `02_adc_dma` | Stage 1: 1 kHz sampling with the continuous (DMA) ADC driver, measuring how regularly frames reach the CPU. |
| `03_wifi_interference` | Stage 1b: whether Wi-Fi activity disturbs the 1 kHz DMA sampler's timing, and whether pinning it to core 1 helps. |

## Regenerating figures

The figures in `docs/figures/` are generated from the captures in `docs/data/` by the scripts in `analysis/`. They use their own virtual environment, separate from the ESP-IDF Python environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r analysis/requirements.txt
.venv/bin/python analysis/plot_03_wifi_interference.py
.venv/bin/python analysis/plot_04_isr_core_affinity.py
```

Colors, fonts and the white background are shared through `analysis/style.py`.
