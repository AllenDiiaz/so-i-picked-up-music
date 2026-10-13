idf_component_register(SRCS "wifi_stream.c"
                       PRIV_REQUIRES esp_adc esp_driver_usb_serial_jtag esp_driver_gpio esp_timer esp_wifi
                                     esp_netif esp_event nvs_flash lwip emg_dsp
                       INCLUDE_DIRS ".")

# Use wifi_config.h if it exists, else the template. CONFIGURE_DEPENDS makes every build re-check,
# so creating or deleting the file changes the definition and recompiles wifi_stream.c.
if(NOT CMAKE_BUILD_EARLY_EXPANSION)
    file(GLOB wifi_config CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/wifi_config.h")
    if(wifi_config)
        target_compile_definitions(${COMPONENT_LIB} PRIVATE HAVE_WIFI_CONFIG=1)
    else()
        target_compile_definitions(${COMPONENT_LIB} PRIVATE HAVE_WIFI_CONFIG=0)
    endif()
endif()
