"""OptiStock AI - Configuration

Loads environment variables and provides configurable thresholds
for the multi-agent stockout resolution system.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).resolve().parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# ── LLM ──
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4")

# ── LangGraph / Tracing ──
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "optistock")

# ── Database ──
DATABASE_PATH = str(_project_root / os.getenv("DATABASE_PATH", "database/optistock.db"))

# ── Thresholds (configurable, not hidden in prompts) ──
DATA_FRESHNESS_THRESHOLD_HOURS = int(os.getenv("DATA_FRESHNESS_THRESHOLD", "48"))
DEFAULT_TARGET_COVER_DAYS = int(os.getenv("DEFAULT_TARGET_COVER_DAYS", "14"))
TARGET_COVER_DAYS_MIN = 7
TARGET_COVER_DAYS_MAX = 45

# ── Budget ──
DEFAULT_MONTHLY_BUDGET = float(os.getenv("DEFAULT_MONTHLY_BUDGET", "50000"))

# ── Reliability ──
VENDOR_RELIABILITY_THRESHOLD = 0.90

# ── Agent behaviour ──
MAX_AGENT_RETRIES = int(os.getenv("MAX_AGENT_RETRIES", "1"))
MAX_REVISION_COUNT = 1  # Bounded revision: at most 1 loop back

# ── Approval ──
APPROVAL_TIMEOUT_MINUTES = int(os.getenv("APPROVAL_TIMEOUT_MINUTES", "60"))

# ── Logging ──
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── Policy ──
POLICY_PATH = str(_project_root / "policy.md")
