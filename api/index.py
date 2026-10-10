"""
api/index.py — Vercel Serverless Function entry point.

Exports the ASGI FastAPI application instance for Vercel's Python runtime.
"""

import os
import sys

# Ensure project root is present in Python module search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app  # noqa: E402
