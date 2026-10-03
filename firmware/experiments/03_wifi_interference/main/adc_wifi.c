// Stage 1b: does Wi-Fi activity disturb the 1 kHz DMA sampler, and does core pinning help?
//
// Change the two switches below, rebuild, and compare:
//   A) WIFI_LOAD 0, SAMPLER_CORE 1  -> baseline, no interference
//   B) WIFI_LOAD 1, SAMPLER_CORE 0  -> sampler shares core 0 with the Wi-Fi driver
//   C) WIFI_LOAD 1, SAMPLER_CORE 1  -> sampler isolated on core 1

#define WIFI_LOAD     1     // 1 = keep Wi-Fi scanning continuously, 0 = Wi-Fi off
#define SAMPLER_CORE  1     // core the sampler task is pinned to (0 or 1)

#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_adc/adc_continuous.h"
#include "soc/soc_caps.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_wifi.h"

#define POT_GPIO          4
#define SAMPLE_HZ         1000
#define FRAME_SAMPLES     16
#define FRAME_PERIOD_US   (FRAME_SAMPLES * 1000000 / SAMPLE_HZ)   // 16000 us
#define LATE_MARGIN_US    100                                    // a frame later than this counts as "late"
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)

static const char *TAG = "adc_wifi";
static TaskHandle_t s_sampler_task = NULL;
static volatile uint32_t s_overflows = 0;   // DMA pool full -> samples were dropped

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
        .max_store_buf_size = FRAME_BYTES * 4,   // 4 frames = 64 ms of slack before data is lost
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
        .on_pool_ovf = on_pool_ovf,
    };
    ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(handle, &cbs, NULL));
    return handle;
}

static void sampler_task(void *arg)
{
    adc_continuous_handle_t handle = (adc_continuous_handle_t)arg;
    s_sampler_task = xTaskGetCurrentTaskHandle();

    uint8_t buf[FRAME_BYTES];
    int64_t last_frame_us = 0;
    int64_t window_start_us = esp_timer_get_time();
    int64_t dt_min = INT64_MAX, dt_max = 0, dt_sum = 0;
    uint32_t frames = 0, late = 0, samples = 0, last_raw = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        int64_t now = esp_timer_get_time();

        uint32_t got = 0;
        while (adc_continuous_read(handle, buf, FRAME_BYTES, &got, 0) == ESP_OK) {
            for (uint32_t i = 0; i + BYTES_PER_SAMPLE <= got; i += BYTES_PER_SAMPLE) {
                adc_digi_output_data_t *p = (adc_digi_output_data_t *)&buf[i];
                last_raw = p->type2.data;
                samples++;
            }
        }

        if (last_frame_us != 0) {
            int64_t dt = now - last_frame_us;
            if (dt < dt_min) dt_min = dt;
            if (dt > dt_max) dt_max = dt;
            if (dt > FRAME_PERIOD_US + LATE_MARGIN_US) late++;
            dt_sum += dt;
            frames++;
        }
        last_frame_us = now;

        int64_t elapsed = now - window_start_us;
        if (elapsed >= 1000000) {
            // Rate = samples / actual elapsed time (fixes the 1008 artifact from the last version).
            int64_t rate_mhz = (int64_t)samples * 1000000000LL / elapsed;
            int64_t dt_avg = frames ? dt_sum / frames : 0;
            ESP_LOGI(TAG, "core=%d wifi=%d  rate=%" PRId64 ".%03" PRId64 " Hz  frame_dt min/avg/max=%" PRId64 "/%" PRId64 "/%" PRId64
                     "  late=%" PRIu32 "/%" PRIu32 "  ovf=%" PRIu32 "  raw=%" PRIu32,
                     SAMPLER_CORE, WIFI_LOAD, rate_mhz / 1000, rate_mhz % 1000,
                     dt_min, dt_avg, dt_max, late, frames, s_overflows, last_raw);
            window_start_us = now;
            dt_min = INT64_MAX;
            dt_max = 0;
            dt_sum = 0;
            frames = 0;
            late = 0;
            samples = 0;
        }
    }
}

#if WIFI_LOAD
// Keeps the Wi-Fi driver busy by scanning nearby access points over and over.
// No SSID or password needed.
static void wifi_load_task(void *arg)
{
    uint32_t scans = 0;
    while (true) {
        ESP_ERROR_CHECK(esp_wifi_scan_start(NULL, true));   // blocking scan
        uint16_t found = 0;
        esp_wifi_scan_get_ap_num(&found);
        esp_wifi_clear_ap_list();                            // free scan results
        scans++;
        if (scans % 10 == 0) {
            ESP_LOGI(TAG, "wifi load: %" PRIu32 " scans, last found %u APs", scans, found);
        }
    }
}

static void wifi_start(void)
{
    esp_err_t err = nvs_flash_init();   // Wi-Fi stores calibration data in NVS
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());

    // The load generator itself also lives on core 0, next to the Wi-Fi driver.
    xTaskCreatePinnedToCore(wifi_load_task, "wifi_load", 4096, NULL, 5, NULL, 0);
}
#endif

void app_main(void)
{
    adc_unit_t unit;
    adc_channel_t channel;
    ESP_ERROR_CHECK(adc_continuous_io_to_channel(POT_GPIO, &unit, &channel));
    ESP_LOGI(TAG, "GPIO%d -> ADC%d ch%d, %d Hz, %d samples/frame, sampler on core %d, wifi load %d",
             POT_GPIO, (int)unit + 1, (int)channel, SAMPLE_HZ, FRAME_SAMPLES, SAMPLER_CORE, WIFI_LOAD);

    adc_continuous_handle_t handle = adc_dma_init(channel);
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, SAMPLER_CORE);

#if WIFI_LOAD
    wifi_start();
#endif
}
