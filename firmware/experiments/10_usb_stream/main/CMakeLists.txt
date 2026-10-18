idf_component_register(SRCS "usb_stream.c"
                       PRIV_REQUIRES esp_adc esp_driver_usb_serial_jtag esp_driver_gpio esp_timer esp_hw_support emg_dsp
                       INCLUDE_DIRS ".")
