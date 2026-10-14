"""Throwaway API server for operator-boundary tests. Not a test module.

Usage: boundary_host.py <port>. Configuration comes only from MAC_CONTROL_* variables set by
the test; the per-user .env file is never read.
"""
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

import settings  # noqa: E402

settings.Settings.model_config["env_file"] = None

import uvicorn  # noqa: E402

import main  # noqa: E402

uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
