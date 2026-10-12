idf_component_register(SRCS "raw_emg_stream.c"
                       PRIV_REQUIRES esp_adc esp_driver_usb_serial_jtag
                       INCLUDE_DIRS ".")
