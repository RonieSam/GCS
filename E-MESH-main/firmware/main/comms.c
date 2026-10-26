/**
 * @file comms.c
 * @brief Backend HTTP communication implementation.
 *
 * Uses esp_http_client to send JSON payloads to the FastAPI backend.
 * All requests are fire-and-forget with basic retry logic.
 *
 * IMPORTANT: The FastAPI backend handles all user-facing authentication
 * (JWT, RBAC). The ESP32 nodes do NOT authenticate themselves.
 * Traffic originates from inside the private Radxa hotspot network,
 * so the server trusts it implicitly.
 */

#include "comms.h"
#include "mesh_config.h"

#include <string.h>
#include <stdio.h>

#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "COMMS";

/* Maximum JSON payload size — increased to accommodate sensor fields */
#define JSON_BUF_SIZE   768

/* Maximum retries for a failed HTTP request */
#define MAX_RETRIES     2

/* ── Internal Helpers ───────────────────────────────────────────────────── */

static void build_url(const char *path, char *buf, size_t len)
{
    snprintf(buf, len, "http://%s:%d%s", SERVER_IP, SERVER_PORT, path);
}

static int http_post_json(const char *url, const char *json)
{
    esp_http_client_config_t config = {
        .url        = url,
        .method     = HTTP_METHOD_POST,
        .timeout_ms = 5000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "Failed to init HTTP client");
        return -1;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json, strlen(json));

    int status_code = -1;
    for (int attempt = 0; attempt <= MAX_RETRIES; attempt++) {
        esp_err_t err = esp_http_client_perform(client);
        if (err == ESP_OK) {
            status_code = esp_http_client_get_status_code(client);
            ESP_LOGD(TAG, "POST %s -> %d", url, status_code);
            break;
        } else {
            ESP_LOGW(TAG, "POST %s failed (attempt %d/%d): %s",
                     url, attempt + 1, MAX_RETRIES + 1, esp_err_to_name(err));
        }
    }

    esp_http_client_cleanup(client);
    return status_code;
}

/* ── Public API ─────────────────────────────────────────────────────────── */

void comms_init(void)
{
    ESP_LOGI(TAG, "Communications module initialized.");
    ESP_LOGI(TAG, "  Server: http://%s:%d", SERVER_IP, SERVER_PORT);
}

bool comms_send_heartbeat(const char *node_id, bool is_root,
                          int level, int rssi,
                          bool has_gps_hw,
                          const gps_data_t     *gps,
                          const bmp280_data_t  *env,
                          const mpu6050_data_t *imu)
{
    char url[128];
    char json[JSON_BUF_SIZE];

    /* ── Start building the JSON object ── */
    int pos = 0;
    pos += snprintf(json + pos, sizeof(json) - pos,
        "{"
        "\"node_id\":\"%s\","
        "\"is_gateway\":%s,"
        "\"display_name\":\"%s\","
        "\"battery_level\":100.0,"
        "\"signal_quality\":%d.0,"
        "\"hop_count\":%d,"
        "\"has_gps\":%s",
        node_id,
        is_root ? "true" : "false",
        node_id,
        rssi,
        level,
        has_gps_hw ? "true" : "false"
    );

    /* ── Append GPS fields if available ── */
    if (gps && gps->valid) {
        pos += snprintf(json + pos, sizeof(json) - pos,
            ",\"gps_lat\":%.6f"
            ",\"gps_lon\":%.6f"
            ",\"gps_alt\":%.1f"
            ",\"gps_sats\":%d",
            gps->latitude,
            gps->longitude,
            gps->altitude_m,
            gps->satellites
        );
    }

    /* ── Append BMP280 environmental fields if sensor present ── */
    if (env) {
        pos += snprintf(json + pos, sizeof(json) - pos,
            ",\"temperature_c\":%.2f"
            ",\"pressure_hpa\":%.2f",
            env->temperature_c,
            env->pressure_hpa
        );
    }

    /* ── Append MPU6050 IMU fields if sensor present ── */
    if (imu) {
        pos += snprintf(json + pos, sizeof(json) - pos,
            ",\"accel_x\":%d"
            ",\"accel_y\":%d"
            ",\"accel_z\":%d"
            ",\"gyro_x\":%d"
            ",\"gyro_y\":%d"
            ",\"gyro_z\":%d",
            imu->accel_x, imu->accel_y, imu->accel_z,
            imu->gyro_x,  imu->gyro_y,  imu->gyro_z
        );
    }

    /* ── Close the JSON object ── */
    pos += snprintf(json + pos, sizeof(json) - pos, "}");

    if (pos >= (int)sizeof(json)) {
        ESP_LOGW(TAG, "Heartbeat JSON truncated!");
    }

    build_url("/api/v1/mesh/nodes", url, sizeof(url));
    int status = http_post_json(url, json);

    if (status == 201 || status == 200 || status == 409) {
        ESP_LOGI(TAG, "Heartbeat sent: %s (level=%d, rssi=%ddBm, env=%s, imu=%s)",
                 node_id, level, rssi,
                 env  ? "yes" : "no",
                 imu  ? "yes" : "no");
        return true;
    }

    ESP_LOGW(TAG, "Heartbeat failed: HTTP %d", status);
    return false;
}

bool comms_send_sos(const char *node_id, const gps_data_t *gps)
{
    char url[128];
    char json[JSON_BUF_SIZE];

    snprintf(json, sizeof(json),
        "{"
        "\"people_count\":1,"
        "\"notes\":\"Hardware SOS button pressed on node %s\","
        "\"origin_node_id\":\"%s\""
        "}",
        node_id, node_id
    );

    build_url("/api/v1/mesh/sos", url, sizeof(url));
    int status = http_post_json(url, json);

    if (status == 201 || status == 200) {
        ESP_LOGW(TAG, "SOS alert sent from node %s", node_id);
        return true;
    }

    ESP_LOGE(TAG, "SOS send failed: HTTP %d", status);
    return false;
}
