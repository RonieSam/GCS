"""
E-Mesh Emergency Mesh — FastAPI Application Entry Point

Self-Healing Mesh Communication Network for Disaster Response and Emergency Connectivity

Phase 1: Backend foundation — authentication, RBAC, models, and core APIs.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import EMeshException, emesh_exception_handler
from app.db.init_db import init_db
from app.routers import (
    analytics,
    announcements,
    audit_logs,
    auth,
    community,
    health,
    incidents,
    location,
    nodes,
    resources,
    responders,
    simulation,
    sos,
    users,
    websocket,
    mesh_hardware,
)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown tasks."""
    logger.info("E-Mesh starting up — initializing database...")
    await init_db()

    # Launch background task to mark stale nodes as OFFLINE
    from app.tasks.node_monitor import node_staleness_monitor
    monitor_task = asyncio.create_task(node_staleness_monitor())

    logger.info("E-Mesh ready. API running at %s:%s", settings.HOST, settings.PORT)
    yield
    monitor_task.cancel()
    logger.info("E-Mesh shutting down.")


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "**E-Mesh Emergency Mesh** — Emergency communication and response platform.\n\n"
            "**Academic Title**: Self-Healing Mesh Communication Network for Disaster Response "
            "and Emergency Connectivity\n\n"
            "Phase 1: Backend foundation (authentication, RBAC, incident management, node management).\n\n"
            "> ⚠️ **SIMULATION MODE**: The current mesh network is a software simulation. "
            "No actual ESP32/ESP-NOW hardware is connected."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*",
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────
    app.add_exception_handler(EMeshException, emesh_exception_handler)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "message": "An unexpected error occurred."},
        )

    # ── Routers ───────────────────────────────────────────────────────────
    prefix = settings.API_PREFIX
    app.include_router(health.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)
    app.include_router(nodes.router, prefix=prefix)
    app.include_router(incidents.router, prefix=prefix)
    app.include_router(sos.router, prefix=prefix)
    app.include_router(announcements.router, prefix=prefix)
    app.include_router(resources.router, prefix=prefix)
    app.include_router(responders.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(audit_logs.router, prefix=prefix)
    app.include_router(community.router, prefix=prefix)
    app.include_router(location.router, prefix=prefix)
    app.include_router(simulation.router, prefix=prefix)
    app.include_router(mesh_hardware.router, prefix=prefix)
    app.include_router(websocket.router, prefix=prefix)
    app.include_router(websocket.router)  # also alias /ws at root level

    # Mount the client directory to serve the frontend portal
    import os
    from fastapi.staticfiles import StaticFiles
    client_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "client"))
    if not os.path.exists(client_dir):
        client_dir = r"c:\projects\pjt1\client"
    if os.path.exists(client_dir):
        app.mount("/client", StaticFiles(directory=client_dir, html=True), name="client")


    # ── Root endpoint ─────────────────────────────────────────────────────
    @app.get("/", tags=["Root"], include_in_schema=False)
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "operational",
            "mode": "SIMULATION — No physical mesh hardware connected",
            "docs": "/docs",
        }

    return app


app = create_app()
