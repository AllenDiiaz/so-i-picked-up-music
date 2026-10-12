# Plain C99 DSP shared with host_test/ (no ESP-IDF dependencies).
idf_component_register(SRCS "emg_dsp.c"
                       INCLUDE_DIRS "include")
