// MVP over USB: the on-board EMG tension of experiment 07, streamed to the Mac bridge over the
// USB-Serial-JTAG port instead of Wi-Fi (Wi-Fi raised the relax RMS from ~6.5 to 15-24 mV in
// hardware session 2; that is left for a later experiment).
//
// Sampling and DSP as in 07: 1 kHz continuous ADC (DMA) on GPIO4, sampler task on core 1,
// emg_dsp (mains notches, 45-200 Hz band-pass, 200 ms RMS, relax calibration, three levels).
// Every 50 ms one protocol v1 message (docs/protocol.md) is printed as a line starting with '@':
//   @{"type":"emg","v":1,...}
// bridge/bridge.py --serial reads these lines. Lines starting with '#' and ESP-IDF log lines are
// diagnostics: once per second counters, DSP time and the raw input range; every calibration
// attempt; button presses. The LED on GPIO5 toggles at every level change (latency measurement),
// the button on GPIO6 (to GND) starts a new calibration. Wi-Fi is not started.
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "soc/soc_caps.h"
#include "esp_random.h"
#include "emg_dsp.h"

#define EMG_GPIO          4
#define LED_GPIO          5      // toggled at every level change; also sent as led_state
#define BUTTON_GPIO       6      // to GND; internal pull-up, pressed = low
#define EMG_ATTEN         ADC_ATTEN_DB_12
#define SAMPLE_HZ         EMG_FS_HZ
#define FRAME_SAMPLES     16
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)
#define QUEUE_ITEMS       64     // ~3 s of hop outputs
#define USB_TX_BUFFER     4096
#define PROTOCOL_VERSION  1
#define DEVICE_NAME       "esp32s3-emg-usb"   // sent as "dev"; never a MAC address

static const char *TAG = "usb_stream";

typedef struct {
    emg_output_t out;
    emg_cal_report_t report;    // valid when out.cal_event
    uint8_t led_state;
} hop_t;

static TaskHandle_t s_sampler_task = NULL;
static QueueHandle_t s_hops = NULL;
static adc_channel_t s_channel;
static adc_cali_handle_t s_cali = NULL;

// Written by the sampler / ISR, read by the output task (32-bit, so reads are atomic).
static volatile uint32_t s_samples = 0;
static volatile uint32_t s_overflows = 0;
static volatile uint32_t s_dropped = 0;      // hop outputs that did not fit in the queue
static volatile uint32_t s_bad = 0;
static volatile uint32_t s_dsp_us_max = 0;   // per 16-sample frame, since boot
static volatile uint32_t s_dsp_us_sum = 0;   // since the last statistics line
static volatile uint32_t s_dsp_frames = 0;
static volatile uint32_t s_presses = 0;
// Raw input over the last 1000 samples (wiring and electrode check, as in 08), published by the sampler.
static volatile int32_t s_raw_min_mv, s_raw_max_mv, s_raw_avg_mv;
static volatile uint32_t s_raw_low, s_raw_high, s_raw_windows;

static bool IRAM_ATTR on_conv_done(adc_continuous_handle_t handle, const adc_continuous_evt_data_t *edata,
                                   void *user_data)
{
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(s_sampler_task, &woken);
    return woken == pdTRUE;
}

static bool IRAM_ATTR on_pool_ovf(adc_continuous_handle_t handle, const adc_continuous_evt_data_t *edata,
                                  void *user_data)
{
    s_overflows++;
    return false;
}

static adc_continuous_handle_t adc_dma_init(adc_channel_t channel)
{
    adc_continuous_handle_t handle;
    adc_continuous_handle_cfg_t handle_cfg = {
        .max_store_buf_size = FRAME_BYTES * 4,
        .conv_frame_size = FRAME_BYTES,
    };
    ESP_ERROR_CHECK(adc_continuous_new_handle(&handle_cfg, &handle));
    adc_digi_pattern_config_t pattern = {
        .atten = EMG_ATTEN,
        .channel = channel,
        .unit = ADC_UNIT_1,
        .bit_width = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    adc_continuous_config_t cfg = {
        .pattern_num = 1,
        .adc_pattern = &pattern,
        .sample_freq_hz = SAMPLE_HZ,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        // No .format: it is deprecated, and the driver always outputs TYPE2 on ESP32-S3.
    };
    ESP_ERROR_CHECK(adc_continuous_config(handle, &cfg));
    adc_continuous_evt_cbs_t cbs = {
        .on_conv_done = on_conv_done,
        .on_pool_ovf = on_pool_ovf,
    };
    ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(handle, &cbs, NULL));
    return handle;
}

static void sampler_task(void *arg)
{
    adc_continuous_handle_t handle = (adc_continuous_handle_t)arg;
    s_sampler_task = xTaskGetCurrentTaskHandle();

    static emg_dsp_t dsp;    // static: about 1.3 kB, kept off the task stack
    emg_dsp_init(&dsp);
    uint8_t buf[FRAME_BYTES];
    uint32_t index = 0;
    int low_frames = 0;
    bool armed = true;       // button must be released before it can trigger again
    int raw_min = INT32_MAX, raw_max = INT32_MIN, raw_n = 0;
    int64_t raw_sum = 0;
    uint32_t raw_low = 0, raw_high = 0;
    int8_t last_level = -1;
    uint8_t led = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        // Button: polled once per 16 ms frame; two low frames in a row count as a press.
        if (gpio_get_level(BUTTON_GPIO) == 0) {
            if (++low_frames == 2 && armed) {
                emg_dsp_start_calibration(&dsp);
                armed = false;
                s_presses++;
            }
        } else {
            low_frames = 0;
            armed = true;
        }

        uint32_t got = 0;
        while (adc_continuous_read(handle, buf, FRAME_BYTES, &got, 0) == ESP_OK) {
            int64_t t0 = esp_timer_get_time();
            for (uint32_t i = 0; i + BYTES_PER_SAMPLE <= got; i += BYTES_PER_SAMPLE) {
                adc_digi_output_data_t *p = (adc_digi_output_data_t *)&buf[i];
                if (p->type2.unit != ADC_UNIT_1 || p->type2.channel != s_channel) {
                    s_bad++;
                    continue;
                }
                int mv = 0;
                adc_cali_raw_to_voltage(s_cali, p->type2.data, &mv);
                raw_min = mv < raw_min ? mv : raw_min;
                raw_max = mv > raw_max ? mv : raw_max;
                raw_sum += mv;
                raw_low += mv <= (int)EMG_SAT_LOW_MV;
                raw_high += mv >= (int)EMG_SAT_HIGH_MV;
                if (++raw_n == SAMPLE_HZ) {             // publish once per second of samples
                    s_raw_min_mv = raw_min;
                    s_raw_max_mv = raw_max;
                    s_raw_avg_mv = (int32_t)(raw_sum / raw_n);
                    s_raw_low = raw_low;
                    s_raw_high = raw_high;
                    s_raw_windows++;
                    raw_min = INT32_MAX;
                    raw_max = INT32_MIN;
                    raw_sum = 0;
                    raw_n = 0;
                    raw_low = raw_high = 0;
                }
                hop_t hop;
                if (emg_dsp_process(&dsp, (float)mv, &hop.out)) {
                    if (hop.out.level != last_level) {
                        led ^= 1;                       // the camera sees this flip
                        gpio_set_level(LED_GPIO, led);
                        last_level = hop.out.level;
                    }
                    hop.led_state = led;
                    hop.report = dsp.report;
                    if (xQueueSend(s_hops, &hop, 0) != pdTRUE) {   // never wait here
                        s_dropped++;
                    }
                }
                index++;
            }
            uint32_t us = (uint32_t)(esp_timer_get_time() - t0);
            s_samples = index;
            s_dsp_us_sum += us;
            s_dsp_frames++;
            if (us > s_dsp_us_max) {
                s_dsp_us_max = us;
            }
        }
    }
}

// One protocol v1 message, the same fields as 08 sends over UDP, prefixed with '@'.
static int format_message(char *buf, size_t size, uint32_t boot, uint32_t seq, const hop_t *hop)
{
    const emg_output_t *o = &hop->out;
    int len = snprintf(buf, size,
                       "@{\"type\":\"emg\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32 ",\"seq\":%" PRIu32
                       ",\"sample_index\":%" PRIu32 ",\"device_ms\":%" PRIu32 ",\"rms_mV\":%.3f,\"norm\":%.3f"
                       ",\"level\":%d,\"saturated\":%s,\"calibrating\":%s,\"baseline_mV\":%.3f,\"led_state\":%u",
                       PROTOCOL_VERSION, DEVICE_NAME, boot, seq, o->sample_index,
                       (uint32_t)(esp_timer_get_time() / 1000), o->rms_mv, o->normalized, o->level,
                       o->saturated ? "true" : "false", o->calibrating ? "true" : "false", o->baseline_mv,
                       hop->led_state);
    if (o->cal_event) {
        static const char *names[] = { "none", "accepted", "saturated", "too_high", "unstable" };
        const emg_cal_report_t *r = &hop->report;
        len += snprintf(buf + len, size - len,
                        ",\"cal\":{\"attempt\":%" PRIu32 ",\"result\":\"%s\",\"valid\":%.4f,\"cv\":%.4f,\"rms_mV\":%.3f}",
                        r->attempt, names[r->result], r->valid_fraction, r->cv > 1e9f ? 1e9f : r->cv, r->rms_mv);
    }
    len += snprintf(buf + len, size - len, "}\n");
    return len;
}

static void output_task(void *arg)
{
    static char text[768];
    hop_t hop;
    uint32_t hops = 0, last_presses = 0, seq = 0;
    const uint32_t boot = esp_random();

    while (true) {
        xQueueReceive(s_hops, &hop, portMAX_DELAY);
        const emg_output_t *o = &hop.out;
        int len = format_message(text, sizeof text, boot, seq++, &hop);
        if (s_presses != last_presses) {
            last_presses = s_presses;
            len += snprintf(text + len, sizeof text - len, "# button: calibration started\n");
        }
        if (o->cal_event) {
            const emg_cal_report_t *r = &hop.report;
            len += snprintf(text + len, sizeof text - len,
                            "# calibration attempt %" PRIu32 ": %s (valid %.1f%%, cv %.3f, rms %.3f mV); baseline_mv=%.3f\n",
                            r->attempt, emg_cal_result_name(r->result), 100.0f * r->valid_fraction, r->cv, r->rms_mv,
                            o->baseline_mv);
        }
        if (++hops % (SAMPLE_HZ / EMG_HOP_SAMPLES) == 0) {   // once per second
            uint32_t frames = s_dsp_frames, sum = s_dsp_us_sum;
            s_dsp_frames = 0;
            s_dsp_us_sum = 0;
            len += snprintf(text + len, sizeof text - len,
                            "# samples=%" PRIu32 " ovf=%" PRIu32 " dropped=%" PRIu32 " bad=%" PRIu32
                            " dsp_us_frame_avg=%.1f dsp_us_frame_max=%" PRIu32 "\n",
                            s_samples, s_overflows, s_dropped, s_bad, frames ? (float)sum / frames : 0.0f,
                            s_dsp_us_max);
            if (s_raw_windows) {
                len += snprintf(text + len, sizeof text - len,
                                "# raw_mV min=%" PRId32 " avg=%" PRId32 " max=%" PRId32 " at_low=%" PRIu32
                                " at_high=%" PRIu32 " (of 1000; rails <= %d / >= %d mV)\n",
                                s_raw_min_mv, s_raw_avg_mv, s_raw_max_mv, s_raw_low, s_raw_high,
                                (int)EMG_SAT_LOW_MV, (int)EMG_SAT_HIGH_MV);
            }
        }
        usb_serial_jtag_write_bytes(text, len, portMAX_DELAY);
    }
}

void app_main(void)
{
    usb_serial_jtag_driver_config_t usb_cfg = {
        .tx_buffer_size = USB_TX_BUFFER,
        .rx_buffer_size = 256,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_cfg));
    usb_serial_jtag_vfs_use_driver();

    gpio_config_t button = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&button));
    gpio_config_t led = { .pin_bit_mask = 1ULL << LED_GPIO, .mode = GPIO_MODE_OUTPUT };
    ESP_ERROR_CHECK(gpio_config(&led));
    gpio_set_level(LED_GPIO, 0);

    adc_unit_t unit;
    ESP_ERROR_CHECK(adc_continuous_io_to_channel(EMG_GPIO, &unit, &s_channel));
    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id = unit,
        .chan = s_channel,
        .atten = EMG_ATTEN,
        .bitwidth = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali));

    ESP_LOGI(TAG, "GPIO%d -> ADC%d channel %d, %d Hz; button GPIO%d; window %d ms, hop %d ms, "
             "levels in %.2f/%.2fx, out %.2f/%.2fx (provisional)", EMG_GPIO, (int)unit + 1, (int)s_channel,
             SAMPLE_HZ, BUTTON_GPIO, EMG_WINDOW_SAMPLES, EMG_HOP_SAMPLES, EMG_LEVEL1_ENTER, EMG_LEVEL2_ENTER,
             EMG_LEVEL1_EXIT, EMG_LEVEL2_EXIT);
    ESP_LOGI(TAG, "output: '@' + protocol v1 JSON every 50 ms; '#' lines are status; LED GPIO%d", LED_GPIO);

    s_hops = xQueueCreate(QUEUE_ITEMS, sizeof(hop_t));
    adc_continuous_handle_t handle = adc_dma_init(s_channel);
    xTaskCreatePinnedToCore(output_task, "output", 4096, NULL, 5, NULL, 0);
    // Sampler and DSP on core 1, away from core 0 (experiment 03). Wi-Fi is not started.
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, 1);
}
