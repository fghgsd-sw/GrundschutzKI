from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import json
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from llm import chat, embed
from settings import (
    BAUSTEIN_ROUTING_ENABLED,
    BAUSTEIN_ROUTING_THRESHOLD,
    CITATION_MAP_PATH,
    DOC_ROUTING_ENABLED,
    DOC_ROUTING_GAP,
    DOC_ROUTING_THRESHOLD,
    GRUNDSCHUTZ_SOURCE_PDF,
    HYDE_ENABLED,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
    SCORE_THRESHOLD,
    SCORE_THRESHOLD_SCOPED,
    TOP_K,
)

if TYPE_CHECKING:
    from user_profile import UserProfile


@dataclass
class RagResult:
    text: str
    score: float
    metadata: dict[str, Any]


_client: QdrantClient | None = None
_citation_map: dict[str, dict[str, str]] | None = None


def _canonical_pdf_from_text(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    if lower.endswith(".pdf"):
        return raw.split("/")[-1]

    if "standard_200_1" in lower or "standard 200 1" in lower:
        return "standard_200_1.pdf"
    if "standard_200_2" in lower or "standard 200 2" in lower:
        return "standard_200_2.pdf"
    if "standard_200_3" in lower or "standard 200 3" in lower:
        return "standard_200_3.pdf"
    if "standard_200_4" in lower or "standard 200 4" in lower:
        return "standard_200_4.pdf"

    if "kompendium" in lower or "grundschutz" in lower:
        return GRUNDSCHUTZ_SOURCE_PDF

    return None


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


def resolve_section_title(metadata: dict[str, Any]) -> str | None:
    """Resolve the most specific human-readable label for one chunk.

    Single source of truth for section-title resolution, shared between the
    in-context citation hint (_extract_citation, below) and the post-hoc
    citation panel / canonicalizer (app.py's _resolve_section_title, which
    re-exports this). Priority: explicit section_title (standard_abschnitt
    chunks) > anforderung_id (anforderung chunks — distinguishes e.g.
    "OPS.2.2.A10" from every other Anforderung in the same Baustein) >
    baustein_id + doc_type suffix (baustein_beschreibung/gefaehrdungslage) >
    generic title.
    """
    explicit = metadata.get("section_title")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    anforderung_id = metadata.get("anforderung_id")
    if isinstance(anforderung_id, str) and anforderung_id.strip():
        return anforderung_id.strip()

    baustein_id = metadata.get("baustein_id")
    if isinstance(baustein_id, str) and baustein_id.strip():
        doc_type = metadata.get("doc_type")
        if doc_type == "baustein_beschreibung":
            return f"{baustein_id} Beschreibung"
        if doc_type == "baustein_gefaehrdungslage":
            return f"{baustein_id} Gefaehrdungslage"
        return baustein_id

    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def _extract_citation(payload: dict[str, Any]) -> str:
    """Build the "Quelle: ..." hint shown to the LLM for one retrieved chunk.

    Previously used source/document/title/file priority, which for every
    Kompendium chunk resolved to the constant "grundschutz.json" (always
    truthy, identical across chunks) — the model had no way to distinguish
    which specific Anforderung a chunk belonged to and defaulted to citing
    whichever Baustein-level overview chunk it noticed. Now mirrors
    resolve_section_title() so the model sees the exact, distinct alias
    text it is expected to reproduce per system.md's citation format.
    """
    section_title = resolve_section_title(payload)
    if not section_title:
        # Non-Kompendium fallback (e.g. unexpected/foreign payload shapes).
        source = payload.get("source") or payload.get("document") or payload.get("file")
        section_title = str(source) if source else "Quelle unbekannt"

    page_start = payload.get("page_start")
    if not isinstance(page_start, int):
        page = payload.get("page") or payload.get("page_number") or payload.get("pages")
        page_start = page if isinstance(page, int) else None
    page_end = payload.get("page_end")

    if isinstance(page_start, int) and isinstance(page_end, int) and page_end != page_start:
        page_label = f"S.{page_start}-{page_end}"
    elif isinstance(page_start, int):
        page_label = f"S.{page_start}"
    else:
        page_label = "S.?"

    return f"{section_title} ({page_label})"


def extract_source_file(payload: dict[str, Any]) -> str | None:
    value = payload.get("file")
    if isinstance(value, str):
        resolved = _canonical_pdf_from_text(value)
        if resolved:
            return resolved

    source = payload.get("source")
    if isinstance(source, dict):
        value = source.get("file")
        if isinstance(value, str):
            resolved = _canonical_pdf_from_text(value)
            if resolved:
                return resolved

        for key in ("document", "title", "source"):
            nested = source.get(key)
            if isinstance(nested, str):
                resolved = _canonical_pdf_from_text(nested)
                if resolved:
                    return resolved

    for key in ("source", "document", "title"):
        value = payload.get(key)
        if isinstance(value, str):
            resolved = _canonical_pdf_from_text(value)
            if resolved:
                return resolved

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


_HYDE_PROMPT = (
    "Generiere einen kurzen Absatz (3–5 Sätze) auf Deutsch, der die folgende Frage im Kontext des "
    "IT-Grundschutzes beantwortet. Verwende thematisch passendes Fachvokabular aus dem BSI-Kompendium "
    "(technische Begriffe, Schichtbezeichnungen, Konzepte). Keine Baustein-IDs nennen. "
    "Inhaltliche Genauigkeit ist nicht erforderlich — der Absatz dient ausschließlich zur Verbesserung "
    "der semantischen Dokumentensuche.\n\nFrage: {query}\n\nAbsatz:"
)


async def _generate_hyde_query(query: str) -> str:
    try:
        response = await chat(
            messages=[{"role": "user", "content": _HYDE_PROMPT.format(query=query)}],
            tools=None,
            tool_choice=None,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()
        if text:
            print(f"[DEBUG] HyDE generated: {text[:120]}...")
            return text
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] HyDE generation failed, falling back to raw query: {e}")
    return query


def _clean_text(text: str, max_len: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Schicht 1: Regex-Dokumenten-Router
# ---------------------------------------------------------------------------

_STANDARD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?1\b", re.I), "standard_200_1"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?2\b", re.I), "standard_200_2"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?3\b", re.I), "standard_200_3"),
    (re.compile(r"\b(?:BSI[- ])?Standard[- ]?200[- ]?4\b", re.I), "standard_200_4"),
]


def detect_explicit_standard(query: str) -> str | None:
    """Detects explicit BSI standard reference in query text (routing layer 1)."""
    for pattern, standard_id in _STANDARD_PATTERNS:
        if pattern.search(query):
            return standard_id
    return None


# ---------------------------------------------------------------------------
# Schicht 2: Semantischer Dokumenten-Router
# ---------------------------------------------------------------------------

DOCUMENT_PROFILES: dict[str, str] = {
    "standard_200_1": (
        "BSI-Standard 200-1 behandelt Aufbau und Betrieb eines Informationssicherheits-"
        "Managementsystems (ISMS). Inhalte: Definition des ISMS und des Sicherheitsprozesses, "
        "Management-Prinzipien, Ressourcen und Mitarbeitereinbindung, Sicherheitsleitlinie, "
        "Informationssicherheitsbeauftragter, kontinuierlicher Verbesserungsprozess (PDCA), "
        "Kompatibilität mit ISO 27001 und ISO 27002, ISMS-Zertifizierung auf Basis "
        "IT-Grundschutz. Zuständig für Fragen zum Managementsystem, zur Sicherheitsorganisation "
        "und zu Rollen. Nicht zuständig für konkrete technische Maßnahmen, "
        "Risikoanalysemethodik oder Notfallplanung."
    ),
    "standard_200_2": (
        "BSI-Standard 200-2 beschreibt die IT-Grundschutz-Methodik zur Erstellung von "
        "Sicherheitskonzepten in Behörden und Unternehmen. Inhalte: Initiierung des "
        "Sicherheitsprozesses, drei Vorgehensweisen (Basis-Absicherung, Kern-Absicherung, "
        "Standard-Absicherung), Strukturanalyse, Schutzbedarfsfeststellung, Modellierung "
        "nach IT-Grundschutz, IT-Grundschutz-Check, Risikoanalyse als Bestandteil der "
        "Standard-Absicherung, Umsetzungsplanung. Primärquelle für Fragen zur Vorgehensweise "
        "bei der IT-Grundschutz-Einführung, zur Sicherheitskonzeption und zu Absicherungsarten. "
        "Risikoanalyse hier: integrierter Schritt im Sicherheitskonzept — nicht als "
        "eigenständige Methodik für erhöhten Schutzbedarf."
    ),
    "standard_200_3": (
        "BSI-Standard 200-3 beschreibt eine eigenständige Methodik zur Risikoanalyse "
        "auf Basis der elementaren Gefährdungen des IT-Grundschutzes. Anwendungsfall: "
        "Systeme und Prozesse mit erhöhtem oder hohem Schutzbedarf, die über den "
        "IT-Grundschutz-Check hinausgehen. Inhalte: Vorarbeiten zur Risikoanalyse, "
        "Ermittlung und Bewertung elementarer Gefährdungen, Gefährdungsübersicht, "
        "Risikoeinstufung (Risikoeinschätzung und Risikobewertung), "
        "Risikobehandlungsoptionen (Reduktion, Übernahme, Vermeidung, Transfer), "
        "Risiken unter Beobachtung, Konsolidierung des Sicherheitskonzepts, "
        "Risikoappetit, Bezug zu ISO/IEC 31000. Zuständig für tiefergehende "
        "Risikoanalyse-Methodik und Eintrittshäufigkeit-Schadensauswirkungs-Matrizen. "
        "Nicht zuständig für allgemeine Sicherheitskonzept-Erstellung oder BCM."
    ),
    "standard_200_4": (
        "BSI-Standard 200-4 behandelt Business Continuity Management (BCM) und "
        "Notfallmanagement für Behörden und Unternehmen. Inhalte: BCMS-Stufenmodell "
        "(Reaktiv-BCMS, Aufbau-BCMS, Standard-BCMS), Bewältigungsorganisation (BAO), "
        "Stabsarbeit, BIA-Vorfilter und Business-Impact-Analyse (BIA), Identifikation "
        "zeitkritischer Geschäftsprozesse, Wiederanlaufplanung, Notfallvorsorge, "
        "Krisenmanagement und Krisenkommunikation, Notfallübungen, BC-Beauftragter. "
        "Zuständig ausschließlich wenn Notfallmanagement, Betriebskontinuität, "
        "Wiederherstellung nach Schadensereignissen oder BCM den Fragekontext bilden. "
        "Nicht zuständig für ISMS-Aufbau, Sicherheitskonzept oder Risikoanalyse-Methodik."
    ),
    "kompendium": (
        "Das IT-Grundschutz-Kompendium (Edition 2023) enthält alle IT-Grundschutz-Bausteine "
        "mit konkreten Sicherheitsanforderungen. Struktur: Elementare Gefährdungen (G 0.1–G 0.47), "
        "Prozess-Bausteine (ISMS, ORP, CON, OPS, DER) und System-Bausteine (APP, SYS, IND, NET, INF). "
        "Beispiel-Bausteine: ORP.4 Identitäts- und Berechtigungsmanagement, OPS.1.1.3 "
        "Patch- und Änderungsmanagement, APP.3.1 Webanwendungen, SYS.1.1 Allgemeiner Server, "
        "SYS.1.8 Speicherlösungen, NET.3.2 Firewall, INF.2 Rechenzentrum. "
        "Anforderungen sind nach Schutzbedarfsstufe klassifiziert (Basis, Standard, Erhöht). "
        "Zuständig für Fragen zu konkreten Anforderungen, Maßnahmen, Gefährdungslagen "
        "und Umsetzungshinweisen für bestimmte IT-Systeme, Anwendungen oder Prozesse."
    ),
}

_profile_vectors: dict[str, list[float]] = {}


async def _ensure_profile_vectors() -> None:
    """Computes document profile embeddings once and caches them in-process."""
    if _profile_vectors:
        return
    keys = list(DOCUMENT_PROFILES.keys())
    vectors = await embed(list(DOCUMENT_PROFILES.values()))
    _profile_vectors.update(zip(keys, vectors))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


async def detect_document_scope(
    query_vector: list[float],
    threshold: float,
    min_gap: float,
) -> tuple[str | None, str, float, float]:
    """Semantic document routing via profile embeddings (routing layer 2).

    Returns (winner, best_candidate, best_score, gap).

    winner is best_candidate when score > threshold AND gap > min_gap, else None.
    best_candidate and best_score are always returned so the caller can detect
    near-miss situations (plausible signal that did not clear the threshold/gap)
    and suppress Layer 3 accordingly.
    """
    await _ensure_profile_vectors()
    scores = sorted(
        ((_cosine_similarity(query_vector, vec), doc_id) for doc_id, vec in _profile_vectors.items()),
        reverse=True,
    )
    best_score, best_id = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    gap = best_score - second_score
    print(
        f"[ROUTING] layer2_scores: {best_id}={best_score:.4f} "
        f"gap={gap:.4f} threshold={threshold} min_gap={min_gap}"
    )
    winner = best_id if best_score > threshold and gap > min_gap else None
    return winner, best_id, best_score, gap


# ---------------------------------------------------------------------------
# Schicht 3: Semantischer Baustein-Router
# ---------------------------------------------------------------------------

async def detect_baustein_scope(
    query_vector: list[float],
    threshold: float,
    top_n: int = 2,
) -> list[str]:
    """Finds relevant Bausteine via embedding search on description chunks (routing layer 3).

    Returns list of baustein_ids (empty when no clear match above threshold).
    """
    client = _get_client()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=query_vector,
        query_filter=Filter(must=[
            FieldCondition(key="doc_type", match=MatchValue(value="baustein_beschreibung")),
        ]),
        limit=top_n,
        score_threshold=threshold,
        with_payload=True,
    )
    bausteine: list[str] = []
    for point in (response.points or []):
        bid = (point.payload or {}).get("baustein_id")
        if isinstance(bid, str) and bid:
            bausteine.append(bid)
    if bausteine:
        print(f"[ROUTING] layer3_baustein: {bausteine}")
    return bausteine


def _qdrant_query(
    vector: list[float],
    k: int,
    *,
    source_scope: str | None = None,
    standard_id: str | None = None,
    baustein_id: str | None = None,
    schicht_id: str | None = None,
    include_vectors: bool = False,
) -> list[Any]:
    """Execute a single Qdrant vector search with optional hard filters.

    All filters are combined as AND (must). Returns raw ScoredPoint objects
    so the caller can merge multiple result sets before converting to RagResult.
    """
    must: list[FieldCondition] = []
    if source_scope:
        must.append(FieldCondition(key="source_scope", match=MatchValue(value=source_scope)))
    if standard_id:
        must.append(FieldCondition(key="standard_id", match=MatchValue(value=standard_id)))
    if baustein_id:
        must.append(FieldCondition(key="baustein_id", match=MatchValue(value=baustein_id)))
    if schicht_id:
        must.append(FieldCondition(key="schicht_id", match=MatchValue(value=schicht_id)))

    # A hard standard_id/baustein_id/schicht_id filter already guarantees scope
    # correctness (Qdrant only returns points from that exact standard/Baustein/
    # Schicht) — a lower score_threshold here only affects recall *within* that
    # already-correct scope, not precision across the wider corpus. Anforderung
    # chunks are terse imperative BSI clauses that score systematically lower
    # against a natural-language question than descriptive prose chunks, so the
    # default threshold can starve a scoped query of any anforderung hits.
    threshold = SCORE_THRESHOLD_SCOPED if (standard_id or baustein_id or schicht_id) else SCORE_THRESHOLD

    response = _get_client().query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        limit=k,
        score_threshold=threshold,
        with_payload=True,
        with_vectors=include_vectors,
        query_filter=Filter(must=must) if must else None,
    )
    return list(response.points or [])


async def retrieve(
    query: str,
    top_k: int | None = None,
    *,
    source_scope: str | None = None,
    standard_id: str | None = None,
    baustein_id: str | None = None,
    schicht_id: str | None = None,
    include_vectors: bool = False,
) -> list[RagResult]:
    """Retrieve documents matching the query.

    Args:
        query: Search query text
        top_k: Number of results to return
        source_scope: Optional filter by source scope
        standard_id: Optional filter by standard ID
        baustein_id: Optional filter restricting results to one IT-Grundschutz
            Baustein (e.g. "OPS.1.1.3"). Only chunks of doc_type anforderung /
            baustein_beschreibung / baustein_gefaehrdungslage carry this field;
            standard_abschnitt chunks (BSI-200-x) never match and are excluded
            when this filter is set.
        schicht_id: Optional filter restricting results to one IT-Grundschutz
            Schicht/layer (e.g. "ORP", "APP", "SYS", "NET", "INF", "CON",
            "OPS", "DER", "IND", "ISMS"). Broader than baustein_id — use when
            the question names a whole layer (e.g. "ORP") rather than one
            specific Baustein number. Same doc_type restriction as
            baustein_id applies.
        include_vectors: If True, include embedding vectors in results (for personalization)

    Returns:
        List of RagResult objects
    """
    embed_query = (await _generate_hyde_query(query)) if HYDE_ENABLED else query
    vector = (await embed([embed_query]))[0]

    # Routing hints. Layer 2/3 are additive blended supplements, never exclusive
    # filters, since they involve genuine ambiguity (embedding-threshold match) and
    # a question can legitimately span multiple sources (e.g. "ISMS-Prinzipien" →
    # 200-1 text + ISMS.1 Anforderungen — excluding either would be wrong). Layer 1
    # is different: an explicit, literal standard mention ("BSI-Standard 200-2") has
    # no ambiguity to hedge against, so it is applied as a hard filter on the main
    # query — same as an LLM-set standard_id. Without this, an unfiltered main query
    # can still surface generically high-scoring but topically unrelated chunks from
    # other standards that outscore and silently displace the correct standard's
    # content even after boosting (observed: "BSI-Standard 200-2" question, only 6
    # of 12 final hits were actually standard_200_2 despite Layer 1 firing).
    _routing_standard_id: str | None = None
    _routing_baustein_id: str | None = None
    _exclusive_standard_id: str | None = None

    if DOC_ROUTING_ENABLED and standard_id is None and baustein_id is None:
        # Routing always classifies on the raw query embedding, never on the HyDE
        # paraphrase. HyDE is a sampled LLM completion and can drift into a neighboring
        # topic's vocabulary (observed case: an "ISMS-Aufbau" question generated a HyDE
        # paragraph about "Schutzbedarfs-/Risikoanalyse", i.e. 200-2/200-3 vocabulary,
        # which then skewed the document-router score toward the wrong standard). Feeding
        # that drifted vector into the router would propagate the error into the scope
        # decision instead of correcting it. This decouples HYDE_ENABLED from routing
        # entirely: HyDE only ever affects the retrieval vector used for chunk search
        # below, never which document/Baustein gets detected.
        routing_vector = (await embed([query]))[0] if HYDE_ENABLED else vector

        # Layer 1: regex — explicit standard reference in query text → exclusive filter
        detected_std = detect_explicit_standard(query)
        if detected_std:
            _exclusive_standard_id = detected_std
            print(f"[ROUTING] layer1_regex → exclusive standard_id={detected_std}")
        else:
            # Layer 2: semantic document profile match → boost only
            detected_doc, _l2_best, _l2_score, _l2_gap = await detect_document_scope(
                query_vector=routing_vector,
                threshold=DOC_ROUTING_THRESHOLD,
                min_gap=DOC_ROUTING_GAP,
            )
            if detected_doc and detected_doc != "kompendium":
                _routing_standard_id = detected_doc
                print(f"[ROUTING] layer2_semantic → boost standard_id={detected_doc}")

        # Layer 3: always runs alongside Layer 1/2 — not as fallback.
        # A question can span both a BSI standard and a Kompendium Baustein
        # (e.g. "ISMS-Prinzipien" → 200-1 text + ISMS.1 Anforderungen).
        if BAUSTEIN_ROUTING_ENABLED:
            detected_bausteine = await detect_baustein_scope(
                query_vector=routing_vector,
                threshold=BAUSTEIN_ROUTING_THRESHOLD,
            )
            if detected_bausteine:
                _routing_baustein_id = detected_bausteine[0]
                print(f"[ROUTING] layer3_baustein → boost baustein_id={_routing_baustein_id}")

    k = top_k or TOP_K
    print(
        "[DEBUG] retrieve",
        {
            "top_k": k,
            "source_scope": source_scope,
            "standard_id": standard_id,
            "baustein_id": baustein_id,
            "schicht_id": schicht_id,
            "_exclusive_standard_id": _exclusive_standard_id,
            "_routing_standard_id": _routing_standard_id,
            "_routing_baustein_id": _routing_baustein_id,
        },
    )

    # Main retrieval — exclusive filters: explicit LLM-set params take precedence,
    # Layer 1's exclusive standard_id (explicit literal mention) applies otherwise.
    points = _qdrant_query(
        vector, k,
        source_scope=source_scope,
        standard_id=standard_id or _exclusive_standard_id,
        baustein_id=baustein_id,
        schicht_id=schicht_id,
        include_vectors=include_vectors,
    )

    # Fallback: exclusive filter yielded nothing (stale metadata in older collections)
    if not points and (source_scope or standard_id or _exclusive_standard_id):
        print("[WARN] filtered_retrieval_empty_fallback_unfiltered", {"top_k": k})
        points = _qdrant_query(vector, k, include_vectors=include_vectors)

    # Blended supplements: inject routing-hint chunks without displacing main results.
    # Each supplement is deduplicated against already-seen point IDs. Up to boost_k
    # items per source get GUARANTEED slots (reserved, not score-competed) instead of
    # a pure score-sort-and-trim: the unfiltered main pool can contain generically
    # high-scoring but topically unrelated chunks (e.g. boilerplate sections shared
    # across BSI standards) that would otherwise outscore and silently displace the
    # exact routing target the boost was meant to guarantee — observed repeatedly in
    # TASK_13 testing (e.g. a clearly-won standard_200_1 match still ended up only 3
    # of 10 final hits after a plain score-sort-and-trim merge).
    seen_ids: set[Any] = {p.id for p in points}
    boost_groups: list[list[Any]] = []
    boost_k = max(k // 2, 3)

    if _routing_standard_id:
        std_pts = _qdrant_query(
            vector, boost_k,
            source_scope=source_scope,
            standard_id=_routing_standard_id,
            include_vectors=include_vectors,
        )
        new = [p for p in std_pts if p.id not in seen_ids]
        if new:
            print(f"[ROUTING] blend_standard: +{len(new)} from {_routing_standard_id}")
            seen_ids.update(p.id for p in new)
            boost_groups.append(new)

    if _routing_baustein_id and baustein_id is None:
        bas_pts = _qdrant_query(
            vector, boost_k,
            source_scope=source_scope,
            baustein_id=_routing_baustein_id,
            include_vectors=include_vectors,
        )
        new = [p for p in bas_pts if p.id not in seen_ids]
        if new:
            print(f"[ROUTING] blend_baustein: +{len(new)} from {_routing_baustein_id}")
            seen_ids.update(p.id for p in new)
            boost_groups.append(new)

    if boost_groups:
        guaranteed: list[Any] = []
        for group in boost_groups:
            guaranteed.extend(sorted(group, key=lambda p: p.score, reverse=True)[:boost_k])
        # Safety cap: with a small k and both boosts firing simultaneously,
        # guaranteed slots alone could otherwise exceed k.
        guaranteed = sorted(guaranteed, key=lambda p: p.score, reverse=True)[:k]
        guaranteed_ids = {p.id for p in guaranteed}
        remaining_pool = [p for p in points if p.id not in guaranteed_ids]
        remaining = sorted(remaining_pool, key=lambda p: p.score, reverse=True)[: max(k - len(guaranteed), 0)]
        points = sorted(guaranteed + remaining, key=lambda p: p.score, reverse=True)

    hits: list[RagResult] = []
    for hit in points:
        payload = dict(hit.payload or {})
        text = _extract_text(payload)
        if not text:
            continue
        # Store embedding vector if requested (for personalization scoring)
        if include_vectors and hit.vector is not None:
            if isinstance(hit.vector, list):
                payload["_embedding"] = hit.vector
        hits.append(
            RagResult(
                text=_clean_text(text),
                score=float(hit.score),
                metadata=payload,
            )
        )
    return hits


async def personalized_retrieve(
    query: str,
    user_profile: "UserProfile | None",
    balance: float = 1.0,
    top_k: int | None = None,
    *,
    source_scope: str | None = None,
    standard_id: str | None = None,
) -> list[RagResult]:
    """Retrieve documents. Personalization (keyword-based filtering) has been
    removed — retrieval always uses standard semantic search.

    Keywords now only influence the system prompt ('Bezug zu Ihren Interessen'
    section), not chunk retrieval or scoring.

    Args:
        query: Search query text
        user_profile: User profile (unused for retrieval, kept for API compat)
        balance: Unused, kept for API compatibility
        top_k: Number of results to return
        source_scope: Optional filter by source scope
        standard_id: Optional filter by standard ID

    Returns:
        List of RagResult objects
    """
    return await retrieve(
        query, top_k, source_scope=source_scope, standard_id=standard_id
    )


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
        lines.append(line)
    return "\n".join(lines)
