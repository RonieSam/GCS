# -*- coding: utf-8 -*-
"""
E-MESH Backend Launcher
=======================
Starts TWO servers from one command:

  HTTP  port 8000  -- for ESP32 nodes (firmware uses this, no changes needed)
  HTTPS port 8443  -- for user phones  (GPS requires HTTPS)

Usage (from the backend/ directory):
    python start.py

Phone URL : https://192.168.137.1:8443/client
  -> Tap "Advanced" then "Proceed" once -> GPS permission works from then on.

ESP32 URL : http://192.168.137.1:8000  (unchanged, no firmware changes needed)
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

CERT_FILE  = Path(__file__).parent / "certs" / "cert.pem"
KEY_FILE   = Path(__file__).parent / "certs" / "key.pem"
GEN_SCRIPT = Path(__file__).parent / "gen_cert.py"

APP = "app.main:app"


def ensure_cert() -> None:
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        print("[CERT] Generating self-signed certificate...")
        result = subprocess.run([sys.executable, str(GEN_SCRIPT)], check=False)
        if result.returncode != 0:
            print("[ERROR] Could not generate certificate.")
            sys.exit(1)
    else:
        print(f"[CERT] Using existing certificate: {CERT_FILE}")


async def run_servers() -> None:
    try:
        import uvicorn
    except ImportError:
        print("[ERROR] uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    # HTTP server - for ESP32 firmware (no SSL)
    http_config = uvicorn.Config(
        APP,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )

    # HTTPS server - for user phones (GPS requires HTTPS)
    https_config = uvicorn.Config(
        APP,
        host="0.0.0.0",
        port=8443,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
        log_level="info",
    )

    http_server  = uvicorn.Server(http_config)
    https_server = uvicorn.Server(https_config)

    print()
    print("=" * 55)
    print("  E-MESH Emergency Network - Backend Server")
    print("=" * 55)
    print()
    print("  [ESP32 nodes]  http://192.168.137.1:8000")
    print("  [User phones]  https://192.168.137.1:8443/client")
    print("                 (tap Advanced > Proceed once for GPS)")
    print()
    print("  API docs  : https://192.168.137.1:8443/docs")
    print("  Cert file : certs/cert.pem")
    print()
    print("=" * 55)
    print()

    # Run both servers concurrently
    await asyncio.gather(
        http_server.serve(),
        https_server.serve(),
    )


def main() -> None:
    ensure_cert()
    try:
        asyncio.run(run_servers())
    except KeyboardInterrupt:
        print("\n[INFO] E-MESH backend stopped.")


if __name__ == "__main__":
    main()
