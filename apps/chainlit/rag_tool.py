from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import json
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from llm import embed
from settings import (
    CITATION_MAP_PATH,
    GRUNDSCHUTZ_SOURCE_PDF,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
    SCORE_THRESHOLD,
    TOP_K,
)


@dataclass
class RagResult:
    text: str
    score: float
    metadata: dict[str, Any]


_client: QdrantClient | None = None
_citation_map: dict[str, dict[str, str]] | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _client


def _load_citation_map() -> dict[str, dict[str, str]]:
    global _citation_map
    if _citation_map is not None:
        return _citation_map
    try:
        if CITATION_MAP_PATH.is_file():
            _citation_map = json.loads(CITATION_MAP_PATH.read_text(encoding="utf-8"))
        else:
            _citation_map = {}
    except Exception:  # noqa: BLE001
        _citation_map = {}
    return _citation_map


def _extract_text(payload: dict[str, Any]) -> str:
    for key in ("text", "content", "chunk", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _extract_citation(payload: dict[str, Any]) -> str:
    source = payload.get("source") or payload.get("document") or payload.get("title") or payload.get("file")
    page = payload.get("page") or payload.get("page_number") or payload.get("pages")
    module = payload.get("module") or payload.get("baustein")
    parts: list[str] = []
    if source:
        parts.append(str(source))
    if module:
        parts.append(f"Modul {module}")
    if page:
        parts.append(f"Seite {page}")
    if not parts:
        return "Quelle unbekannt"
    return " | ".join(parts)


def extract_source_file(payload: dict[str, Any]) -> str | None:
    value = payload.get("file")
    if isinstance(value, str) and value.lower().endswith(".pdf"):
        return value

    source = payload.get("source")
    if isinstance(source, dict):
        value = source.get("file")
        if isinstance(value, str) and value.lower().endswith(".pdf"):
            return value

    for key in ("source", "document"):
        value = payload.get(key)
        if isinstance(value, str) and value.lower().endswith(".pdf"):
            return value

    # Fallback for Grundschutz chunks ingested from structured JSON without explicit PDF file.
    source = payload.get("source")
    if isinstance(source, str) and source.lower().endswith("grundschutz.json"):
        return GRUNDSCHUTZ_SOURCE_PDF
    doc_type = payload.get("doc_type")
    if isinstance(doc_type, str) and doc_type in {
        "anforderung",
        "baustein_beschreibung",
        "baustein_gefaehrdungslage",
    }:
        return GRUNDSCHUTZ_SOURCE_PDF
    return None


def extract_page(payload: dict[str, Any]) -> int | None:
    page_start = payload.get("page_start")
    if isinstance(page_start, int):
        return page_start

    page = payload.get("page")
    if isinstance(page, int):
        return page
    if isinstance(page, dict):
        start = page.get("start")
        if isinstance(start, int):
            return start
    return None


def _clean_text(text: str, max_len: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


async def retrieve(
    query: str,
    top_k: int | None = None,
    *,
    source_scope: str | None = None,
    standard_id: str | None = None,
) -> list[RagResult]:
    client = _get_client()
    vector = (await embed([query]))[0]
    k = top_k or TOP_K
    must: list[FieldCondition] = []
    if source_scope:
        must.append(FieldCondition(key="source_scope", match=MatchValue(value=source_scope)))
    if standard_id:
        must.append(FieldCondition(key="standard_id", match=MatchValue(value=standard_id)))
    query_filter = Filter(must=must) if must else None
    print("[DEBUG] retrieve", {"top_k": k, "source_scope": source_scope, "standard_id": standard_id})
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        limit=k,
        score_threshold=SCORE_THRESHOLD,
        with_payload=True,
        query_filter=query_filter,
    )
    points = list(response.points or [])
    if not points and (source_scope or standard_id):
        # Compatibility fallback for older collections without new metadata fields.
        print("[WARN] filtered_retrieval_empty_fallback_unfiltered", {"top_k": k})
        response = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=vector,
            limit=k,
            score_threshold=SCORE_THRESHOLD,
            with_payload=True,
        )
        points = list(response.points or [])

    hits: list[RagResult] = []
    for hit in points:
        payload = dict(hit.payload or {})
        text = _extract_text(payload)
        if not text:
            continue
        hits.append(
            RagResult(
                text=_clean_text(text),
                score=float(hit.score),
                metadata=payload,
            )
        )
    return hits


def build_context(results: list[RagResult]) -> str:
    lines: list[str] = []
    for idx, result in enumerate(results, start=1):
        citation = _extract_citation(result.metadata)
        lines.append(f"[{idx}] {result.text}\nQuelle: {citation}")
    return "\n\n".join(lines)


def format_citations(results: list[RagResult]) -> str:
    citation_map = _load_citation_map()
    lines: list[str] = []
    for idx, result in enumerate(results, start=1):
        meta = result.metadata
        source = meta.get("source") or {}
        document = meta.get("document") or (source.get("document") if isinstance(source, dict) else None)
        file_name = extract_source_file(meta) or (source.get("file") if isinstance(source, dict) else None)
        page = meta.get("page") or meta.get("page_start")
        if isinstance(page, dict):
            start = page.get("start")
            end = page.get("end")
        else:
            start = page if isinstance(page, int) else None
            end = None

        # Grundschutz-specific fields
        baustein_id = meta.get("baustein")
        baustein_title = meta.get("baustein_titel")
        anforderung_id = meta.get("anforderung_id")

        doc_key = None
        if isinstance(document, str):
            doc_key = document
        elif isinstance(file_name, str):
            doc_key = file_name.replace(".pdf", "")
        meta_entry = citation_map.get(doc_key or "", {})

        author = meta_entry.get("author")
        year = meta_entry.get("year")
        title = meta_entry.get("title") or doc_key
        publisher = meta_entry.get("publisher")

        page_label = None
        if start is not None and end is not None and start != end:
            page_label = f"S. {start}–{end}"
        elif start is not None:
            page_label = f"S. {start}"
        elif end is not None:
            page_label = f"S. {end}"

        if baustein_id:
            parts = [f"Modul {baustein_id}"]
            if baustein_title:
                parts.append(str(baustein_title))
            if anforderung_id:
                parts.append(f"Anforderung {anforderung_id}")
            if page_label:
                parts.append(page_label)
            line = " | ".join(parts)
        elif author or year or title:
            parts = []
            if author:
                parts.append(author)
            if year:
                parts.append(f"({year}).")
            if title:
                parts.append(title + ".")
            if publisher:
                parts.append(publisher + ".")
            if page_label:
                parts.append(page_label + ".")
            line = " ".join(parts)
        else:
            line = _extract_citation(meta)
        lines.append(f"[{idx}] {line}")
    return "\n".join(lines)
