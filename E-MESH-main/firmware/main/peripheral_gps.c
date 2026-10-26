/**
 * @file peripheral_gps.c
 * @brief NEO-6M GPS UART driver with NMEA sentence parsing.
 *
 * Runs a dedicated FreeRTOS task to continuously read UART data,
 * parse $GPGGA sentences, and store the latest fix in a thread-safe
 * global structure. On boot, waits up to GPS_DETECT_TIMEOUT_SEC for
 * valid NMEA data. If none arrives, marks GPS as absent.
 */

#include "peripheral_gps.h"
#include "board_config.h"
#include "sdkconfig.h"

#include <string.h>
#include <stdlib.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/uart.h"
#include "esp_log.h"

static const char *TAG = "GPS";

/* How long to wait for NMEA data before declaring GPS absent */
#define GPS_DETECT_TIMEOUT_SEC  10
#define GPS_TASK_STACK_SIZE     4096
#define GPS_TASK_PRIORITY       5

/* ── Internal State ─────────────────────────────────────────────────────── */

static gps_data_t   s_gps_data;
static SemaphoreHandle_t s_gps_mutex = NULL;
static bool          s_gps_present = false;
static bool          s_gps_initialized = false;

/* ── NMEA Parsing Helpers ───────────────────────────────────────────────── */

/**
 * @brief Convert NMEA coordinate (DDMM.MMMM) to decimal degrees.
 */
static double nmea_to_decimal(const char *raw, const char *dir)
{
    if (!raw || !dir || strlen(raw) < 4) return 0.0;

    double val = atof(raw);
    int degrees = (int)(val / 100);
    double minutes = val - (degrees * 100);
    double decimal = degrees + (minutes / 60.0);

    if (*dir == 'S' || *dir == 'W') {
        decimal = -decimal;
    }
    return decimal;
}

/**
 * @brief Parse a $GPGGA or $GNGGA sentence and update s_gps_data.
 *
 * Format: $GPGGA,time,lat,N/S,lon,E/W,quality,numSV,hdop,alt,M,...
 */
static bool parse_gpgga(const char *sentence)
{
    /* Work on a copy since strtok modifies the string */
    char buf[256];
    strncpy(buf, sentence, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *fields[15] = {0};
    int idx = 0;
    char *p = buf;
    while (p && idx < 15) {
        fields[idx++] = p;
        char *comma = strchr(p, ',');
        if (comma) {
            *comma = '\0';
            p = comma + 1;
        } else {
            break;
        }
    }

    /* Need at least 10 fields for a valid GGA */
    if (idx < 10) return false;

    /* Field 6 = Fix quality (0 = no fix) */
    int quality = atoi(fields[6]);
    if (quality == 0) return false;

    gps_data_t tmp;
    tmp.valid = true;

    /* Time: HHMMSS.ss */
    if (fields[1] && strlen(fields[1]) >= 6) {
        tmp.hour   = (fields[1][0] - '0') * 10 + (fields[1][1] - '0');
        tmp.minute = (fields[1][2] - '0') * 10 + (fields[1][3] - '0');
        tmp.second = (fields[1][4] - '0') * 10 + (fields[1][5] - '0');
    } else {
        tmp.hour = tmp.minute = tmp.second = 0;
    }

    tmp.latitude   = nmea_to_decimal(fields[2], fields[3]);
    tmp.longitude  = nmea_to_decimal(fields[4], fields[5]);
    tmp.satellites = atoi(fields[7]);
    tmp.hdop       = atof(fields[8]);
    tmp.altitude_m = atof(fields[9]);

    /* Thread-safe update */
    if (xSemaphoreTake(s_gps_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        s_gps_data = tmp;
        xSemaphoreGive(s_gps_mutex);
    }

    return true;
}

/* ── GPS Reader Task ────────────────────────────────────────────────────── */

static void gps_task(void *arg)
{
    uint8_t rx_buf[GPS_UART_BUF_SIZE];
    char    line_buf[512];
    int     line_pos = 0;
    bool    detected = false;
    TickType_t start_tick = xTaskGetTickCount();

    ESP_LOGI(TAG, "GPS reader task started, waiting for NMEA data...");

    while (1) {
        int len = uart_read_bytes(GPS_UART_PORT_NUM, rx_buf, sizeof(rx_buf) - 1,
                                  pdMS_TO_TICKS(100));

        if (len > 0) {
            for (int i = 0; i < len; i++) {
                char c = (char)rx_buf[i];

                if (c == '$') {
                    line_pos = 0; /* Start of a new NMEA sentence */
                }

                if (line_pos < (int)(sizeof(line_buf) - 1)) {
                    line_buf[line_pos++] = c;
                }

                if (c == '\n' || c == '\r') {
                    line_buf[line_pos] = '\0';

                    if (strstr(line_buf, "$GP") || strstr(line_buf, "$GN")) {
                        if (!detected) {
                            detected = true;
                            s_gps_present = true;
                            ESP_LOGI(TAG, "GPS module detected!");
                        }
                    }

                    /* Parse GGA sentences (both GPS-only and multi-GNSS) */
                    if (strstr(line_buf, "$GPGGA") || strstr(line_buf, "$GNGGA")) {
                        parse_gpgga(line_buf);
                    }

                    line_pos = 0;
                }
            }
        }

        /* Detection timeout: if no data after N seconds, GPS is absent */
        if (!detected) {
            TickType_t elapsed = xTaskGetTickCount() - start_tick;
            if (elapsed > pdMS_TO_TICKS(GPS_DETECT_TIMEOUT_SEC * 1000)) {
                ESP_LOGW(TAG, "No GPS module detected after %ds — running without GPS.",
                         GPS_DETECT_TIMEOUT_SEC);
                s_gps_present = false;
                /* Keep the task alive but at lower frequency in case GPS is
                 * hot-plugged later (unlikely but defensive) */
                vTaskDelay(pdMS_TO_TICKS(5000));
                start_tick = xTaskGetTickCount(); /* Reset for next check */
            }
        }
    }
}

/* ── Public API ─────────────────────────────────────────────────────────── */

int gps_init(void)
{
#if !defined(CONFIG_EMESH_GPS_ENABLED) || !CONFIG_EMESH_GPS_ENABLED
    ESP_LOGI(TAG, "GPS support disabled in menuconfig.");
    return 0;
#endif

    if (s_gps_initialized) return 0;

    s_gps_mutex = xSemaphoreCreateMutex();
    if (!s_gps_mutex) {
        ESP_LOGE(TAG, "Failed to create GPS mutex");
        return -1;
    }

    memset(&s_gps_data, 0, sizeof(s_gps_data));

    /* Configure UART for NEO-6M (9600 baud, 8N1) */
    uart_config_t uart_cfg = {
        .baud_rate  = GPS_UART_BAUD_RATE,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t err = uart_param_config(GPS_UART_PORT_NUM, &uart_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "UART param config failed: %s", esp_err_to_name(err));
        return -1;
    }

    err = uart_set_pin(GPS_UART_PORT_NUM,
                       PIN_GPS_UART_TX, PIN_GPS_UART_RX,
                       UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "UART set pin failed: %s", esp_err_to_name(err));
        return -1;
    }

    err = uart_driver_install(GPS_UART_PORT_NUM, GPS_UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "UART driver install failed: %s", esp_err_to_name(err));
        return -1;
    }

    /* Launch the GPS reader task */
    BaseType_t ret = xTaskCreate(gps_task, "gps_task", GPS_TASK_STACK_SIZE,
                                 NULL, GPS_TASK_PRIORITY, NULL);
    if (ret != pdPASS) {
        ESP_LOGE(TAG, "Failed to create GPS task");
        return -1;
    }

    s_gps_initialized = true;
    ESP_LOGI(TAG, "GPS UART initialized on TX=%d, RX=%d", PIN_GPS_UART_TX, PIN_GPS_UART_RX);
    return 0;
}

bool gps_is_present(void)
{
    return s_gps_present;
}

bool gps_get_data(gps_data_t *data)
{
    if (!data || !s_gps_mutex) return false;

    if (xSemaphoreTake(s_gps_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        *data = s_gps_data;
        xSemaphoreGive(s_gps_mutex);
        return data->valid;
    }
    return false;
}
