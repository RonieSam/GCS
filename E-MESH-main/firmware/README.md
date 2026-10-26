# E-MESH Firmware

Self-healing ESP32 mesh network firmware for emergency communication.  
Built with **ESP-IDF** + **ESP-MESH-LITE** + **PlatformIO**.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     RADXA SBC (Server)                          │
│                   ┌──────────────────┐                          │
│                   │  FastAPI Backend  │                          │
│                   │  (Port 8000)     │                          │
│                   └────────┬─────────┘                          │
│                            │ Wi-Fi Hotspot                      │
│                       SSID: E-MESH-SERVER                       │
└────────────────────────────┼────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Root Node     │  ← Auto-elected by mesh
                    │  (Gateway)      │     (closest to Radxa)
                    │  SoftAP: E-MESH │
                    └───┬─────────┬───┘
                        │         │
               ┌────────▼──┐  ┌──▼────────┐
               │  Node A   │  │  Node B   │
               │  SoftAP   │  │  SoftAP   │
               │  GPS+SOS  │  │  (no GPS) │
               └────┬──────┘  └───────────┘
                    │
               ┌────▼──────┐
               │  Node C   │
               │  SoftAP   │
               │  GPS+SOS  │
               └───────────┘
```

- Every node broadcasts `E-MESH-PUBLIC` SoftAP for clients (phones/laptops).
- Client HTTP traffic is transparently routed via NAPT to the Radxa server.
- The root node is **dynamically elected** (no hardcoding).
- GPS and SOS button are **optional** — nodes without them act as routers.

## Project Structure

```
firmware/
├── platformio.ini          # Build environments (wroom, c3)
├── CMakeLists.txt          # Top-level ESP-IDF project file
├── sdkconfig.defaults      # Default config (NAPT, IP forwarding)
├── main/
│   ├── CMakeLists.txt      # Component source registration
│   ├── idf_component.yml   # ESP-MESH-LITE dependency
│   ├── Kconfig.projbuild   # Menuconfig options
│   ├── board_config.h      # GPIO pin maps (WROOM vs C3)
│   ├── mesh_config.h       # Network & server configuration
│   ├── main.c              # Entry point & main loop
│   ├── mesh_layer.h/.c     # ESP-MESH-LITE init & events
│   ├── peripheral_gps.h/.c # NEO-6M GPS UART driver
│   ├── peripheral_ui.h/.c  # LED, Buzzer, SOS button (ISR)
│   └── comms.h/.c          # HTTP telemetry to backend
└── README.md               # This file
```

## Hardware Wiring

### ESP32-WROOM (DevKit 38-pin)

| Peripheral      | ESP32 Pin | Wire Color (suggested) | Notes                     |
|-----------------|-----------|------------------------|---------------------------|
| NEO-6M GPS TX   | GPIO 16   | Green                  | GPS TX → ESP32 RX (UART2) |
| NEO-6M GPS RX   | GPIO 17   | Yellow                 | GPS RX → ESP32 TX (UART2) |
| NEO-6M GPS VCC  | 3.3V      | Red                    | ⚠ Use 3.3V, NOT 5V       |
| NEO-6M GPS GND  | GND       | Black                  |                           |
| SOS Button      | GPIO 27   | White                  | Other leg to GND          |
| LED             | GPIO 2    | -                      | Built-in on most devkits  |
| Buzzer (+)      | GPIO 25   | Orange                 | Active buzzer, + to GPIO  |
| Buzzer (-)      | GND       | Black                  |                           |

```
ESP32-WROOM DevKit
     ┌──────────────┐
     │  ┌────────┐  │
     │  │ ESP32  │  │
     │  │ WROOM  │  │
     │  └────────┘  │
     │              │
3V3 ─┤              ├─ GND
     │              │
G16 ─┤ GPS RX      ├─ G17 (GPS TX)
     │              │
G27 ─┤ SOS Button  ├─ GND (button)
     │              │
G25 ─┤ Buzzer +    ├─ GND (buzzer)
     │              │
G2  ─┤ LED (built-in)
     │              │
     └──────────────┘
```

### ESP32-C3-Mini (DevKitM-1)

| Peripheral      | ESP32 Pin | Wire Color (suggested) | Notes                     |
|-----------------|-----------|------------------------|---------------------------|
| NEO-6M GPS TX   | GPIO 4    | Green                  | GPS TX → ESP32 RX (UART1) |
| NEO-6M GPS RX   | GPIO 5    | Yellow                 | GPS RX → ESP32 TX (UART1) |
| NEO-6M GPS VCC  | 3.3V      | Red                    | ⚠ Use 3.3V, NOT 5V       |
| NEO-6M GPS GND  | GND       | Black                  |                           |
| SOS Button      | GPIO 9    | White                  | BOOT button, other to GND |
| LED             | GPIO 8    | -                      | On-board LED              |
| Buzzer (+)      | GPIO 3    | Orange                 | Active buzzer, + to GPIO  |
| Buzzer (-)      | GND       | Black                  |                           |

```
ESP32-C3-Mini DevKit
     ┌──────────────┐
     │  ┌────────┐  │
     │  │ ESP32  │  │
     │  │  C3    │  │
     │  └────────┘  │
     │              │
3V3 ─┤              ├─ GND
     │              │
G4  ─┤ GPS RX      ├─ G5 (GPS TX)
     │              │
G9  ─┤ SOS Button  ├─ GND (button)
     │              │
G3  ─┤ Buzzer +    ├─ GND (buzzer)
     │              │
G8  ─┤ LED (on-board)
     │              │
     └──────────────┘
```

## Prerequisites

1. **PlatformIO CLI** — Install via `pip install platformio`
2. **ESP-IDF** — PlatformIO will download the correct version automatically.
3. **USB Driver** — CP2102 or CH340 depending on your devkit.

## Build & Flash

### Step 1: Configure (optional)

Use `menuconfig` to change the Radxa hotspot SSID, password, or server IP:

```bash
cd firmware
pio run -e wroom -t menuconfig
```

Key settings under **E-MESH Firmware Configuration**:
- `Radxa Hotspot SSID` → Your Radxa's Wi-Fi hotspot name
- `Radxa Hotspot Password` → Hotspot password
- `Backend Server IP` → Static IP of the Radxa (e.g., `192.168.4.1`)
- `Backend Server Port` → `8000` (default FastAPI port)

### Step 2: Build

```bash
# Build for ESP32-WROOM
pio run -e wroom

# Build for ESP32-C3-Mini
pio run -e c3
```

### Step 3: Flash

Connect the ESP32 via USB and run:

```bash
# Flash WROOM
pio run -e wroom -t upload

# Flash C3
pio run -e c3 -t upload
```

### Step 4: Monitor Serial Output

```bash
pio device monitor -e wroom
# or
pio device monitor -e c3
```

You should see logs like:
```
I (523) MAIN: ╔══════════════════════════════════════════╗
I (523) MAIN: ║   E-MESH Node Firmware v1.0              ║
I (523) MAIN: ║   Self-Healing Emergency Mesh Network    ║
I (523) MAIN: ╚══════════════════════════════════════════╝
I (533) MAIN: [1/4] Initializing UI peripherals...
I (543) UI:   LED initialized on GPIO 2
I (543) UI:   Buzzer initialized on GPIO 25
I (553) UI:   SOS button initialized on GPIO 27 (ISR active)
I (563) MAIN: [2/4] Initializing GPS...
I (573) GPS:  GPS UART initialized on TX=17, RX=16
I (583) GPS:  GPS module detected!
I (593) MAIN: [3/4] Initializing mesh network...
I (603) MESH: Node ID: EMESH-A1B2C3
I (613) MESH: Got IP: 192.168.4.5
I (623) MAIN: ✓ Mesh connected! Level=2, Root=NO
I (633) MAIN: [4/4] Initializing communications...
I (643) COMMS: Heartbeat sent: EMESH-A1B2C3 (level=2, root=no)
```

## How It Works

1. **Boot**: Node initializes GPIO, attempts GPS detection, starts mesh.
2. **Mesh Formation**: ESP-MESH-LITE auto-discovers the Radxa hotspot.
   The node with strongest signal becomes Root. Others form a tree.
3. **Client Access**: Phones connect to any node's `E-MESH-PUBLIC` Wi-Fi.
   HTTP requests route transparently through the mesh to the Radxa server.
4. **Heartbeat**: Every 30s (configurable), each node POSTs its status
   (node ID, mesh level, GPS coordinates) to the FastAPI backend.
5. **SOS**: When the physical button is pressed (hardware interrupt),
   the node activates the LED/buzzer alarm and POSTs an SOS alert.
6. **Self-Healing**: If a parent node drops, ESP-MESH-LITE automatically
   reassigns orphaned children to a new parent within seconds.
