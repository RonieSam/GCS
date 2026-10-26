# E-Mesh — Emergency Mesh

**Self-Healing Mesh Communication Network for Disaster Response and Emergency Connectivity**

E-Mesh is an infrastructure-independent emergency communication and response platform.
This repository contains the **Phase 1** backend implementation — a fully functional
REST API with authentication, RBAC, incident management, and a simulated mesh network.

> ⚠️ **SIMULATION MODE**: The current build runs a software-simulated mesh network.
> No actual ESP32/ESP-NOW hardware is required. The simulation is clearly labeled in all interfaces.

---

## Architecture

```
e-mesh/
├── backend/         ← FastAPI + SQLAlchemy + SQLite
├── client/          ← Lightweight HTML/CSS/JS (Phase 2)
├── admin/           ← React + TypeScript + Vite (Phase 3)
├── docs/            ← Architecture documentation
├── scripts/         ← Seed data and utility scripts
└── tests/           ← Pytest test suite
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- pip

### 2. Install backend dependencies

```powershell
cd e-mesh/backend
python -m pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings "python-jose[cryptography]" "passlib[bcrypt]" python-multipart httpx aiosqlite greenlet python-dotenv pytest pytest-asyncio "anyio[trio]"
```

### 3. Configure environment

```powershell
cd e-mesh/backend
copy .env.example .env
# Edit .env if needed (defaults work for local development)
```

### 4. Start the backend

```powershell
cd e-mesh/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at:
- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 5. Default admin credentials

```
Username: admin
Password: Admin@Mesh2025
```

---

## Local Network (LAN) Access

To access E-Mesh from another device on the same Wi-Fi:

### Find your LAN IP

```powershell
ipconfig
# Look for "IPv4 Address" under your Wi-Fi adapter
# Example: 192.168.1.100
```

### Start backend accessible on LAN

The backend already listens on `0.0.0.0` — it accepts connections from any interface.

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Access from phone

1. Connect your phone to the **same Wi-Fi network** as your laptop.
2. Open the browser on your phone.
3. Navigate to: `http://192.168.1.100:8000/docs` (replace with your actual IP).

---

## Running Tests

```powershell
cd e-mesh
python -m pytest tests/ -v
```

### Test coverage

```powershell
python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Login — returns JWT access + refresh tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Logout (audit logged) |
| GET | `/api/v1/auth/me` | Get current user |

### Users (Admin only write)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/users` | List users (manager+) |
| POST | `/api/v1/users` | Create user (admin) |
| GET | `/api/v1/users/{id}` | Get user (manager+) |
| PATCH | `/api/v1/users/{id}` | Update user (admin) |
| DELETE | `/api/v1/users/{id}` | Deactivate user (admin) |

### Incidents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/incidents` | List incidents (RBAC-filtered) |
| POST | `/api/v1/incidents` | Create incident (all authenticated) |
| GET | `/api/v1/incidents/{id}` | Get incident |
| PATCH | `/api/v1/incidents/{id}` | Update (manager+) |
| POST | `/api/v1/incidents/{id}/acknowledge` | Acknowledge (manager+) |
| POST | `/api/v1/incidents/{id}/assign` | Assign responder (manager+) |

### SOS

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/sos` | Send SOS (all authenticated, 60s cooldown) |
| GET | `/api/v1/sos` | List SOS (RBAC-filtered) |
| PATCH | `/api/v1/sos/{id}` | Update SOS status (manager+) |

### Nodes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/nodes` | List nodes (privileged) |
| POST | `/api/v1/nodes` | Create node (admin) |
| GET | `/api/v1/nodes/links` | All topology links (privileged) |
| GET | `/api/v1/nodes/{id}` | Get node (privileged) |
| PATCH | `/api/v1/nodes/{id}` | Update node (admin) |
| DELETE | `/api/v1/nodes/{id}` | Delete node (admin) |

### Announcements

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/announcements` | List active announcements |
| POST | `/api/v1/announcements` | Create (manager+) |
| PATCH | `/api/v1/announcements/{id}` | Update (manager+) |
| DELETE | `/api/v1/announcements/{id}` | Deactivate (manager+) |

### Audit Logs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/audit-logs` | List audit logs (admin/manager) |

---

## User Roles

| Role | Description |
|------|-------------|
| `CIVILIAN` | Register, submit SOS, report incidents, view own data |
| `RESPONDER` | View and respond to assigned incidents |
| `INCIDENT_MANAGER` | Full incident lifecycle management |
| `ADMIN` | Full system access |
| `VIEWER` | Read-only access to all data |

---

## Security

- Passwords hashed with **bcrypt** (never stored in plaintext)
- Authentication via **JWT** (access + refresh token pair)
- **RBAC** enforced at the dependency injection level
- SOS endpoint has a **60-second cooldown** to prevent accidental duplicates
- All administrative actions are **audit logged**
- CORS configured for local development

---

## Hardware Abstraction

The codebase is designed for future ESP32 integration:

```
Current (Phase 1):
Phone → LAN Wi-Fi → FastAPI → SimulatedGateway

Future (Phase 5+):
Phone → ESP32 AP → ESP-NOW Mesh → Gateway ESP32 → FastAPI → ESP32Gateway
```

The `GatewayInterface` in `backend/app/gateway/interface.py` defines the clean
boundary between the web layer and the transport/hardware layer.

To add real hardware, implement `ESP32Gateway(GatewayInterface)` — no changes
to any router, service, or model code are required.

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Complete | Backend foundation, auth, RBAC, models, tests |
| 2 | 🔲 Planned | Lightweight client portal (HTML/CSS/JS) |
| 3 | 🔲 Planned | Admin React dashboard |
| 4 | 🔲 Planned | WebSocket real-time events |
| 5 | 🔲 Planned | Node management and simulation router |
| 6 | 🔲 Planned | Failure simulation, network health, analytics |
| 7 | 🔲 Planned | Security hardening, Playwright tests |
