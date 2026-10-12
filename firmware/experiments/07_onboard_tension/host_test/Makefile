# Builds the host test with the same emg_dsp.c that runs on the board.
DSP = ../components/emg_dsp
CFLAGS = -std=c99 -O2 -Wall -Wextra -Werror -I$(DSP)/include

emg_host: main.c $(DSP)/emg_dsp.c $(DSP)/include/emg_dsp.h $(DSP)/include/emg_coeffs.h
	$(CC) $(CFLAGS) -o $@ main.c $(DSP)/emg_dsp.c -lm

clean:
	rm -f emg_host

.PHONY: clean
