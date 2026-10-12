idf_component_register(SRCS "wifi_stream.c"
                       PRIV_REQUIRES esp_adc esp_driver_usb_serial_jtag esp_driver_gpio esp_timer esp_wifi
                                     esp_netif esp_event nvs_flash lwip emg_dsp
                       INCLUDE_DIRS ".")
