// Coach loop, device side (experiment 11): downlink command parsing and the one tunable
// parameter of the level decision. Plain C99, no ESP-IDF dependencies: the same file runs on
// the ESP32-S3, in host_test/ and in tools/fake_device.py (ctypes).
//
// Downlink (host -> device), one line per command, prefixed with '!':
//   !{"v":1,"cmd":"set_params","hard_scale":1.10,"seq":7}
//   !{"v":1,"cmd":"set_params","seq":8}                      (no parameter: nothing changes)
//   !{"v":1,"cmd":"segment","state":"start","seq":9}         (or "end")
//   !{"v":1,"cmd":"mode","mode":"naive","seq":10}            (or "designed")
// The parser is strict on purpose: a flat JSON object with only the keys above, string or
// number values, no escapes, no duplicates. Anything else is rejected; the caller drops the
// line and counts it. Values outside the allowed range are clamped and flagged, not rejected.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "emg_dsp.h"

#define COACH_PROTOCOL_VERSION  1
#define COACH_LINE_MAX          160     // longest accepted command line, including '!'

// hard_scale multiplies the "hard" entry and exit ratios (EMG_LEVEL2_ENTER / _EXIT).
// 1.0 = the thresholds of emg_dsp.h. The range keeps hard above medium:
// 0.80 * 2.45 = 1.96 > EMG_LEVEL1_ENTER (1.49).
#define COACH_HARD_SCALE_DEFAULT 1.00f
#define COACH_HARD_SCALE_MIN     0.80f
#define COACH_HARD_SCALE_MAX     1.50f

typedef enum { COACH_CMD_SET_PARAMS = 1, COACH_CMD_SEGMENT, COACH_CMD_MODE } coach_cmd_kind_t;

typedef struct {
    coach_cmd_kind_t kind;
    uint32_t seq;
    bool has_hard_scale;    // set_params: a hard_scale value was given
    float hard_scale;       // already clamped to [MIN, MAX]
    bool clamped;           // the given value was outside the range
    bool segment_start;     // segment: true = start, false = end
    bool naive;             // mode: true = naive, false = designed
} coach_cmd_t;

// Parse one line (with or without a trailing "\r\n"). Returns false if it is not a valid command.
bool coach_cmd_parse(const char *line, coach_cmd_t *out);

typedef struct {
    float hard_scale;
} coach_params_t;

typedef struct {
    int8_t level;           // -1 none, 0 relax, 1 medium, 2 hard
} coach_level_t;

void coach_params_init(coach_params_t *p);
void coach_level_init(coach_level_t *s);

// Level for one hop from the DSP output (its level, saturated flag and normalized value).
// With hard_scale = 1.0 the result equals the DSP's own level on every hop (host test).
int8_t coach_level_update(coach_level_t *s, int8_t dsp_level, bool saturated, float normalized,
                          const coach_params_t *p);
