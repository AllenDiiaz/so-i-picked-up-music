// Coach loop: the USB tension stream of 10_usb_stream plus a downlink, so that a language model
// on the host can adjust one parameter of the level decision between practice segments.
// "LLM in the loop, outside the hard real-time path":
//
//   core 1  sampler (prio 10)  1 kHz ADC (DMA) -> emg_dsp -> level -> hop queue. Never waits for
//                              anything but the ADC. Same sampling and DSP as 07 / 10.
//   core 0  output  (prio 5)   hop queue -> '@' JSON lines on USB; acks; once per second a
//                              "cores" message with the timing of core 1 and the command counters.
//           cmd_rx  (prio 3)   reads '!' command lines from USB, parses them (coach.c), hands
//                              parameters to the sampler through one 32-bit word.
//
// Downlink commands (docs/protocol.md): set_params (hard_scale), segment (start / end), mode.
// A parameter takes effect on the next hop (<= 50 ms) and is acked with that hop's sample index.
// Lines that do not parse are dropped and counted.
//
// mode = naive is the counter-example for the A/B comparison: after "segment end" the sampler
// itself waits on USB for the reply (up to 15 s), as a single-loop design would. Meanwhile no
// frames are collected, the DMA pool overflows and the stream stops. The default is designed.
//
// Button on GPIO6: short press = segment start / end (sent to the host as a "button" message),
// held for 1 s = new calibration. LED on GPIO5 toggles at every level change, as in 10.
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
#include "coach.h"

#define EMG_GPIO          4
#define LED_GPIO          5      // toggled at every level change; also sent as led_state
#define BUTTON_GPIO       6      // to GND; internal pull-up, pressed = low
#define EMG_ATTEN         ADC_ATTEN_DB_12
#define SAMPLE_HZ         EMG_FS_HZ
#define FRAME_SAMPLES     16
#define FRAME_PERIOD_US   (FRAME_SAMPLES * 1000000 / SAMPLE_HZ)   // 16000 us
#define LATE_MARGIN_US    100    // as in experiments 03 / 04: a frame later than this is "late"
#define BYTES_PER_SAMPLE  SOC_ADC_DIGI_RESULT_BYTES
#define FRAME_BYTES       (FRAME_SAMPLES * BYTES_PER_SAMPLE)
#define QUEUE_ITEMS       64     // ~3 s of hop outputs
#define EVENT_ITEMS       16
#define PENDING_ACKS      4
#define USB_TX_BUFFER     4096
#define USB_RX_BUFFER     512
#define LONG_PRESS_FRAMES 62     // ~1 s of 16 ms frames
#define NAIVE_TIMEOUT_MS  15000
#define PROTOCOL_VERSION  1
#define DEVICE_NAME       "esp32s3-emg-coach"   // sent as "dev"; never a MAC address

static const char *TAG = "coach_loop";

typedef struct {
    emg_output_t out;
    emg_cal_report_t report;    // valid when out.cal_event
    int8_t level;               // coach level (hard threshold scaled); equals out.level at scale 1.0
    uint8_t led_state;
    uint16_t param_gen;         // generation of the parameters used for this hop
} hop_t;

typedef enum { EV_ACK_SEGMENT, EV_ACK_MODE, EV_SET_PARAMS, EV_BUTTON_SEGMENT, EV_BUTTON_CAL } event_kind_t;

typedef struct {
    event_kind_t kind;
    coach_cmd_t cmd;
    uint16_t gen;               // EV_SET_PARAMS: ack when a hop carries this generation
    uint32_t waited_ms;         // EV_SET_PARAMS in naive mode: how long the sampler was blocked
} event_t;

static TaskHandle_t s_sampler_task = NULL;
static QueueHandle_t s_hops = NULL;
static QueueHandle_t s_events = NULL;
static adc_channel_t s_channel;
static adc_cali_handle_t s_cali = NULL;

// --- single hand-over point for parameters ---------------------------------------------------
// One 32-bit word, written by whoever parsed a set_params command and read by the sampler at
// each hop: bits 31..16 = generation, bits 15..0 = hard_scale in 1/1000. A 32-bit store is
// atomic on this CPU, so the sampler needs no lock and never sees half an update.
#define PARAM_WORD(gen, milli) (((uint32_t)(gen) << 16) | (uint32_t)(milli))
static volatile uint32_t s_param_word = PARAM_WORD(0, 1000);
static uint16_t s_param_gen = 0;             // last generation handed out (see publish_params)

// --- flags and counters (32-bit, so reads are atomic) ----------------------------------------
static volatile uint32_t s_naive = 0;        // mode: 0 designed, 1 naive
static volatile uint32_t s_naive_wait = 0;   // naive only: the sampler owns the USB input until it clears this
static volatile uint32_t s_segment = 0;      // a segment is being recorded (information only)
// core 1, written by the sampler / ISR
static volatile uint32_t s_samples = 0;
static volatile uint32_t s_overflows = 0;    // DMA pool full: samples were lost
static volatile uint32_t s_dropped = 0;      // hop outputs that did not fit in the queue
static volatile uint32_t s_bad = 0;
static volatile uint32_t s_frames = 0;       // frame wake-ups since boot
static volatile uint32_t s_late = 0;         // wake-ups later than FRAME_PERIOD_US + LATE_MARGIN_US, since boot
static volatile uint32_t s_dev_max_us = 0;   // largest |interval - 16000| since the output task last cleared it
static volatile uint32_t s_block_since_ms = 0;   // naive: start of the current wait (0 = not waiting)
static volatile uint32_t s_block_last_ms = 0;    // naive: length of the last finished wait, until reported
static volatile uint32_t s_dsp_us_max = 0;
static volatile int32_t s_raw_min_mv, s_raw_max_mv, s_raw_avg_mv;
static volatile uint32_t s_raw_low, s_raw_high, s_raw_windows;
// core 0
static volatile uint32_t s_cmd_rx = 0;       // complete lines received
static volatile uint32_t s_parse_fail = 0;   // lines dropped by the parser (or too long)
static volatile uint32_t s_applied = 0;      // commands carried out
static volatile uint32_t s_event_drop = 0;   // events that did not fit in the queue

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static void post_event(const event_t *ev)
{
    if (xQueueSend(s_events, ev, 0) != pdTRUE) {    // never wait
        s_event_drop++;
    }
}

// Called by the task that parsed a set_params command: cmd_rx in designed mode, the sampler
// itself while it waits in naive mode (never both: s_naive_wait hands the USB input over).
// The event is queued before the word is published, so the output task always knows about a
// generation before the first hop that carries it.
static void publish_params(const coach_cmd_t *cmd, uint32_t waited_ms)
{
    uint32_t milli = s_param_word & 0xFFFF;
    if (cmd->has_hard_scale) {
        milli = (uint32_t)(cmd->hard_scale * 1000.0f + 0.5f);
    }
    event_t ev = { .kind = EV_SET_PARAMS, .cmd = *cmd, .gen = ++s_param_gen, .waited_ms = waited_ms };
    post_event(&ev);
    s_param_word = PARAM_WORD(ev.gen, milli);
}

// Carry out one parsed command. Returns true for a set_params (what a naive wait is waiting for).
static bool handle_command(const coach_cmd_t *cmd, uint32_t waited_ms)
{
    event_t ev = { .cmd = *cmd };
    switch (cmd->kind) {
    case COACH_CMD_SET_PARAMS:
        publish_params(cmd, waited_ms);
        return true;
    case COACH_CMD_MODE:
        s_naive = cmd->naive;
        ev.kind = EV_ACK_MODE;
        post_event(&ev);
        break;
    case COACH_CMD_SEGMENT:
        s_segment = cmd->segment_start;
        ev.kind = EV_ACK_SEGMENT;
        post_event(&ev);
        if (s_naive && !cmd->segment_start) {
            s_naive_wait = 1;       // naive: the sampler will now wait for the reply itself
        }
        break;
    }
    return false;
}

// --- USB input: line assembly shared by cmd_rx and the naive wait (one user at a time) --------
static char s_line[COACH_LINE_MAX + 2];
static size_t s_line_len = 0;
static bool s_line_overflow = false;

// Wait up to `ticks` for one byte; returns true when s_line holds a complete command line that
// parsed into *cmd. Bad lines are dropped and counted here.
static bool read_command(coach_cmd_t *cmd, TickType_t ticks)
{
    char c;
    if (usb_serial_jtag_read_bytes(&c, 1, ticks) != 1) {
        return false;
    }
    if (c != '\n') {
        if (s_line_len < sizeof s_line - 1) {
            s_line[s_line_len++] = c;
        } else {
            s_line_overflow = true;
        }
        return false;
    }
    s_line[s_line_len] = '\0';
    const bool empty = s_line_len == 0 || (s_line_len == 1 && s_line[0] == '\r');
    const bool overflow = s_line_overflow;
    s_line_len = 0;
    s_line_overflow = false;
    if (empty) {
        return false;
    }
    s_cmd_rx++;
    if (overflow || !coach_cmd_parse(s_line, cmd)) {
        s_parse_fail++;
        return false;
    }
    s_applied++;
    return true;
}

static void cmd_rx_task(void *arg)
{
    coach_cmd_t cmd;
    while (true) {
        if (s_naive_wait) {                     // naive: the sampler is reading the port
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        if (read_command(&cmd, pdMS_TO_TICKS(100))) {
            handle_command(&cmd, 0);
        }
    }
}

// Naive mode only: the sampler waits here for the reply to "segment end".
static void naive_wait_for_reply(void)
{
    const uint32_t start = now_ms();
    s_block_since_ms = start ? start : 1;
    coach_cmd_t cmd;
    while (now_ms() - start < NAIVE_TIMEOUT_MS) {
        if (read_command(&cmd, pdMS_TO_TICKS(50)) && handle_command(&cmd, now_ms() - start)) {
            break;
        }
    }
    s_block_last_ms = now_ms() - start;
    s_block_since_ms = 0;
    s_naive_wait = 0;
}

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
    coach_params_t params;
    coach_params_init(&params);
    coach_level_t level;
    coach_level_init(&level);
    uint32_t param_word = s_param_word;
    uint8_t buf[FRAME_BYTES];
    uint32_t index = 0;
    int low_frames = 0;
    int raw_min = INT32_MAX, raw_max = INT32_MIN, raw_n = 0;
    int64_t raw_sum = 0;
    uint32_t raw_low = 0, raw_high = 0;
    int8_t last_level = -1;
    uint8_t led = 0;
    int64_t last_wake_us = 0;

    ESP_ERROR_CHECK(adc_continuous_start(handle));

    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        // Frame timing as in experiments 03 / 04: interval between wake-ups against 16000 us.
        // Plain integer work on local and 32-bit shared variables; no printing, no locks.
        const int64_t now_us = esp_timer_get_time();
        if (last_wake_us != 0) {
            const int64_t dt = now_us - last_wake_us;
            const uint32_t dev = (uint32_t)(dt > FRAME_PERIOD_US ? dt - FRAME_PERIOD_US : FRAME_PERIOD_US - dt);
            if (dev > s_dev_max_us) {
                s_dev_max_us = dev;     // the output task clears it once per second
            }
            if (dt > FRAME_PERIOD_US + LATE_MARGIN_US) {
                s_late++;
            }
        }
        last_wake_us = now_us;
        s_frames++;

        // Button, polled once per 16 ms frame. Released after 2..61 low frames: segment
        // start / end. Held for LONG_PRESS_FRAMES: new calibration.
        if (gpio_get_level(BUTTON_GPIO) == 0) {
            if (++low_frames == LONG_PRESS_FRAMES) {
                emg_dsp_start_calibration(&dsp);
                event_t ev = { .kind = EV_BUTTON_CAL };
                post_event(&ev);
            }
        } else {
            if (low_frames >= 2 && low_frames < LONG_PRESS_FRAMES) {
                event_t ev = { .kind = EV_BUTTON_SEGMENT };
                post_event(&ev);
            }
            low_frames = 0;
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
                    // The one place where new parameters enter the level decision.
                    const uint32_t word = s_param_word;
                    if (word != param_word) {
                        param_word = word;
                        params.hard_scale = (float)(word & 0xFFFF) / 1000.0f;
                    }
                    hop.level = coach_level_update(&level, hop.out.level, hop.out.saturated, hop.out.normalized,
                                                   &params);
                    hop.param_gen = (uint16_t)(param_word >> 16);
                    if (hop.level != last_level) {
                        led ^= 1;                       // the camera sees this flip
                        gpio_set_level(LED_GPIO, led);
                        last_level = hop.level;
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
            if (us > s_dsp_us_max) {
                s_dsp_us_max = us;
            }
        }

        // Naive mode only (s_naive_wait is never set in designed mode): block right here, in
        // the sampling task, until the host's reply arrives.
        if (s_naive_wait) {
            naive_wait_for_reply();
        }
    }
}

// One protocol v1 message, the same fields as 08 / 10, with the coach level.
static int format_message(char *buf, size_t size, uint32_t boot, uint32_t seq, const hop_t *hop)
{
    const emg_output_t *o = &hop->out;
    int len = snprintf(buf, size,
                       "@{\"type\":\"emg\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32 ",\"seq\":%" PRIu32
                       ",\"sample_index\":%" PRIu32 ",\"device_ms\":%" PRIu32 ",\"rms_mV\":%.3f,\"norm\":%.3f"
                       ",\"level\":%d,\"saturated\":%s,\"calibrating\":%s,\"baseline_mV\":%.3f,\"led_state\":%u",
                       PROTOCOL_VERSION, DEVICE_NAME, boot, seq, o->sample_index, now_ms(), o->rms_mv,
                       o->normalized, hop->level, o->saturated ? "true" : "false",
                       o->calibrating ? "true" : "false", o->baseline_mv, hop->led_state);
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

static int format_ack(char *buf, size_t size, uint32_t boot, const coach_cmd_t *cmd, uint32_t sample_index,
                      uint32_t waited_ms, bool with_wait)
{
    int len = snprintf(buf, size, "@{\"type\":\"ack\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32 ",\"seq\":%" PRIu32,
                       PROTOCOL_VERSION, DEVICE_NAME, boot, cmd->seq);
    switch (cmd->kind) {
    case COACH_CMD_SET_PARAMS:
        if (cmd->has_hard_scale) {
            len += snprintf(buf + len, size - len, ",\"cmd\":\"set_params\",\"applied\":{\"hard_scale\":%.3f}",
                            cmd->hard_scale);
        } else {
            len += snprintf(buf + len, size - len, ",\"cmd\":\"set_params\",\"applied\":{}");
        }
        break;
    case COACH_CMD_SEGMENT:
        len += snprintf(buf + len, size - len, ",\"cmd\":\"segment\",\"applied\":{\"state\":\"%s\"}",
                        cmd->segment_start ? "start" : "end");
        break;
    case COACH_CMD_MODE:
        len += snprintf(buf + len, size - len, ",\"cmd\":\"mode\",\"applied\":{\"mode\":\"%s\"}",
                        cmd->naive ? "naive" : "designed");
        break;
    }
    len += snprintf(buf + len, size - len, ",\"clamped\":%s,\"sample_index\":%" PRIu32 ",\"device_ms\":%" PRIu32,
                    cmd->clamped ? "true" : "false", sample_index, now_ms());
    if (with_wait) {
        len += snprintf(buf + len, size - len, ",\"waited_ms\":%" PRIu32, waited_ms);
    }
    len += snprintf(buf + len, size - len, "}\n");
    return len;
}

static void output_task(void *arg)
{
    static char text[1536];
    hop_t hop;
    event_t ev;
    event_t pending[PENDING_ACKS];      // set_params commands waiting for their hop
    int n_pending = 0;
    uint32_t seq = 0, sent = 0, last_sample = 0, last_cores_ms = now_ms();
    uint32_t frames_prev = 0, late_prev = 0;
    const uint32_t boot = esp_random();

    while (true) {
        // Wake at least every 100 ms, so acks and the "cores" message keep flowing even when no
        // hop arrives (naive mode while the sampler is blocked).
        const bool have_hop = xQueueReceive(s_hops, &hop, pdMS_TO_TICKS(100)) == pdTRUE;
        int len = 0;

        while (xQueueReceive(s_events, &ev, 0) == pdTRUE) {
            switch (ev.kind) {
            case EV_SET_PARAMS:
                if (n_pending == PENDING_ACKS) {        // should not happen: ack the oldest now
                    len += format_ack(text + len, sizeof text - len, boot, &pending[0].cmd, last_sample, 0, false);
                    sent++;
                    for (int i = 1; i < n_pending; i++) {
                        pending[i - 1] = pending[i];
                    }
                    n_pending--;
                }
                pending[n_pending++] = ev;
                break;
            case EV_ACK_SEGMENT:
            case EV_ACK_MODE:
                len += format_ack(text + len, sizeof text - len, boot, &ev.cmd, last_sample, 0, false);
                sent++;
                break;
            case EV_BUTTON_SEGMENT:
                len += snprintf(text + len, sizeof text - len,
                                "@{\"type\":\"button\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32
                                ",\"event\":\"segment\",\"device_ms\":%" PRIu32 "}\n",
                                PROTOCOL_VERSION, DEVICE_NAME, boot, now_ms());
                sent++;
                break;
            case EV_BUTTON_CAL:
                len += snprintf(text + len, sizeof text - len, "# button: calibration started\n");
                break;
            }
        }

        if (have_hop) {
            const emg_output_t *o = &hop.out;
            last_sample = o->sample_index;
            // Ack every set_params whose generation this hop already used.
            int kept = 0;
            for (int i = 0; i < n_pending; i++) {
                if ((int16_t)(pending[i].gen - hop.param_gen) <= 0) {
                    len += format_ack(text + len, sizeof text - len, boot, &pending[i].cmd, o->sample_index,
                                      pending[i].waited_ms, pending[i].waited_ms > 0);
                    sent++;
                } else {
                    pending[kept++] = pending[i];
                }
            }
            n_pending = kept;
            len += format_message(text + len, sizeof text - len, boot, seq++, &hop);
            sent++;
            if (o->cal_event) {
                const emg_cal_report_t *r = &hop.report;
                len += snprintf(text + len, sizeof text - len,
                                "# calibration attempt %" PRIu32 ": %s (valid %.1f%%, cv %.3f, rms %.3f mV); baseline_mv=%.3f\n",
                                r->attempt, emg_cal_result_name(r->result), 100.0f * r->valid_fraction, r->cv,
                                r->rms_mv, o->baseline_mv);
            }
        }

        const uint32_t now = now_ms();
        if (now - last_cores_ms >= 1000) {              // once per second, by the clock
            last_cores_ms += 1000;
            const uint32_t frames = s_frames, late = s_late;
            const uint32_t dev_max = s_dev_max_us;
            s_dev_max_us = 0;       // a maximum written by the sampler at this very moment may move to the next second
            const uint32_t since = s_block_since_ms;
            uint32_t blocked = s_block_last_ms;
            s_block_last_ms = 0;
            if (since) {
                blocked = now - since;                  // still waiting
            }
            sent++;
            len += snprintf(text + len, sizeof text - len,
                            "@{\"type\":\"cores\",\"v\":%d,\"dev\":\"%s\",\"boot\":%" PRIu32 ",\"device_ms\":%" PRIu32
                            ",\"mode\":\"%s\",\"simulated\":false,\"hard_scale\":%.3f,\"segment\":%s"
                            ",\"core1\":{\"frames\":%" PRIu32 ",\"max_dev_us\":%" PRIu32 ",\"late\":%" PRIu32
                            ",\"blocked_ms\":%" PRIu32 ",\"ovf\":%" PRIu32 ",\"drop\":%" PRIu32 "}"
                            ",\"core0\":{\"cmd_rx\":%" PRIu32 ",\"parse_fail\":%" PRIu32 ",\"applied\":%" PRIu32
                            ",\"sent\":%" PRIu32 "}}\n",
                            PROTOCOL_VERSION, DEVICE_NAME, boot, now, s_naive ? "naive" : "designed",
                            (float)(s_param_word & 0xFFFF) / 1000.0f, s_segment ? "true" : "false",
                            frames - frames_prev, since ? blocked * 1000 : dev_max, late - late_prev, blocked,
                            s_overflows, s_dropped, s_cmd_rx, s_parse_fail, s_applied, sent);
            frames_prev = frames;
            late_prev = late;
            len += snprintf(text + len, sizeof text - len,
                            "# samples=%" PRIu32 " bad=%" PRIu32 " event_drop=%" PRIu32 " dsp_us_frame_max=%" PRIu32 "\n",
                            s_samples, s_bad, s_event_drop, s_dsp_us_max);
            if (s_raw_windows) {
                len += snprintf(text + len, sizeof text - len,
                                "# raw_mV min=%" PRId32 " avg=%" PRId32 " max=%" PRId32 " at_low=%" PRIu32
                                " at_high=%" PRIu32 " (of 1000; rails <= %d / >= %d mV)\n",
                                s_raw_min_mv, s_raw_avg_mv, s_raw_max_mv, s_raw_low, s_raw_high,
                                (int)EMG_SAT_LOW_MV, (int)EMG_SAT_HIGH_MV);
            }
        }
        if (len > 0) {
            usb_serial_jtag_write_bytes(text, len, portMAX_DELAY);
        }
    }
}

void app_main(void)
{
    usb_serial_jtag_driver_config_t usb_cfg = {
        .tx_buffer_size = USB_TX_BUFFER,
        .rx_buffer_size = USB_RX_BUFFER,
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

    ESP_LOGI(TAG, "GPIO%d -> ADC%d channel %d, %d Hz; button GPIO%d (short: segment, 1 s: calibration); "
             "levels in %.2f/%.2fx, out %.2f/%.2fx (provisional); hard_scale %.2f..%.2f",
             EMG_GPIO, (int)unit + 1, (int)s_channel, SAMPLE_HZ, BUTTON_GPIO, EMG_LEVEL1_ENTER, EMG_LEVEL2_ENTER,
             EMG_LEVEL1_EXIT, EMG_LEVEL2_EXIT, COACH_HARD_SCALE_MIN, COACH_HARD_SCALE_MAX);
    ESP_LOGI(TAG, "output: '@' protocol v1 JSON (emg every 50 ms, cores every 1 s, acks); input: '!' commands; "
             "'#' lines are status; LED GPIO%d", LED_GPIO);

    s_hops = xQueueCreate(QUEUE_ITEMS, sizeof(hop_t));
    s_events = xQueueCreate(EVENT_ITEMS, sizeof(event_t));
    adc_continuous_handle_t handle = adc_dma_init(s_channel);
    // Core 0: everything that talks to the host. cmd_rx has the lowest priority of the three.
    xTaskCreatePinnedToCore(output_task, "output", 6144, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(cmd_rx_task, "cmd_rx", 4096, NULL, 3, NULL, 0);
    // Core 1: sampler and DSP only (experiments 03 / 04). Wi-Fi is not started.
    xTaskCreatePinnedToCore(sampler_task, "sampler", 4096, handle, 10, NULL, 1);
}
