"""
Diagnose: an welcher Rangposition liegen die Kapitel-9-Chunks (die tatsächlich
richtige Antwort auf "Welche Schritte umfasst die Basis-Absicherung...") in
einer UNGECAPPTEN Ähnlichkeitssuche? Beantwortet direkt die Frage "würde ein
größeres top_k helfen, oder liegt das Problem woanders (Embedding-Distanz)?"

Nutzung: gleiches Muster wie measure_citation_judge.py (Host oder Container).
"""
from __future__ import annotations

import sys
from pathlib import Path

if Path("/app/app.py").is_file() and Path("/data").is_dir():
    CHAINLIT_DIR = Path("/app")
else:
    CHAINLIT_DIR = Path(__file__).resolve().parent.parent / "apps" / "chainlit"
sys.path.insert(0, str(CHAINLIT_DIR))

import asyncio  # noqa: E402

from llm import embed  # noqa: E402
from rag_tool import _get_client  # noqa: E402
from settings import QDRANT_COLLECTION  # noqa: E402
from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: E402

QUESTION = "Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?"
LIMIT = 60


async def main() -> None:
    vector = (await embed([QUESTION]))[0]
    client = _get_client()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        query_filter=Filter(must=[FieldCondition(key="standard_id", match=MatchValue(value="standard_200_2"))]),
        limit=LIMIT,
        score_threshold=0.0,
        with_payload=True,
    )
    points = response.points or []
    print(f"Insgesamt {len(points)} Treffer (limit={LIMIT}, standard_id=standard_200_2, kein Score-Cutoff)\n")
    for rank, p in enumerate(points, start=1):
        payload = p.payload or {}
        section = payload.get("section_title") or payload.get("title") or "?"
        page = payload.get("page_start")
        marker = ""
        if isinstance(section, str) and (
            section.strip().startswith(("9.", "9 "))
            or "Umsetzung der Sicherheitskonzeption" in section
        ):
            marker = "  <<< KAPITEL 9"
        print(f"[{rank:2d}] score={p.score:.3f} p={page} {str(section)[:70]}{marker}")


if __name__ == "__main__":
    asyncio.run(main())
