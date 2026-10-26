/**
 * @file peripheral_gps.h
 * @brief NEO-6M GPS module driver interface.
 *
 * Provides hardware-independent GPS functions. The actual UART pins
 * are resolved from board_config.h at compile time.
 */

#pragma once

#include <stdbool.h>

/**
 * @brief GPS fix data structure.
 */
typedef struct {
    bool    valid;          /**< True if we have a valid GPS fix */
    double  latitude;       /**< Latitude in decimal degrees */
    double  longitude;      /**< Longitude in decimal degrees */
    float   altitude_m;     /**< Altitude in meters */
    int     satellites;     /**< Number of satellites in view */
    float   hdop;           /**< Horizontal dilution of precision */
    int     hour;           /**< UTC hour */
    int     minute;         /**< UTC minute */
    int     second;         /**< UTC second */
} gps_data_t;

/**
 * @brief Initialize the GPS UART peripheral.
 *
 * Attempts to configure the UART and start the GPS reader task.
 * If the GPS module is not physically connected, it will detect
 * this after a timeout and set gps_is_present() to false.
 *
 * @return ESP_OK on success, ESP_FAIL if UART init fails.
 */
int gps_init(void);

/**
 * @brief Check if a GPS module was detected on boot.
 * @return true if GPS hardware is present and responding.
 */
bool gps_is_present(void);

/**
 * @brief Get the latest GPS fix data.
 * @param[out] data Pointer to gps_data_t to fill.
 * @return true if data is valid (has a fix), false otherwise.
 */
bool gps_get_data(gps_data_t *data);
