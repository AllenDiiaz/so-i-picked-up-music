// On-board EMG tension estimate (experiment 07). See emg_dsp.h.
#include "emg_dsp.h"

#include <math.h>
#include <string.h>

void emg_dsp_init(emg_dsp_t *d)
{
    memset(d, 0, sizeof(*d));
    d->last_level = -1;
    d->settle_left = EMG_SETTLE_SAMPLES;
    emg_dsp_start_calibration(d);
}

void emg_dsp_start_calibration(emg_dsp_t *d)
{
    d->cal_left = EMG_CAL_SAMPLES;
    d->cal_sum = 0.0f;
    d->cal_count = 0;
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

static int8_t level_of(float normalized)
{
    if (normalized >= EMG_LEVEL2_RATIO) {
        return 2;
    }
    return normalized >= EMG_LEVEL1_RATIO ? 1 : 0;
}

bool emg_dsp_process(emg_dsp_t *d, float raw_mv, emg_output_t *out)
{
    if (d->n == 0) {
        // The band-pass removes DC anyway; subtracting the first reading only avoids the
        // start-up transient of a step from 0 to ~1.6 V, which would spoil the first calibration.
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

    if (d->settle_left > 0) {
        d->settle_left--;   // filter start-up transient: not part of the baseline
    } else if (d->cal_left > 0) {
        if (!sat) {
            d->cal_sum += y2;
            d->cal_count++;
        }
        if (--d->cal_left == 0) {
            // A calibration taken mostly at the ADC rails says nothing about relax: keep the old baseline.
            d->last_cal_ok = d->cal_count >= EMG_CAL_MIN_VALID;
            if (d->last_cal_ok) {
                d->baseline_mv = sqrtf(d->cal_sum / (float)d->cal_count);
            }
        }
    }

    if (d->n < EMG_WINDOW_SAMPLES || d->n % EMG_HOP_SAMPLES != 0) {
        return false;
    }

    out->sample_index = d->n - 1;
    out->calibrating = d->cal_left > 0;
    out->saturated = d->sat_count > 0;
    if (!out->saturated) {
        float sum = 0.0f;   // summed afresh each hop: no drift from a running sum
        for (int i = 0; i < EMG_WINDOW_SAMPLES; i++) {
            sum += d->sq[i];
        }
        d->last_rms = sqrtf(sum / EMG_WINDOW_SAMPLES);
        if (d->baseline_mv > 0.0f && !out->calibrating) {
            d->last_normalized = d->last_rms / d->baseline_mv;
            d->last_level = level_of(d->last_normalized);
        } else {
            d->last_normalized = 0.0f;
            d->last_level = -1;
        }
        d->have_valid = true;
    } else if (out->calibrating || d->baseline_mv <= 0.0f) {
        d->last_normalized = 0.0f;
        d->last_level = -1;
    }
    out->rms_mv = d->have_valid ? d->last_rms : 0.0f;
    out->normalized = d->last_normalized;
    out->level = d->last_level;
    return true;
}
