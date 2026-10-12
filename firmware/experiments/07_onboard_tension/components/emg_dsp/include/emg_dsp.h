// On-board EMG tension estimate (experiment 07). Plain C99, no ESP-IDF dependencies, so the
// same file builds for the ESP32-S3, for host tests and as a shared library for the replayer.
//
// Per sample: mains notches (60/120/180 Hz) -> 45-200 Hz band-pass -> squared into a 200 ms
// window. Every 50 ms (one hop) the window RMS is compared with a relax baseline from a 5 s
// calibration, giving normalized = RMS / baseline and a level 0 (relax), 1 (medium) or
// 2 (hard) with hysteresis. Filter coefficients come from emg_coeffs.h
// (analysis/design_emg_filters.py).
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "emg_coeffs.h"

#define EMG_WINDOW_SAMPLES  200     // 200 ms RMS window at 1 kHz
#define EMG_HOP_SAMPLES     50      // one output every 50 ms (20 Hz)

// --- calibration -----------------------------------------------------------------------------
#define EMG_SETTLE_SAMPLES     500      // after reset, wait 0.5 s for the filters to settle
#define EMG_CAL_SAMPLES        5000     // one attempt collects 5 s
#define EMG_CAL_RETRY_SAMPLES  2000     // after a rejected attempt, wait 2 s and try again
// An attempt is accepted only if all three hold (all PROVISIONAL):
#define EMG_CAL_MIN_VALID      4500     // >= 90 % of its samples are unsaturated
#define EMG_CAL_MAX_BASELINE_MV 15.0f   // relax RMS stays below the medium range seen in experiment 06
#ifndef EMG_CAL_MAX_CV                  // overridable for host experiments (-DEMG_CAL_MAX_CV=0.3f)
#define EMG_CAL_MAX_CV         0.5f     // coefficient of variation of the 50 ms RMS values (see README)
#endif
#define EMG_CAL_CHUNK_SAMPLES  50       // length of those RMS values
#define EMG_CAL_CHUNKS         (EMG_CAL_SAMPLES / EMG_CAL_CHUNK_SAMPLES)
#define EMG_CAL_CHUNK_MIN      25       // a chunk needs this many unsaturated samples to count

// --- levels: multiples of the baseline, with hysteresis. PROVISIONAL: entry ratios chosen
// in-sample from experiment 06, exit ratios about 10 % lower; not validated on new data.
#define EMG_LEVEL1_ENTER    1.49f
#define EMG_LEVEL2_ENTER    2.72f
#ifndef EMG_LEVEL1_EXIT                 // overridable for host experiments (= ENTER: no hysteresis)
#define EMG_LEVEL1_EXIT     1.35f
#endif
#ifndef EMG_LEVEL2_EXIT
#define EMG_LEVEL2_EXIT     2.45f
#endif

// A raw reading at or beyond these limits is at the ADC rails (largest calibrated value 3108 mV).
#define EMG_SAT_LOW_MV      5.0f
#define EMG_SAT_HIGH_MV     3100.0f

typedef enum {
    EMG_CAL_NONE = 0,       // no attempt finished yet
    EMG_CAL_OK,             // accepted
    EMG_CAL_SATURATED,      // rejected: under EMG_CAL_MIN_VALID unsaturated samples
    EMG_CAL_TOO_HIGH,       // rejected: RMS >= EMG_CAL_MAX_BASELINE_MV
    EMG_CAL_UNSTABLE,       // rejected: 50 ms RMS too variable (CV >= EMG_CAL_MAX_CV)
} emg_cal_result_t;

typedef struct {
    emg_cal_result_t result;
    uint32_t attempt;       // 1, 2, ... since the last reset or button press
    float valid_fraction;   // unsaturated share of the attempt's samples
    float cv;               // coefficient of variation of the 50 ms RMS values
    float rms_mv;           // RMS of the attempt (the new baseline if accepted)
} emg_cal_report_t;

typedef struct {
    uint32_t sample_index;  // index of the last sample in the window (0 = first sample processed)
    float rms_mv;           // window RMS of the filtered signal; last valid value while saturated
    float normalized;       // rms_mv / baseline; 0 while there is no baseline or while calibrating
    int8_t level;           // 0 relax, 1 medium, 2 hard; -1 while there is no baseline or while calibrating
    bool saturated;         // a raw sample in the window was at a rail (outputs held)
    bool calibrating;       // the filters are settling or an attempt is collecting
    float baseline_mv;      // baseline in use, 0 = none
    bool cal_event;         // an attempt finished since the previous hop: see emg_dsp_t.report
} emg_output_t;

typedef enum { EMG_PHASE_SETTLE, EMG_PHASE_COLLECT, EMG_PHASE_WAIT, EMG_PHASE_IDLE } emg_cal_phase_t;

typedef struct {
    float z[EMG_NUM_SECTIONS][2];   // biquad states (Direct Form II transposed)
    float offset_mv;                // first raw sample, subtracted from every input
    float sq[EMG_WINDOW_SAMPLES];   // squared filtered samples, ring buffer
    uint8_t sat[EMG_WINDOW_SAMPLES];
    uint32_t sat_count;             // saturated raw samples currently in the window
    uint32_t pos;                   // ring position
    uint32_t n;                     // samples processed

    float baseline_mv;              // relax RMS, 0 = none yet
    emg_cal_phase_t phase;
    uint32_t phase_left;            // samples left in SETTLE, COLLECT or WAIT
    float cal_sum;                  // sum of squares of the attempt's unsaturated samples
    uint32_t cal_count;
    float chunk_sum;                // current 50 ms chunk
    uint32_t chunk_valid, chunk_samples;
    float chunk_rms[EMG_CAL_CHUNKS];
    uint32_t n_chunks;
    uint32_t attempt;
    emg_cal_report_t report;        // last finished attempt
    bool report_pending;

    bool have_valid;                // last_* hold a valid (unsaturated) output
    float last_rms, last_normalized;
    int8_t last_level;
} emg_dsp_t;

// Reset all state. Calibration attempts start after EMG_SETTLE_SAMPLES samples and repeat
// every EMG_CAL_RETRY_SAMPLES until one is accepted.
void emg_dsp_init(emg_dsp_t *d);

// Start a new calibration attempt with the next sample (e.g. after a button press). Levels are
// -1 while it collects; if it is rejected, attempts repeat until one is accepted, and the
// previous baseline (if any) is used in between.
void emg_dsp_start_calibration(emg_dsp_t *d);

// Process one raw ADC reading in mV. Returns true when *out holds a new hop output.
bool emg_dsp_process(emg_dsp_t *d, float raw_mv, emg_output_t *out);

// Short name of a calibration result, e.g. for logs.
const char *emg_cal_result_name(emg_cal_result_t r);
