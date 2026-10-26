/**
 * @file board_config.h
 * @brief Hardware-specific GPIO pin mappings for ESP32-WROOM and ESP32-C3-Mini.
 *
 * All board-specific constants are isolated here. The rest of the firmware
 * uses only the generic macro names (e.g., PIN_GPS_TX, PIN_SOS_BUTTON).
 * To add a new board, create a new #elif block with the appropriate defines.
 */

#pragma once

/* =============================================================================
   ESP32-WROOM (DevKitC / 38-pin variant)
   =============================================================================

   Wiring Reference (WROOM):
   +-----------------+----------+----------------------------+
   | Peripheral      | GPIO Pin | Notes                      |
   +-----------------+----------+----------------------------+
   | GPS TX -> ESP RX| GPIO 16  | UART2 RX (connect NEO TX)  |
   | GPS RX -> ESP TX| GPIO 17  | UART2 TX (connect NEO RX)  |
   | SOS Button      | GPIO 27  | Active LOW, internal PU    |
   | LED Indicator   | GPIO 2   | Built-in LED on most devs  |
   | Buzzer          | GPIO 25  | Active HIGH                |
   | I2C SDA         | GPIO 21  | BMP280 + MPU6050 shared    |
   | I2C SCL         | GPIO 22  | BMP280 + MPU6050 shared    |
   +-----------------+----------+----------------------------+
   ============================================================================= */
#if defined(BOARD_WROOM)

#define PIN_GPS_UART_TX     17
#define PIN_GPS_UART_RX     16
#define GPS_UART_PORT_NUM   UART_NUM_2

#define PIN_SOS_BUTTON      27
#define PIN_LED             2
#define PIN_BUZZER          25

#define PIN_I2C_SDA         21
#define PIN_I2C_SCL         22

/* =============================================================================
   ESP32-C3-Mini (DevKitM-1)
   =============================================================================

   Wiring Reference (C3 Mini):
   +-----------------+----------+----------------------------+
   | Peripheral      | GPIO Pin | Notes                      |
   +-----------------+----------+----------------------------+
   | GPS TX -> ESP RX| GPIO 4   | UART1 RX (connect NEO TX)  |
   | GPS RX -> ESP TX| GPIO 5   | UART1 TX (connect NEO RX)  |
   | SOS Button      | GPIO 9   | Active LOW (BOOT button)   |
   | LED Indicator   | GPIO 8   | On-board RGB/LED           |
   | Buzzer          | GPIO 3   | Active HIGH                |
   | I2C SDA         | GPIO 6   | BMP280 + MPU6050 shared    |
   | I2C SCL         | GPIO 7   | BMP280 + MPU6050 shared    |
   +-----------------+----------+----------------------------+

   Note: C3 only has UART0 (console) and UART1. We use UART1 for GPS.
   ============================================================================= */
#elif defined(BOARD_C3)

#define PIN_GPS_UART_TX     5
#define PIN_GPS_UART_RX     4
#define GPS_UART_PORT_NUM   UART_NUM_1

#define PIN_SOS_BUTTON      9
#define PIN_LED             8
#define PIN_BUZZER          3

#define PIN_I2C_SDA         6
#define PIN_I2C_SCL         7

#else
#error "No board defined! Set -DBOARD_WROOM or -DBOARD_C3 in build_flags."
#endif

/* =============================================================================
   Common Constants (board-independent)
   ============================================================================= */
#define GPS_UART_BAUD_RATE      9600
#define GPS_UART_BUF_SIZE       1024

/* SOS button debounce time in milliseconds */
#define SOS_DEBOUNCE_MS         300

/* LED and Buzzer timing */
#define LED_BLINK_FAST_MS       150
#define LED_BLINK_SLOW_MS       500
#define BUZZER_BEEP_SHORT_MS    100
#define BUZZER_BEEP_LONG_MS     500

/* I2C master configuration */
#define I2C_MASTER_FREQ_HZ      400000   /* 400 kHz fast mode */
#define I2C_MASTER_PORT         I2C_NUM_0

/* BMP280 I2C address (SDO pin LOW = 0x76, SDO pin HIGH = 0x77) */
#define BMP280_I2C_ADDR         0x76

/* MPU6050 I2C address (AD0 pin LOW = 0x68, AD0 pin HIGH = 0x69) */
#define MPU6050_I2C_ADDR        0x68
