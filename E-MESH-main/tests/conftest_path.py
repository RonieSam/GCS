"""
Root conftest for pytest — adds backend/app to sys.path so tests can import app modules.
"""
import sys
import os

# Ensure the backend directory is on the path so `app.*` imports resolve
backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(backend_dir))
