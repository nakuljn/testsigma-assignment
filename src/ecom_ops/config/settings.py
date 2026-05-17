"""
Centralised configuration. All policy constants and provider settings live here.
Agents read from this module — never from os.environ directly.
"""
import os
import pathlib
from dotenv import load_dotenv

# Load .env from project root regardless of cwd (CLI, Streamlit, tests)
_ROOT_FOR_ENV = pathlib.Path(__file__).resolve().parents[3]
load_dotenv(_ROOT_FOR_ENV / ".env")

# ---------------------------------------------------------------------------
# Model provider
# ---------------------------------------------------------------------------
MODEL_PROVIDER: str = os.getenv("MODEL_PROVIDER", "openai").lower()
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

# ---------------------------------------------------------------------------
# Search provider
# ---------------------------------------------------------------------------
SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "duckduckgo").lower()
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
SKIP_WEB_SEARCH: bool = os.getenv("SKIP_WEB_SEARCH", "").lower() in ("1", "true", "yes")
BATCH_LLM: bool = os.getenv("BATCH_LLM", "").lower() in ("1", "true", "yes")
SEARCH_TIMEOUT_SECONDS: int = int(os.getenv("SEARCH_TIMEOUT_SECONDS", "15"))
MAX_PRICING_WEB_SEARCHES: int = int(os.getenv("MAX_PRICING_WEB_SEARCHES", "3"))

# ---------------------------------------------------------------------------
# Policy thresholds
# ---------------------------------------------------------------------------
MIN_MARGIN_PCT: float = float(os.getenv("MIN_MARGIN_PCT", "0.20"))
DAYS_COVER_CRITICAL: int = int(os.getenv("DAYS_COVER_CRITICAL", "3"))
DAYS_COVER_LOW: int = int(os.getenv("DAYS_COVER_LOW", "7"))
LOW_SALES_QUARTILE: float = float(os.getenv("LOW_SALES_QUARTILE", "0.25"))

# Default restock multiple: order enough for N days of cover
RESTOCK_TARGET_DAYS: int = 30

# ---------------------------------------------------------------------------
# Paths
# src/ecom_ops/config/settings.py → 4 parents up = project root
# ---------------------------------------------------------------------------
ROOT_DIR: pathlib.Path = pathlib.Path(__file__).resolve().parents[3]
DATA_DIR: pathlib.Path = ROOT_DIR / "data" / "seed"
OUTPUT_DIR: pathlib.Path = ROOT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
