// On-board EMG tension estimate (experiment 07). Plain C99, no ESP-IDF dependencies, so the
// same file builds for the ESP32-S3 and for host tests.
//
// Per sample: mains notches (60/120/180 Hz) -> 45-200 Hz band-pass -> squared into a 200 ms
// window. Every 50 ms (one hop) the window RMS is compared with a relax baseline taken from a
// 5 s calibration, giving normalized = RMS / baseline and a level 0 (relax), 1 (medium) or
// 2 (hard). Filter coefficients come from emg_coeffs.h (analysis/design_emg_filters.py).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "emg_coeffs.h"

#define EMG_WINDOW_SAMPLES  200     // 200 ms RMS window at 1 kHz
#define EMG_HOP_SAMPLES     50      // one output every 50 ms (20 Hz)
#define EMG_CAL_SAMPLES     5000    // 5 s relax calibration
#define EMG_SETTLE_SAMPLES  500     // after reset, wait 0.5 s for the filters to settle before calibrating
#define EMG_CAL_MIN_VALID   4500    // a calibration needs at least 90 % unsaturated samples to count

// Level thresholds as multiples of the relax baseline. PROVISIONAL: chosen in-sample from
// experiment 06 (halfway between relax and the weakest medium effort, and between the
// strongest medium and the weakest hard effort) and not yet validated on new recordings.
#define EMG_LEVEL1_RATIO    1.49f
#define EMG_LEVEL2_RATIO    2.72f

// A raw reading at or beyond these limits is at the ADC rails (largest calibrated value 3108 mV).
#define EMG_SAT_LOW_MV      5.0f
#define EMG_SAT_HIGH_MV     3100.0f

typedef struct {
    uint32_t sample_index;  // index of the last sample in the window (0 = first sample processed)
    float rms_mv;           // window RMS of the filtered signal; last valid value while saturated
    float normalized;       // rms_mv / baseline; 0 while there is no baseline or while calibrating
    int8_t level;           // 0 relax, 1 medium, 2 hard; -1 while there is no baseline or while calibrating
    bool saturated;         // a raw sample in the window was at a rail (outputs held)
    bool calibrating;       // a calibration is in progress
} emg_output_t;

typedef struct {
    float z[EMG_NUM_SECTIONS][2];   // biquad states (Direct Form II transposed)
    float offset_mv;                // first raw sample, subtracted from every input
    float sq[EMG_WINDOW_SAMPLES];   // squared filtered samples, ring buffer
    uint8_t sat[EMG_WINDOW_SAMPLES];
    uint32_t sat_count;             // saturated raw samples currently in the window
    uint32_t pos;                   // ring position
    uint32_t n;                     // samples processed

    float baseline_mv;              // relax RMS, 0 = none yet
    bool last_cal_ok;               // the most recent finished calibration was accepted
    uint32_t settle_left;           // samples to skip before the first calibration (filter start-up)
    uint32_t cal_left;              // samples still to collect in the current calibration
    float cal_sum;                  // sum of squares of the non-saturated calibration samples
    uint32_t cal_count;

    bool have_valid;                // last_* hold a valid (unsaturated) output
    float last_rms, last_normalized;
    int8_t last_level;
} emg_dsp_t;

// Reset all state. The first calibration starts after EMG_SETTLE_SAMPLES samples.
void emg_dsp_init(emg_dsp_t *d);

// Use the next EMG_CAL_SAMPLES samples as the new relax baseline (e.g. after a button press).
// The previous baseline stays stored but levels are reported as -1 until the new one is ready.
// If fewer than EMG_CAL_MIN_VALID of those samples are unsaturated, the calibration is
// rejected and the previous baseline (or none) is kept.
void emg_dsp_start_calibration(emg_dsp_t *d);

// Process one raw ADC reading in mV. Returns true when *out holds a new hop output.
bool emg_dsp_process(emg_dsp_t *d, float raw_mv, emg_output_t *out);
