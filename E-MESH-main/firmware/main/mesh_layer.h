/**
 * @file mesh_layer.h
 * @brief ESP-MESH-LITE initialization and event handling interface.
 */

#pragma once

#include <stdbool.h>

/**
 * @brief Initialize ESP-MESH-LITE with esp-iot-bridge.
 *
 * Sets up NVS, network interfaces (STA + SoftAP with NAPT),
 * configures the upstream router credentials, and starts the mesh.
 * The mesh will auto-elect a root node based on signal strength
 * to the configured Radxa hotspot.
 *
 * @return 0 on success, -1 on failure.
 */
int mesh_init(void);

/**
 * @brief Check if this node is currently the root (Gateway) node.
 * @return true if this node is the elected root.
 */
bool mesh_is_root(void);

/**
 * @brief Check if this node is connected to the mesh network.
 * @return true if connected to a parent or is the root.
 */
bool mesh_is_connected(void);

/**
 * @brief Get the unique node ID string (derived from MAC address).
 * @return Null-terminated node ID string (e.g., "EMESH-A1B2C3").
 */
const char* mesh_get_node_id(void);

/**
 * @brief Get the mesh tree level (depth) of this node.
 * @return Level number (1 = root, 2 = direct child, etc.)
 */
int mesh_get_level(void);
