"""
Background task — periodically marks nodes as OFFLINE if their
last_heartbeat exceeds the staleness threshold.

Runs every 5 seconds. If a node hasn't sent a heartbeat in 10 seconds
(2 × the default 5-second heartbeat interval), it is marked OFFLINE
and a WebSocket event is emitted so the Admin Dashboard updates in real time.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.core.enums import NodeStatus
from app.db.base import AsyncSessionLocal
from app.models.node import Node
from app.services.network_event_service import emit_node_offline

logger = logging.getLogger(__name__)

# If a node misses 2 heartbeats (10s with 5s interval), mark it OFFLINE.
STALENESS_THRESHOLD_SECONDS = 10

# How often to run the sweep (seconds).
SWEEP_INTERVAL_SECONDS = 5


async def _sweep_stale_nodes() -> None:
    """Single sweep: find ONLINE nodes with stale heartbeats and mark OFFLINE."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALENESS_THRESHOLD_SECONDS)

            result = await session.execute(
                select(Node).where(
                    Node.status == NodeStatus.ONLINE,
                    Node.last_heartbeat < cutoff,
                )
            )
            stale_nodes = list(result.scalars().all())

            for node in stale_nodes:
                node.status = NodeStatus.OFFLINE
                logger.info("Node %s marked OFFLINE (last heartbeat: %s)", node.node_id, node.last_heartbeat)

                emit_node_offline(
                    node_id=node.node_id,
                    name=node.display_name or node.node_id,
                )


async def node_staleness_monitor() -> None:
    """Long-running coroutine that sweeps for stale nodes every SWEEP_INTERVAL_SECONDS."""
    logger.info("Node staleness monitor started (threshold=%ds, interval=%ds)",
                STALENESS_THRESHOLD_SECONDS, SWEEP_INTERVAL_SECONDS)
    while True:
        try:
            await _sweep_stale_nodes()
        except Exception:
            logger.exception("Error in node staleness sweep")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
