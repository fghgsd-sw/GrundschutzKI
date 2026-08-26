"""
TASK_14: Batch-Messung der Citation-Judge-Fehlerquote.

Schickt eine Stichprobe von Fragen (einfach + komplex) durch die reale
Produktions-Pipeline (system.md + Tool-Loop + retrieve() + Zitations-
Nachbearbeitung) und aggregiert die Phase-3-Judge-Ergebnisse.

Wichtig: importiert die Pipeline-Bausteine direkt aus apps/chainlit/app.py
(SYSTEM_PROMPT, TOOLS, _canonicalize_citations, _extract_claim_source_pairs,
_judge_citation_support, ...) statt sie nachzubauen — nur die Chainlit-UI-
Schicht (Streaming, cl.Step, DB-Persistenz) wird durch einen minimalen
Tool-Loop ersetzt, da diese Teile die Zitat-Qualität nicht beeinflussen.

Nutzung:
    cd scripts && ../.venv/bin/python3 measure_citation_judge.py
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import random
import sys
from pathlib import Path

# Läuft sowohl direkt auf dem Host (Repo-relative Pfade) als auch per
# `docker compose exec chainlit python3 ...` innerhalb des gski-chainlit-
# Containers (dort: /app = apps/chainlit, /data = data/, siehe docker-compose.yml).
if Path("/app/app.py").is_file() and Path("/data").is_dir():
    CHAINLIT_DIR = Path("/app")
    DATA_ROOT = Path("/data")
else:
    CHAINLIT_DIR = Path(__file__).resolve().parent.parent / "apps" / "chainlit"
    DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

sys.path.insert(0, str(CHAINLIT_DIR))

import app as gski_app  # noqa: E402
from llm import chat, message_to_dict  # noqa: E402
from rag_tool import (  # noqa: E402
    build_context,
    extract_page,
    extract_source_file,
    format_citations,
    resolve_section_title,
    retrieve,
)
from settings import MAX_TOP_K, TOP_K, WEAK_RETRIEVAL_HINT_THRESHOLD  # noqa: E402

DATA_DIR = DATA_ROOT / "data_evaluation"
EINFACH_CSV = DATA_DIR / "GSKI_Fragen-Antworten-Fundstellen_123_Einfach.csv"
KOMPLEX_CSV = DATA_DIR / "GSKI_Fragen-Antworten-Fundstellen_43_Komplex.csv"
OUT_PATH = DATA_ROOT / "results" / "citation_judge_measurement.json"

N_EINFACH = 10
N_KOMPLEX = 10
SEED = 42


def _load_questions(csv_path: Path, n: int) -> list[str]:
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        questions = [row["Frage"].strip() for row in reader if row.get("Frage", "").strip()]
    random.Random(SEED).shuffle(questions)
    return questions[:n]


async def _run_tool_loop(question: str) -> list:
    """Minimaler, headless Nachbau des Tool-Loops aus app.py main() —
    identische Kernlogik (System-Prompt, TOOLS, retrieve(), hinweis-Feld,
    round-übergreifende Score-Aggregation), ohne UI/Streaming/Persistenz.
    """
    messages = [
        {"role": "system", "content": gski_app.SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    response = await chat(messages, tools=gski_app.TOOLS, tool_choice="required")
    assistant_msg = response.choices[0].message

    if not getattr(assistant_msg, "tool_calls", None):
        retry_messages = [
            *messages,
            {"role": "system", "content": "Rufe zuerst das Tool rag_retrieve auf, bevor du antwortest."},
        ]
        retry_response = await chat(retry_messages, tools=gski_app.TOOLS, tool_choice="required")
        retry_msg = retry_response.choices[0].message
        if getattr(retry_msg, "tool_calls", None):
            assistant_msg = retry_msg

    aggregated_by_key: dict = {}
    current_msg = assistant_msg
    tool_round = 0
    try:
        max_tool_rounds = max(1, int(os.getenv("MAX_TOOL_CALL_ROUNDS", "12")))
    except ValueError:
        max_tool_rounds = 12

    while getattr(current_msg, "tool_calls", None) and tool_round < max_tool_rounds:
        tool_round += 1
        messages.append(message_to_dict(current_msg))
        for tool_call in current_msg.tool_calls:
            function_name = getattr(getattr(tool_call, "function", None), "name", "")
            if function_name != "rag_retrieve":
                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps({"error": "unsupported"})}
                )
                continue

            args = json.loads(tool_call.function.arguments or "{}")
            query = str(args.get("query") or question)
            if gski_app._BARE_ID_QUERY_RE.match(query.strip()):
                query = question

            raw_top_k = args.get("top_k")
            try:
                requested_top_k = int(raw_top_k) if raw_top_k is not None else TOP_K
            except (TypeError, ValueError):
                requested_top_k = TOP_K
            top_k = max(1, min(requested_top_k, MAX_TOP_K))

            raw_baustein_id = args.get("baustein_id")
            baustein_id = raw_baustein_id.strip() if isinstance(raw_baustein_id, str) and raw_baustein_id.strip() else None
            if baustein_id:
                id_match = gski_app._BAUSTEIN_ID_ONLY_RE.match(baustein_id)
                if id_match:
                    baustein_id = id_match.group(1)
            if baustein_id and baustein_id.lower() not in question.lower():
                baustein_id = None

            raw_schicht_id = args.get("schicht_id")
            schicht_id = raw_schicht_id.strip().upper() if isinstance(raw_schicht_id, str) and raw_schicht_id.strip() else None
            if schicht_id not in gski_app._VALID_SCHICHT_IDS:
                schicht_id = None
            if schicht_id and schicht_id.lower() not in question.lower():
                schicht_id = None
            if baustein_id and schicht_id:
                schicht_id = None

            results = await retrieve(query=query, top_k=top_k, baustein_id=baustein_id, schicht_id=schicht_id)
            context = build_context(results)
            citations_text = format_citations(results)
            tool_payload = {"query": query, "context": context, "citations": citations_text}
            best_score = max((r.score for r in results), default=0.0)
            if best_score < WEAK_RETRIEVAL_HINT_THRESHOLD:
                tool_payload["hinweis"] = (
                    f"Die Treffer sind nur mäßig relevant (bester Score: {best_score:.2f}). "
                    "Falls die Antwort dadurch lückenhaft wirkt, ist ein zweiter "
                    "rag_retrieve-Aufruf mit anders formulierter Anfrage erlaubt."
                )

            for item in results:
                key = gski_app._result_key(item)
                existing = aggregated_by_key.get(key)
                if existing is None or float(getattr(item, "score", 0.0) or 0.0) > float(getattr(existing, "score", 0.0) or 0.0):
                    aggregated_by_key[key] = item

            messages.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(tool_payload, ensure_ascii=False)}
            )

        followup = await chat(messages, tools=gski_app.TOOLS, tool_choice="auto")
        current_msg = followup.choices[0].message

    content = current_msg.content or ""
    last_results = sorted(
        aggregated_by_key.values(), key=lambda r: float(getattr(r, "score", 0.0) or 0.0), reverse=True
    )
    return content, last_results


def _build_canon_alias_map(last_results: list) -> tuple[list, dict[str, str]]:
    """Repliziert app.py's canon_rows/canon_alias_to_full_text-Aufbau
    (uncapped Kandidatenliste für die Zitat-Korrektur, siehe app.py:4179ff)."""
    canon_rows: list = []
    canon_alias_to_full_text: dict[str, str] = {}
    canon_alias_to_modal_verben: dict[str, list[str]] = {}
    seen: set = set()
    for idx, result in enumerate(last_results, start=1):
        file_name = extract_source_file(result.metadata)
        if not file_name:
            continue
        page = extract_page(result.metadata)
        section = resolve_section_title(result.metadata)
        key = (file_name, page, section)
        if key in seen:
            continue
        seen.add(key)
        page_end = result.metadata.get("page_end") if isinstance(result.metadata.get("page_end"), int) else None
        alias = gski_app._source_alias(idx, section, page, page_end)
        canon_rows.append((idx, alias, file_name, page, page_end, section, ""))
        canon_alias_to_full_text[alias] = result.text or ""
        modal_verben = result.metadata.get("modal_verben")
        if isinstance(modal_verben, list) and modal_verben:
            canon_alias_to_modal_verben[alias] = modal_verben
    return canon_rows, canon_alias_to_full_text, canon_alias_to_modal_verben


async def _process_question(question: str, label: str) -> dict:
    content, last_results = await _run_tool_loop(question)
    canon_rows, canon_alias_to_full_text, canon_alias_to_modal_verben = _build_canon_alias_map(last_results)
    content = gski_app._canonicalize_citations(content, canon_rows, alias_to_full_text=canon_alias_to_full_text)

    pairs = gski_app._extract_claim_source_pairs(content, canon_alias_to_full_text)
    verdicts = await gski_app._judge_citation_support(pairs) if pairs else []
    unsupported = [v for v in verdicts if not v["supported"]]

    modal_checks = gski_app._extract_modal_verb_checks(content, canon_alias_to_modal_verben)
    modal_mismatches = [c for c in modal_checks if not c["matches"]]

    return {
        "label": label,
        "question": question,
        "checked": len(verdicts),
        "unsupported": len(unsupported),
        "mismatches": unsupported,
        "modal_verb_checked": len(modal_checks),
        "modal_verb_mismatches": modal_mismatches,
    }


async def main() -> None:
    einfach = _load_questions(EINFACH_CSV, N_EINFACH)
    komplex = _load_questions(KOMPLEX_CSV, N_KOMPLEX)
    tasks = [("einfach", q) for q in einfach] + [("komplex", q) for q in komplex]

    results = []
    for label, question in tasks:
        print(f"--- [{label}] {question[:80]}", flush=True)
        try:
            r = await _process_question(question, label)
        except Exception as exc:
            print(f"    FEHLER: {exc}", flush=True)
            continue
        modal_ratio = (
            f"{len(r['modal_verb_mismatches']) / r['modal_verb_checked']:.2%}"
            if r["modal_verb_checked"]
            else "n/a"
        )
        print(
            f"    checked={r['checked']} unsupported={r['unsupported']} "
            f"modal_verb_checked={r['modal_verb_checked']} "
            f"modal_verb_mismatches={len(r['modal_verb_mismatches'])} ({modal_ratio})",
            flush=True,
        )
        results.append(r)

    total_checked = sum(r["checked"] for r in results)
    total_unsupported = sum(r["unsupported"] for r in results)
    total_modal_checked = sum(r["modal_verb_checked"] for r in results)
    total_modal_mismatches = sum(len(r["modal_verb_mismatches"]) for r in results)
    print("\n" + "=" * 60)
    print("GESAMT")
    print("=" * 60)
    print(f"Fragen verarbeitet:            {len(results)}/{len(tasks)}")
    print(f"Zitate geprüft (Judge):        {total_checked}")
    print(f"Nicht belegt (Judge):          {total_unsupported}")
    if total_checked:
        print(f"Fehlerquote (Judge):           {total_unsupported / total_checked:.2%}")
    print(f"Modalverb-Paare geprüft:       {total_modal_checked}")
    print(f"Modalverb-Abweichungen:        {total_modal_mismatches}")
    if total_modal_checked:
        print(f"Fehlerquote (Modalverb):       {total_modal_mismatches / total_modal_checked:.2%}")

    for scope in ("einfach", "komplex"):
        scoped = [r for r in results if r["label"] == scope]
        checked = sum(r["checked"] for r in scoped)
        unsupported = sum(r["unsupported"] for r in scoped)
        modal_checked = sum(r["modal_verb_checked"] for r in scoped)
        modal_mismatches = sum(len(r["modal_verb_mismatches"]) for r in scoped)
        ratio = f"{unsupported / checked:.2%}" if checked else "n/a"
        modal_ratio = f"{modal_mismatches / modal_checked:.2%}" if modal_checked else "n/a"
        print(
            f"  davon {scope}: checked={checked} unsupported={unsupported} ratio={ratio} | "
            f"modal_verb_checked={modal_checked} modal_verb_mismatches={modal_mismatches} "
            f"modal_ratio={modal_ratio}"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetails gespeichert: {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
