/**
 * @file comms.h
 * @brief Backend communication interface (HTTP telemetry).
 *
 * Provides functions to send node heartbeat, GPS coordinates,
 * sensor data, and SOS alerts to the FastAPI backend.
 */

#pragma once

#include "peripheral_gps.h"
#include "peripheral_sensors.h"
#include <stdbool.h>

/**
 * @brief Initialize the communications module.
 */
void comms_init(void);

/**
 * @brief Send a heartbeat/telemetry update to the backend.
 *
 * Sends node identity, mesh level, RSSI, optional GPS data,
 * and optional sensor readings (BMP280 + MPU6050) to the server.
 *
 * @param node_id   Unique node identifier (e.g. "EMESH-AABBCC").
 * @param is_root   Whether this node is currently the root.
 * @param level     Current mesh tree level / hop count.
 * @param rssi      Wi-Fi RSSI to AP in dBm.
 * @param has_gps_hw True if GPS hardware is detected (even if no fix).
 * @param gps       Pointer to GPS data (NULL if GPS fix not available).
 * @param env       Pointer to BMP280 data (NULL if sensor not present).
 * @param imu       Pointer to MPU6050 data (NULL if sensor not present).
 * @return true if the server acknowledged the request.
 */
bool comms_send_heartbeat(const char *node_id, bool is_root,
                          int level, int rssi,
                          bool has_gps_hw,
                          const gps_data_t     *gps,
                          const bmp280_data_t  *env,
                          const mpu6050_data_t *imu);

/**
 * @brief Send an SOS alert to the backend.
 *
 * @param node_id  Originating node ID.
 * @param gps      Pointer to GPS data (NULL if unavailable).
 * @return true if the server acknowledged the SOS.
 */
bool comms_send_sos(const char *node_id, const gps_data_t *gps);
