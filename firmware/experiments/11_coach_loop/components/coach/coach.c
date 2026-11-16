#include "coach.h"

#include <stdlib.h>
#include <string.h>

// --- strict flat-JSON reader ---------------------------------------------------------------
static const char *skip_ws(const char *p)
{
    while (*p == ' ' || *p == '\t') {
        p++;
    }
    return p;
}

// p at the opening quote. Copies the string (no escapes, printable ASCII only) and returns
// the position after the closing quote, or NULL.
static const char *read_string(const char *p, char *out, size_t size)
{
    if (*p != '"') {
        return NULL;
    }
    p++;
    size_t n = 0;
    while (*p != '"') {
        if (*p < 0x20 || *p > 0x7e || *p == '\\' || n + 1 >= size) {
            return NULL;
        }
        out[n++] = *p++;
    }
    out[n] = '\0';
    return p + 1;
}

// JSON number grammar: -? digits (. digits)? ([eE] [+-]? digits)?
static const char *read_number(const char *p, double *value)
{
    const char *start = p;
    if (*p == '-') {
        p++;
    }
    if (*p < '0' || *p > '9') {
        return NULL;
    }
    while (*p >= '0' && *p <= '9') {
        p++;
    }
    if (*p == '.') {
        p++;
        if (*p < '0' || *p > '9') {
            return NULL;
        }
        while (*p >= '0' && *p <= '9') {
            p++;
        }
    }
    if (*p == 'e' || *p == 'E') {
        p++;
        if (*p == '+' || *p == '-') {
            p++;
        }
        if (*p < '0' || *p > '9') {
            return NULL;
        }
        while (*p >= '0' && *p <= '9') {
            p++;
        }
    }
    char buf[32];
    size_t len = (size_t)(p - start);
    if (len >= sizeof buf) {
        return NULL;
    }
    memcpy(buf, start, len);
    buf[len] = '\0';
    *value = strtod(buf, NULL);
    if (!(*value == *value) || *value > 1e12 || *value < -1e12) {   // NaN or absurd
        return NULL;
    }
    return p;
}

enum { K_V = 1, K_CMD = 2, K_SEQ = 4, K_HARD_SCALE = 8, K_STATE = 16, K_MODE = 32 };

bool coach_cmd_parse(const char *line, coach_cmd_t *out)
{
    if (line == NULL || out == NULL || line[0] != '!') {
        return false;
    }
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        len--;
    }
    if (len > COACH_LINE_MAX) {
        return false;
    }
    char text[COACH_LINE_MAX + 1];
    memcpy(text, line, len);
    text[len] = '\0';

    unsigned seen = 0;
    double v = 0, seq = 0, hard_scale = 0;
    char cmd[16] = "", state[8] = "", mode[12] = "";
    const char *p = skip_ws(text + 1);
    if (*p != '{') {
        return false;
    }
    p = skip_ws(p + 1);
    while (true) {
        char key[16];
        p = read_string(p, key, sizeof key);
        if (p == NULL) {
            return false;
        }
        p = skip_ws(p);
        if (*p != ':') {
            return false;
        }
        p = skip_ws(p + 1);
        unsigned bit;
        if (strcmp(key, "v") == 0) {
            bit = K_V;
            p = read_number(p, &v);
        } else if (strcmp(key, "seq") == 0) {
            bit = K_SEQ;
            p = read_number(p, &seq);
        } else if (strcmp(key, "hard_scale") == 0) {
            bit = K_HARD_SCALE;
            p = read_number(p, &hard_scale);
        } else if (strcmp(key, "cmd") == 0) {
            bit = K_CMD;
            p = read_string(p, cmd, sizeof cmd);
        } else if (strcmp(key, "state") == 0) {
            bit = K_STATE;
            p = read_string(p, state, sizeof state);
        } else if (strcmp(key, "mode") == 0) {
            bit = K_MODE;
            p = read_string(p, mode, sizeof mode);
        } else {
            return false;                   // unknown key
        }
        if (p == NULL || (seen & bit)) {    // bad value or duplicate key
            return false;
        }
        seen |= bit;
        p = skip_ws(p);
        if (*p == ',') {
            p = skip_ws(p + 1);
            continue;
        }
        if (*p == '}') {
            p = skip_ws(p + 1);
            break;
        }
        return false;
    }
    if (*p != '\0') {
        return false;                       // trailing text
    }
    const unsigned base = K_V | K_CMD | K_SEQ;
    if ((seen & base) != base || v != COACH_PROTOCOL_VERSION) {
        return false;
    }
    if (seq < 0 || seq > 4294967295.0 || seq != (double)(uint32_t)seq) {
        return false;
    }
    memset(out, 0, sizeof *out);
    out->seq = (uint32_t)seq;
    out->hard_scale = COACH_HARD_SCALE_DEFAULT;
    if (strcmp(cmd, "set_params") == 0) {
        if (seen & ~(base | K_HARD_SCALE)) {
            return false;
        }
        out->kind = COACH_CMD_SET_PARAMS;
        if (seen & K_HARD_SCALE) {
            out->has_hard_scale = true;
            const float hs = (float)hard_scale;     // compare as float, like the limits
            if (hs < COACH_HARD_SCALE_MIN) {
                out->hard_scale = COACH_HARD_SCALE_MIN;
                out->clamped = true;
            } else if (hs > COACH_HARD_SCALE_MAX) {
                out->hard_scale = COACH_HARD_SCALE_MAX;
                out->clamped = true;
            } else {
                out->hard_scale = hs;
            }
        }
        return true;
    }
    if (strcmp(cmd, "segment") == 0) {
        if (seen != (base | K_STATE)) {
            return false;
        }
        out->kind = COACH_CMD_SEGMENT;
        if (strcmp(state, "start") == 0) {
            out->segment_start = true;
        } else if (strcmp(state, "end") != 0) {
            return false;
        }
        return true;
    }
    if (strcmp(cmd, "mode") == 0) {
        if (seen != (base | K_MODE)) {
            return false;
        }
        out->kind = COACH_CMD_MODE;
        if (strcmp(mode, "naive") == 0) {
            out->naive = true;
        } else if (strcmp(mode, "designed") != 0) {
            return false;
        }
        return true;
    }
    return false;
}

// --- level with a scaled hard threshold ------------------------------------------------------
void coach_params_init(coach_params_t *p)
{
    p->hard_scale = COACH_HARD_SCALE_DEFAULT;
}

void coach_level_init(coach_level_t *s)
{
    s->level = -1;
}

int8_t coach_level_update(coach_level_t *s, int8_t dsp_level, bool saturated, float normalized,
                          const coach_params_t *p)
{
    if (dsp_level < 0) {            // calibrating or no baseline
        s->level = -1;
    } else if (!saturated) {        // while saturated the DSP holds its outputs: hold ours too
        const float enter2 = EMG_LEVEL2_ENTER * p->hard_scale;
        const float exit2 = EMG_LEVEL2_EXIT * p->hard_scale;
        if (normalized >= enter2 || (s->level == 2 && normalized >= exit2)) {
            s->level = 2;
        } else if (normalized >= EMG_LEVEL1_ENTER || (s->level >= 1 && normalized >= EMG_LEVEL1_EXIT)) {
            s->level = 1;
        } else {
            s->level = 0;
        }
    }
    return s->level;
}
