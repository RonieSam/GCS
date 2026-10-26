/**
 * @file mesh_config.h
 * @brief Shared mesh network configuration and node identity constants.
 */

#pragma once

#include "sdkconfig.h"

/* ═══════════════════════════════════════════════════════════════════════════
   Network Credentials (from menuconfig / Kconfig)
   ═══════════════════════════════════════════════════════════════════════════ */

/* The upstream router SSID/password that the root node connects to */
#define MESH_ROUTER_SSID        CONFIG_EMESH_ROUTER_SSID
#define MESH_ROUTER_PASSWORD    CONFIG_EMESH_ROUTER_PASSWORD

/* The SoftAP SSID/password broadcast by every node for client devices */
#define MESH_SOFTAP_SSID        CONFIG_EMESH_SOFTAP_SSID
#define MESH_SOFTAP_PASSWORD    CONFIG_EMESH_SOFTAP_PASSWORD
#define MESH_SOFTAP_MAX_CONN    CONFIG_EMESH_SOFTAP_MAX_CONNECTIONS

/* ═══════════════════════════════════════════════════════════════════════════
   Backend Server Configuration
   ═══════════════════════════════════════════════════════════════════════════ */

#define SERVER_IP               CONFIG_EMESH_SERVER_IP
#define SERVER_PORT             CONFIG_EMESH_SERVER_PORT

/* ═══════════════════════════════════════════════════════════════════════════
   Telemetry & Timing
   ═══════════════════════════════════════════════════════════════════════════ */

#define HEARTBEAT_INTERVAL_SEC  CONFIG_EMESH_HEARTBEAT_INTERVAL_SEC

/* ═══════════════════════════════════════════════════════════════════════════
   Mesh Topology
   ═══════════════════════════════════════════════════════════════════════════ */

#define MESH_MAX_LEVEL          CONFIG_EMESH_MESH_MAX_LEVEL

/* ═══════════════════════════════════════════════════════════════════════════
   Node Identity
   ═══════════════════════════════════════════════════════════════════════════ */

/* Node ID will be derived from the MAC address at runtime.
 * Format: "EMESH-AABBCC" (last 3 bytes of MAC in hex, uppercase)
 * This ensures every node has a unique, deterministic identifier. */
#define NODE_ID_PREFIX          "EMESH-"
#define NODE_ID_MAX_LEN         16
