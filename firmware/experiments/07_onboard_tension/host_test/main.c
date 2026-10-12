// Host test for emg_dsp.c: feed a record_serial.py capture of experiment 06 through the same
// DSP code that runs on the board and print one CSV line per hop.
//
//   make -C firmware/experiments/07_onboard_tension/host_test
//   ./host_test/emg_host LOG > out.csv
//
// Uses the newest board run in the log (the run that starts at sample index 0 last), from its
// first sample, exactly as the firmware would see it after boot.
#include <stdio.h>
#include <stdlib.h>

#include "emg_dsp.h"

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s LOG\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "r");
    if (!f) {
        perror(argv[1]);
        return 1;
    }

    size_t cap = 1 << 17, n = 0;
    float *mv = malloc(cap * sizeof(float));
    char line[256];
    long last_index = -1;
    while (fgets(line, sizeof line, f)) {
        double host_s;
        long index;
        int value;
        if (sscanf(line, " %lf\t%ld,%d", &host_s, &index, &value) != 3) {
            continue;   // boot log, '#' statistics lines
        }
        if (n > 0 && index != last_index + 1) {
            n = 0;      // restart or leftover lines from an older run: wait for index 0 again
        }
        if (n == 0 && index != 0) {
            last_index = index;
            continue;
        }
        if (n == cap) {
            cap *= 2;
            mv = realloc(mv, cap * sizeof(float));
        }
        mv[n++] = (float)value;
        last_index = index;
    }
    fclose(f);

    emg_dsp_t dsp;
    emg_dsp_init(&dsp);
    emg_output_t out;
    printf("sample_index,rms_mv,normalized,level,saturated,calibrating\n");
    for (size_t i = 0; i < n; i++) {
        if (emg_dsp_process(&dsp, mv[i], &out)) {
            printf("%u,%.6f,%.6f,%d,%d,%d\n", (unsigned)out.sample_index, out.rms_mv, out.normalized,
                   out.level, out.saturated, out.calibrating);
        }
    }
    fprintf(stderr, "%zu samples, baseline %.4f mV\n", n, dsp.baseline_mv);
    free(mv);
    return 0;
}
