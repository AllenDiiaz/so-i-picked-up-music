idf_component_register(SRCS "onboard_tension.c"
                       PRIV_REQUIRES esp_adc esp_driver_usb_serial_jtag esp_driver_gpio esp_timer emg_dsp
                       INCLUDE_DIRS ".")
