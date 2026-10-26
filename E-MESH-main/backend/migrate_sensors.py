"""
One-time migration script: adds sensor telemetry columns to the nodes table.
Run this while the backend is stopped to avoid locking conflicts.
Usage: python migrate_sensors.py
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "e_mesh.db")

NEW_COLUMNS = [
    ("temperature_c", "REAL"),
    ("pressure_hpa",  "REAL"),
    ("accel_x",       "INTEGER"),
    ("accel_y",       "INTEGER"),
    ("accel_z",       "INTEGER"),
    ("gyro_x",        "INTEGER"),
    ("gyro_y",        "INTEGER"),
    ("gyro_z",        "INTEGER"),
    ("has_gps",       "BOOLEAN NOT NULL DEFAULT 0"),
    ("gps_lat",       "REAL"),
    ("gps_lon",       "REAL"),
    ("gps_alt_m",     "REAL"),
    ("gps_sats",      "INTEGER"),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(nodes)")
    existing = {row[1] for row in cursor.fetchall()}
    print(f"Existing columns: {existing}")

    added = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            sql = f"ALTER TABLE nodes ADD COLUMN {col_name} {col_type}"
            cursor.execute(sql)
            added.append(col_name)
            print(f"  Added column: {col_name} ({col_type})")
        else:
            print(f"  Skipped (already exists): {col_name}")

    conn.commit()
    conn.close()

    if added:
        print(f"\nMigration complete. Added {len(added)} column(s): {', '.join(added)}")
    else:
        print("\nNo changes needed — all columns already present.")

if __name__ == "__main__":
    migrate()
