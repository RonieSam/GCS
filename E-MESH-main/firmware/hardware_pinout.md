# E-MESH Hardware Pinout Guide

This document outlines the standard wiring and GPIO pinout for the E-MESH nodes, supporting both the **ESP32-WROOM (38-pin DevKitC)** and the **ESP32-C3-Mini (DevKitM-1)**.

## 1. ESP32-WROOM (38-Pin Variant)

| Component | ESP32 GPIO Pin | Description / Notes |
| :--- | :--- | :--- |
| **I2C SDA** | `GPIO 21` | Shared I2C bus for **BMP280** and **MPU6050** |
| **I2C SCL** | `GPIO 22` | Shared I2C bus for **BMP280** and **MPU6050** |
| **GPS Module (NEO-6M)** | | |
| GPS TX -> ESP RX | `GPIO 16` | UART2 RX (Connect to NEO-6M TX pin) |
| GPS RX -> ESP TX | `GPIO 17` | UART2 TX (Connect to NEO-6M RX pin) |
| **User Interface** | | |
| SOS Button | `GPIO 27` | Active LOW (Connect button between pin and GND). Uses internal pull-up. |
| LED Indicator | `GPIO 2` | Active HIGH (Built-in LED on most dev boards) |
| Buzzer | `GPIO 25` | Active HIGH (Connect to active buzzer module) |

---

## 2. ESP32-C3-Mini (DevKitM-1)

| Component | ESP32 GPIO Pin | Description / Notes |
| :--- | :--- | :--- |
| **I2C SDA** | `GPIO 6` | Shared I2C bus for **BMP280** and **MPU6050** |
| **I2C SCL** | `GPIO 7` | Shared I2C bus for **BMP280** and **MPU6050** |
| **GPS Module (NEO-6M)** | | |
| GPS TX -> ESP RX | `GPIO 4` | UART1 RX (Connect to NEO-6M TX pin) |
| GPS RX -> ESP TX | `GPIO 5` | UART1 TX (Connect to NEO-6M RX pin) |
| **User Interface** | | |
| SOS Button | `GPIO 9` | Active LOW (Also acts as the BOOT button on the dev board) |
| LED Indicator | `GPIO 8` | Active HIGH (Built-in LED / RGB on DevKitM-1) |
| Buzzer | `GPIO 3` | Active HIGH (Connect to active buzzer module) |

---

## I2C Device Addresses

The firmware automatically scans the I2C bus for the following default addresses on boot:

- **BMP280 (Temperature & Pressure):** `0x76` (SDO pin pulled LOW)
- **MPU6050 (6-Axis IMU):** `0x68` (AD0 pin pulled LOW)

> **Note:** If your sensor modules have different default addresses (e.g., BMP280 at `0x77` or MPU6050 at `0x69`), you will need to update the `BMP280_I2C_ADDR` or `MPU6050_I2C_ADDR` macros in `firmware/main/board_config.h`.

## Power Supply Notes

- **GPS (NEO-6M):** Typically requires 3.3V or 5V (check your specific module). TX/RX logic levels are 3.3V.
- **BMP280 & MPU6050:** These are 3.3V devices. Power them from the `3V3` pin on the ESP32.
- **Buzzer:** Ensure you are using an "Active Buzzer" module (which beeps simply by applying power), not a passive buzzer (which requires a PWM signal). Power it from 3.3V or 5V depending on the module.
