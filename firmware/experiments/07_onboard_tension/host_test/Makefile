# Builds the host test and the shared library for tools/replay_stream.py, both from the same
# emg_dsp.c that runs on the board.
DSP = ../components/emg_dsp
CFLAGS = -std=c99 -O2 -Wall -Wextra -Werror -I$(DSP)/include
DEPS = $(DSP)/emg_dsp.c $(DSP)/include/emg_dsp.h $(DSP)/include/emg_coeffs.h

all: emg_host libemg_dsp.dylib

emg_host: main.c $(DEPS)
	$(CC) $(CFLAGS) -o $@ main.c $(DSP)/emg_dsp.c -lm

libemg_dsp.dylib: emg_api.c $(DEPS)
	$(CC) $(CFLAGS) -dynamiclib -o $@ emg_api.c $(DSP)/emg_dsp.c -lm

clean:
	rm -f emg_host libemg_dsp.dylib

.PHONY: all clean
