# TASK 03 – PDF-Resolver in `rag_tool.py` modularisieren

**Betroffener Code:** [apps/chainlit/rag_tool.py:37-58](../apps/chainlit/rag_tool.py#L37-L58) (`_canonical_pdf_from_text`) und [apps/chainlit/rag_tool.py:106-146](../apps/chainlit/rag_tool.py#L106-L146) (`extract_source_file`)

**Symptom:** Hartkodierte `if`-Kaskade für PDF-Zuordnung – jedes neue Dokument erfordert Codeänderungen an mehreren Stellen.

---

## Was die Funktion tatsächlich tut

`_canonical_pdf_from_text()` ist **kein** Endpoint-Definitions-Mechanismus, sondern ein **defensiver Resolver**: Sie versucht, aus irgendwelchen frei­textigen Hinweisen in der Payload (`source`, `document`, `title`, `file`) auf den **echten PDF-Dateinamen** zu kommen, weil unterschiedliche Ingest-Pfade die Payload unterschiedlich befüllen.

Wo das wirkt:

```
User-Frage
    ↓
retrieve()  →  Treffer mit Payload
    ↓
extract_source_file(payload)      ← gibt einen PDF-Dateinamen zurück
    ↓
_canonical_pdf_from_text(string)  ← der ratende Teil
    ↓
/sources/pdf/<file_name>          ← FastAPI-Endpoint in app.py:2137
    ↓
FileResponse vom Filesystem (data/data_raw/)
```

Der Endpoint selbst ist generisch: `@chainlit_fastapi_app.get("/sources/pdf/{file_name:path}")` nimmt **jeden** PDF-Dateinamen entgegen – Endpoints für jedes PDF sind nicht definiert. Das wirklich Hartkodierte sind:

1. Die `if "standard_200_X" in lower`-Kaskade.
2. Die `if "kompendium" in lower or "grundschutz" in lower`-Heuristik.
3. Die Allowlist in `extract_source_file()` Zeile 140–145 (welche `doc_type`-Werte auf das Grundschutz-PDF zurückfallen).

Beim Hinzufügen einer neuen Quelle (z. B. „IT-Sicherheitsleitfaden Hochschulen.pdf") wären **drei Codestellen** zu ändern.

## Warum das überhaupt existiert

`ingest.py` legt das `file`-Feld korrekt an ([ingest.py:248](../apps/chainlit/ingest.py#L248): `"file": GRUNDSCHUTZ_SOURCE_PDF`). `ingest_docling.py` und alte Notebook-Ingests waren weniger diszipliniert – die Payload enthielt nur `source: "BSI Standard 200-1"` als Freitext. Der Resolver kompensiert das.

Erfreulich: **`citation_map.json` existiert bereits** und ist die natürliche Heimat dieser Information:

```json
"standard_200_1": {
    "author": "BSI", "year": "2023",
    "title": "BSI-Standard 200-1: IT-Grundschutz",
    ...
}
```

Es fehlen nur zwei Felder pro Eintrag: der **PDF-Dateiname** und die **Match-Muster**.

## Drei Lösungswege, von minimal bis sauber

### Variante A – Citation-Map als Single Source of Truth (empfohlen)

`citation_map.json` um zwei Felder erweitern:

```json
{
  "standard_200_1": {
    "pdf_file": "standard_200_1.pdf",
    "match_patterns": ["standard_200_1", "standard 200 1", "bsi 200-1"],
    "author": "BSI",
    "year": "2023",
    "title": "BSI-Standard 200-1: IT-Grundschutz",
    "publisher": "BSI"
  },
  "kompendium_2023": {
    "pdf_file": "IT_Grundschutz_Kompendium_Edition2023.pdf",
    "match_patterns": ["kompendium", "grundschutz", "grundschutz.json"],
    "doc_type_fallbacks": ["anforderung", "baustein_beschreibung", "baustein_gefaehrdungslage"],
    "title": "IT-Grundschutz-Kompendium (Edition 2023)",
    ...
  }
}
```

`_canonical_pdf_from_text` wird zu einem Konfig-Lookup, nicht 20+ Zeilen `if`-Kaskade:

```python
def _canonical_pdf_from_text(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw: return None
    lower = raw.lower()
    if lower.endswith(".pdf"):
        return raw.split("/")[-1]
    cmap = _load_citation_map()
    for entry in cmap.values():
        patterns = entry.get("match_patterns", [])
        if any(p.lower() in lower for p in patterns):
            return entry.get("pdf_file")
    return None
```

Die `doc_type`-Fallback-Liste in `extract_source_file()` Zeile 140 wird analog aus der Citation-Map abgeleitet. Eine neue Quelle hinzufügen heißt: **einen Eintrag in `citation_map.json` ergänzen**. Kein Codeänderung mehr.

- ✅ Konfigurations­getrieben
- ✅ Nutzt eine bereits vorhandene Datei
- ✅ Bibliografie-Daten und PDF-Resolving an einem Ort
- ⚠️ Bestehende `citation_map.json`-Konsumenten müssen die neuen Felder ignorieren (sie tun das, weil `.get()` defaults zurückgibt)

### Variante B – Payload muss `file` enthalten, Resolver entfällt

Der Ingest wird so diszipliniert, dass **jedes** ingestierte Dokument ein eindeutiges `file`-Feld bekommt (z. B. `IT_Grundschutz_Kompendium_Edition2023.pdf`, `standard_200_1.pdf`). Dann reicht in `extract_source_file()`:

```python
def extract_source_file(payload: dict[str, Any]) -> str | None:
    return payload.get("file")
```

– 40 Zeilen Resolver-Code verschwinden komplett.

- ✅ Maximal sauber
- ✅ Keine Heuristiken mehr
- ⚠️ Setzt voraus, dass jeder neue Ingest-Pfad diese Disziplin einhält
- ⚠️ Bestehende Collections (auch die aktuelle `grundschutz_bge_m3`) müssten neu ingestiert oder per `update_payload`-Batch korrigiert werden

### Variante C – Hybride (Übergangs­strategie)

Variante A als sofortige Strukturverbesserung, mittelfristig Migration zu Variante B durch konsequenten Ingest-Code. Der Resolver bleibt als „Defensiv-Sicherheits­netz" für legacy Payloads stehen.

## Empfehlung

**Variante A** umsetzen. Sie bringt die Modularität, die erwartet wird, ohne den Ingest anzufassen und ohne bestehende Daten zu migrieren. Wenn später ein neues Dokument dazukommt, ist eine Änderung in `citation_map.json` ausreichend – Codeänderung null.

Konkret hieße das drei kleine Edits:

1. **`citation_map.json`** um `pdf_file`, `match_patterns` und ggf. `doc_type_fallbacks` pro Eintrag ergänzen
2. **`rag_tool.py`** – `_canonical_pdf_from_text` auf Citation-Map-Lookup umstellen, hartkodierte `doc_type`-Liste in `extract_source_file` durch Citation-Map-Lookup ersetzen
3. **`settings.py`** – `GRUNDSCHUTZ_SOURCE_PDF`-Konstante kann als reiner Fallback stehen bleiben (für Migrationsfälle)
