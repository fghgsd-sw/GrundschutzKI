from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import bcrypt
import chainlit as cl
from chainlit.auth import get_current_user
from chainlit.types import Starter
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chat_history import (
    add_chat_message,
    create_chat_session,
    export_all_sessions_openai_jsonl,
    export_session_openai_json,
    get_session_messages,
    init_chat_db,
    list_chat_sessions,
    set_session_title_if_missing,
)
from llm import chat, message_to_dict
from native_chat import (
    check_user_exists,
    create_user,
    ensure_native_schema,
    export_all_chats_zip,
    get_user_by_identifier,
)
from rag_tool import build_context, extract_page, extract_source_file, format_citations, retrieve
from settings import (
    CHAT_DB_PATH,
    CHAT_EXPORT_DIR,
    CHAINLIT_AUTH_PASSWORD,
    CHAINLIT_AUTH_USERNAME,
    CHAINLIT_INIT_DB,
    DATA_RAW_DIR,
    DATABASE_URL,
    EMBED_MODEL,
    MAX_TOP_K,
    MAX_SOURCE_LINKS,
    STARTER_QUESTIONS,
    SYSTEM_PROMPT_PATH,
    TOP_K,
)


def _load_system_prompt(path: Path) -> str | None:
    if path.is_file():
        content = path.read_text(encoding="utf-8").strip()
        return content or None
    return None


SYSTEM_PROMPT = _load_system_prompt(SYSTEM_PROMPT_PATH)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "rag_retrieve",
            "description": "Suche relevante Dokumente in der Wissensbasis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Die Nutzerfrage oder Suchanfrage."},
                    "top_k": {"type": "integer", "description": "Anzahl der Treffer.", "default": 5},
                },
                "required": ["query"],
            },
        },
    }
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _truncate(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _current_chat_session_id() -> str | None:
    value = cl.user_session.get("chat_history_session_id")
    return value if isinstance(value, str) and value.strip() else None


def _format_history_overview(limit: int = 15) -> str:
    sessions = list_chat_sessions(CHAT_DB_PATH, limit=limit)
    if not sessions:
        return "Keine gespeicherten Chats gefunden."
    lines = ["## Gespeicherte Chats", ""]
    for item in sessions:
        lines.append(
            "- "
            f"`{item['id']}` | {item['title']} | {item['message_count']} Nachrichten | "
            f"zuletzt: {item['updated_at']}"
        )
    lines.append("")
    lines.append("Nutze `/history <session_id>` für den Verlauf oder `/export <session_id>` für JSON.")
    return "\n".join(lines)


def _format_session_messages(session_id: str, limit: int = 20) -> str:
    messages = get_session_messages(CHAT_DB_PATH, session_id)
    if not messages:
        return f"Keine Nachrichten für Session `{session_id}` gefunden."
    tail = messages[-limit:]
    lines = [f"## Verlauf `{session_id}` (letzte {len(tail)} Nachrichten)", ""]
    for msg in tail:
        role = msg.get("role", "unknown")
        content = _truncate(str(msg.get("content", "")), max_len=280)
        created_at = msg.get("created_at", "")
        lines.append(f"- **{role}** ({created_at}): {content}")
    return "\n".join(lines)


async def _handle_control_message(message: cl.Message) -> bool:
    text = (message.content or "").strip()
    if not text.startswith("/"):
        return False

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/history":
        if arg:
            await cl.Message(content=_format_session_messages(arg)).send()
        else:
            await cl.Message(content=_format_history_overview()).send()
        return True

    if cmd == "/export":
        CHAT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _utc_stamp()
        if arg.lower() == "all":
            out_jsonl = CHAT_EXPORT_DIR / f"chat-export-openai-all-{stamp}.jsonl"
            export_all_sessions_openai_jsonl(CHAT_DB_PATH, out_jsonl)
            await cl.Message(
                content="OpenAI-Export für alle Chats erstellt (JSONL).",
                elements=[
                    cl.File(name=out_jsonl.name, path=str(out_jsonl), display="inline"),
                ],
            ).send()
            return True

        session_id = arg or _current_chat_session_id()
        if not session_id:
            await cl.Message(content="Keine aktive Session gefunden. Nutze `/export <session_id>` oder `/export all`.").send()
            return True
        out_json = CHAT_EXPORT_DIR / f"chat-export-openai-{session_id}-{stamp}.json"
        try:
            export_session_openai_json(CHAT_DB_PATH, session_id, out_json)
        except ValueError:
            await cl.Message(content=f"Session nicht gefunden: `{session_id}`").send()
            return True
        await cl.Message(
            content=f"OpenAI-Export erstellt für Session `{session_id}`.",
            elements=[cl.File(name=out_json.name, path=str(out_json), display="inline")],
        ).send()
        return True

    if cmd in {"/help-history", "/help"}:
        await cl.Message(
            content=(
                "Verfügbare Befehle:\n"
                "- `/history` zeigt gespeicherte Chats\n"
                "- `/history <session_id>` zeigt die letzten Nachrichten einer Session\n"
                "- `/export` exportiert den aktuellen Chat im OpenAI-Format (JSON)\n"
                "- `/export <session_id>` exportiert eine bestimmte Session im OpenAI-Format (JSON)\n"
                "- `/export all` exportiert alle Chats im OpenAI-Format (JSONL)"
            )
        ).send()
        return True

    return False

def _first_sentence(text: str, max_len: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
    sentence = parts[0]
    if len(sentence) > max_len:
        sentence = sentence[: max_len - 3].rstrip() + "..."
    return sentence


def _extractive_answer_from_results(question: str, results: list[Any], max_points: int = 5) -> str:
    if not results:
        return "Im bereitgestellten Kontext nicht enthalten"

    seen: set[str] = set()
    bullets: list[str] = []
    for idx, result in enumerate(results, start=1):
        if len(bullets) >= max_points:
            break
        sentence = _first_sentence(getattr(result, "text", "") or "", max_len=280)
        if not sentence:
            continue
        key = re.sub(r"\s+", " ", sentence).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(f"- {sentence} [{idx}]")

    if not bullets:
        bullets = [
            f"- {(getattr(r, 'text', '') or '').strip()[:220]} [{i}]"
            for i, r in enumerate(results[:max_points], start=1)
            if (getattr(r, "text", "") or "").strip()
        ]
    if not bullets:
        bullets = ["- Relevante Fundstellen vorhanden, aber kein extrahierbarer Kurzsatz. [1]"]

    return (
        f"Ich habe relevante Inhalte im Kontext zur Frage \"{question}\" gefunden.\n\n"
        "Kernaussagen aus den Trefferstellen:\n"
        + "\n".join(bullets)
    )


def _strip_model_source_blocks(text: str) -> str:
    text = text.rstrip()
    patterns = [
        r"\n+\*\*Quellen\*\*[\s\S]*$",
        r"\n+Quellen[\s\S]*$",
        r"\n+Sources[\s\S]*$",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).rstrip()
    return text


def _page_label(page_start: int | None, page_end: int | None) -> str:
    # Very large ranges are usually fallback mappings; show a compact page anchor.
    if page_start and page_end and page_end >= page_start and (page_end - page_start) > 60:
        return f"S.{page_start}+"
    if page_start and page_end and page_end != page_start:
        return f"S.{page_start}-{page_end}"
    if page_start:
        return f"S.{page_start}"
    return "S.?"


def _source_alias(index: int, section_title: str | None, page_start: int | None, page_end: int | None) -> str:
    section = (section_title or "Abschnitt unbekannt").strip()
    section = re.sub(r"\s+", " ", section)
    if len(section) > 48:
        section = section[:45].rstrip() + "..."
    return f"Quelle {index}: {section} ({_page_label(page_start, page_end)})"


def _resolve_section_title(metadata: dict[str, Any]) -> str | None:
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


def _inject_clickable_refs(text: str, alias_by_index: dict[int, str]) -> str:
    if not text or not alias_by_index:
        return text

    def repl(match: re.Match) -> str:
        idx = int(match.group(1))
        alias = alias_by_index.get(idx)
        if not alias:
            return match.group(0)
        return alias

    # Covers citations like: 【1†L1-L4】 and [1†L1-L4]
    text = re.sub(r"【(\d+)[^】]*】", repl, text)
    text = re.sub(r"\[(\d+)†[^\]]*\]", repl, text)
    # Covers citations like: [1]
    text = re.sub(r"\[(\d+)\]", repl, text)
    return text


def _inject_named_source_refs(
    text: str,
    source_rows: list[tuple[int, str, str, int | None, int | None, str | None, str]],
) -> str:
    if not text or not source_rows:
        return text

    def norm(s: str) -> str:
        s = s.lower()
        s = re.sub(r"[^a-z0-9äöüß]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    entries = []
    for _, alias, file_name, page_start, page_end, section_title, _ in source_rows:
        file_stem = file_name.lower().removesuffix(".pdf")
        entries.append(
            {
                "alias": alias,
                "file_stem": norm(file_stem),
                "section": norm(section_title or ""),
                "page_start": page_start,
                "page_end": page_end,
                "is_kompendium": "kompendium" in file_stem,
            }
        )

    def replace_bracket(match: re.Match) -> str:
        raw = match.group(1).strip()
        # Keep pure numeric references for the numeric pass.
        if re.fullmatch(r"\d+", raw):
            return match.group(0)
        if "quelle " in raw.lower():
            return match.group(0)

        rnorm = norm(raw)
        if not rnorm:
            return match.group(0)

        page_match = re.search(r"(?:s\.?|seite)\s*(\d+)", raw, flags=re.IGNORECASE)
        wanted_page = int(page_match.group(1)) if page_match else None

        best_alias = None
        best_score = 0
        for entry in entries:
            score = 0
            if entry["file_stem"] and entry["file_stem"] in rnorm:
                score += 4
            if entry["section"] and any(tok in rnorm for tok in entry["section"].split()[:4]):
                score += 2
            if "kompendium" in rnorm and entry["is_kompendium"]:
                score += 2
            if "standard 200 2" in rnorm and "standard 200 2" in entry["file_stem"]:
                score += 3
            if wanted_page is not None:
                start = entry["page_start"]
                end = entry["page_end"] or start
                if isinstance(start, int) and isinstance(end, int) and start <= wanted_page <= end:
                    score += 2
            if score > best_score:
                best_score = score
                best_alias = entry["alias"]

        return best_alias if best_alias and best_score >= 3 else match.group(0)

    return re.sub(r"\[([^\[\]]{3,140})\]", replace_bracket, text)


def _normalize_source_alias_mentions(text: str, alias_by_index: dict[int, str]) -> str:
    if not text or not alias_by_index:
        return text

    def repl(match: re.Match) -> str:
        idx = int(match.group(1))
        return alias_by_index.get(idx, match.group(0))

    # Normalize free-form mentions like
    # "Quelle 1: APP.3.2.A20 ... (S) [Zentrale Verwaltung] (S.397)" or
    # "Quelle 2: Einleitung ... (Seite 12)" to exact alias token.
    text = re.sub(
        r"Quelle\s*([0-9]+)\s*:\s*[^\n]*?\((?:S\.?|Seite)\s*[^)\n]+\)",
        repl,
        text,
        flags=re.IGNORECASE,
    )
    # Also normalize bracket-wrapped alias mentions so they become clickable tokens.
    text = re.sub(
        r"【\s*Quelle\s*([0-9]+)\s*:\s*[^】]+\s*】",
        repl,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[\s*Quelle\s*([0-9]+)\s*:\s*[^\]]+\s*\]",
        repl,
        text,
        flags=re.IGNORECASE,
    )
    # Normalize plain mentions like "Quelle 2" (without trailing ": ...").
    text = re.sub(
        r"\bQuelle\s*([0-9]+)\b(?!\s*:)",
        repl,
        text,
        flags=re.IGNORECASE,
    )
    return text


def _normalize_source_mentions_by_content(
    text: str,
    source_rows: list[tuple[int, str, str, int | None, int | None, str | None, str]],
) -> str:
    if not text or not source_rows:
        return text

    def norm(s: str) -> str:
        s = s.lower()
        s = re.sub(r"[^a-z0-9äöüß]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    entries = []
    for _, alias, _, page_start, page_end, section_title, _ in source_rows:
        entries.append(
            {
                "alias": alias,
                "section": norm(section_title or ""),
                "page_start": page_start,
                "page_end": page_end,
            }
        )

    def repl(match: re.Match) -> str:
        raw = match.group(0)
        page_match = re.search(r"(?:S\.?|Seite)\s*(\d+)", raw, flags=re.IGNORECASE)
        wanted_page = int(page_match.group(1)) if page_match else None
        rnorm = norm(raw)

        best_alias = None
        best_score = 0
        for entry in entries:
            score = 0
            if wanted_page is not None:
                start = entry["page_start"]
                end = entry["page_end"] or start
                if isinstance(start, int) and isinstance(end, int) and start <= wanted_page <= end:
                    score += 3
            if entry["section"] and any(tok in rnorm for tok in entry["section"].split()[:5]):
                score += 2
            if score > best_score:
                best_score = score
                best_alias = entry["alias"]

        return best_alias if best_alias and best_score >= 2 else raw

    return re.sub(
        r"Quelle\s*\d+\s*:\s*[^\n]{1,260}?\((?:S\.?|Seite)\s*[^)\n]+\)",
        repl,
        text,
        flags=re.IGNORECASE,
    )


def _desired_source_count(text: str, available: int) -> int:
    if available <= 0:
        return 0
    refs: list[int] = []
    for pattern in (
        r"\[(\d+)\]",
        r"【(\d+)[^】]*】",
        r"\[(\d+)†[^\]]*\]",
        r"Quelle\s*(\d+)\s*:",
        r"\bQuelle\s*(\d+)\b",
    ):
        refs.extend(int(x) for x in re.findall(pattern, text or ""))
    if refs:
        return min(max(refs), available)
    return available


def _top_score(results: list[Any]) -> float:
    return max((float(getattr(r, "score", 0.0) or 0.0) for r in results), default=0.0)


def _is_weak_retrieval(results: list[Any], *, min_hits: int = 2, min_top_score: float = 0.22) -> bool:
    return len(results) < min_hits or _top_score(results) < min_top_score


def _is_strong_retrieval(results: list[Any], *, min_hits: int = 3, min_top_score: float = 0.45) -> bool:
    return len(results) >= min_hits and _top_score(results) >= min_top_score


def _is_context_abstention(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "")).strip().lower().rstrip(".!")
    if not normalized:
        return False
    if normalized.startswith("im bereitgestellten kontext nicht enthalten"):
        return True
    # Catch common model variants like "Die Information ist ... nicht enthalten."
    return "bereitgestellten kontext" in normalized and "nicht enthalten" in normalized


def _extract_standard_id(query: str) -> str | None:
    q = (query or "").lower()
    m = re.search(r"\b(?:bsi[- ]?standard\s*)?200[- ]?([1-4])\b", q)
    if not m:
        return None
    return f"standard_200_{m.group(1)}"


def _normalize_query_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _keyword_query_variant(query: str) -> str | None:
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß0-9.\-]+", query or "")
    if not tokens:
        return None
    stopwords = {
        "welche",
        "welcher",
        "welches",
        "wie",
        "was",
        "sind",
        "ist",
        "der",
        "die",
        "das",
        "bei",
        "für",
        "im",
        "in",
        "nach",
        "und",
        "oder",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einer",
        "sinnvoll",
        "grundsätzlich",
    }
    kept = [t for t in tokens if len(t) > 2 and t.lower() not in stopwords]
    if len(kept) < 2:
        return None
    return " ".join(kept)


def _extract_baustein_id(query: str) -> str | None:
    m = re.search(r"\b([A-Z]{2,4}\.\d+(?:\.\d+){1,2})\b", (query or "").upper())
    if not m:
        return None
    return m.group(1)


def _build_query_variants(query: str, standard_id: str | None) -> list[str]:
    base = _normalize_query_text(query)
    if not base:
        return []

    variants: list[str] = [base]
    lower = base.lower()
    keyword_variant = _keyword_query_variant(base)

    if standard_id:
        std_label = standard_id.replace("standard_", "BSI-Standard ").replace("_", "-")
        if "basis-absicherung" in lower or "basis absicherung" in lower:
            variants.append(f"{std_label} Basis-Absicherung Schritte Vorgehensweise")
        if keyword_variant:
            variants.append(f"{std_label} {keyword_variant}")
    else:
        elevated_need = ("erhöht" in lower or "erhoeh" in lower) and "schutzbedarf" in lower
        if elevated_need:
            variants.append(f"{base} (H) Anforderungen bei erhöhtem Schutzbedarf")
            baustein_id = _extract_baustein_id(base)
            if not baustein_id and "webserver" in lower:
                baustein_id = "APP.3.2"
            if baustein_id:
                variants.append(f"{baustein_id} Anforderungen bei erhöhtem Schutzbedarf (H) Redundanz DDoS")
            else:
                variants.append("Anforderungen bei erhöhtem Schutzbedarf (H) Maßnahmen")
        elif keyword_variant:
            variants.append(f"IT-Grundschutz {keyword_variant}")

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in variants:
        normalized = _normalize_query_text(candidate)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= 3:
            break
    return deduped


def _result_key(item: Any) -> tuple[str, int | None, str]:
    metadata = getattr(item, "metadata", {}) or {}
    file_name = extract_source_file(metadata) or ""
    page = extract_page(metadata)
    snippet = re.sub(r"\s+", " ", (getattr(item, "text", "") or "").strip())[:120]
    return (file_name, page, snippet)


def _fuse_results(result_sets: list[list[Any]], max_items: int) -> list[Any]:
    fused: dict[tuple[str, int | None, str], dict[str, Any]] = {}
    for results in result_sets:
        for rank, item in enumerate(results, start=1):
            key = _result_key(item)
            score = float(getattr(item, "score", 0.0) or 0.0)
            state = fused.get(key)
            if state is None:
                state = {"item": item, "rrf": 0.0, "hits": 0, "best_score": score}
                fused[key] = state
            state["rrf"] += 1.0 / (60.0 + rank)
            state["hits"] += 1
            if score > state["best_score"]:
                state["item"] = item
                state["best_score"] = score

    ranked = sorted(
        fused.values(),
        key=lambda s: (float(s["rrf"]), int(s["hits"]), float(s["best_score"])),
        reverse=True,
    )
    return [entry["item"] for entry in ranked[:max_items]]


async def _retrieve_fused(
    *,
    query: str,
    top_k: int,
    source_scope: str | None,
    standard_id: str | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    variants = _build_query_variants(query, standard_id)
    if not variants:
        return [], []

    result_sets: list[list[Any]] = []
    variant_stats: list[dict[str, Any]] = []
    for v in variants:
        hits = await retrieve(
            query=v,
            top_k=top_k,
            source_scope=source_scope,
            standard_id=standard_id,
        )
        result_sets.append(hits)
        variant_stats.append(
            {
                "query": v,
                "hits": len(hits),
                "top_score": round(_top_score(hits), 4),
            }
        )

    fused = _fuse_results(result_sets, max_items=top_k)
    print(
        "[DEBUG] retrieve_fused",
        {
            "source_scope": source_scope,
            "standard_id": standard_id,
            "variants": len(variants),
            "variant_stats": variant_stats,
            "fused_hits": len(fused),
            "fused_top_score": _top_score(fused),
        },
    )
    return fused, variant_stats


def _merge_results(primary: list[Any], secondary: list[Any], max_items: int) -> list[Any]:
    merged: list[Any] = []
    seen: set[tuple[str, int | None, str]] = set()

    def key_for(item: Any) -> tuple[str, int | None, str]:
        return _result_key(item)

    for item in [*primary, *secondary]:
        k = key_for(item)
        if k in seen:
            continue
        seen.add(k)
        merged.append(item)
        if len(merged) >= max_items:
            break
    return merged


def _extract_followups(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if re.search(r"anschlussfragen|weitere fragen", line, flags=re.IGNORECASE):
            start_idx = i
            break
    if start_idx is None:
        return text, []

    questions: list[str] = []
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        raw = lines[j].strip()
        if not raw:
            if questions:
                end_idx = j
                break
            continue

        m = re.match(r"^(?:\d+[\).\:]|-|\*)\s+(.*)$", raw)
        candidate = m.group(1).strip() if m else raw
        candidate = re.sub(r"\s+", " ", candidate)
        # Prefer question-shaped lines, but keep numbered follow-ups even without '?'.
        if candidate.endswith("?") or re.match(r"^(?:\d+[\).\:]|-|\*)\s+", raw):
            questions.append(candidate)
        elif questions:
            end_idx = j
            break
        if len(questions) >= 3:
            end_idx = j + 1
            break

    # Fallback: collect up to 3 trailing numbered/bullet lines anywhere in the answer.
    if not questions:
        for raw in lines:
            m = re.match(r"^\s*(?:\d+[\).\:]|-|\*)\s+(.+)$", raw)
            if not m:
                continue
            candidate = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(candidate) < 12:
                continue
            questions.append(candidate)
            if len(questions) >= 3:
                break

    if not questions:
        return text, []

    cleaned_lines = lines[:start_idx] + lines[end_idx:]
    cleaned_text = "\n".join(cleaned_lines).strip()
    return cleaned_text, questions


def _coerce_step_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("content")
        if isinstance(text, str):
            return text
    return str(value)


<<<<<<< HEAD
def _coerce_step_metadata(step: dict[str, Any]) -> dict[str, Any]:
    raw = step.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}
=======
def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
>>>>>>> e915692 (feat(auth): add GitHub OAuth + PostgreSQL user persistence)


@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    # Try database authentication first (if DATABASE_URL is configured)
    if DATABASE_URL:
        user = await get_user_by_identifier(DATABASE_URL, username)
        if user and user.get("password_hash"):
            if _verify_password(password, user["password_hash"]):
                metadata = json.loads(user.get("metadata") or "{}")
                metadata["provider"] = "local"
                return cl.User(identifier=user["identifier"], metadata=metadata)
            return None  # Wrong password for existing user

    # Fallback to environment variable authentication (for backwards compatibility / admin)
    expected_user = CHAINLIT_AUTH_USERNAME or "admin"
    expected_password = CHAINLIT_AUTH_PASSWORD
    if expected_password and username == expected_user and password == expected_password:
        return cl.User(identifier=expected_user, metadata={"provider": "password", "role": "admin"})

    return None


@cl.oauth_callback
async def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: dict[str, str],
    default_user: cl.User,
) -> cl.User | None:
    """Handle OAuth login from GitHub."""
    if provider_id == "github":
        return cl.User(
            identifier=raw_user_data.get("login"),  # GitHub username
            metadata={
                "provider": "github",
                "name": raw_user_data.get("name"),
                "email": raw_user_data.get("email"),
                "avatar_url": raw_user_data.get("avatar_url"),
                "github_id": str(raw_user_data.get("id")),
            },
        )
    return None


@cl.on_app_startup
async def on_app_startup() -> None:
    print(
        "[STARTUP] system_prompt_path=",
        str(SYSTEM_PROMPT_PATH),
        "exists=",
        SYSTEM_PROMPT_PATH.is_file(),
        "loaded=",
        bool(SYSTEM_PROMPT),
    )
    print(
        "[STARTUP] retrieval_tuning",
        "embed_model=",
        EMBED_MODEL,
        "top_k=",
        TOP_K,
        "| mode: simple_docling",
    )
    from chainlit.server import app as chainlit_fastapi_app

    if DATABASE_URL and CHAINLIT_INIT_DB:
        await ensure_native_schema(DATABASE_URL)

    init_chat_db(CHAT_DB_PATH)
    CHAT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    if not DATABASE_URL:
        return

    if getattr(chainlit_fastapi_app.state, "native_export_route_added", False):
        return

    @chainlit_fastapi_app.get("/export/all-chats")
    async def export_all_chats(current_user=Depends(get_current_user)):
        if current_user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        user_id = getattr(current_user, "id", None)
        bundle = await export_all_chats_zip(
            database_url=DATABASE_URL,
            out_dir=CHAT_EXPORT_DIR,
            user_id=str(user_id) if user_id else None,
        )
        return FileResponse(path=str(bundle), media_type="application/zip", filename=bundle.name)

    # Registration endpoint for self-registration
    class RegisterRequest(BaseModel):
        username: str
        email: str
        password: str

    @chainlit_fastapi_app.post("/auth/register")
    async def register_user(request: RegisterRequest):
        # Validate input
        if not request.username or len(request.username) < 3:
            raise HTTPException(status_code=400, detail="Benutzername muss mindestens 3 Zeichen haben")
        if not request.email or "@" not in request.email:
            raise HTTPException(status_code=400, detail="Ungültige E-Mail-Adresse")
        if not request.password or len(request.password) < 8:
            raise HTTPException(status_code=400, detail="Passwort muss mindestens 8 Zeichen haben")

        # Check if user/email already exists
        exists = await check_user_exists(DATABASE_URL, request.username, request.email)
        if exists["username_exists"]:
            raise HTTPException(status_code=409, detail="Benutzername bereits vergeben")
        if exists["email_exists"]:
            raise HTTPException(status_code=409, detail="E-Mail-Adresse bereits registriert")

        # Create user with hashed password
        password_hash = _hash_password(request.password)
        user = await create_user(DATABASE_URL, request.username, request.email, password_hash)
        if user is None:
            raise HTTPException(status_code=500, detail="Registrierung fehlgeschlagen")

        return {"message": "Registrierung erfolgreich", "username": user["identifier"]}

    chainlit_fastapi_app.state.native_export_route_added = True
    print("[STARTUP] native export route registered at /export/all-chats")
    print("[STARTUP] registration route registered at /auth/register")


@cl.on_chat_resume
async def on_chat_resume(thread: dict[str, Any]):
    messages: list[dict[str, Any]] = []
    restored_panel_content: str | None = None
    restored_source_rows: list[dict[str, Any]] = []
    if SYSTEM_PROMPT:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})

    steps = thread.get("steps") or []
    sorted_steps = sorted(
        [s for s in steps if isinstance(s, dict)],
        key=lambda s: (s.get("start") or s.get("createdAt") or "", s.get("id") or ""),
    )
    for step in sorted_steps:
        step_type = str(step.get("type") or "").lower()
        if "user_message" in step_type:
            text = _coerce_step_text(step.get("output") or step.get("input"))
            if text:
                messages.append({"role": "user", "content": text})
        elif "assistant_message" in step_type:
            text = _coerce_step_text(step.get("output") or step.get("input"))
            if text:
                messages.append({"role": "assistant", "content": text})
            metadata = _coerce_step_metadata(step)
            panel_content = metadata.get("citation_panel_content")
            source_rows = metadata.get("citation_source_rows")
            if isinstance(panel_content, str) and panel_content.strip():
                restored_panel_content = panel_content
            if isinstance(source_rows, list):
                valid_rows: list[dict[str, Any]] = []
                for row in source_rows:
                    if isinstance(row, dict):
                        file_name = row.get("file")
                        alias = row.get("alias")
                        if isinstance(file_name, str) and isinstance(alias, str):
                            valid_rows.append(row)
                if valid_rows:
                    restored_source_rows = valid_rows

    cl.user_session.set("messages", messages)
    cl.user_session.set("citation_panel_content", restored_panel_content)
    cl.user_session.set("citation_source_rows", restored_source_rows)


@cl.on_chat_start
async def on_chat_start():
    session_id = str(uuid4())
    create_chat_session(
        CHAT_DB_PATH,
        session_id,
        metadata={"system_prompt_loaded": bool(SYSTEM_PROMPT)},
    )
    cl.user_session.set("chat_history_session_id", session_id)
    messages: list[dict[str, Any]] = []
    if SYSTEM_PROMPT:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
        add_chat_message(CHAT_DB_PATH, session_id, "system", SYSTEM_PROMPT)
    cl.user_session.set("messages", messages)


@cl.set_starters
async def set_starters() -> list[Starter]:
    starter_icons = [
        "/public/icons/shield.svg",
        "/public/icons/search.svg",
        "/public/icons/book.svg",
    ]
    starters: list[Starter] = []
    for i, q in enumerate(STARTER_QUESTIONS[:6]):
        starters.append(
            Starter(
                label=q if len(q) <= 70 else q[:67].rstrip() + "...",
                message=q,
                icon=starter_icons[i % len(starter_icons)],
            )
        )
    return starters


@cl.action_callback("open_source_pdf")
async def open_source_pdf(action: cl.Action):
    file_name = action.payload.get("file")
    page = action.payload.get("page")
    if not isinstance(file_name, str):
        return
    file_path = (DATA_RAW_DIR / file_name).resolve()
    if not file_path.exists():
        await cl.Message(content=f"Datei nicht gefunden: {file_name}").send()
        return

    pdf_name = f"{file_name} (S.{page})" if isinstance(page, int) else file_name
    element = cl.Pdf(name=pdf_name, path=str(file_path), page=page if isinstance(page, int) else 1, display="side")
    await cl.Message(content=f"Quelle geöffnet: {pdf_name}", elements=[element]).send()


@cl.action_callback("open_all_citations")
async def open_all_citations(action: cl.Action):
    panel_content = cl.user_session.get("citation_panel_content")
    source_rows = cl.user_session.get("citation_source_rows") or []
    if not isinstance(panel_content, str) or not panel_content.strip():
        await cl.Message(content="Keine Zitierungen verfügbar.").send()
        return

    elements: list[Any] = [cl.Text(name="CITATIONS_PANEL", content=panel_content, display="side")]
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        file_name = row.get("file")
        page = row.get("page")
        alias = row.get("alias")
        if not isinstance(file_name, str) or not isinstance(alias, str):
            continue
        file_path = (DATA_RAW_DIR / file_name).resolve()
        if not file_path.exists():
            continue
        elements.append(
            cl.Pdf(
                name=alias,
                path=str(file_path),
                page=page if isinstance(page, int) else 1,
                display="side",
            )
        )

    await cl.Message(content="Alle Zitierungen: CITATIONS_PANEL", elements=elements).send()


@cl.action_callback("ask_followup")
async def ask_followup(action: cl.Action):
    question = action.payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return
    await cl.Message(content=question, author="You", type="user_message").send()
    await main(cl.Message(content=question))


@cl.on_message
async def main(message: cl.Message):
    if await _handle_control_message(message):
        return

    messages = cl.user_session.get("messages") or []
    session_id = _current_chat_session_id()
    if not session_id:
        session_id = str(uuid4())
        create_chat_session(CHAT_DB_PATH, session_id)
        cl.user_session.set("chat_history_session_id", session_id)

    messages.append({"role": "user", "content": message.content})
    add_chat_message(CHAT_DB_PATH, session_id, "user", message.content)
    set_session_title_if_missing(CHAT_DB_PATH, session_id, _first_sentence(message.content, max_len=96))

    response = await chat(messages, tools=TOOLS, tool_choice="required")
    assistant_msg = response.choices[0].message
    print(
        "[DEBUG] first_call",
        "content_empty=",
        not bool(assistant_msg.content),
        "tool_calls=",
        bool(getattr(assistant_msg, "tool_calls", None)),
    )

    if not getattr(assistant_msg, "tool_calls", None):
        print("[WARN] first_call_without_tool_retrying")
        retry_messages = [
            *messages,
            {
                "role": "system",
                "content": "Rufe zuerst das Tool rag_retrieve auf, bevor du antwortest.",
            },
        ]
        retry_response = await chat(retry_messages, tools=TOOLS, tool_choice="required")
        retry_msg = retry_response.choices[0].message
        print(
            "[DEBUG] first_call_retry",
            "content_empty=",
            not bool(retry_msg.content),
            "tool_calls=",
            bool(getattr(retry_msg, "tool_calls", None)),
        )
        if getattr(retry_msg, "tool_calls", None):
            assistant_msg = retry_msg

    if getattr(assistant_msg, "tool_calls", None):
        citations_text: str | None = None
        last_results = []
        content = ""
        current_msg = assistant_msg
        aggregated_by_key: dict[tuple[str, int | None, str], Any] = {}
        cached_tool_payloads: dict[str, tuple[list[Any], dict[str, Any]]] = {}

        max_tool_rounds_raw = os.getenv("MAX_TOOL_CALL_ROUNDS", "12")
        try:
            max_tool_rounds = max(1, int(max_tool_rounds_raw))
        except ValueError:
            max_tool_rounds = 12
        tool_round = 0

        while getattr(current_msg, "tool_calls", None) and tool_round < max_tool_rounds:
            tool_round += 1
            messages.append(message_to_dict(current_msg))
            print(
                "[DEBUG] tool_round_start",
                "round=",
                tool_round,
                "tool_calls=",
                len(current_msg.tool_calls),
            )
            for tool_call in current_msg.tool_calls:
                function_name = getattr(getattr(tool_call, "function", None), "name", "")
                if function_name != "rag_retrieve":
                    tool_payload = {"error": f"Unsupported tool: {function_name}"}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(tool_payload, ensure_ascii=False),
                        }
                    )
                    continue

                args = json.loads(tool_call.function.arguments or "{}")
                query = str(args.get("query") or message.content or "")
                raw_top_k = args.get("top_k")
                try:
                    requested_top_k = int(raw_top_k) if raw_top_k is not None else TOP_K
                except (TypeError, ValueError):
                    requested_top_k = TOP_K
                top_k = max(1, min(requested_top_k, MAX_TOP_K))

                signature = f"{function_name}:{json.dumps({'query': query, 'top_k': top_k}, ensure_ascii=False, sort_keys=True)}"
                if signature in cached_tool_payloads:
                    results, tool_payload = cached_tool_payloads[signature]
                    with cl.Step(name="rag_retrieve", type="tool") as step:
                        step.input = {"query": query, "top_k": top_k, "cached": True}
                        step.output = {"hits": len(results), "cached": True}
                else:
                    with cl.Step(name="rag_retrieve", type="tool") as step:
                        step.input = {"query": query, "top_k": top_k}
                        results = await retrieve(query=query, top_k=top_k)
                        print(
                            "[DEBUG] rag_retrieve",
                            "hits=",
                            len(results),
                            "first_text_len=",
                            len(results[0].text) if results else 0,
                        )
                        step.output = {"hits": len(results)}

                    context = build_context(results)
                    citations_text = format_citations(results)
                    tool_payload = {
                        "query": query,
                        "context": context,
                        "citations": citations_text,
                    }
                    cached_tool_payloads[signature] = (results, tool_payload)

                for item in results:
                    key = _result_key(item)
                    existing = aggregated_by_key.get(key)
                    if existing is None:
                        aggregated_by_key[key] = item
                        continue
                    if float(getattr(item, "score", 0.0) or 0.0) > float(getattr(existing, "score", 0.0) or 0.0):
                        aggregated_by_key[key] = item

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_payload, ensure_ascii=False),
                    }
                )
                add_chat_message(
                    CHAT_DB_PATH,
                    session_id,
                    "tool",
                    json.dumps(tool_payload, ensure_ascii=False),
                    metadata={"tool_name": "rag_retrieve"},
                )

            followup = await chat(messages, tools=TOOLS, tool_choice="auto")
            current_msg = followup.choices[0].message
            print(
                "[DEBUG] tool_round_followup",
                "round=",
                tool_round,
                "content_empty=",
                not bool(current_msg.content),
                "tool_calls=",
                bool(getattr(current_msg, "tool_calls", None)),
            )

        last_results = sorted(
            aggregated_by_key.values(),
            key=lambda r: float(getattr(r, "score", 0.0) or 0.0),
            reverse=True,
        )

        if getattr(current_msg, "tool_calls", None):
            # Safety stop: avoid endless tool loops, force final answer from collected context.
            print(
                "[WARN] tool_round_limit_reached",
                "max_tool_rounds=",
                max_tool_rounds,
                "aggregated_hits=",
                len(last_results),
            )
            final_context = build_context(last_results[: max(TOP_K, 8)])
            forced_messages = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Erstelle jetzt die finale Antwort ausschließlich aus dem Kontext. "
                        "Keine weiteren Tool-Aufrufe."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Frage: {message.content}\n\n"
                        f"Kontext:\n{final_context}\n\n"
                        "Antworte auf Deutsch mit Quellenhinweisen [1], [2], ..."
                    ),
                },
            ]
            forced_final = await chat(forced_messages)
            forced_final_msg = forced_final.choices[0].message
            content = forced_final_msg.content or ""
        else:
            content = current_msg.content or ""

        if not content.strip():
            if last_results:
                content = _extractive_answer_from_results(message.content, last_results)
            else:
                content = "Im bereitgestellten Kontext nicht enthalten"

        content = _strip_model_source_blocks(content)

        elements = []

        # Attach local PDFs as clickable page-specific links.
        seen_links: set[tuple[str, int | None]] = set()
        source_rows: list[tuple[int, str, str, int | None, int | None, str | None, str]] = []
        alias_by_index: dict[int, str] = {}
        source_rows_for_session: list[dict[str, Any]] = []
        desired_sources = _desired_source_count(content, len(last_results))
        if MAX_SOURCE_LINKS > 0:
            desired_sources = min(desired_sources, MAX_SOURCE_LINKS)
        link_counter = 1
        for idx, result in enumerate(last_results, start=1):
            file_name = extract_source_file(result.metadata)
            if not file_name:
                continue
            page = extract_page(result.metadata)
            key = (file_name, page)
            if key in seen_links:
                existing_alias = next((alias for _, alias, fname, pstart, _, _, _ in source_rows if fname == file_name and pstart == page), None)
                if existing_alias:
                    alias_by_index[idx] = existing_alias
                continue
            file_path = (DATA_RAW_DIR / file_name).resolve()
            if file_path.exists():
                page_end = result.metadata.get("page_end") if isinstance(result.metadata.get("page_end"), int) else None
                section_title = _resolve_section_title(result.metadata)
                page_start = extract_page(result.metadata)
                alias = _source_alias(link_counter, section_title, page_start, page_end)
                elements.append(cl.Pdf(name=alias, path=str(file_path), page=page, display="side"))
                alias_by_index[idx] = alias
                source_rows.append(
                    (
                        idx,
                        alias,
                        file_name,
                        page_start,
                        page_end,
                        section_title,
                        _first_sentence(result.text),
                    )
                )
                source_rows_for_session.append({"alias": alias, "file": file_name, "page": page})
                link_counter += 1
                seen_links.add(key)
            if desired_sources and len(seen_links) >= desired_sources:
                break

        # Make in-text citations clickable (supports [1], [1†...], 【1†...】).
        content = _inject_clickable_refs(content, alias_by_index)
        # Also map named refs like [standard_200_2.pdf, S. 2] to known source aliases.
        content = _inject_named_source_refs(content, source_rows)
        # Normalize model-written "Quelle n: ..." strings to exact alias values.
        content = _normalize_source_alias_mentions(content, alias_by_index)
        # Fallback: if model index does not match retrieved order, map by title/page similarity.
        content = _normalize_source_mentions_by_content(content, source_rows)

        # Build a detailed source block for the citation panel.
        detail_block = ""
        if source_rows:
            box_lines = ["## Quellen & Belegstellen", ""]
            for src_idx, alias, file_name, page_start, page_end, section_title, evidence in source_rows:
                page_label = _page_label(page_start, page_end)
                section_label = section_title or "Abschnitt unbekannt"
                box_lines.append(f"### [{src_idx}] {alias}")
                box_lines.append(f"- Datei: `{file_name}`")
                box_lines.append(f"- Seiten: {page_label}")
                box_lines.append(f"- Abschnitt: {section_label}")
                if evidence:
                    box_lines.append(f"- Belegsnippet: \"{evidence}\"")
                box_lines.append("")
            detail_block = "\n".join(box_lines)

        # Put only the detailed evidence list into a separate side panel.
        citation_panel_content = detail_block
        if citation_panel_content:
            elements.append(cl.Text(name="CITATIONS_PANEL", content=citation_panel_content, display="side"))
            cl.user_session.set("citation_panel_content", citation_panel_content)
            cl.user_session.set("citation_source_rows", source_rows_for_session)
        else:
            cl.user_session.set("citation_panel_content", None)
            cl.user_session.set("citation_source_rows", [])

        content, followups = _extract_followups(content)
        render_content = content
        if citation_panel_content and "Zitationsfenster: CITATIONS_PANEL" not in render_content:
            render_content = f"{render_content}\n\nZitationsfenster: CITATIONS_PANEL"
        actions: list[cl.Action] = []
        for question in followups:
            actions.append(
                cl.Action(
                    name="ask_followup",
                    label=question,
                    tooltip=question,
                    payload={"question": question},
                )
            )
        print("[DEBUG] followup_actions=", len(followups), "total_actions=", len(actions))
        message_metadata: dict[str, Any] = {
            "has_citations_panel": bool(citation_panel_content),
            "followup_count": len(followups),
        }
        if citation_panel_content:
            message_metadata["citation_panel_content"] = citation_panel_content
            message_metadata["citation_source_rows"] = source_rows_for_session

        await cl.Message(
            content=render_content,
            elements=elements or None,
            actions=actions,
            metadata=message_metadata,
        ).send()
        messages.append({"role": "assistant", "content": content})
        add_chat_message(
            CHAT_DB_PATH,
            session_id,
            "assistant",
            content,
            metadata=message_metadata,
        )
    else:
        content = assistant_msg.content or ""
        content, followups = _extract_followups(content)
        actions: list[cl.Action] = []
        for question in followups:
            actions.append(
                cl.Action(
                    name="ask_followup",
                    label=question,
                    tooltip=question,
                    payload={"question": question},
                )
            )
        await cl.Message(content=content, actions=actions or None).send()
        messages.append({"role": "assistant", "content": content})
        add_chat_message(
            CHAT_DB_PATH,
            session_id,
            "assistant",
            content,
            metadata={"followup_count": len(followups)},
        )

    cl.user_session.set("messages", messages)
