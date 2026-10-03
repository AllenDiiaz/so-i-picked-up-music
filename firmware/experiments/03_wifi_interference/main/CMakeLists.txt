idf_component_register(SRCS "adc_wifi.c"
                       PRIV_REQUIRES esp_adc esp_timer esp_wifi esp_netif esp_event nvs_flash
                       INCLUDE_DIRS ".")
