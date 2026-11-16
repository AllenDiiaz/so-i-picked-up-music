# Plain C99, shared with host_test/ and tools/fake_device.py (no ESP-IDF dependencies).
idf_component_register(SRCS "coach.c"
                       INCLUDE_DIRS "include"
                       REQUIRES emg_dsp)
