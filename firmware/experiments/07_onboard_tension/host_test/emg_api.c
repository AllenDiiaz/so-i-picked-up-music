// Flat C API around emg_dsp for ctypes (tools/replay_stream.py): the caller allocates
// emg_api_state_size() bytes and reads each hop output as an array of doubles.
#include <stddef.h>

#include "emg_dsp.h"

size_t emg_api_state_size(void) { return sizeof(emg_dsp_t); }
void emg_api_init(void *state) { emg_dsp_init((emg_dsp_t *)state); }
void emg_api_start_calibration(void *state) { emg_dsp_start_calibration((emg_dsp_t *)state); }
const char *emg_api_result_name(int result) { return emg_cal_result_name((emg_cal_result_t)result); }

// out[0..12]: sample_index, rms_mv, normalized, level, saturated, calibrating, baseline_mv,
// cal_event, cal_result, cal_attempt, cal_valid_fraction, cal_cv, cal_rms_mv
int emg_api_process(void *state, float raw_mv, double *out)
{
    emg_dsp_t *d = (emg_dsp_t *)state;
    emg_output_t o;
    if (!emg_dsp_process(d, raw_mv, &o)) {
        return 0;
    }
    const emg_cal_report_t *r = &d->report;
    out[0] = o.sample_index;
    out[1] = o.rms_mv;
    out[2] = o.normalized;
    out[3] = o.level;
    out[4] = o.saturated;
    out[5] = o.calibrating;
    out[6] = o.baseline_mv;
    out[7] = o.cal_event;
    out[8] = o.cal_event ? r->result : 0;
    out[9] = o.cal_event ? r->attempt : 0;
    out[10] = o.cal_event ? r->valid_fraction : 0;
    out[11] = o.cal_event ? r->cv : 0;
    out[12] = o.cal_event ? r->rms_mv : 0;
    return 1;
}
