"""
Phase 5 — SQLite persistence.

Four tables, per the project spec: nodes, missions, telemetry, deployments.
Only `nodes` and `missions` are actually written to in Phase 5 — `telemetry`
and `deployments` are created now (so the schema is stable and doesn't need
a migration later) but stay empty until Phase 7 (telemetry) and Phase 10
(deployment simulation) actually populate them. An empty-but-correctly-
shaped table is honest; a table that doesn't exist yet would just mean
`/api/deployments` has to lie about why it's empty.

Uses the stdlib sqlite3 module only — no ORM, consistent with the rest of
the prototype's "no unnecessary complexity" approach. One connection per
call (SQLite handles this fine at prototype scale, and it sidesteps any
cross-request connection/threading concerns under uvicorn's default
threaded execution of sync endpoints).
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "uav_emergency.db")
NODES_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "nodes.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    coverage_radius_m REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    target_lat REAL NOT NULL,
    target_lon REAL NOT NULL,
    target_alt REAL NOT NULL,
    score REAL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER,
    timestamp TEXT NOT NULL,
    lat REAL,
    lon REAL,
    altitude REAL,
    ground_speed REAL,
    heading REAL,
    battery REAL,
    mode TEXT,
    armed INTEGER,
    FOREIGN KEY (mission_id) REFERENCES missions(id)
);

CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER,
    node_id TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (mission_id) REFERENCES missions(id)
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they don't exist yet, and seed `nodes` from
    data/nodes.json if the table is currently empty (first run)."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _seed_nodes_if_empty(conn)
    finally:
        conn.close()


def _seed_nodes_if_empty(conn):
    count = conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"]
    if count > 0:
        return
    if not os.path.exists(NODES_JSON_PATH):
        return
    with open(NODES_JSON_PATH) as f:
        nodes = json.load(f)
    conn.executemany(
        "INSERT OR REPLACE INTO nodes (id, lat, lon, coverage_radius_m) VALUES (?, ?, ?, ?)",
        [(n["id"], n["lat"], n["lon"], n.get("coverage_radius_m", 250)) for n in nodes],
    )
    conn.commit()


def list_nodes():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, lat, lon, coverage_radius_m FROM nodes").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def insert_mission(target_lat, target_lon, target_alt, score, status="MISSION_READY"):
    conn = get_connection()
    try:
        created_at = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO missions (created_at, target_lat, target_lon, target_alt, score, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (created_at, target_lat, target_lon, target_alt, score, status),
        )
        conn.commit()
        return get_mission(cur.lastrowid, conn=conn)
    finally:
        conn.close()


def get_mission(mission_id, conn=None):
    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if owns_conn:
            conn.close()


def update_mission_status(mission_id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE missions SET status = ? WHERE id = ?", (status, mission_id))
        conn.commit()
        return get_mission(mission_id, conn=conn)
    finally:
        conn.close()


def list_missions():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM missions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_deployments():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM deployments ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def reset_db_for_tests():
    """Test-only helper: drop and recreate every table. Never called from
    application code — main.py always calls init_db(), which is additive."""
    conn = get_connection()
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS deployments;"
            "DROP TABLE IF EXISTS telemetry;"
            "DROP TABLE IF EXISTS missions;"
            "DROP TABLE IF EXISTS nodes;"
        )
        conn.commit()
    finally:
        conn.close()
    init_db()
