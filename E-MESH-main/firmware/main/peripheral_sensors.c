/**
 * @file peripheral_sensors.c
 * @brief BMP280 and MPU6050 I2C driver implementation.
 *
 * Uses the ESP-IDF i2c driver for all bus communication.
 * Auto-detects both sensors on init; missing sensors are gracefully skipped.
 */

#include "peripheral_sensors.h"
#include "board_config.h"

#include <string.h>
#include "driver/i2c.h"
#include "esp_log.h"

static const char *TAG = "SENSORS";

/* ── Internal state ─────────────────────────────────────────────────────── */

static bool s_i2c_ready   = false;
static bool s_has_bmp280  = false;
static bool s_has_mpu6050 = false;
static uint8_t s_mpu6050_addr = MPU6050_I2C_ADDR;

/* BMP280 calibration coefficients (read from sensor NVM on init) */
static uint16_t dig_T1;
static int16_t  dig_T2, dig_T3;
static uint16_t dig_P1;
static int16_t  dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;

/* ── Internal I2C helpers ───────────────────────────────────────────────── */

static esp_err_t i2c_read_reg(uint8_t dev_addr, uint8_t reg, uint8_t *buf, size_t len)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_READ, true);
    i2c_master_read(cmd, buf, len, I2C_MASTER_LAST_NACK);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(I2C_MASTER_PORT, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return err;
}

static esp_err_t i2c_write_reg(uint8_t dev_addr, uint8_t reg, uint8_t value)
{
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (dev_addr << 1) | I2C_MASTER_WRITE, true);
    i2c_master_write_byte(cmd, reg, true);
    i2c_master_write_byte(cmd, value, true);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(I2C_MASTER_PORT, cmd, pdMS_TO_TICKS(100));
    i2c_cmd_link_delete(cmd);
    return err;
}

/* ── BMP280 ─────────────────────────────────────────────────────────────── */

#define BMP280_REG_ID          0xD0
#define BMP280_REG_RESET       0xE0
#define BMP280_REG_CALIB_START 0x88
#define BMP280_REG_CTRL_MEAS   0xF4
#define BMP280_REG_CONFIG      0xF5
#define BMP280_REG_PRESS_MSB   0xF7
#define BMP280_CHIP_ID         0x60  /* Also 0x58 for older BMP280 */
#define BMP280_CHIP_ID_ALT     0x58

static bool bmp280_init(void)
{
    uint8_t chip_id = 0;
    if (i2c_read_reg(BMP280_I2C_ADDR, BMP280_REG_ID, &chip_id, 1) != ESP_OK) {
        ESP_LOGI(TAG, "BMP280 not found at 0x%02X", BMP280_I2C_ADDR);
        return false;
    }
    if (chip_id != BMP280_CHIP_ID && chip_id != BMP280_CHIP_ID_ALT) {
        ESP_LOGI(TAG, "BMP280 unexpected chip ID: 0x%02X", chip_id);
        return false;
    }

    /* Read calibration coefficients from NVM (0x88..0x9F) */
    uint8_t calib[24];
    if (i2c_read_reg(BMP280_I2C_ADDR, BMP280_REG_CALIB_START, calib, 24) != ESP_OK) {
        ESP_LOGE(TAG, "BMP280 calibration read failed");
        return false;
    }

    dig_T1 = (uint16_t)(calib[1] << 8 | calib[0]);
    dig_T2 = (int16_t) (calib[3] << 8 | calib[2]);
    dig_T3 = (int16_t) (calib[5] << 8 | calib[4]);
    dig_P1 = (uint16_t)(calib[7] << 8 | calib[6]);
    dig_P2 = (int16_t) (calib[9] << 8 | calib[8]);
    dig_P3 = (int16_t) (calib[11] << 8 | calib[10]);
    dig_P4 = (int16_t) (calib[13] << 8 | calib[12]);
    dig_P5 = (int16_t) (calib[15] << 8 | calib[14]);
    dig_P6 = (int16_t) (calib[17] << 8 | calib[16]);
    dig_P7 = (int16_t) (calib[19] << 8 | calib[18]);
    dig_P8 = (int16_t) (calib[21] << 8 | calib[20]);
    dig_P9 = (int16_t) (calib[23] << 8 | calib[22]);

    /* Normal mode, oversampling x1 for temp and pressure */
    i2c_write_reg(BMP280_I2C_ADDR, BMP280_REG_CONFIG,   0xA0); /* t_standby=1000ms, filter=off */
    i2c_write_reg(BMP280_I2C_ADDR, BMP280_REG_CTRL_MEAS, 0x27); /* osrs_t=x1, osrs_p=x1, mode=normal */

    ESP_LOGI(TAG, "BMP280 detected (chip_id=0x%02X)", chip_id);
    return true;
}

static bool bmp280_read(bmp280_data_t *out)
{
    uint8_t raw[6];
    if (i2c_read_reg(BMP280_I2C_ADDR, BMP280_REG_PRESS_MSB, raw, 6) != ESP_OK) {
        return false;
    }

    /* Reconstruct 20-bit ADC values */
    int32_t adc_P = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) | (raw[2] >> 4);
    int32_t adc_T = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);

    /* BMP280 compensated temperature formula (from datasheet) */
    int32_t var1 = ((((adc_T >> 3) - ((int32_t)dig_T1 << 1))) * (int32_t)dig_T2) >> 11;
    int32_t var2 = (((((adc_T >> 4) - (int32_t)dig_T1) *
                      ((adc_T >> 4) - (int32_t)dig_T1)) >> 12) * (int32_t)dig_T3) >> 14;
    int32_t t_fine = var1 + var2;
    out->temperature_c = (float)((t_fine * 5 + 128) >> 8) / 100.0f;

    /* BMP280 compensated pressure formula (from datasheet) */
    int64_t p_var1 = (int64_t)t_fine - 128000;
    int64_t p_var2 = p_var1 * p_var1 * (int64_t)dig_P6;
    p_var2 = p_var2 + ((p_var1 * (int64_t)dig_P5) << 17);
    p_var2 = p_var2 + (((int64_t)dig_P4) << 35);
    p_var1 = ((p_var1 * p_var1 * (int64_t)dig_P3) >> 8) + ((p_var1 * (int64_t)dig_P2) << 12);
    p_var1 = (((((int64_t)1) << 47) + p_var1)) * ((int64_t)dig_P1) >> 33;
    if (p_var1 == 0) {
        out->pressure_hpa = 0.0f;
        return true;
    }
    int64_t p = 1048576 - adc_P;
    p = (((p << 31) - p_var2) * 3125) / p_var1;
    p_var1 = ((int64_t)dig_P9 * (p >> 13) * (p >> 13)) >> 25;
    p_var2 = (((int64_t)dig_P8) * p) >> 19;
    p = ((p + p_var1 + p_var2) >> 8) + (((int64_t)dig_P7) << 4);
    out->pressure_hpa = (float)p / 25600.0f;

    return true;
}

/* ── MPU6050 ────────────────────────────────────────────────────────────── */

#define MPU6050_REG_PWR_MGMT_1  0x6B
#define MPU6050_REG_SMPLRT_DIV  0x19
#define MPU6050_REG_CONFIG_REG  0x1A
#define MPU6050_REG_GYRO_CONFIG 0x1B
#define MPU6050_REG_ACCEL_CFG   0x1C
#define MPU6050_REG_ACCEL_XOUT  0x3B
#define MPU6050_REG_WHO_AM_I    0x75
#define MPU6050_WHO_AM_I_VAL    0x68

static bool mpu6050_init(void)
{
    uint8_t who_am_i = 0;
    s_mpu6050_addr = MPU6050_I2C_ADDR;
    
    if (i2c_read_reg(s_mpu6050_addr, MPU6050_REG_WHO_AM_I, &who_am_i, 1) != ESP_OK) {
        /* Try alternate address 0x69 */
        s_mpu6050_addr = 0x69;
        if (i2c_read_reg(s_mpu6050_addr, MPU6050_REG_WHO_AM_I, &who_am_i, 1) != ESP_OK) {
            ESP_LOGI(TAG, "MPU6050 not found at 0x68 or 0x69");
            return false;
        }
    }
    
    if (who_am_i != MPU6050_WHO_AM_I_VAL) {
        ESP_LOGI(TAG, "MPU6050 unexpected WHO_AM_I: 0x%02X", who_am_i);
        return false;
    }

    /* Wake up the MPU6050 (clears SLEEP bit in PWR_MGMT_1) */
    i2c_write_reg(s_mpu6050_addr, MPU6050_REG_PWR_MGMT_1,  0x00);
    /* Sample rate = 8kHz / (1 + 7) = 1kHz */
    i2c_write_reg(s_mpu6050_addr, MPU6050_REG_SMPLRT_DIV,  0x07);
    /* DLPF = 260Hz bandwidth */
    i2c_write_reg(s_mpu6050_addr, MPU6050_REG_CONFIG_REG,  0x00);
    /* Gyro full-scale = +/- 250 deg/s */
    i2c_write_reg(s_mpu6050_addr, MPU6050_REG_GYRO_CONFIG, 0x00);
    /* Accel full-scale = +/- 2g */
    i2c_write_reg(s_mpu6050_addr, MPU6050_REG_ACCEL_CFG,   0x00);

    ESP_LOGI(TAG, "MPU6050 detected (WHO_AM_I=0x%02X)", who_am_i);
    return true;
}

static bool mpu6050_read(mpu6050_data_t *out)
{
    uint8_t raw[14];
    /* 14 bytes: ACCEL_X(2), ACCEL_Y(2), ACCEL_Z(2), TEMP(2), GYRO_X(2), GYRO_Y(2), GYRO_Z(2) */
    if (i2c_read_reg(s_mpu6050_addr, MPU6050_REG_ACCEL_XOUT, raw, 14) != ESP_OK) {
        return false;
    }

    out->accel_x  = (int16_t)(raw[0]  << 8 | raw[1]);
    out->accel_y  = (int16_t)(raw[2]  << 8 | raw[3]);
    out->accel_z  = (int16_t)(raw[4]  << 8 | raw[5]);
    out->temp_raw = (int16_t)(raw[6]  << 8 | raw[7]);
    out->gyro_x   = (int16_t)(raw[8]  << 8 | raw[9]);
    out->gyro_y   = (int16_t)(raw[10] << 8 | raw[11]);
    out->gyro_z   = (int16_t)(raw[12] << 8 | raw[13]);

    return true;
}

/* ── Public API ─────────────────────────────────────────────────────────── */

void sensors_init(void)
{
    ESP_LOGI(TAG, "Initializing I2C master on SDA=%d, SCL=%d @ %d Hz",
             PIN_I2C_SDA, PIN_I2C_SCL, I2C_MASTER_FREQ_HZ);

    i2c_config_t conf = {
        .mode             = I2C_MODE_MASTER,
        .sda_io_num       = PIN_I2C_SDA,
        .scl_io_num       = PIN_I2C_SCL,
        .sda_pullup_en    = GPIO_PULLUP_ENABLE,
        .scl_pullup_en    = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_MASTER_FREQ_HZ,
    };

    esp_err_t err = i2c_param_config(I2C_MASTER_PORT, &conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C param config failed: %s", esp_err_to_name(err));
        return;
    }

    err = i2c_driver_install(I2C_MASTER_PORT, I2C_MODE_MASTER, 0, 0, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C driver install failed: %s", esp_err_to_name(err));
        return;
    }

    s_i2c_ready = true;

    /* Auto-detect each sensor independently */
    s_has_bmp280  = bmp280_init();
    s_has_mpu6050 = mpu6050_init();

    ESP_LOGI(TAG, "Sensor scan complete: BMP280=%s, MPU6050=%s",
             s_has_bmp280 ? "OK" : "NOT FOUND",
             s_has_mpu6050 ? "OK" : "NOT FOUND");
}

bool sensors_has_bmp280(void)  { return s_has_bmp280;  }
bool sensors_has_mpu6050(void) { return s_has_mpu6050; }

bool sensors_read_bmp280(bmp280_data_t *data)
{
    if (!s_has_bmp280 || !data) return false;
    return bmp280_read(data);
}

bool sensors_read_mpu6050(mpu6050_data_t *data)
{
    if (!s_has_mpu6050 || !data) return false;
    return mpu6050_read(data);
}
