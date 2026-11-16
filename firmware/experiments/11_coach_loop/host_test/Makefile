# Host build of the coach component (command parser + scaled level) together with the 07 DSP:
#   make test             parser cases, and "hard_scale = 1.0 equals the DSP level" on the
#                         experiment 06 recordings
#   libcoach.dylib        the same C code for tools/fake_device.py (ctypes)
DSP = ../../07_onboard_tension/components/emg_dsp
DSP_API = ../../07_onboard_tension/host_test/emg_api.c
COACH = ../components/coach
DATA = ../../../../docs/data/06_forearm_emg
CFLAGS = -std=c99 -O2 -Wall -Wextra -Werror -I$(DSP)/include -I$(COACH)/include
DEPS = $(DSP)/emg_dsp.c $(DSP)/include/emg_dsp.h $(DSP)/include/emg_coeffs.h $(COACH)/coach.c $(COACH)/include/coach.h

all: coach_host libcoach.dylib

coach_host: main.c $(DEPS)
	$(CC) $(CFLAGS) -o $@ main.c $(COACH)/coach.c $(DSP)/emg_dsp.c -lm

libcoach.dylib: coach_api.c $(DSP_API) $(DEPS)
	$(CC) $(CFLAGS) -dynamiclib -o $@ coach_api.c $(DSP_API) $(COACH)/coach.c $(DSP)/emg_dsp.c -lm

test: coach_host
	./coach_host $(DATA)/03_A_light_hard.log $(DATA)/04_B_chord.log

clean:
	rm -f coach_host libcoach.dylib

.PHONY: all test clean
