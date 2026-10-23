"""Application settings loaded from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
EXPORT_DIR = BASE_DIR / "exports"
UPLOAD_DIR = DATA_DIR / "uploads"

DEMO_CALLS_PATH = DATA_DIR / "demo_calls.jsonl"
LIVE_CALLS_PATH = DATA_DIR / "calls.jsonl"
DEMOGRAPHICS_PATH = DATA_DIR / "customer_demographics.csv"

MODEL = os.getenv("SENTICALL_MODEL", "claude-haiku-5-5")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
PORT = int(os.getenv("SENTICALL_PORT", "8050"))

for _d in (EXPORT_DIR, UPLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def api_key_present() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
