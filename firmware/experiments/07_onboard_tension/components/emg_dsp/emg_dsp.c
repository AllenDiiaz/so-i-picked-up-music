// On-board EMG tension estimate (experiment 07). See emg_dsp.h.
#include "emg_dsp.h"

#include <math.h>
#include <string.h>

static void begin_attempt(emg_dsp_t *d)
{
    d->phase = EMG_PHASE_COLLECT;
    d->phase_left = EMG_CAL_SAMPLES;
    d->cal_sum = 0.0f;
    d->cal_count = 0;
    d->chunk_sum = 0.0f;
    d->chunk_valid = 0;
    d->chunk_samples = 0;
    d->n_chunks = 0;
    d->attempt++;
}

void emg_dsp_init(emg_dsp_t *d)
{
    memset(d, 0, sizeof(*d));
    d->last_level = -1;
    d->phase = EMG_PHASE_SETTLE;
    d->phase_left = EMG_SETTLE_SAMPLES;
}

void emg_dsp_start_calibration(emg_dsp_t *d)
{
    d->attempt = 0;
    begin_attempt(d);
}

const char *emg_cal_result_name(emg_cal_result_t r)
{
    switch (r) {
    case EMG_CAL_OK: return "accepted";
    case EMG_CAL_SATURATED: return "rejected: saturated";
    case EMG_CAL_TOO_HIGH: return "rejected: baseline too high";
    case EMG_CAL_UNSTABLE: return "rejected: unstable";
    default: return "none";
    }
}

static float filter(emg_dsp_t *d, float x)
{
    for (int s = 0; s < EMG_NUM_SECTIONS; s++) {
        const float *c = EMG_SOS[s];
        float *z = d->z[s];
        float y = c[0] * x + z[0];
        z[0] = c[1] * x - c[3] * y + z[1];
        z[1] = c[2] * x - c[4] * y;
        x = y;
    }
    return x;
}

// Level with hysteresis: entering a level needs its ENTER ratio, staying needs only EXIT.
static int8_t next_level(int8_t prev, float r)
{
    if (r >= EMG_LEVEL2_ENTER || (prev == 2 && r >= EMG_LEVEL2_EXIT)) {
        return 2;
    }
    if (r >= EMG_LEVEL1_ENTER || (prev >= 1 && r >= EMG_LEVEL1_EXIT)) {
        return 1;
    }
    return 0;
}

static void finish_attempt(emg_dsp_t *d)
{
    emg_cal_report_t *r = &d->report;
    r->attempt = d->attempt;
    r->valid_fraction = (float)d->cal_count / EMG_CAL_SAMPLES;
    r->rms_mv = d->cal_count ? sqrtf(d->cal_sum / (float)d->cal_count) : 0.0f;
    float mean = 0.0f, var = 0.0f;
    for (uint32_t i = 0; i < d->n_chunks; i++) {
        mean += d->chunk_rms[i];
    }
    mean = d->n_chunks ? mean / (float)d->n_chunks : 0.0f;
    for (uint32_t i = 0; i < d->n_chunks; i++) {
        float e = d->chunk_rms[i] - mean;
        var += e * e;
    }
    r->cv = (d->n_chunks > 1 && mean > 0.0f) ? sqrtf(var / (float)d->n_chunks) / mean : INFINITY;

    if (d->cal_count < EMG_CAL_MIN_VALID) {
        r->result = EMG_CAL_SATURATED;
    } else if (r->rms_mv >= EMG_CAL_MAX_BASELINE_MV) {
        r->result = EMG_CAL_TOO_HIGH;
    } else if (!(r->cv < EMG_CAL_MAX_CV)) {
        r->result = EMG_CAL_UNSTABLE;
    } else {
        r->result = EMG_CAL_OK;
    }
    d->report_pending = true;
    if (r->result == EMG_CAL_OK) {
        d->baseline_mv = r->rms_mv;
        d->phase = EMG_PHASE_IDLE;
    } else {
        d->phase = EMG_PHASE_WAIT;
        d->phase_left = EMG_CAL_RETRY_SAMPLES;
    }
}

static void calibration_step(emg_dsp_t *d, float y2, bool sat)
{
    switch (d->phase) {
    case EMG_PHASE_SETTLE:          // filter start-up transient: not part of any baseline
    case EMG_PHASE_WAIT:
        if (--d->phase_left == 0) {
            begin_attempt(d);
        }
        break;
    case EMG_PHASE_COLLECT:
        if (!sat) {
            d->cal_sum += y2;
            d->cal_count++;
            d->chunk_sum += y2;
            d->chunk_valid++;
        }
        if (++d->chunk_samples == EMG_CAL_CHUNK_SAMPLES) {
            if (d->chunk_valid >= EMG_CAL_CHUNK_MIN) {
                d->chunk_rms[d->n_chunks++] = sqrtf(d->chunk_sum / (float)d->chunk_valid);
            }
            d->chunk_sum = 0.0f;
            d->chunk_valid = 0;
            d->chunk_samples = 0;
        }
        if (--d->phase_left == 0) {
            finish_attempt(d);
        }
        break;
    case EMG_PHASE_IDLE:
        break;
    }
}

bool emg_dsp_process(emg_dsp_t *d, float raw_mv, emg_output_t *out)
{
    if (d->n == 0) {
        // The band-pass removes DC anyway; subtracting the first reading only avoids the
        // start-up transient of a step from 0 to ~1.6 V.
        d->offset_mv = raw_mv;
    }
    const bool sat = raw_mv <= EMG_SAT_LOW_MV || raw_mv >= EMG_SAT_HIGH_MV;
    const float y = filter(d, raw_mv - d->offset_mv);
    const float y2 = y * y;

    // Window ring: replace the oldest sample.
    d->sat_count -= d->sat[d->pos];
    d->sat[d->pos] = sat;
    d->sat_count += sat;
    d->sq[d->pos] = y2;
    d->pos = (d->pos + 1) % EMG_WINDOW_SAMPLES;
    d->n++;

    calibration_step(d, y2, sat);

    if (d->n < EMG_WINDOW_SAMPLES || d->n % EMG_HOP_SAMPLES != 0) {
        return false;
    }

    const bool calibrating = d->phase == EMG_PHASE_SETTLE || d->phase == EMG_PHASE_COLLECT;
    out->sample_index = d->n - 1;
    out->calibrating = calibrating;
    out->saturated = d->sat_count > 0;
    out->baseline_mv = d->baseline_mv;
    out->cal_event = d->report_pending;
    d->report_pending = false;
    if (!out->saturated) {
        float sum = 0.0f;   // summed afresh each hop: no drift from a running sum
        for (int i = 0; i < EMG_WINDOW_SAMPLES; i++) {
            sum += d->sq[i];
        }
        d->last_rms = sqrtf(sum / EMG_WINDOW_SAMPLES);
        if (d->baseline_mv > 0.0f && !calibrating) {
            d->last_normalized = d->last_rms / d->baseline_mv;
            d->last_level = next_level(d->last_level, d->last_normalized);
        } else {
            d->last_normalized = 0.0f;
            d->last_level = -1;
        }
        d->have_valid = true;
    } else if (calibrating || d->baseline_mv <= 0.0f) {
        d->last_normalized = 0.0f;
        d->last_level = -1;
    }
    out->rms_mv = d->have_valid ? d->last_rms : 0.0f;
    out->normalized = d->last_normalized;
    out->level = d->last_level;
    return true;
}
