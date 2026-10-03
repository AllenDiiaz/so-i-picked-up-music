// Stage 0: read a potentiometer on GPIO4 with the ESP-IDF v6 oneshot ADC driver.
// Goal: verify the wiring and the ADC path before moving on to DMA continuous sampling.

#include <stdio.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"

#define POT_GPIO 4                  // must be an ADC1 pin (GPIO1-10) so Wi-Fi won't block it later
#define POT_ATTEN ADC_ATTEN_DB_12   // widest input range (roughly 0 to 3.1 V)

static const char *TAG = "adc_pot";

void app_main(void)
{
    // Let the driver translate GPIO -> (ADC unit, channel) instead of hard-coding it.
    adc_unit_t unit;
    adc_channel_t channel;
    ESP_ERROR_CHECK(adc_oneshot_io_to_channel(POT_GPIO, &unit, &channel));
    ESP_LOGI(TAG, "GPIO%d -> ADC%d channel %d", POT_GPIO, (int)unit + 1, (int)channel);

    // 1. Create the ADC unit.
    adc_oneshot_unit_handle_t adc;
    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = unit,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &adc));

    // 2. Configure the channel: attenuation sets the input voltage range.
    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = POT_ATTEN,
        .bitwidth = ADC_BITWIDTH_DEFAULT,   // 12-bit on ESP32-S3: raw 0-4095
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc, channel, &chan_cfg));

    // 3. Calibration: converts raw counts to millivolts using factory eFuse data,
    //    correcting the ADC's non-linearity.
    adc_cali_handle_t cali = NULL;
    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id = unit,
        .chan = channel,
        .atten = POT_ATTEN,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    bool calibrated = (adc_cali_create_scheme_curve_fitting(&cali_cfg, &cali) == ESP_OK);
    if (!calibrated) {
        ESP_LOGW(TAG, "calibration unavailable, printing raw values only");
    }

    // 4. Read every 200 ms. Turn the potentiometer and watch the numbers move.
    while (true) {
        int raw = 0;
        ESP_ERROR_CHECK(adc_oneshot_read(adc, channel, &raw));

        if (calibrated) {
            int mv = 0;
            ESP_ERROR_CHECK(adc_cali_raw_to_voltage(cali, raw, &mv));
            ESP_LOGI(TAG, "raw=%4d  voltage=%4d mV", raw, mv);
        } else {
            ESP_LOGI(TAG, "raw=%4d", raw);
        }

        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
