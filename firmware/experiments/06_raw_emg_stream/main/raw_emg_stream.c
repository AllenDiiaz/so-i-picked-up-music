// Stage 2: stream every 1 kHz ADC sample from GPIO4 (AD8232 OUTPUT) to the host.
//
// Output, one line per sample:   <sample index>,<mV>
// Once per second:               # samples=<n> ovf=<n> dropped=<n> bad=<n>
// Sample time = index / 1000 s. It comes from the ADC hardware clock, not from when
// the CPU received the sample.
//
// The sampler task (core 1) never waits on the serial port: it hands each frame to a
// queue without blocking and counts frames that do not fit. A lower-priority output
// task (core 0) formats and writes them over the native USB port (USB-Serial-JTAG).

#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "soc/soc_caps.h"

#define EMG_GPIO          4
#define EMG_ATTEN         ADC_ATTEN_DB_12
#define SAMPLE_HZ         1000
#define FRAME_SAMPLES     16                                   // one frame every 16 ms at 1 kHz
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES            // 4 bytes per result on ESP32-S3
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)
#define QUEUE_FRAMES      128                                  // ~2 s of slack for the output task
#define USB_TX_BUFFER     8192

static const char *TAG = "raw_emg";

typedef struct {
    uint32_t first_index;            // index of mv[0]
    uint16_t n;
    uint16_t mv[FRAME_SAMPLES];
} frame_t;

static TaskHandle_t s_sampler_task = NULL;
static QueueHandle_t s_frames = NULL;
static adc_channel_t s_channel;
static adc_cali_handle_t s_cali = NULL;

// Counters written by the sampler / ISR, read by the output task (32-bit, so reads are atomic).
static volatile uint32_t s_samples = 0;    // samples taken from the DMA pool
static volatile uint32_t s_overflows = 0;  // DMA pool full -> samples lost before we saw them
static volatile uint32_t s_dropped = 0;    // samples that did not fit in the output queue
static volatile uint32_t s_bad = 0;        // results from an unexpected channel (should stay 0)

static bool IRAM_ATTR on_conv_done(adc_continuous_handle_t handle,
                                   const adc_continuous_evt_data_t *edata,
                                   void *user_data)
{
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(s_sampler_task, &woken);
    return woken == pdTRUE;
}

static bool IRAM_ATTR on_pool_ovf(adc_continuous_handle_t handle,
                                  const adc_continuous_evt_data_t *edata,
                                  void *user_data)
{
    s_overflows++;
    return false;
}

static adc_continuous_handle_t adc_dma_init(adc_channel_t channel)
{
    adc_continuous_handle_t handle;
    adc_continuous_handle_cfg_t handle_cfg = {
        .max_store_buf_size = FRAME_BYTES * 4,   // room for 4 frames if the task falls behind
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
    s_sampler_task = xTaskGetCurrentTaskHandle();   // set before the first interrupt can fire

    uint8_t buf[FRAME_BYTES];
    frame_t frame = { 0 };
    uint32_t index = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);    // sleep until a frame is ready

        uint32_t got = 0;
        while (adc_continuous_read(handle, buf, FRAME_BYTES, &got, 0) == ESP_OK) {
            for (uint32_t i = 0; i + BYTES_PER_SAMPLE <= got; i += BYTES_PER_SAMPLE) {
                adc_digi_output_data_t *p = (adc_digi_output_data_t *)&buf[i];
                if (p->type2.unit != ADC_UNIT_1 || p->type2.channel != s_channel) {
                    s_bad++;
                    continue;
                }
                int mv = 0;
                adc_cali_raw_to_voltage(s_cali, p->type2.data, &mv);
                if (frame.n == 0) {
                    frame.first_index = index;
                }
                frame.mv[frame.n++] = (uint16_t)mv;
                index++;
                s_samples = index;
                if (frame.n == FRAME_SAMPLES) {
                    if (xQueueSend(s_frames, &frame, 0) != pdTRUE) {   // never wait here
                        s_dropped += frame.n;
                    }
                    frame.n = 0;
                }
            }
        }
    }
}

static void output_task(void *arg)
{
    // 16 lines of "4294967295,65535\n" plus one statistics line fit easily.
    static char text[FRAME_SAMPLES * 18 + 96];
    frame_t frame;

    while (true) {
        xQueueReceive(s_frames, &frame, portMAX_DELAY);
        int len = 0;
        for (uint16_t i = 0; i < frame.n; i++) {
            len += snprintf(text + len, sizeof(text) - len, "%" PRIu32 ",%u\n",
                            frame.first_index + i, frame.mv[i]);
        }
        uint32_t next = frame.first_index + frame.n;
        if (next / SAMPLE_HZ != frame.first_index / SAMPLE_HZ) {   // crossed a whole second
            len += snprintf(text + len, sizeof(text) - len,
                            "# samples=%" PRIu32 " ovf=%" PRIu32 " dropped=%" PRIu32 " bad=%" PRIu32 "\n",
                            s_samples, s_overflows, s_dropped, s_bad);
        }
        usb_serial_jtag_write_bytes(text, len, portMAX_DELAY);    // may wait; only this task does
    }
}

void app_main(void)
{
    // Interrupt-driven USB output with a large buffer; console logs go through the same driver.
    usb_serial_jtag_driver_config_t usb_cfg = {
        .tx_buffer_size = USB_TX_BUFFER,
        .rx_buffer_size = 256,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_cfg));
    usb_serial_jtag_vfs_use_driver();

    adc_unit_t unit;
    ESP_ERROR_CHECK(adc_continuous_io_to_channel(EMG_GPIO, &unit, &s_channel));

    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id = unit,
        .chan = s_channel,
        .atten = EMG_ATTEN,
        .bitwidth = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali));

    ESP_LOGI(TAG, "GPIO%d -> ADC%d channel %d, %d Hz, 12 dB attenuation, calibrated mV",
             EMG_GPIO, (int)unit + 1, (int)s_channel, SAMPLE_HZ);
    ESP_LOGI(TAG, "streaming: <sample index>,<mV> per line; '#' lines are statistics");

    s_frames = xQueueCreate(QUEUE_FRAMES, sizeof(frame_t));
    adc_continuous_handle_t handle = adc_dma_init(s_channel);

    xTaskCreatePinnedToCore(output_task, "output", 4096, NULL, 5, NULL, 0);
    // Sampler on core 1, away from core 0 (experiment 03). Wi-Fi is not started.
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, 1);
}
