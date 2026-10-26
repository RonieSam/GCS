/**
 * @file peripheral_sensors.h
 * @brief BMP280 (Temp/Pressure) and MPU6050 (6-axis IMU) driver interface.
 *
 * Both sensors share the same I2C bus (pins defined in board_config.h).
 * This module performs auto-detection on boot. If a sensor is absent,
 * its data fields remain zeroed and has_bmp280/has_mpu6050 report false.
 * The node continues normal operation regardless.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Environmental sensor data from BMP280.
 */
typedef struct {
    float temperature_c;    /**< Temperature in degrees Celsius */
    float pressure_hpa;     /**< Atmospheric pressure in hPa */
} bmp280_data_t;

/**
 * @brief 6-axis IMU raw data from MPU6050.
 * All values are raw sensor readings (not scaled to physical units).
 * Scaling factors: Accel = raw / 16384.0 (g), Gyro = raw / 131.0 (deg/s)
 */
typedef struct {
    int16_t accel_x;    /**< Accelerometer X-axis raw value */
    int16_t accel_y;    /**< Accelerometer Y-axis raw value */
    int16_t accel_z;    /**< Accelerometer Z-axis raw value */
    int16_t gyro_x;     /**< Gyroscope X-axis raw value */
    int16_t gyro_y;     /**< Gyroscope Y-axis raw value */
    int16_t gyro_z;     /**< Gyroscope Z-axis raw value */
    int16_t temp_raw;   /**< Internal temperature raw (not used, BMP280 is preferred) */
} mpu6050_data_t;

/**
 * @brief Initialize I2C master and auto-detect connected sensors.
 *
 * Scans for BMP280 at address 0x76 and MPU6050 at address 0x68.
 * Safe to call even when no sensors are physically connected.
 * Detected sensors are configured with sensible defaults.
 */
void sensors_init(void);

/**
 * @brief Check if a BMP280 was detected on boot.
 * @return true if BMP280 is present and initialized.
 */
bool sensors_has_bmp280(void);

/**
 * @brief Check if an MPU6050 was detected on boot.
 * @return true if MPU6050 is present and initialized.
 */
bool sensors_has_mpu6050(void);

/**
 * @brief Read latest data from the BMP280.
 * @param[out] data Pointer to bmp280_data_t to fill.
 * @return true if the read was successful.
 */
bool sensors_read_bmp280(bmp280_data_t *data);

/**
 * @brief Read latest raw data from the MPU6050.
 * @param[out] data Pointer to mpu6050_data_t to fill.
 * @return true if the read was successful.
 */
bool sensors_read_mpu6050(mpu6050_data_t *data);
