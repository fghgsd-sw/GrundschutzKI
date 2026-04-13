from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)


def _getenv(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value is not None else default


def _getenv_list(name: str, default: list[str] | None = None, sep: str = "||") -> list[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default or []
    return [item.strip() for item in value.split(sep) if item.strip()]


LITELLM_BASE_URL = _getenv("LITELLM_BASE_URL")
LITELLM_API_KEY = _getenv("LITELLM_API_KEY")
CHAT_MODEL = _getenv("CHAT_MODEL", "gpt-4o-mini")
FALLBACK_CHAT_MODEL = _getenv("FALLBACK_CHAT_MODEL")
EMBED_MODEL = _getenv("EMBED_MODEL", "text-embedding-3-large")

QDRANT_URL = _getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = _getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = _getenv("QDRANT_COLLECTION", "grundschutz")
TOP_K = int(_getenv("TOP_K", "5"))
MAX_TOP_K = int(_getenv("MAX_TOP_K", str(TOP_K)))
MAX_SOURCE_LINKS = int(_getenv("MAX_SOURCE_LINKS", "8"))
SCORE_THRESHOLD = float(_getenv("SCORE_THRESHOLD", "0.0"))
STREAMING_ENABLED = (_getenv("STREAMING_ENABLED", "false") or "false").lower() == "true"
STREAMING_DOUBLE_PASS = (_getenv("STREAMING_DOUBLE_PASS", "false") or "false").lower() == "true"

SYSTEM_PROMPT_PATH = Path(
    _getenv(
        "SYSTEM_PROMPT_PATH",
        str((BASE_DIR / ".." / ".." / "system.md").resolve()),
    )
)

DATA_RAW_DIR = Path(
    _getenv(
        "DATA_RAW_DIR",
        str((BASE_DIR / ".." / ".." / "data" / "data_raw").resolve()),
    )
)

GRUNDSCHUTZ_SOURCE_PDF = (
    _getenv("GRUNDSCHUTZ_SOURCE_PDF", "IT_Grundschutz_Kompendium_Edition2023.pdf")
    or "IT_Grundschutz_Kompendium_Edition2023.pdf"
)

CITATION_MAP_PATH = Path(
    _getenv(
        "CITATION_MAP_PATH",
        str((BASE_DIR / "citation_map.json").resolve()),
    )
)

STARTER_QUESTIONS = _getenv_list(
    "STARTER_QUESTIONS",
    default=[
        "Was ist der Unterschied zwischen Prozess- und Systembausteinen?",
        "Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?",
        "Wie müssen Passwörter bei der Authentisierung am Webserver gesichert werden?",
        "Was sind die Kernabsicherung und die Standard-Absicherung?",
        "Welche Rolle spielt der IT-Sicherheitsbeauftragte im BSI-Grundschutz?",
        "Wie wird eine Schutzbedarfsfeststellung durchgeführt?",
        "Was ist ein IT-Grundschutz-Baustein und wie ist er aufgebaut?",
        "Welche Gefährdungen adressiert der Baustein OPS.1.1.3 Patch- und Änderungsmanagement?",
        "Wie funktioniert die Risikoanalyse nach BSI-Standard 200-3?",
        "Was versteht man unter dem Schichtenmodell im IT-Grundschutz?",
        "Welche Anforderungen stellt der Baustein APP.1.1 Office-Produkte?",
        "Was sind die Phasen des BSI-Sicherheitsprozesses?",
    ],
)
STARTER_QUESTIONS_COUNT = int(_getenv("STARTER_QUESTIONS_COUNT", "3"))

CHAT_DB_PATH = Path(
    _getenv(
        "CHAT_DB_PATH",
        str((BASE_DIR / ".chainlit" / "chat_history.sqlite3").resolve()),
    )
)

CHAT_EXPORT_DIR = Path(
    _getenv(
        "CHAT_EXPORT_DIR",
        str((BASE_DIR / ".files" / "chat_exports").resolve()),
    )
)

DATABASE_URL = _getenv("DATABASE_URL")
CHAINLIT_AUTH_USERNAME = _getenv("CHAINLIT_AUTH_USERNAME", "admin")
CHAINLIT_AUTH_PASSWORD = _getenv("CHAINLIT_AUTH_PASSWORD", "admin")
CHAINLIT_INIT_DB = (_getenv("CHAINLIT_INIT_DB", "true") or "true").lower() == "true"

# ---------------------------------------------------------------------------
# SMTP / Email Verification Settings
# ---------------------------------------------------------------------------
SMTP_HOST = _getenv("SMTP_HOST")
SMTP_PORT = int(_getenv("SMTP_PORT", "587"))
SMTP_USER = _getenv("SMTP_USER")
SMTP_PASSWORD = _getenv("SMTP_PASSWORD")
SMTP_FROM = _getenv("SMTP_FROM", SMTP_USER)
SMTP_USE_TLS = (_getenv("SMTP_USE_TLS", "true") or "true").lower() == "true"
EMAIL_VERIFICATION_ENABLED = (_getenv("EMAIL_VERIFICATION_ENABLED", "false") or "false").lower() == "true"
APP_BASE_URL = _getenv("APP_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Personalization Settings
# ---------------------------------------------------------------------------
PERSONALIZATION_ENABLED = (_getenv("PERSONALIZATION_ENABLED", "true") or "true").lower() == "true"
PROFILE_MIN_MESSAGES = int(_getenv("PROFILE_MIN_MESSAGES", "5"))
PROFILE_TOPIC_LIMIT = int(_getenv("PROFILE_TOPIC_LIMIT", "8"))
PROFILE_RELEVANCE_THRESHOLD = float(_getenv("PROFILE_RELEVANCE_THRESHOLD", "0.3"))
PERSONALIZED_FOLLOWUPS_COUNT = int(_getenv("PERSONALIZED_FOLLOWUPS_COUNT", "2"))

# Validate personalization settings at import time
if PROFILE_MIN_MESSAGES < 1:
    raise ValueError(f"PROFILE_MIN_MESSAGES must be >= 1, got {PROFILE_MIN_MESSAGES}")
if PROFILE_TOPIC_LIMIT < 0:
    raise ValueError(f"PROFILE_TOPIC_LIMIT must be >= 0, got {PROFILE_TOPIC_LIMIT}")
if not (0.0 <= PROFILE_RELEVANCE_THRESHOLD <= 1.0):
    raise ValueError(f"PROFILE_RELEVANCE_THRESHOLD must be between 0.0 and 1.0, got {PROFILE_RELEVANCE_THRESHOLD}")
if PERSONALIZED_FOLLOWUPS_COUNT < 0:
    raise ValueError(f"PERSONALIZED_FOLLOWUPS_COUNT must be >= 0, got {PERSONALIZED_FOLLOWUPS_COUNT}")
