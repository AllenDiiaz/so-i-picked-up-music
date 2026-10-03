// Stage 1: sample GPIO4 at 1 kHz with the ADC continuous (DMA) driver.
// The hardware decides WHEN each sample is taken; the CPU only collects finished frames.
// What we measure here: how regularly frames arrive at the CPU (ideal: every 16000 us).

#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_adc/adc_continuous.h"
#include "soc/soc_caps.h"

#define POT_GPIO          4
#define SAMPLE_HZ         1000
#define FRAME_SAMPLES     16                                   // one frame every 16 ms at 1 kHz
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES            // 4 bytes per result on ESP32-S3
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)

static const char *TAG = "adc_dma";
static TaskHandle_t s_sampler_task = NULL;

// Runs in interrupt context when one frame is complete: keep it minimal,
// just wake the sampler task.
static bool IRAM_ATTR on_conv_done(adc_continuous_handle_t handle,
                                   const adc_continuous_evt_data_t *edata,
                                   void *user_data)
{
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(s_sampler_task, &woken);
    return woken == pdTRUE;
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
        .atten = ADC_ATTEN_DB_12,
        .channel = channel,
        .unit = ADC_UNIT_1,
        .bit_width = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    adc_continuous_config_t cfg = {
        .pattern_num = 1,
        .adc_pattern = &pattern,
        .sample_freq_hz = SAMPLE_HZ,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    ESP_ERROR_CHECK(adc_continuous_config(handle, &cfg));

    adc_continuous_evt_cbs_t cbs = {
        .on_conv_done = on_conv_done,
    };
    ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(handle, &cbs, NULL));
    return handle;
}

static void sampler_task(void *arg)
{
    adc_continuous_handle_t handle = (adc_continuous_handle_t)arg;
    s_sampler_task = xTaskGetCurrentTaskHandle();   // set before the first interrupt can fire

    uint8_t buf[FRAME_BYTES];
    int64_t last_frame_us = 0;
    int64_t window_start_us = esp_timer_get_time();
    int64_t dt_min = INT64_MAX, dt_max = 0, dt_sum = 0;
    uint32_t frames = 0, samples = 0, last_raw = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);    // sleep until a frame is ready
        int64_t now = esp_timer_get_time();

        // Drain everything that is ready.
        uint32_t got = 0;
        while (adc_continuous_read(handle, buf, FRAME_BYTES, &got, 0) == ESP_OK) {
            for (uint32_t i = 0; i + BYTES_PER_SAMPLE <= got; i += BYTES_PER_SAMPLE) {
                adc_digi_output_data_t *p = (adc_digi_output_data_t *)&buf[i];
                last_raw = p->type2.data;
                samples++;
            }
        }

        // Frame arrival interval, as seen by the CPU.
        if (last_frame_us != 0) {
            int64_t dt = now - last_frame_us;
            if (dt < dt_min) dt_min = dt;
            if (dt > dt_max) dt_max = dt;
            dt_sum += dt;
            frames++;
        }
        last_frame_us = now;

        // Print a summary once per second.
        if (now - window_start_us >= 1000000) {
            int64_t dt_avg = frames ? dt_sum / frames : 0;
            ESP_LOGI(TAG, "samples/s=%" PRIu32 "  frame_dt us min/avg/max=%" PRId64 "/%" PRId64 "/%" PRId64 "  raw=%" PRIu32,
                     samples, dt_min, dt_avg, dt_max, last_raw);
            window_start_us = now;
            dt_min = INT64_MAX;
            dt_max = 0;
            dt_sum = 0;
            frames = 0;
            samples = 0;
        }
    }
}

void app_main(void)
{
    adc_unit_t unit;
    adc_channel_t channel;
    ESP_ERROR_CHECK(adc_continuous_io_to_channel(POT_GPIO, &unit, &channel));
    ESP_LOGI(TAG, "GPIO%d -> ADC%d channel %d, %d Hz, %d samples per frame",
             POT_GPIO, (int)unit + 1, (int)channel, SAMPLE_HZ, FRAME_SAMPLES);

    adc_continuous_handle_t handle = adc_dma_init(channel);

    // Pin the sampler to core 1; Wi-Fi (added later) runs on core 0.
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, 1);
}
