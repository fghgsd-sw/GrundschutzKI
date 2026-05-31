# Modul: `apps/chainlit/rag_tool.py`

**Pfad:** [apps/chainlit/rag_tool.py](../../apps/chainlit/rag_tool.py)
**Schicht:** Retrieval-Layer der Chainlit-Anwendung
**Sprache:** Python 3.12, async

## Zweck

Implementiert den RAG-Retrieval-Layer der Chainlit-Anwendung. Übersetzt Benutzer­fragen in semantische Vektorsuchen gegen Qdrant, normalisiert die Treffer­payload zu typisierten `RagResult`-Objekten und liefert daraus zwei Aufbereitungen: den **LLM-Kontext** (Text für den Prompt) und die **Citations** (Quellen­anzeige für die UI inkl. PDF-Sprungmarken).

## Position im System

```
                                                                        ┌──────────────────┐
                                                                        │ citation_map.json│
                                                                        └────────┬─────────┘
[apps/chainlit/app.py]              [apps/chainlit/rag_tool.py]                  │ (lazy load)
  on_message()  ─────────retrieve()──▶  embed query (llm.embed)                  │
                                        Qdrant query_points         ◀── Qdrant ◀─┘
                                        normalize hits → RagResult
                                                            │
                                build_context()  ◀──────────┤
                                format_citations()◀─────────┘
                                  │
                                  ▼
                          LLM-Prompt + UI-Sidebar
```

Die Datei wird zur **Laufzeit** pro User-Anfrage aufgerufen. Sie hält zwei Modul-Singletons (Qdrant-Client, Citation-Map), die beim ersten Aufruf initialisiert werden.

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `qdrant_client` | Vektorsuche, Payload-Filter |
| `llm.embed` (eigener Wrapper über LiteLLM) | Embedding der Query, identisch zum Ingest-Pfad |
| `settings` | Konfigurationskonstanten |
| `citation_map.json` | Bibliografische Metadaten pro PDF-Quelle |
| Qdrant (HTTP) | Externer Service unter `QDRANT_URL` |

## Aufrufer

| Aufrufer | Importierte Funktionen | Zweck |
|----------|------------------------|-------|
| [apps/chainlit/app.py](../../apps/chainlit/app.py) | `retrieve`, `build_context`, `format_citations`, `extract_source_file`, `extract_page` | Haupt-Pipeline pro Chat-Frage + Citation-Rendering in Sidebar |

## Datenklassen

| Klasse | Felder | Zweck |
|--------|--------|-------|
| `RagResult` | `text: str`, `score: float`, `metadata: dict[str, Any]` | Typisierter Container für ein einzelnes Retrieval-Ergebnis |

## Funktionen

### Öffentliche API

| Funktion | Signatur (gekürzt) | Zweck |
|----------|-------------------|-------|
| `retrieve` | `(query, top_k=None, *, source_scope=None, standard_id=None, include_vectors=False) -> list[RagResult]` | Hauptfunktion: embeddet die Query, fragt Qdrant ab, optional gefiltert nach `source_scope`/`standard_id`, mit automatischem Fallback bei leerer Treffer­liste. |
| `personalized_retrieve` | wie `retrieve` + `user_profile`, `balance` | Deprecated-Wrapper für API-Kompatibilität. Personalisierungs­logik wurde entfernt, ruft `retrieve()` durch. |
| `build_context` | `(results) -> str` | Baut den Kontext-Block für den System-/User-Prompt: nummerierte Treffer mit Inline-Quellenangabe. |
| `format_citations` | `(results) -> str` | Erzeugt die Citation-Liste für die UI. Grundschutz-Treffer mit Modul/Anforderung, sonstige im bibliografischen Format (Autor (Jahr). Titel. Verleger. S. X). |
| `extract_source_file` | `(payload) -> str \| None` | Resolved den kanonischen PDF-Dateinamen aus heterogenen Payload-Strukturen. |
| `extract_page` | `(payload) -> int \| None` | Extrahiert die Start-Seitenzahl aus heterogenen Payload-Strukturen. |

### Interne Helfer (`_private`)

| Funktion | Zweck |
|----------|-------|
| `_get_client` | Lazy-Initializer + Singleton für `QdrantClient`. |
| `_load_citation_map` | Lazy-Loader für `citation_map.json`, mit fehlertolerantem Fallback auf `{}`. |
| `_canonical_pdf_from_text` | Heuristik: leitet aus Freitext-Hinweisen (`source`, `document`, …) einen PDF-Dateinamen ab. Hartkodierte Kaskade – Modularisierung beschrieben in [TASK_03](../TASK_03_PDF-Resolver-modularisieren.md). |
| `_extract_text` | Sucht im Payload nach gängigen Text-Feldnamen (`text`, `content`, `chunk`, `body`) – robust gegen Schema-Varianten. |
| `_extract_citation` | Minimal-Citation-String als Fallback (`Quelle | Modul X | Seite Y`). |
| `_clean_text` | Whitespace-Normalisierung + Längenkürzung auf max. 1200 Zeichen mit `...`-Suffix. |

## Modul-Zustand

| Variable | Typ | Initialisierung | Threading |
|----------|-----|-----------------|-----------|
| `_client` | `QdrantClient \| None` | Lazy in `_get_client()` | Singleton, nicht thread-safe (Chainlit nutzt asyncio im selben Prozess → unkritisch) |
| `_citation_map` | `dict \| None` | Lazy in `_load_citation_map()` | wie oben |

## Konfiguration

Aus [apps/chainlit/settings.py](../../apps/chainlit/settings.py) werden gelesen:

| Setting | Standard | Wirkung |
|---------|----------|---------|
| `QDRANT_URL` | `http://localhost:6333` | Verbindung zum Vektorspeicher |
| `QDRANT_API_KEY` | (leer) | API-Auth (löst sonst Warnung bei `http://` aus) |
| `QDRANT_COLLECTION` | `grundschutz` | Aktiv abgefragte Collection |
| `TOP_K` | `5` | Anzahl Treffer pro Anfrage (sofern Caller kein `top_k` setzt) |
| `SCORE_THRESHOLD` | `0.0` | Minimaler Cosine-Score zur Aufnahme in das Ergebnis |
| `CITATION_MAP_PATH` | `./citation_map.json` | Pfad zur bibliografischen Map |
| `GRUNDSCHUTZ_SOURCE_PDF` | `IT_Grundschutz_Kompendium_Edition2023.pdf` | Fallback-Dateiname für strukturierte Grundschutz-Treffer |

## Verhaltens­hinweise und Edge-Cases

- **Filter-Fallback in `retrieve`**: Werden `source_scope` oder `standard_id` gesetzt und das gefilterte Ergebnis ist leer, wird ein zweiter unfiltered Query abgesetzt. Das ist gedacht für Migrationsphasen, in denen alte Collections die neuen Metadaten-Felder nicht enthalten.
- **`include_vectors=True`** speichert das Embedding unter `metadata["_embedding"]` – wird derzeit nicht mehr genutzt (Reste der entfernten Personalisierung).
- **`format_citations` doppelter Pfad**: Für Grundschutz-Treffer mit `baustein_id` wird ein Citation-Format mit „Modul / Anforderung / Seite" erzeugt, ansonsten das bibliografische Format aus der Citation-Map. Fehlt beides, greift `_extract_citation` als minimal sinnvolle Ausgabe.

## Bekannte Einschränkungen

- **`_canonical_pdf_from_text`** ist hartkodiert (vier Standards + Kompendium). Neue PDF-Quellen erfordern Code-Änderung. Lösung: [TASK_03](../TASK_03_PDF-Resolver-modularisieren.md).
- **`personalized_retrieve`** ist ein No-Op-Wrapper und sollte langfristig entfernt werden, sobald keine Aufrufer mit Personalisierungs-API mehr existieren.
- **Keine Pagination** – `retrieve()` gibt immer max. `top_k` Treffer zurück, kein „mehr laden". Für die UI bisher nicht nötig.
