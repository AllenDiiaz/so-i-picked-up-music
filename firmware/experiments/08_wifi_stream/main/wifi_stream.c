// MVP step 2: stream the on-board EMG tension (07 DSP) to the Mac bridge over Wi-Fi UDP.
//
// Core 1: 1 kHz ADC (DMA) on GPIO4 -> emg_dsp (as in 07) -> one hop record every 50 ms into a
//         queue, never waiting. Level changes toggle the LED on GPIO5 (latency measurement).
// Core 0: Wi-Fi station and the network task, which turns each hop into a protocol v1 JSON
//         message (docs/protocol.md) and sends it with a non-blocking UDP sendto().
// USB-Serial-JTAG: one status line per second (no per-hop lines) and calibration results.
//
// Credentials and the bridge address come from wifi_config.h (git-ignored; see
// wifi_config.h.example). No MAC address is logged or sent: the Wi-Fi driver's own INFO logs,
// which include the station MAC and the AP's BSSID, are turned off.
//
// UNTESTED on hardware: written and built without flashing.
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "lwip/sockets.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "soc/soc_caps.h"
#include "emg_dsp.h"

// HAVE_WIFI_CONFIG is set by main/CMakeLists.txt, which re-checks for the file at every build.
// (__has_include alone missed a wifi_config.h created after the first build: nothing triggered
// a recompile, so the board ran with the placeholder.)
#if HAVE_WIFI_CONFIG
#include "wifi_config.h"
#else
#include "wifi_config.h.example"
#endif
#ifndef WIFI_CONFIG_IS_EXAMPLE
#define WIFI_CONFIG_IS_EXAMPLE 0
#endif

#define PROTOCOL_VERSION  1
#define EMG_GPIO          4
#define LED_GPIO          5      // toggled at every level change; also sent as led_state
#define BUTTON_GPIO       6      // to GND; internal pull-up, pressed = low: new calibration
#define EMG_ATTEN         ADC_ATTEN_DB_12
#define SAMPLE_HZ         EMG_FS_HZ
#define FRAME_SAMPLES     16
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)
#define QUEUE_ITEMS       64     // ~3 s of hops if the network task stalls
#define USB_TX_BUFFER     2048
#define RECONNECT_MAX_MS  10000

static const char *TAG = "wifi_stream";

typedef struct {
    emg_output_t out;
    emg_cal_report_t report;     // valid when out.cal_event
    uint8_t led_state;
} hop_t;

static TaskHandle_t s_sampler_task = NULL;
static QueueHandle_t s_hops = NULL;
static adc_channel_t s_channel;
static adc_cali_handle_t s_cali = NULL;

// Counters (32-bit, written by one task, read by the status line).
static volatile uint32_t s_samples, s_overflows, s_queue_drops, s_bad, s_presses;
static volatile uint32_t s_button_low_frames;   // frames in which the button pin read low (wiring check)
static volatile uint32_t s_dsp_us_max, s_dsp_us_sum, s_dsp_frames;
static volatile uint32_t s_sent, s_send_fail, s_offline, s_reconnects;
static volatile bool s_wifi_up = false;
static int s_sock = -1;
static struct sockaddr_in s_dest;

// ---------------------------------------------------------------------------------------------
// ADC (as in 07)
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

// Core 1: sampling, DSP, LED, button. Never waits on the network.
static void sampler_task(void *arg)
{
    adc_continuous_handle_t handle = (adc_continuous_handle_t)arg;
    s_sampler_task = xTaskGetCurrentTaskHandle();

    static emg_dsp_t dsp;
    emg_dsp_init(&dsp);
    uint8_t buf[FRAME_BYTES];
    uint32_t index = 0;
    int low_frames = 0;
    bool armed = true;
    int8_t last_level = -1;
    uint8_t led = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        if (gpio_get_level(BUTTON_GPIO) == 0) {        // two low 16 ms frames = a press
            s_button_low_frames++;
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
                hop_t hop;
                if (emg_dsp_process(&dsp, (float)mv, &hop.out)) {
                    if (hop.out.level != last_level) {
                        led ^= 1;                       // the camera sees this flip
                        gpio_set_level(LED_GPIO, led);
                        last_level = hop.out.level;
                    }
                    hop.led_state = led;
                    hop.report = dsp.report;
                    if (xQueueSend(s_hops, &hop, 0) != pdTRUE) {
                        s_queue_drops++;
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

// ---------------------------------------------------------------------------------------------
// Wi-Fi (core 0)
static esp_timer_handle_t s_reconnect_timer;
static uint32_t s_backoff_ms = 500;

static void reconnect_cb(void *arg)
{
    esp_wifi_connect();
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_up = false;
        s_reconnects++;
        // Back off up to 10 s; the timer callback runs in the esp_timer task, not the sampler.
        esp_timer_start_once(s_reconnect_timer, (uint64_t)s_backoff_ms * 1000);
        s_backoff_ms = s_backoff_ms * 2 > RECONNECT_MAX_MS ? RECONNECT_MAX_MS : s_backoff_ms * 2;
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_backoff_ms = 500;
        s_wifi_up = true;
    }
}

static void wifi_start(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    // The Wi-Fi driver logs the station MAC and the AP BSSID at INFO level: keep it to warnings.
    esp_log_level_set("wifi", ESP_LOG_WARN);
    esp_log_level_set("wifi_init", ESP_LOG_WARN);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    const esp_timer_create_args_t timer = { .callback = reconnect_cb, .name = "wifi_reconnect" };
    ESP_ERROR_CHECK(esp_timer_create(&timer, &s_reconnect_timer));

    wifi_config_t cfg = { 0 };
    strlcpy((char *)cfg.sta.ssid, WIFI_SSID, sizeof cfg.sta.ssid);
    strlcpy((char *)cfg.sta.password, WIFI_PASSWORD, sizeof cfg.sta.password);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));     // modem sleep would add tens of ms of latency
    ESP_ERROR_CHECK(esp_wifi_start());
}

// ---------------------------------------------------------------------------------------------
// Network task (core 0): hop -> JSON -> UDP. Builds every message (seq counts all of them, so
// the bridge sees messages produced while Wi-Fi is down as lost) and sends without blocking.
static int format_message(char *buf, size_t size, uint32_t boot, uint32_t seq, const hop_t *hop)
{
    const emg_output_t *o = &hop->out;
    int len = snprintf(buf, size,
                       "{\"type\":\"emg\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32 ",\"seq\":%" PRIu32
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
    len += snprintf(buf + len, size - len, "}");
    return len;
}

static void net_task(void *arg)
{
    const uint32_t boot = esp_random();
    uint32_t seq = 0;
    static char msg[384];
    hop_t hop;

    s_dest.sin_family = AF_INET;
    s_dest.sin_port = htons(BRIDGE_PORT);
    inet_pton(AF_INET, BRIDGE_HOST, &s_dest.sin_addr);

    while (true) {
        xQueueReceive(s_hops, &hop, portMAX_DELAY);
        int len = format_message(msg, sizeof msg, boot, seq++, &hop);
        if (hop.out.cal_event) {
            ESP_LOGI(TAG, "calibration attempt %" PRIu32 ": %s (valid %.1f%%, cv %.3f, rms %.3f mV)",
                     hop.report.attempt, emg_cal_result_name(hop.report.result), 100.0f * hop.report.valid_fraction,
                     hop.report.cv, hop.report.rms_mv);
        }
        if (!s_wifi_up) {
            s_offline++;
            continue;
        }
        if (s_sock < 0) {
            s_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
            if (s_sock < 0) {
                s_send_fail++;
                continue;
            }
        }
        if (sendto(s_sock, msg, len, MSG_DONTWAIT, (struct sockaddr *)&s_dest, sizeof s_dest) == len) {
            s_sent++;
        } else {
            s_send_fail++;             // e.g. ENOMEM when the Wi-Fi TX queue is full: drop, do not wait
        }
    }
}

// Once per second over USB: transport and sampling statistics (no MAC, no credentials).
static void status_task(void *arg)
{
    static char line[256];
    uint32_t last_presses = 0;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        uint32_t frames = s_dsp_frames, sum = s_dsp_us_sum;
        s_dsp_frames = 0;
        s_dsp_us_sum = 0;
        int rssi = 0;
        wifi_ap_record_t ap;
        if (s_wifi_up && esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            rssi = ap.rssi;            // only the RSSI is printed from this record
        }
        int len = snprintf(line, sizeof line,
                           "# samples=%" PRIu32 " ovf=%" PRIu32 " queue_drop=%" PRIu32 " bad=%" PRIu32
                           " wifi=%s rssi=%d sent=%" PRIu32 " send_fail=%" PRIu32 " offline=%" PRIu32
                           " reconnects=%" PRIu32 " dsp_us_frame_avg=%.1f dsp_us_frame_max=%" PRIu32
                           " button=%d button_low_frames=%" PRIu32 "\n",
                           s_samples, s_overflows, s_queue_drops, s_bad, s_wifi_up ? "up" : "down", rssi,
                           s_sent, s_send_fail, s_offline, s_reconnects, frames ? (float)sum / frames : 0.0f,
                           s_dsp_us_max, gpio_get_level(BUTTON_GPIO), s_button_low_frames);
        if (s_presses != last_presses) {
            last_presses = s_presses;
            len += snprintf(line + len, sizeof line - len, "# button: calibration started\n");
        }
        usb_serial_jtag_write_bytes(line, len, pdMS_TO_TICKS(50));
    }
}

void app_main(void)
{
    usb_serial_jtag_driver_config_t usb_cfg = { .tx_buffer_size = USB_TX_BUFFER, .rx_buffer_size = 256 };
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
        .unit_id = unit, .chan = s_channel, .atten = EMG_ATTEN, .bitwidth = SOC_ADC_DIGI_MAX_BITWIDTH,
    };
    ESP_ERROR_CHECK(adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali));

    if (WIFI_CONFIG_IS_EXAMPLE) {
        ESP_LOGW(TAG, "wifi_config.h not found: using the placeholder from wifi_config.h.example");
    }
    ESP_LOGI(TAG, "GPIO%d -> ADC%d ch%d at %d Hz; LED GPIO%d, button GPIO%d; sending to %s:%d as \"%s\"",
             EMG_GPIO, (int)unit + 1, (int)s_channel, SAMPLE_HZ, LED_GPIO, BUTTON_GPIO, BRIDGE_HOST, BRIDGE_PORT,
             DEVICE_NAME);

    s_hops = xQueueCreate(QUEUE_ITEMS, sizeof(hop_t));
    adc_continuous_handle_t handle = adc_dma_init(s_channel);
    // Sampler and DSP on core 1 (experiment 03); Wi-Fi, network and status on core 0.
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, 1);
    wifi_start();
    xTaskCreatePinnedToCore(net_task, "net", 4096, NULL, 6, NULL, 0);
    xTaskCreatePinnedToCore(status_task, "status", 3072, NULL, 2, NULL, 0);
}
