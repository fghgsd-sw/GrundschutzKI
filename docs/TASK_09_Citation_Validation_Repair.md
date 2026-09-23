# TASK_09: Citation Validation & Repair (LLM-as-Judge)

## Problem

Der LLM generiert inhaltlich korrekte Aussagen aus Parameterwissen und zitiert dazu thematisch nahe, aber inhaltlich nicht deckende Chunks. Das Entfernen falscher Zitate allein macht die Antwort unvollständig oder falsch — es braucht eine Reparaturlogik.

**Typisches Fehlerbild:**
- Text: `IND.2.2 Speicherprogrammierbare Steuerung (SPS) – Maßnahmen für PLCs`
- Zitat: `Quelle: 8.1.6 Erhebung der ICS-Systeme (S.95-96)` ← Standard 200-2, belegt IND.2.2 nicht

## Architektur: Post-hoc Repair Loop

```
Antwort generiert (assistant_reply.content)
    ↓
1. Parse: Liste aller (Textpassage, zitierter Chunk) Paare extrahieren
    ↓
2. Validate: Passt der Chunk inhaltlich zur Passage?
    ├─ JA → unverändert
    ├─ NEIN + anderer Chunk aus source_rows passt → Zitat ersetzen
    └─ NEIN + kein Chunk passt → Aussage umformulieren (LLM-Repair)
    ↓
3. Reparierte Antwort senden
```

## Implementierung

### Schritt 1: Zitations-Paare extrahieren

Nach der Antwortgenerierung, vor `assistant_reply.send()`:

```python
import re

def _extract_citation_pairs(
    content: str,
    source_rows: list[tuple],
) -> list[dict]:
    """Gibt Liste von {text_snippet, alias, chunk_text, chunk_meta} zurück."""
    pairs = []
    for match in re.finditer(
        r"([^\n]{0,200}?)(Quelle:\s*[^\n]{1,260}?\(S\.[^)]+\))",
        content,
        flags=re.IGNORECASE,
    ):
        snippet = match.group(1).strip()
        alias = match.group(2).strip()
        # Finde passenden source_row über Alias-Name
        for _, row_alias, _, page_start, page_end, section, chunk_text in source_rows:
            if row_alias == alias:
                pairs.append({
                    "snippet": snippet,
                    "alias": alias,
                    "chunk_text": chunk_text,
                    "page_start": page_start,
                    "section": section,
                })
                break
    return pairs
```

### Schritt 2: Programmatischer Pre-Check (schnell, kostenlos)

Vor dem LLM-Call: einfacher BSI-ID-Abgleich für Kompendium-Chunks.

```python
_BSI_ID_RE = re.compile(r"[A-Z]{2,4}\.\d+(?:\.\w+)*")

def _citation_valid_fast(snippet: str, chunk_meta: dict) -> bool | None:
    """
    Gibt True/False zurück wenn eindeutig, None wenn unklar (→ LLM-Check nötig).
    Funktioniert nur für Kompendium-Chunks mit baustein_id-Metadatum.
    """
    baustein_id = chunk_meta.get("baustein_id") or chunk_meta.get("baustein")
    if not baustein_id:
        return None  # kein Metadatum → LLM-Check

    ids_in_snippet = {m.group(0) for m in _BSI_ID_RE.finditer(snippet)}
    if not ids_in_snippet:
        return None  # kein BSI-ID im Text → LLM-Check

    # BSI-ID im Text stimmt mit Chunk-Baustein überein?
    return any(id_.startswith(baustein_id) for id_ in ids_in_snippet)
```

### Schritt 3: LLM-as-Judge für unklare Fälle

```python
async def _validate_and_repair_citations(
    content: str,
    source_rows: list[tuple],
    all_chunks: list[RagResult],
) -> str:
    """
    Validiert Zitationen und repariert wenn möglich.
    Gibt reparierten content zurück.
    """
    pairs = _extract_citation_pairs(content, source_rows)
    if not pairs:
        return content

    needs_llm = []
    for pair in pairs:
        fast_result = _citation_valid_fast(pair["snippet"], pair.get("meta", {}))
        if fast_result is False:
            needs_llm.append(pair)
        elif fast_result is None:
            needs_llm.append(pair)

    if not needs_llm:
        return content

    # LLM-Check: Batch alle unklaren Paare in einem Call
    check_prompt = (
        "Prüfe für jedes der folgenden Paare (Textpassage / Quellen-Chunk), "
        "ob der Chunk die Textpassage inhaltlich belegt.\n"
        "Antworte für jedes Paar mit: GÜLTIG, FALSCH (+ Korrektur-Alias wenn möglich), "
        "oder ENTFERNEN (wenn kein Chunk die Aussage belegt).\n\n"
    )
    for i, pair in enumerate(needs_llm, 1):
        check_prompt += (
            f"--- Paar {i} ---\n"
            f"Textpassage: {pair['snippet']}\n"
            f"Zitierter Chunk: {pair['chunk_text'][:400]}\n\n"
        )

    repair_response = await chat(
        [{"role": "user", "content": check_prompt}],
        model=CHAT_MODEL,
    )
    repair_text = repair_response.choices[0].message.content or ""

    # Repair-Ergebnis auf content anwenden (vereinfacht)
    for i, pair in enumerate(needs_llm, 1):
        if f"Paar {i}" in repair_text:
            if "ENTFERNEN" in repair_text:
                content = content.replace(pair["alias"], "[Quelle nicht verifiziert]")
            # FALSCH + Korrektur: komplexere Alias-Ersetzung (→ nächste Iteration)

    return content
```

### Schritt 4: Integration in `app.py`

```python
# In main(), nach Antwortgenerierung, vor assistant_reply.send():
if source_rows_for_session and assistant_reply.content:
    assistant_reply.content = await _validate_and_repair_citations(
        assistant_reply.content,
        source_rows_for_session,
        results,
    )
```

## Abhängigkeit: Ingest-Qualität

Der programmatische Pre-Check (Schritt 2) funktioniert **nur für Kompendium-Chunks** mit reichem Metadatum (`baustein_id`, `anforderung_id`). Für Standard 200-2-Chunks ohne Baustein-Metadatum ist immer der LLM-Check nötig.

**Langfristige Voraussetzung für vollständige Validierung:**
- Standard 200-2-Chunks beim Ingest mit Kapitel-IDs (`section_id`) anreichern
- Einheitliches Metadatum-Schema über alle Quelldokumente

Aktueller Metadaten-Stand:

| Dokument | baustein_id | page_start | section_title | Validierbar |
|---|---|---|---|---|
| Kompendium | ✅ | ✅ | ✅ | programmatisch |
| Standard 200-2 | ❌ | ✅ | ✅ | nur LLM |
| Standard 200-1/3/4 | ❌ | ✅ | ✅ | nur LLM |

## Risiken

- **Latenz**: Extra LLM-Call pro Antwort (~1-2s)
- **Kosten**: Zusätzliche Token pro Validation-Call
- **Repair-Qualität**: LLM-Repair kann inhaltliche Bedeutung verändern
- **Scope Creep**: Repair-Loop kann Antwort verkürzen bis sie unbrauchbar wird → max. Entfernung begrenzen

## Priorisierung

1. Programmatischer Pre-Check für Kompendium-Chunks → sofort umsetzbar, kein Overhead
2. LLM-Judge für Standard 200-2-Chunks → mittlerer Aufwand, spürbare Verbesserung
3. Ingest-Verbesserung Standard 200-2 → langfristig, Grundvoraussetzung für vollständige Abdeckung
