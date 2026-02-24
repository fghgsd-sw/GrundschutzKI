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
    ],
)

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
