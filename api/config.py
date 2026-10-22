import os
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018/?replicaSet=rs0&directConnection=true")
DB_NAME = os.environ.get("DB_NAME", "scheme_assistant")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me-" + "x" * 16)
JWT_TTL_MINUTES = int(os.environ.get("JWT_TTL_MINUTES", "720"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # optional: LLM narration of grounded answers
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-opus-5-5")
CHAT_RATE_LIMIT_PER_MIN = int(os.environ.get("CHAT_RATE_LIMIT_PER_MIN", "20"))
STALE_AFTER_DAYS = 90
# Atlas exposes $vectorSearch / $search; on a self-hosted server we fall back to
# in-process cosine similarity + a $text index. Auto-detected at startup.
USE_ATLAS_SEARCH = os.environ.get("USE_ATLAS_SEARCH", "auto")
