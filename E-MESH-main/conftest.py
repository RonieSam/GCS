"""
Pytest configuration for E-Mesh backend tests.
This file ensures the backend/app package is importable from the tests/ directory.
"""
import sys
import os

# Add the backend directory to sys.path so `app.*` imports work
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
