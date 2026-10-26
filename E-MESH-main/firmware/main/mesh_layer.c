/**
 * @file mesh_layer.c
 * @brief ESP-MESH-LITE initialization and event handling.
 *
 * Initializes NVS, Wi-Fi, esp-iot-bridge network interfaces,
 * and the mesh_lite component. After esp_mesh_lite_start(),
 * the mesh self-organizes: the node closest to the Radxa hotspot
 * becomes root, all others become intermediate/leaf nodes.
 */

#include "mesh_layer.h"
#include "mesh_config.h"

#include <string.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_bridge.h"
#include "esp_mesh_lite.h"

static const char *TAG = "MESH";

/* ── Internal State ─────────────────────────────────────────────────────── */

static char  s_node_id[NODE_ID_MAX_LEN] = {0};
static bool  s_mesh_connected = false;
static bool  s_mesh_is_root   = false;
static int   s_mesh_level     = 0;

/* Event group for mesh status signaling */
static EventGroupHandle_t s_mesh_event_group = NULL;
#define MESH_CONNECTED_BIT  BIT0

/* ── Helpers ────────────────────────────────────────────────────────────── */

/**
 * @brief Derive a unique node ID from the ESP32's base MAC address.
 * Format: "EMESH-AABBCC" (last 3 bytes of MAC)
 */
static void derive_node_id(void)
{
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_node_id, sizeof(s_node_id), "%s%02X%02X%02X",
             NODE_ID_PREFIX, mac[3], mac[4], mac[5]);
    ESP_LOGI(TAG, "Node ID: %s (MAC: %02X:%02X:%02X:%02X:%02X:%02X)",
             s_node_id, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

/* ── Event Handlers ─────────────────────────────────────────────────────── */

/**
 * @brief Wi-Fi event handler for STA connect/disconnect.
 */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
            case WIFI_EVENT_STA_CONNECTED:
                ESP_LOGI(TAG, "Wi-Fi STA connected to parent / router");
                break;
            case WIFI_EVENT_STA_DISCONNECTED:
                ESP_LOGW(TAG, "Wi-Fi STA disconnected — mesh will auto-reconnect");
                s_mesh_connected = false;
                if (s_mesh_event_group) {
                    xEventGroupClearBits(s_mesh_event_group, MESH_CONNECTED_BIT);
                }
                break;
            default:
                break;
        }
    }
}

/**
 * @brief IP event handler — triggered when the node gets an IP address
 * (either from the router as root, or from a parent node).
 */
static void ip_event_handler(void *arg, esp_event_base_t event_base,
                              int32_t event_id, void *event_data)
{
    if (event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_mesh_connected = true;
        if (s_mesh_event_group) {
            xEventGroupSetBits(s_mesh_event_group, MESH_CONNECTED_BIT);
        }
    }
}

/* ── Public API ─────────────────────────────────────────────────────────── */

int mesh_init(void)
{
    ESP_LOGI(TAG, "Initializing E-MESH network layer...");

    /* Create event group for synchronization */
    s_mesh_event_group = xEventGroupCreate();

    /* ── 1. Initialize NVS ── */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* ── 2. Initialize TCP/IP and Event Loop ── */
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    /* ── 3. Register Wi-Fi and IP event handlers ── */
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &ip_event_handler, NULL, NULL));

    /* ── 4. Create bridge network interfaces (STA + SoftAP with NAPT) ── */
    esp_bridge_create_all_netif();

    /* ── 5. Configure the upstream router (Radxa Hotspot) credentials ── */
    wifi_config_t router_cfg = {0};
    strncpy((char *)router_cfg.sta.ssid, MESH_ROUTER_SSID, sizeof(router_cfg.sta.ssid) - 1);
    strncpy((char *)router_cfg.sta.password, MESH_ROUTER_PASSWORD, sizeof(router_cfg.sta.password) - 1);
    esp_bridge_wifi_set_config(WIFI_IF_STA, &router_cfg);

    /* ── 6. Configure the SoftAP (for client devices) ── */
    wifi_config_t softap_cfg = {
        .ap = {
            .max_connection = MESH_SOFTAP_MAX_CONN,
            .authmode       = WIFI_AUTH_WPA2_PSK,
        },
    };
    strncpy((char *)softap_cfg.ap.ssid, MESH_SOFTAP_SSID, sizeof(softap_cfg.ap.ssid) - 1);
    strncpy((char *)softap_cfg.ap.password, MESH_SOFTAP_PASSWORD, sizeof(softap_cfg.ap.password) - 1);
    softap_cfg.ap.ssid_len = strlen(MESH_SOFTAP_SSID);
    esp_bridge_wifi_set_config(WIFI_IF_AP, &softap_cfg);

    /* ── 7. Initialize and start ESP-MESH-LITE ── */
    esp_mesh_lite_config_t mesh_cfg = ESP_MESH_LITE_DEFAULT_INIT();
    esp_mesh_lite_init(&mesh_cfg);

    /* Tell the mesh layer the SoftAP credentials so child nodes can
     * authenticate with parent nodes during the WPA2 4-way handshake.
     * Without this call, inter-node connections fail with reason 15. */
    esp_mesh_lite_set_softap_info(MESH_SOFTAP_SSID, MESH_SOFTAP_PASSWORD);

    esp_mesh_lite_start();

    /* ── 8. Derive the unique node ID from MAC ── */
    derive_node_id();

    ESP_LOGI(TAG, "E-MESH network layer initialized.");
    ESP_LOGI(TAG, "  Router SSID : %s", MESH_ROUTER_SSID);
    ESP_LOGI(TAG, "  SoftAP SSID : %s", MESH_SOFTAP_SSID);
    ESP_LOGI(TAG, "  Max Level   : %d", MESH_MAX_LEVEL);

    return 0;
}

bool mesh_is_root(void)
{
    /* Query the mesh_lite API for current role */
    s_mesh_is_root = (esp_mesh_lite_get_level() == 1);
    return s_mesh_is_root;
}

bool mesh_is_connected(void)
{
    return s_mesh_connected;
}

const char* mesh_get_node_id(void)
{
    return s_node_id;
}

int mesh_get_level(void)
{
    s_mesh_level = esp_mesh_lite_get_level();
    return s_mesh_level;
}
