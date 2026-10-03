// Stage 1c: does the core that owns the ADC DMA interrupt affect frame timing jitter?
//
// esp_intr_alloc() binds an interrupt to the core that calls it. For the ADC continuous
// driver on ESP32-S3 that call happens inside adc_continuous_new_handle() (via the GDMA
// driver), so whichever task runs adc_dma_init() decides where the ISR lives.
//
// Change the switches below, rebuild, and compare:
//   A) WIFI_LOAD 0, SAMPLER_CORE 1, ADC_INIT_ON_SAMPLER 0 -> baseline, ISR on core 0 (app_main)
//   C) WIFI_LOAD 1, SAMPLER_CORE 1, ADC_INIT_ON_SAMPLER 0 -> ISR on core 0, next to Wi-Fi
//   D) WIFI_LOAD 1, SAMPLER_CORE 1, ADC_INIT_ON_SAMPLER 1 -> ISR on core 1, with the sampler

#define WIFI_LOAD            1  // 1 = keep Wi-Fi scanning continuously, 0 = Wi-Fi off
#define SAMPLER_CORE         1  // core the sampler task is pinned to (0 or 1)
#define ADC_INIT_ON_SAMPLER  1  // 1 = init ADC inside the sampler task, 0 = init in app_main

#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_intr_alloc.h"
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

#define WARMUP_US         2000000   // ignore the first 2 s after the ADC starts
#define RECORD_FRAMES     3750      // 3750 x 16 ms = 60 s

static const char *TAG = "isr_affinity";
static TaskHandle_t s_sampler_task = NULL;
static TaskHandle_t s_report_task = NULL;
static volatile uint32_t s_overflows = 0;   // DMA pool full -> samples were dropped
static volatile bool s_quiet = false;       // true while recording: nobody may print

static uint32_t s_dt_us[RECORD_FRAMES];     // frame-to-frame intervals
static uint32_t s_ovf_during_record = 0;

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
    // The GDMA interrupt is allocated in here, on the calling core.
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

// Low-priority task: waits until recording is done, then dumps the data.
static void report_task(void *arg)
{
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    uint32_t dt_min = UINT32_MAX, dt_max = 0, late = 0;
    uint64_t dt_sum = 0;
    printf("DATA_BEGIN\n");
    for (int i = 0; i < RECORD_FRAMES; i++) {
        uint32_t dt = s_dt_us[i];
        printf("%" PRIu32 "\n", dt);
        if (dt < dt_min) dt_min = dt;
        if (dt > dt_max) dt_max = dt;
        if (dt > FRAME_PERIOD_US + LATE_MARGIN_US) late++;
        dt_sum += dt;
    }
    printf("DATA_END\n");

    uint64_t avg_x1000 = dt_sum * 1000 / RECORD_FRAMES;
    printf("SUMMARY wifi=%d core=%d init_on_sampler=%d frames=%d min=%" PRIu32 " avg=%" PRIu64 ".%03" PRIu64
           " max=%" PRIu32 " late(>%d)=%" PRIu32 " ovf=%" PRIu32 "\n",
           WIFI_LOAD, SAMPLER_CORE, ADC_INIT_ON_SAMPLER, RECORD_FRAMES, dt_min,
           avg_x1000 / 1000, avg_x1000 % 1000, dt_max,
           FRAME_PERIOD_US + LATE_MARGIN_US, late, s_ovf_during_record);
    s_quiet = false;
    vTaskDelete(NULL);
}

static void sampler_task(void *arg)
{
    s_sampler_task = xTaskGetCurrentTaskHandle();
#if ADC_INIT_ON_SAMPLER
    adc_continuous_handle_t handle = adc_dma_init((adc_channel_t)(intptr_t)arg);
#else
    adc_continuous_handle_t handle = (adc_continuous_handle_t)arg;
#endif

    uint8_t buf[FRAME_BYTES];
    int64_t last_frame_us = 0;
    uint32_t recorded = 0, ovf_at_start = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));
    int64_t start_us = esp_timer_get_time();
    ESP_LOGI(TAG, "ADC started on core %d, interrupt table:", xPortGetCoreID());
    esp_intr_dump(NULL);

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        int64_t now = esp_timer_get_time();

        uint32_t got = 0;
        while (adc_continuous_read(handle, buf, FRAME_BYTES, &got, 0) == ESP_OK) {
            // drain only; sample values are not needed here
        }

        if (recorded < RECORD_FRAMES && now - start_us >= WARMUP_US) {
            if (!s_quiet) {
                // first frame after warm-up: only sets the reference time
                s_quiet = true;
                ovf_at_start = s_overflows;
            } else {
                s_dt_us[recorded++] = (uint32_t)(now - last_frame_us);
                if (recorded == RECORD_FRAMES) {
                    s_ovf_during_record = s_overflows - ovf_at_start;
                    xTaskNotifyGive(s_report_task);
                }
            }
        }
        last_frame_us = now;
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
        if (scans % 10 == 0 && !s_quiet) {
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
    ESP_LOGI(TAG, "GPIO%d -> ADC%d ch%d, %d Hz, %d samples/frame, WIFI_LOAD=%d SAMPLER_CORE=%d ADC_INIT_ON_SAMPLER=%d",
             POT_GPIO, (int)unit + 1, (int)channel, SAMPLE_HZ, FRAME_SAMPLES,
             WIFI_LOAD, SAMPLER_CORE, ADC_INIT_ON_SAMPLER);

    xTaskCreate(report_task, "report", 4096, NULL, 1, &s_report_task);

#if ADC_INIT_ON_SAMPLER
    void *sampler_arg = (void *)(intptr_t)channel;
#else
    void *sampler_arg = adc_dma_init(channel);
#endif
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, sampler_arg, 10, NULL, SAMPLER_CORE);

#if WIFI_LOAD
    wifi_start();
#endif
}
