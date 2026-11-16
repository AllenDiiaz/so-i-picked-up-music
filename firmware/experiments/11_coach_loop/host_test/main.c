// Host test of the coach component (experiment 11).
//
//   make -C firmware/experiments/11_coach_loop/host_test test
//
// 1. Command parser: valid commands, clamping, and a list of lines that must be rejected.
// 2. Level: with hard_scale = 1.0, coach_level_update() equals the DSP's own level on every
//    hop of the given experiment 06 recordings; with a larger scale it never shows more hard.
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "coach.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); failures++; } } while (0)

static void test_parser(void)
{
    coach_cmd_t c;

    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":1.10,\"seq\":7}", &c));
    CHECK(c.kind == COACH_CMD_SET_PARAMS && c.seq == 7 && c.has_hard_scale && !c.clamped);
    CHECK(fabsf(c.hard_scale - 1.10f) < 1e-6f);

    // key order, spaces and line endings do not matter
    CHECK(coach_cmd_parse("! { \"seq\" : 4294967295 , \"cmd\" : \"set_params\" , \"v\" : 1 }\r\n", &c));
    CHECK(c.kind == COACH_CMD_SET_PARAMS && c.seq == 4294967295u && !c.has_hard_scale);

    // out of range: clamped and flagged
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":9,\"seq\":1}", &c));
    CHECK(c.clamped && c.hard_scale == COACH_HARD_SCALE_MAX);
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":-3e2,\"seq\":1}", &c));
    CHECK(c.clamped && c.hard_scale == COACH_HARD_SCALE_MIN);
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":0.8,\"seq\":1}", &c));
    CHECK(!c.clamped);

    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"segment\",\"state\":\"start\",\"seq\":2}", &c));
    CHECK(c.kind == COACH_CMD_SEGMENT && c.segment_start && c.seq == 2);
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"segment\",\"state\":\"end\",\"seq\":3}\n", &c));
    CHECK(c.kind == COACH_CMD_SEGMENT && !c.segment_start);
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"mode\",\"mode\":\"naive\",\"seq\":4}", &c));
    CHECK(c.kind == COACH_CMD_MODE && c.naive);
    CHECK(coach_cmd_parse("!{\"v\":1,\"cmd\":\"mode\",\"mode\":\"designed\",\"seq\":5}", &c));
    CHECK(c.kind == COACH_CMD_MODE && !c.naive);

    static const char *bad[] = {
        "",
        "!",
        "{\"v\":1,\"cmd\":\"set_params\",\"seq\":1}",                          // no '!'
        "@{\"v\":1,\"cmd\":\"set_params\",\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1",                          // truncated
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1}}",                        // trailing text
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1} x",
        "!{\"v\":2,\"cmd\":\"set_params\",\"seq\":1}",                         // wrong version
        "!{\"cmd\":\"set_params\",\"seq\":1}",                                 // no version
        "!{\"v\":1,\"cmd\":\"set_params\"}",                                   // no seq
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":-1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1.5}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":4294967296}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1,\"seq\":2}",               // duplicate key
        "!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":\"1.1\",\"seq\":1}",  // string instead of number
        "!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":nan,\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":1e99,\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":null,\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"hard_scale\":{\"x\":1},\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_params\",\"medium_scale\":1.1,\"seq\":1}",    // unknown key
        "!{\"v\":1,\"cmd\":\"set_params\",\"state\":\"end\",\"seq\":1}",       // key of another command
        "!{\"v\":1,\"cmd\":\"reboot\",\"seq\":1}",                             // unknown command
        "!{\"v\":1,\"cmd\":\"segment\",\"seq\":1}",                            // missing state
        "!{\"v\":1,\"cmd\":\"segment\",\"state\":\"pause\",\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"mode\",\"mode\":\"fast\",\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"mode\",\"mode\":\"naive\",\"hard_scale\":1,\"seq\":1}",
        "!{\"v\":1,\"cmd\":\"set_\\u0070arams\",\"seq\":1}",                   // escapes are not accepted
        "!{\"v\":1,,\"cmd\":\"set_params\",\"seq\":1}",
        "![1,2,3]",
        "!hello",
    };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        if (coach_cmd_parse(bad[i], &c)) {
            printf("FAIL: accepted bad line %zu: %s\n", i, bad[i]);
            failures++;
        }
    }
    char longline[400];
    memset(longline, ' ', sizeof longline);
    memcpy(longline, "!{\"v\":1,\"cmd\":\"set_params\",\"seq\":1", 34);
    longline[sizeof longline - 2] = '}';
    longline[sizeof longline - 1] = '\0';
    CHECK(!coach_cmd_parse(longline, &c));                                     // over COACH_LINE_MAX
    CHECK(!coach_cmd_parse(NULL, &c));
    printf("parser: %zu rejected lines, valid and clamped cases checked\n", sizeof bad / sizeof bad[0] + 2);
}

static void test_levels(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        perror(path);
        failures++;
        return;
    }
    static emg_dsp_t dsp;
    emg_dsp_init(&dsp);
    coach_level_t same, strict, loose;
    coach_level_init(&same);
    coach_level_init(&strict);
    coach_level_init(&loose);
    const coach_params_t p_same = { 1.0f }, p_strict = { COACH_HARD_SCALE_MIN }, p_loose = { COACH_HARD_SCALE_MAX };
    char line[256];
    long last_index = -1, n = 0, hops = 0, differ = 0, hard_dsp = 0, hard_strict = 0, hard_loose = 0, order = 0;
    while (fgets(line, sizeof line, f)) {
        double host_s;
        long index;
        int value;
        if (sscanf(line, " %lf\t%ld,%d", &host_s, &index, &value) != 3) {
            continue;
        }
        if (n > 0 && index != last_index + 1) {     // a newer board run starts: begin again
            n = 0;
        }
        last_index = index;
        if (n == 0) {
            if (index != 0) {
                continue;
            }
            emg_dsp_init(&dsp);
            coach_level_init(&same);
            coach_level_init(&strict);
            coach_level_init(&loose);
            hops = differ = hard_dsp = hard_strict = hard_loose = order = 0;
        }
        n++;
        emg_output_t o;
        if (!emg_dsp_process(&dsp, (float)value, &o)) {
            continue;
        }
        hops++;
        int a = coach_level_update(&same, o.level, o.saturated, o.normalized, &p_same);
        int s = coach_level_update(&strict, o.level, o.saturated, o.normalized, &p_strict);
        int l = coach_level_update(&loose, o.level, o.saturated, o.normalized, &p_loose);
        differ += a != o.level;
        hard_dsp += o.level == 2;
        hard_strict += s == 2;
        hard_loose += l == 2;
        order += !(l <= a && a <= s);               // a higher threshold never shows a higher level
        order += (o.level < 0) != (s < 0) || (o.level < 0) != (l < 0);
    }
    fclose(f);
    CHECK(hops > 100);
    CHECK(differ == 0);
    CHECK(order == 0);
    CHECK(hard_loose <= hard_dsp && hard_dsp <= hard_strict);
    printf("levels: %s: %ld hops, scale 1.00 differs from the DSP on %ld; hard hops at scale %.2f / 1.00 / %.2f: "
           "%ld / %ld / %ld\n", path, hops, differ, (double)COACH_HARD_SCALE_MIN, (double)COACH_HARD_SCALE_MAX,
           hard_strict, hard_dsp, hard_loose);
}

int main(int argc, char **argv)
{
    test_parser();
    for (int i = 1; i < argc; i++) {
        test_levels(argv[i]);
    }
    if (failures) {
        printf("%d check(s) FAILED\n", failures);
        return 1;
    }
    printf("coach host test passed\n");
    return 0;
}
