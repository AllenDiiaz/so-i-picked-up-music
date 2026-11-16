// Flat C API around the coach component for ctypes (tools/fake_device.py). The emg_api_*
// functions of the 07 host test are linked into the same library.
#include "coach.h"

// out[0..6]: kind, seq, has_hard_scale, hard_scale, clamped, segment_start, naive
int coach_api_parse(const char *line, double *out)
{
    coach_cmd_t c;
    if (!coach_cmd_parse(line, &c)) {
        return 0;
    }
    out[0] = c.kind;
    out[1] = c.seq;
    out[2] = c.has_hard_scale;
    out[3] = c.hard_scale;
    out[4] = c.clamped;
    out[5] = c.segment_start;
    out[6] = c.naive;
    return 1;
}

// *state: the previous level (start with -1); returns and stores the new level.
int coach_api_level(int *state, int dsp_level, int saturated, double normalized, double hard_scale)
{
    coach_level_t s = { .level = (int8_t)*state };
    coach_params_t p = { .hard_scale = (float)hard_scale };
    *state = coach_level_update(&s, (int8_t)dsp_level, saturated != 0, (float)normalized, &p);
    return *state;
}

double coach_api_hard_scale_min(void) { return COACH_HARD_SCALE_MIN; }
double coach_api_hard_scale_max(void) { return COACH_HARD_SCALE_MAX; }
