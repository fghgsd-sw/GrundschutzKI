from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # noqa: BLE001
    fuzz = None


GERMAN_STOPWORDS = {
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einer",
    "einem",
    "eines",
    "und",
    "oder",
    "mit",
    "ohne",
    "für",
    "von",
    "im",
    "in",
    "auf",
    "am",
    "an",
    "zu",
    "ist",
    "sind",
    "wird",
    "werden",
    "muss",
    "müssen",
    "soll",
    "sollen",
    "sollte",
    "sollten",
    "kann",
    "können",
    "dass",
    "auch",
    "nicht",
    "als",
    "bei",
    "durch",
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9äöüß\.\- ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> set[str]:
    norm = _normalize(text)
    toks = re.findall(r"[a-z0-9äöüß\-]{3,}", norm)
    return {t for t in toks if t not in GERMAN_STOPWORDS}


def _extract_page_no(prov: Any) -> int | None:
    if isinstance(prov, list):
        pages = [p.get("page_no") for p in prov if isinstance(p, dict) and isinstance(p.get("page_no"), int)]
        return min(pages) if pages else None
    if isinstance(prov, dict):
        page = prov.get("page_no")
        return page if isinstance(page, int) else None
    return None


def _extract_docling_text(item: dict[str, Any]) -> str:
    value = item.get("canonical_text") or item.get("text")
    return value if isinstance(value, str) else ""


def _is_entfallen_requirement(req: dict[str, Any]) -> bool:
    anforderung = req.get("anforderung")
    if not isinstance(anforderung, dict):
        return False
    title = anforderung.get("titel")
    if not isinstance(title, str):
        return False
    return title.strip().upper() == "ENTFALLEN"


@dataclass
class PageIndex:
    page_text: dict[int, str]
    page_tokens: dict[int, set[str]]
    token_pages: dict[str, set[int]]


def build_page_index(docling_json_path: Path) -> PageIndex:
    data = json.loads(docling_json_path.read_text(encoding="utf-8"))
    texts = data.get("texts")
    if not isinstance(texts, list):
        raise ValueError(f"Invalid Docling JSON: missing texts list in {docling_json_path}")

    page_chunks: dict[int, list[str]] = defaultdict(list)
    for item in texts:
        if not isinstance(item, dict):
            continue
        if item.get("content_layer") == "furniture":
            continue
        page_no = _extract_page_no(item.get("prov"))
        if page_no is None:
            continue
        text = _extract_docling_text(item).strip()
        if not text:
            continue
        page_chunks[page_no].append(text)

    page_text = {page: _normalize(" ".join(chunks)) for page, chunks in page_chunks.items()}
    page_tokens = {page: _tokenize(text) for page, text in page_text.items()}

    token_pages: dict[str, set[int]] = defaultdict(set)
    for page, toks in page_tokens.items():
        for tok in toks:
            token_pages[tok].add(page)

    return PageIndex(page_text=page_text, page_tokens=page_tokens, token_pages=token_pages)


def _score_page(req_norm: str, req_tokens: set[str], page_norm: str, page_tokens: set[str]) -> float:
    if not req_norm or not page_norm:
        return 0.0
    if not req_tokens:
        return 0.0

    overlap = len(req_tokens & page_tokens) / max(len(req_tokens), 1)
    if fuzz is not None:
        # token_set_ratio is robust for reordered terms; normalize to 0..1.
        seq = float(fuzz.token_set_ratio(req_norm[:2400], page_norm[:7000])) / 100.0
    else:
        seq = SequenceMatcher(None, req_norm[:2400], page_norm[:7000]).ratio()
    contains = 1.0 if req_norm[:220] and req_norm[:220] in page_norm else 0.0
    return (0.6 * overlap) + (0.3 * seq) + (0.1 * contains)


def infer_pages_for_text(
    text: str,
    index: PageIndex,
    *,
    max_candidates: int = 16,
    min_best_score: float = 0.16,
) -> dict[str, Any] | None:
    req_norm = _normalize(text)
    req_tokens = _tokenize(text)
    if not req_norm or len(req_norm) < 40:
        return None

    page_votes: Counter[int] = Counter()
    for tok in req_tokens:
        for page in index.token_pages.get(tok, set()):
            page_votes[page] += 1

    if page_votes:
        candidate_pages = [p for p, _ in page_votes.most_common(max_candidates)]
    else:
        candidate_pages = sorted(index.page_text)[:max_candidates]

    scored: list[tuple[int, float]] = []
    for page in candidate_pages:
        score = _score_page(req_norm, req_tokens, index.page_text.get(page, ""), index.page_tokens.get(page, set()))
        scored.append((page, score))
    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return None
    best_page, best_score = scored[0]
    if best_score < min_best_score:
        return None

    selected_pages = [p for p, s in scored if s >= max(0.12, best_score * 0.72)]
    selected_pages = sorted(set(selected_pages))
    if not selected_pages:
        selected_pages = [best_page]

    return {
        "page_start": selected_pages[0],
        "page_end": selected_pages[-1],
        "pages": selected_pages,
        "score": round(best_score, 4),
        "method": "docling_token_overlap_sequence",
    }


def annotate_grundschutz(
    grundschutz_data: dict[str, Any],
    index: PageIndex,
    *,
    limit: int | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    out = deepcopy(grundschutz_data)

    total = 0
    mapped = 0
    mapped_with_fallback = 0
    skipped_entfallen = 0
    bausteine_mapped = 0
    baustein_beschreibung_mapped = 0
    baustein_gefaehrdung_mapped = 0

    schichten = out.get("schichten")
    if not isinstance(schichten, list):
        return out, {"anforderungen_total": 0, "anforderungen_mapped": 0, "bausteine_mapped": 0}

    for schicht in schichten:
        if not isinstance(schicht, dict):
            continue
        bausteine = schicht.get("bausteine")
        if not isinstance(bausteine, list):
            continue

        for baustein in bausteine:
            if not isinstance(baustein, dict):
                continue

            # Map Baustein description sections separately.
            beschreibung = baustein.get("beschreibung")
            beschreibung_pages: set[int] = set()
            if isinstance(beschreibung, dict):
                mapped_sections: dict[str, Any] = {}
                for section_name, section_text in beschreibung.items():
                    if not isinstance(section_text, str) or not section_text.strip():
                        continue
                    section_mapping = infer_pages_for_text(section_text, index)
                    if not section_mapping:
                        continue
                    mapped_sections[section_name] = section_mapping
                    for p in section_mapping.get("pages", []):
                        if isinstance(p, int):
                            beschreibung_pages.add(p)
                if mapped_sections:
                    baustein["page_mapping_beschreibung"] = {
                        "sections": mapped_sections,
                        "page_start": min(beschreibung_pages),
                        "page_end": max(beschreibung_pages),
                        "pages": sorted(beschreibung_pages),
                        "method": "docling_token_overlap_sequence",
                    }
                    baustein_beschreibung_mapped += 1

            # Map each Gefaehrdungslage entry separately.
            gefaehrdungen = baustein.get("gefaehrdungslage")
            gefaehrdung_pages: set[int] = set()
            if isinstance(gefaehrdungen, list):
                any_entry_mapped = False
                for item in gefaehrdungen:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("titel")
                    desc = item.get("beschreibung")
                    text_parts = []
                    if isinstance(title, str) and title.strip():
                        text_parts.append(title.strip())
                    if isinstance(desc, str) and desc.strip():
                        text_parts.append(desc.strip())
                    if not text_parts:
                        continue
                    entry_mapping = infer_pages_for_text(" ".join(text_parts), index)
                    if not entry_mapping:
                        continue
                    item["page_mapping"] = entry_mapping
                    any_entry_mapped = True
                    for p in entry_mapping.get("pages", []):
                        if isinstance(p, int):
                            gefaehrdung_pages.add(p)
                if any_entry_mapped:
                    baustein["page_mapping_gefaehrdungslage"] = {
                        "page_start": min(gefaehrdung_pages),
                        "page_end": max(gefaehrdung_pages),
                        "pages": sorted(gefaehrdung_pages),
                        "method": "aggregate_from_gefaehrdungslage",
                    }
                    baustein_gefaehrdung_mapped += 1

            anforderungen = baustein.get("anforderungen")
            if not isinstance(anforderungen, dict):
                continue

            baustein_pages_req: set[int] = set()
            for level_items in anforderungen.values():
                if not isinstance(level_items, list):
                    continue
                for req in level_items:
                    if limit is not None and total >= limit:
                        break
                    if not isinstance(req, dict):
                        continue
                    if _is_entfallen_requirement(req):
                        skipped_entfallen += 1
                        continue
                    total += 1

                    inhalt = req.get("inhalt")
                    if not isinstance(inhalt, str) or not inhalt.strip():
                        continue

                    mapping = infer_pages_for_text(inhalt, index)
                    if mapping is None:
                        continue
                    req["page_mapping"] = mapping
                    mapped += 1
                    for p in mapping.get("pages", []):
                        if isinstance(p, int):
                            baustein_pages_req.add(p)
                if limit is not None and total >= limit:
                    break

            baustein_pages_all = set(baustein_pages_req) | set(beschreibung_pages) | set(gefaehrdung_pages)
            if baustein_pages_all:
                sorted_pages = sorted(baustein_pages_all)
                baustein["page_mapping"] = {
                    "page_start": sorted_pages[0],
                    "page_end": sorted_pages[-1],
                    "pages": sorted_pages,
                    "method": "aggregate_from_baustein_content",
                }
                bausteine_mapped += 1

                # Fallback: assign baustein-range pages to requirement entries that could not be matched directly.
                for level_items in anforderungen.values():
                    if not isinstance(level_items, list):
                        continue
                    for req in level_items:
                        if not isinstance(req, dict):
                            continue
                        if _is_entfallen_requirement(req):
                            continue
                        if "page_mapping" in req:
                            continue
                        req["page_mapping"] = {
                            "page_start": sorted_pages[0],
                            "page_end": sorted_pages[-1],
                            "pages": sorted_pages,
                            "score": 0.0,
                            "method": "fallback_from_baustein_aggregate",
                        }
                        mapped_with_fallback += 1

                # Fallback for description subsections without direct match.
                if isinstance(beschreibung, dict):
                    sec_map = (
                        baustein.get("page_mapping_beschreibung", {}).get("sections", {})
                        if isinstance(baustein.get("page_mapping_beschreibung"), dict)
                        else {}
                    )
                    if isinstance(sec_map, dict):
                        for section_name, section_text in beschreibung.items():
                            if not isinstance(section_text, str) or not section_text.strip():
                                continue
                            if section_name in sec_map:
                                continue
                            sec_map[section_name] = {
                                "page_start": sorted_pages[0],
                                "page_end": sorted_pages[-1],
                                "pages": sorted_pages,
                                "score": 0.0,
                                "method": "fallback_from_baustein_aggregate",
                            }
                            mapped_with_fallback += 1
                        baustein.setdefault("page_mapping_beschreibung", {})
                        baustein["page_mapping_beschreibung"]["sections"] = sec_map
                        baustein["page_mapping_beschreibung"]["page_start"] = sorted_pages[0]
                        baustein["page_mapping_beschreibung"]["page_end"] = sorted_pages[-1]
                        baustein["page_mapping_beschreibung"]["pages"] = sorted_pages
                        baustein["page_mapping_beschreibung"]["method"] = "aggregate_with_fallback"

                # Fallback for Gefaehrdungseintraege without direct match.
                if isinstance(gefaehrdungen, list):
                    for item in gefaehrdungen:
                        if not isinstance(item, dict):
                            continue
                        if "page_mapping" in item:
                            continue
                        item["page_mapping"] = {
                            "page_start": sorted_pages[0],
                            "page_end": sorted_pages[-1],
                            "pages": sorted_pages,
                            "score": 0.0,
                            "method": "fallback_from_baustein_aggregate",
                        }
                        mapped_with_fallback += 1

                    baustein.setdefault("page_mapping_gefaehrdungslage", {})
                    baustein["page_mapping_gefaehrdungslage"]["page_start"] = sorted_pages[0]
                    baustein["page_mapping_gefaehrdungslage"]["page_end"] = sorted_pages[-1]
                    baustein["page_mapping_gefaehrdungslage"]["pages"] = sorted_pages
                    baustein["page_mapping_gefaehrdungslage"]["method"] = "aggregate_with_fallback"
            if limit is not None and total >= limit:
                break
        if limit is not None and total >= limit:
            break

    stats = {
        "anforderungen_total": total,
        "anforderungen_mapped": mapped,
        "page_mappings_added_via_fallback": mapped_with_fallback,
        "anforderungen_entfallen_skipped": skipped_entfallen,
        "bausteine_mapped": bausteine_mapped,
        "baustein_beschreibung_mapped": baustein_beschreibung_mapped,
        "baustein_gefaehrdung_mapped": baustein_gefaehrdung_mapped,
    }
    return out, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add page mappings to grundschutz.json by matching requirement text against Docling OCR JSON."
    )
    parser.add_argument(
        "--grundschutz-json",
        type=Path,
        default=Path("data/data_preprocessed/grundschutz.json"),
        help="Path to structured grundschutz.json",
    )
    parser.add_argument(
        "--docling-json",
        type=Path,
        default=Path("data/data_docling_json_ocr/IT_Grundschutz_Kompendium_Edition2023.json"),
        help="Path to Docling OCR JSON for the Kompendium",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/data_preprocessed/grundschutz_with_pages.json"),
        help="Output path for enriched JSON",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of requirements to process (for quick tests).",
    )
    args = parser.parse_args()

    data = json.loads(args.grundschutz_json.read_text(encoding="utf-8"))
    index = build_page_index(args.docling_json)
    enriched, stats = annotate_grundschutz(data, index, limit=args.limit)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")

    total = stats["anforderungen_total"]
    mapped = stats["anforderungen_mapped"]
    ratio = (mapped / total * 100.0) if total else 0.0
    fuzzy_backend = "rapidfuzz.token_set_ratio" if fuzz is not None else "difflib.SequenceMatcher"
    print(f"Fuzzy backend: {fuzzy_backend}")
    print(
        f"Mapped requirements: {mapped}/{total} ({ratio:.1f}%) | "
        f"Bausteine with aggregated pages: {stats['bausteine_mapped']} | "
        f"Baustein beschreibung mapped: {stats['baustein_beschreibung_mapped']} | "
        f"Baustein gefaehrdungslage mapped: {stats['baustein_gefaehrdung_mapped']} | "
        f"Fallback mappings added: {stats['page_mappings_added_via_fallback']} | "
        f"ENTFALLEN skipped: {stats['anforderungen_entfallen_skipped']}"
    )
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
