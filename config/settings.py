"""Global settings and configuration."""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
PORTALS_FILE = CONFIG_DIR / "portals.yaml"
DB_PATH = DATA_DIR / "nursescraper.db"
FEEDS_DIR = PROJECT_ROOT / "feeds"
FEEDS_OUTPUT_DIR = DATA_DIR / "feeds"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
FEEDS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Scraping defaults ---
DEFAULT_RATE_LIMIT = float(os.getenv("SCRAPE_RATE_LIMIT", "1.5"))  # seconds
DEFAULT_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "30"))  # seconds
DEFAULT_MAX_RETRIES = int(os.getenv("SCRAPE_MAX_RETRIES", "3"))

# --- Output ---
OUTPUT_FORMAT = os.getenv("OUTPUT_FORMAT", "both")  # "csv" | "json" | "both"

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
