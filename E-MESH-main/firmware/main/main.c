/**
 * @file main.c
 * @brief E-MESH node firmware entry point and main loop.
 *
 * Initializes all subsystems in order:
 *   1. UI Peripherals (LED, Buzzer, SOS button)
 *   2. GPS (optional — graceful degradation if absent)
 *   3. Sensors (optional — BMP280 + MPU6050, graceful degradation)
 *   4. Mesh Network (ESP-Mesh-Lite)
 *   5. Communications (HTTP to FastAPI backend)
 *
 * The main loop handles:
 *   - Mesh connection state changes
 *   - SOS button interrupt processing
 *   - Periodic heartbeat with all available telemetry
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "board_config.h"
#include "mesh_config.h"
#include "mesh_layer.h"
#include "peripheral_ui.h"
#include "peripheral_gps.h"
#include "peripheral_sensors.h"
#include "comms.h"

static const char *TAG = "MAIN";

/* ════════════════════════════════════════════════════════════════════════════
   Boot Signal
   ════════════════════════════════════════════════════════════════════════════ */

static void boot_signal(void)
{
    for (int i = 0; i < 3; i++) {
        led_on();
        buzzer_beep(BUZZER_BEEP_SHORT_MS);
        vTaskDelay(pdMS_TO_TICKS(200));
        led_off();
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

/* ════════════════════════════════════════════════════════════════════════════
   Entry Point
   ════════════════════════════════════════════════════════════════════════════ */

void app_main(void)
{
    ESP_LOGI(TAG, "╔══════════════════════════════════════════╗");
    ESP_LOGI(TAG, "║   E-MESH Node Firmware v1.1              ║");
    ESP_LOGI(TAG, "║   Self-Healing Emergency Mesh Network    ║");
    ESP_LOGI(TAG, "╚══════════════════════════════════════════╝");

    /* ── 1. Initialize UI Peripherals ── */
    ESP_LOGI(TAG, "[1/5] Initializing UI peripherals...");
    ui_init();
    boot_signal();

    /* ── 2. Initialize GPS (optional, auto-detected) ── */
    ESP_LOGI(TAG, "[2/5] Initializing GPS...");
    gps_init();

    /* ── 3. Initialize Sensors (optional, auto-detected) ── */
    ESP_LOGI(TAG, "[3/5] Initializing sensors (BMP280 + MPU6050)...");
    sensors_init();

    /* ── 4. Initialize Mesh Network ── */
    ESP_LOGI(TAG, "[4/5] Initializing mesh network...");
    if (mesh_init() != 0) {
        ESP_LOGE(TAG, "FATAL: Mesh initialization failed!");
        led_blink_start(100, 100);
        return;
    }

    /* ── 5. Initialize Communications ── */
    ESP_LOGI(TAG, "[5/5] Initializing communications...");
    comms_init();

    ESP_LOGI(TAG, "All subsystems initialized. Entering main loop.");
    ESP_LOGI(TAG, "  Node ID       : %s", mesh_get_node_id());
    ESP_LOGI(TAG, "  GPS Present   : %s", gps_is_present() ? "YES" : "NO (router-only mode)");
    ESP_LOGI(TAG, "  BMP280 Present: %s", sensors_has_bmp280()  ? "YES" : "NO");
    ESP_LOGI(TAG, "  MPU6050 Present:%s", sensors_has_mpu6050() ? "YES" : "NO");
    ESP_LOGI(TAG, "  Heartbeat     : every %d seconds", HEARTBEAT_INTERVAL_SEC);

    /* ── Wait for mesh connection ── */
    ESP_LOGI(TAG, "Waiting for mesh connection...");
    bool was_connected = false;
    bool sos_active = false;

    /* ══════════════════════════════════════════════════════════════════════
       Main Loop
       ══════════════════════════════════════════════════════════════════════ */
    TickType_t last_heartbeat = 0;

    while (1) {
        TickType_t now = xTaskGetTickCount();
        bool connected = mesh_is_connected();

        /* ── Connection state change detection ── */
        if (connected && !was_connected) {
            ESP_LOGI(TAG, "✓ Mesh connected! Level=%d, Root=%s",
                     mesh_get_level(), mesh_is_root() ? "YES" : "NO");
            led_blink_stop();
            last_heartbeat = 0; /* Trigger immediate heartbeat */
        } else if (!connected && was_connected) {
            ESP_LOGW(TAG, "✗ Mesh connection lost — waiting for reconnect...");
            led_blink_start(LED_BLINK_SLOW_MS, LED_BLINK_SLOW_MS);
        }
        was_connected = connected;

        /* ── SOS Button Check (interrupt-driven, just reading the flag) ── */
        if (sos_button_pressed()) {
            if (!sos_active) {
                ESP_LOGW(TAG, "SOS BUTTON PRESSED!");
                sos_active = true;
                sos_activate_alarm();

                if (connected) {
                    gps_data_t gps;
                    bool has_gps = gps_get_data(&gps);
                    comms_send_sos(mesh_get_node_id(), has_gps ? &gps : NULL);
                } else {
                    ESP_LOGW(TAG, "SOS pressed but no mesh connection — alarm local only");
                }
            } else {
                ESP_LOGI(TAG, "SOS alarm deactivated by button press.");
                sos_active = false;
                sos_deactivate_alarm();
            }
        }

        /* ── Periodic Heartbeat ── */
        if (connected) {
            TickType_t elapsed = now - last_heartbeat;
            if (elapsed >= pdMS_TO_TICKS(HEARTBEAT_INTERVAL_SEC * 1000) || last_heartbeat == 0) {

                /* Collect GPS data */
                gps_data_t gps;
                bool has_gps = gps_get_data(&gps);

                /* Collect Wi-Fi RSSI */
                wifi_ap_record_t ap_info;
                int rssi = 0;
                if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
                    rssi = ap_info.rssi;
                }

                /* Collect BMP280 environmental data */
                bmp280_data_t env_data;
                bmp280_data_t *env_ptr = NULL;
                if (sensors_has_bmp280() && sensors_read_bmp280(&env_data)) {
                    env_ptr = &env_data;
                }

                /* Collect MPU6050 IMU data */
                mpu6050_data_t imu_data;
                mpu6050_data_t *imu_ptr = NULL;
                if (sensors_has_mpu6050() && sensors_read_mpu6050(&imu_data)) {
                    imu_ptr = &imu_data;
                }

                comms_send_heartbeat(
                    mesh_get_node_id(),
                    mesh_is_root(),
                    mesh_get_level(),
                    rssi,
                    gps_is_present(),
                    has_gps ? &gps : NULL,
                    env_ptr,
                    imu_ptr
                );

                last_heartbeat = now;
            }

            /* Stop blink if we were disconnected */
            if (!sos_active) {
                led_blink_stop();
            }
        }

        /* ── Yield to other tasks (50ms loop period) ── */
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}
