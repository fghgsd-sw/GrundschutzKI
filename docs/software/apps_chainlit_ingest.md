# Modul: `apps/chainlit/ingest.py`

**Pfad:** [apps/chainlit/ingest.py](../../apps/chainlit/ingest.py)
**Schicht:** Offline-Ingestion-Layer (Qdrant-Befüllung)
**Sprache:** Python 3.12, async/CLI

## Zweck

Importiert strukturierte Grundschutz- und Standard-Dokumente in Qdrant. Das Modul baut aus JSON-Quellen einheitliche `Doc`-Objekte, erzeugt Embeddings über `llm.embed`, legt/initialisiert die Ziel-Collection und schreibt Dokumente batchweise als Vektorpunkte inklusive Retrieval-Metadaten.

## Position im System

```
[data_preprocessed/, data_docling_json_ocr/]
                 │
                 ▼
      [apps/chainlit/ingest.py]
       - build docs (Grundschutz/Standards)
       - enrich payload (doc_type, IDs, page ranges)
       - embed batches (llm.embed)
       - upsert points (Qdrant)
                 │
                 ▼
              [Qdrant]
                 │
                 ▼
        [apps/chainlit/rag_tool.py]
          retrieve()/filtering zur Laufzeit
```

Das Modul ist primär ein **CLI-Ingest-Tool** und wird typischerweise vor dem Laufzeitbetrieb ausgeführt (lokal oder im Container).

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `qdrant_client` | Collection-Verwaltung, Payload-Indizes, Upsert von Punkten |
| `llm.embed` | Embedding-Generierung für alle Dokumentchunks |
| `settings` | Qdrant-Konfiguration, Collection-Name, Grundschutz-PDF-Default |
| `data_preprocessed` | Strukturierte JSON-Quellen (Grundschutz, Fallback-Standards) |
| `data_docling_json_ocr` | Docling-JSON für Standards (bevorzugte Quelle) |

## Aufrufer / Ausführung

| Einstiegspunkt | Art | Zweck |
|---------------|-----|-------|
| CLI: `python ingest.py ...` | Manuell/Script | Einmalige oder wiederholte Befüllung der Vektordatenbank |
| CLI: `python -m apps.chainlit.ingest ...` | Manuell/Script | Modulbasierte Ausführung im Repo-Kontext |

## Datenklassen

| Klasse | Felder | Zweck |
|--------|--------|-------|
| `Doc` | `id: str`, `text: str`, `payload: dict[str, Any]` | Einheitliches Ingestion-Objekt vor Embedding und Qdrant-Upsert |

## Funktionen

### Öffentliche API / Orchestrierung

| Funktion | Signatur (gekürzt) | Zweck |
|----------|-------------------|-------|
| `main` | `() -> None` | CLI-Entry-Point: parst Argumente, baut Dokumente, startet async Ingest. |
| `_build_docs` | `(source) -> list[Doc]` | Wählt Datenquellen und erzeugt kombinierte Doc-Liste für `grundschutz`/`standards`/`all`. |
| `_ingest` | `(docs, collection, recreate, batch_size) -> None` | Embedding + batchweiser Qdrant-Upsert inkl. Retry bei Payload-Fehlern. |

### Quellenaufbereitung

| Funktion | Zweck |
|----------|-------|
| `_grundschutz_docs` | Erzeugt Docs aus Grundschutz-Struktur (Gefährdungen, Baustein-Beschreibung, Gefährdungslage, Anforderungen). |
| `_standards_docs_from_docling_json` | Liest Docling-JSON der Standards, segmentiert in Abschnitte mit Seitenbereichen. |
| `_standards_docs_from_preprocessed` | Fallback für Standards aus preprocessed JSON-Dateien. |
| `_extract_page_range` | Leitet robuste Seitenbereiche aus Mapping-Objekten ab (inkl. Cluster-Heuristik). |
| `_beschreibung_text`, `_gefaehrdungslage_text` | Normalisieren heterogene Textstrukturen in ingestierbaren Fließtext. |
| `_is_entfallen_requirement` | Filtert Anforderungen mit Titel `ENTFALLEN` aus. |

### Qdrant/Technische Helfer

| Funktion | Zweck |
|----------|-------|
| `_ensure_collection` | Erstellt/recreated Collection und legt Payload-Indizes für Filterfelder an. |
| `_collection_exists` | Prüft Existenz einer Collection (für `--skip-if-exists`). |
| `_point_id` | Erzeugt stabile UUIDv5 aus String-ID für Qdrant-kompatible Punkt-IDs. |
| `_load_json` | Einheitliches Laden von JSON-Dateien. |
| `_extract_page_from_prov` | Extrahiert Seitenzahl aus Docling-`prov`-Struktur. |

## Payload-Design (Auszug)

Das Modul schreibt filter- und zitierfähige Metadaten in Qdrant, u. a.:

- `doc_type` (z. B. `anforderung`, `baustein_beschreibung`, `standard_abschnitt`)
- `source`, `file`, `document_id`
- `page_start`, `page_end`
- Grundschutz-spezifisch: `schicht_id`, `baustein_id`, `anforderung_id`, `anforderung_level`, `anforderung_typ`

Diese Felder werden später von [apps/chainlit/rag_tool.py](../../apps/chainlit/rag_tool.py) für Retrieval-Filter, Kontextbau und Quellenauflösung genutzt.

## Konfiguration

Aus [apps/chainlit/settings.py](../../apps/chainlit/settings.py) werden gelesen:

| Setting | Wirkung |
|---------|---------|
| `QDRANT_URL` | Qdrant-Endpunkt |
| `QDRANT_API_KEY` | Authentifizierung gegenüber Qdrant |
| `QDRANT_COLLECTION` | Ziel-Collection für Upserts |
| `GRUNDSCHUTZ_SOURCE_PDF` | Fallback-Dateiname für Grundschutz-Quellreferenz |

Zusätzlich über CLI/Umgebung:

| Parameter/Env | Wirkung |
|---------------|---------|
| `--source` | Quelle: `all`, `grundschutz`, `standards` |
| `--recreate` | Collection vor Ingest neu anlegen |
| `--skip-if-exists` | Ingest überspringen, falls Collection bereits existiert |
| `--batch-size` | Embedding-/Upsert-Batchgröße |
| `DATA_PREPROCESSED_DIR` | Alternativer Pfad zu preprocessed JSON |
| `INGEST_DOCLING_JSON_DIR` | Alternativer Pfad zu Docling-JSON |

## Verhaltenshinweise und Edge-Cases

- **Standards-Quelle mit Fallback**: bevorzugt Docling-JSON; wenn nicht vorhanden, wird auf preprocessed Standards zurückgefallen.
- **Seitenbereich-Heuristik**: `_extract_page_range` vermeidet große, unplausible Bereiche durch Clustering naher Seitenwerte.
- **Retry bei Payload-Fehlern**: `_ingest` reduziert Batchgröße schrittweise bei Qdrant-Payload-Fehlern.
- **Idempotenz optional**: über `--skip-if-exists` kann ein erneuter Ingest gezielt vermieden werden.

## Bekannte Einschränkungen

- **Monolithischer Zuschnitt**: Datenextraktion, Payload-Modellierung und Persistenz liegen in einer Datei.
- **Heuristikabhängigkeit**: Segmentierung und Seitenableitung sind regelbasiert; Änderungen in Quellformaten können Nachschärfung erfordern.
- **Keine Deduplizierung über Ingest-Läufe**: Wiederholte Läufe überschreiben bestehende Punkt-IDs nur dann stabil, wenn `doc_id` unverändert bleibt.
