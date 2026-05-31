# Modul: `apps/chainlit/ingest_docling.py`

**Pfad:** [apps/chainlit/ingest_docling.py](../../apps/chainlit/ingest_docling.py)
**Schicht:** Offline-Ingestion-Layer (Docling-basierte Extraktion)
**Sprache:** Python 3.12, async/CLI

## Zweck

Importiert PDF-Inhalte in Qdrant auf Basis von Docling. Das Modul unterstützt zwei Betriebsarten:

1. **Live-Konvertierung von PDFs** (mit optionalem OCR),
2. **Ingest aus vorhandenen Docling-JSON-Exports**.

In beiden Fällen werden Abschnitte/Chunks in `Doc`-Objekte transformiert, eingebettet und in Qdrant abgelegt.

## Position im System

```
[data_raw/*.pdf] oder [data_docling_json_ocr/*.json]
                 │
                 ▼
  [apps/chainlit/ingest_docling.py]
   - PDF/JSON parse + sectioning/chunking
   - source_scope/standard_id/doc_type mapping
   - embeddings (llm.embed)
   - qdrant upsert
                 │
                 ▼
              [Qdrant]
                 │
                 ▼
        [apps/chainlit/rag_tool.py]
```

Das Modul ist ein **CLI-Ingest-Tool** für den Aufbau/Aktualisierung der Retrieval-Basis vor dem App-Betrieb.

## Externe Abhängigkeiten

| Quelle | Verwendung |
|--------|-----------|
| `docling` | PDF-Konvertierung, OCR-Pipeline, Dokumentstruktur |
| `qdrant_client` | Collection-Management und Punkt-Upserts |
| `llm.embed` | Embedding-Generierung |
| `settings` | Qdrant-Konfiguration und Collection-Default |
| PDF-Dateien (`data_raw`) | Primäre Ingest-Quelle im Live-Modus |
| Docling-JSON (`data_docling_json_ocr`) | Alternative Ingest-Quelle ohne Live-Konvertierung |

## Aufrufer / Ausführung

| Einstiegspunkt | Art | Zweck |
|---------------|-----|-------|
| CLI: `python ingest_docling.py ...` | Manuell/Container | Docling-basierter Ingest in Qdrant |
| Ingest-Service in [apps/chainlit/docker-compose.yml](../../apps/chainlit/docker-compose.yml) | Automatisiert | One-shot Ingest vor/parallel zum App-Start |

## Datenklassen

| Klasse | Felder | Zweck |
|--------|--------|-------|
| `Doc` | `id: str`, `text: str`, `payload: dict[str, Any]` | Einheitliches Ingestion-Objekt für beide Modi |

## Funktionen

### Öffentliche API / Orchestrierung

| Funktion | Signatur (gekürzt) | Zweck |
|----------|-------------------|-------|
| `main` | `() -> None` | CLI-Entry-Point inkl. Moduswahl (PDF vs. Docling-JSON). |
| `_ingest` | `(docs, collection, recreate, batch_size, max_batch_chars) -> None` | Embedding + Qdrant-Upsert mit char-budgetierter Batchbildung. |

### Dokumentaufbau

| Funktion | Zweck |
|----------|-------|
| `_build_docs` | Live-Konvertierung aus PDFs via Docling, Seitenauslese und Text-Chunking. |
| `_build_docs_from_docling_json` | Ingest aus vorgerenderten Docling-JSON-Dateien mit Abschnittssegmentierung. |
| `_extract_pages` | Extrahiert Seiteninhalte robust aus verschiedenen Docling-Objektformen. |
| `_chunk_text` | Teilt lange Seitentexte in überlappende Chunks. |
| `_ordered_text_indices` | Rekonstruiert sinnvolle Reihenfolge aus Docling-`body/groups/texts`-Referenzen. |
| `_walk_docling_json` | Generischer Baumlauf für Text-/Seitenkontext (Hilfsfunktion für JSON-Parsing). |

### Metadaten- und Technik-Helfer

| Funktion | Zweck |
|----------|-------|
| `_source_meta_from_name` | Leitet `source_scope`, `standard_id`, `doc_type` aus Dateinamen ab. |
| `_build_ocr_options` | Wählt OCR-Backend (`tesseract` oder `mac`) und Sprachoptionen. |
| `_ensure_collection` | Erstellt/recreated Ziel-Collection in Qdrant. |
| `_point_id` | Stabile UUIDv5 aus dokumentinterner String-ID. |
| `_default_pdf_dir` | Standard-PDF-Verzeichnis je nach Laufumgebung (lokal/container). |
| `_extract_page_from_prov`, `_parse_ref_index`, `_collect_text_refs` | Docling-Referenz- und Seiten-Helferfunktionen. |

## Payload-Design (Auszug)

Jeder Punkt enthält mindestens:

- `file`, `source`
- `page_start` (falls bekannt)
- `source_scope` (`standards` oder `grundschutz`)
- `standard_id` (z. B. `standard_200_1`, sonst `None`)
- `doc_type` (z. B. `standard_abschnitt`, `kompendium_abschnitt`)

Bei JSON-basiertem Ingest zusätzlich Abschnittsmetadaten wie `section_title`, `section_index`, `page_end`.

## Konfiguration

Aus [apps/chainlit/settings.py](../../apps/chainlit/settings.py) werden gelesen:

| Setting | Wirkung |
|---------|---------|
| `QDRANT_URL` | Qdrant-Endpunkt |
| `QDRANT_API_KEY` | Qdrant-Authentifizierung |
| `QDRANT_COLLECTION` | Ziel-Collection |

CLI-Parameter (Auszug):

| Parameter | Wirkung |
|----------|---------|
| `--pdf-dir` | Eingangsverzeichnis für PDFs (Live-Modus) |
| `--docling-json-dir` | Schaltet auf JSON-Modus um |
| `--device` | Docling-Device: `cpu`, `mps`, `cuda`, `auto` |
| `--ocr`, `--ocr-engine`, `--ocr-lang`, `--force-full-page-ocr` | OCR-Steuerung |
| `--recreate` | Collection vor Ingest neu erstellen |
| `--batch-size` | Max. Batchgröße |
| `--max-batch-chars` | Zeichenbudget je Embedding-Request |

## Verhaltenshinweise und Edge-Cases

- **Dualer Ingest-Modus**: JSON-Modus ist deterministischer/schneller, Live-PDF-Modus flexibler bei neuen Quellen.
- **Chunking mit Overlap**: verbessert Recall bei langen Seiteninhalten, kann aber Punktzahl und Speicherbedarf erhöhen.
- **Batch-Backoff**: Bei Payload-Problemen reduziert `_ingest` die Batchgröße dynamisch.
- **Seiten-Fallbacks**: Wenn Seitenextraktion scheitert, wird ein Whole-Document-Doc erzeugt.

## Bekannte Einschränkungen

- **Filename-basierte Metadatenableitung**: `_source_meta_from_name` ist konventionsgetrieben; abweichende Dateinamen reduzieren Filtergüte.
- **Laufzeitkosten im Live-Modus**: OCR/Docling-Konvertierung kann je nach PDF sehr CPU/GPU-intensiv sein.
- **Kein zentraler Connection/Client-Pool**: Qdrant-Client wird pro Lauf instanziiert, was für Batch-CLI ok ist, aber nicht für langlaufende Worker optimiert.


So wurden sie ingestiert: Section-basiertes Chunking aus Docling-JSON
Es gibt im Projekt zwei Chunking-Strategien, und für deine Collection wurde nicht die naive verwendet:

Pfad 1 (nicht genutzt): Fixe Zeichen-Chunks mit Overlap
In ingest_docling.py:41-55 existiert _chunk_text(text, max_chars=3000, overlap=300) – das ist die klassische Variante. Sie wird vom Code-Pfad _build_docs(...) (ingest_docling.py:124-188) angewendet, der direkt aus PDFs liest.

Pfad 2 (deine Collection): Strukturelles Section-Chunking aus Docling-JSON
Genutzt wurde _build_docs_from_docling_json(...) in ingest_docling.py:283-373. Ablauf:

Vorverarbeitung außerhalb des Skripts – Docling (IBM) hat das IT-GS-Kompendium-PDF strukturiert geparst und als JSON pro Dokument abgelegt. Die JSON-Dateien liegen in INGEST_DOCLING_JSON_DIR=/data/data_docling_json_ocr (.env:69).
Reading-Order rekonstruieren (ingest_docling.py:292 / _ordered_text_indices) – aus dem JSON-Body wird die korrekte Lesereihenfolge über groups/children-Referenzen ermittelt, nicht die naive Array-Reihenfolge.
Heading-getriebene Section-Bildung (ingest_docling.py:349-354):
Trifft der Parser auf ein Label section_header, title oder chapter_title, wird die laufende Section geflusht (= als Chunk gespeichert) und der Header als neuer Titel übernommen.
Alle Textfragmente bis zum nächsten Header werden zu einer Section zusammengezogen.
Header + Body bleiben zusammen (ingest_docling.py:310-313) – der Section-Title wird dem Body vorangestellt, sodass im Embedding der semantische Kontext der Anforderung enthalten ist.
Minimal-Filter (ingest_docling.py:304) – Sections unter 40 Zeichen werden verworfen (vermeidet leere Header-Stubs).
Furniture-Filter (ingest_docling.py:333) – Kopf-/Fußzeilen aus Docling werden übersprungen.
Kein Overlap – das Section-Pasting greift exakt von Header zu Header, ohne Wiederholung.
Warum das gut zum IT-GS-Kompendium passt
Das Kompendium ist hierarchisch über Bausteine → Anforderungen (z. B. APP.3.2.A1) strukturiert. Docling markiert die Anforderungs-IDs als section_header, sodass jede Anforderung zu genau einem Chunk wird – inkl. ihres Titels als Embedding-Signal. Deshalb siehst du in Qdrant exakt: variable Länge, keine Überlappung, ein Chunk = eine semantische Einheit (meist eine Anforderung).

Payload-Struktur als Beleg
In ingest_docling.py:361-372 bekommt jeder Chunk Felder wie section_title, section_index, page_start, page_end. Diese Felder existieren nur in Pfad 2 – wenn du in Qdrant siehst, dass deine Payloads section_title enthalten, ist das der eindeutige Beweis, dass diese Variante gelaufen ist (nicht der 3000-Zeichen-Pfad, der chunk_index setzt, siehe ingest_docling.py:183).

Anschlusskontext
Die Strategie ist methodisch state-of-the-art für strukturierte Normendokumente und unter dem Begriff layout-aware bzw. semantic chunking in der RAG-Literatur etabliert (z. B. Anthropics „Contextual Retrieval"-Empfehlungen, IBM Docling Whitepaper 2024).
Eine Schwäche: Sehr lange Anforderungen mit Maßnahmen-Listen werden nicht weiter unterteilt – wenn ein Chunk die Embedding-Token-Grenze sprengt, kann die semantische Schärfe leiden. Ein Hybrid (Section-Boundary plus sekundäres Hard-Split bei z. B. > 2000 Zeichen) wäre eine sinnvolle Iteration.
Eine ausführliche Beschreibung des Ingest-Pfads liegt bereits unter docs/notebooks-ingest-beschreibung.md – falls du dort weiter dokumentieren willst, ist diese Section-Chunking-Logik der zentrale Erklärungspunkt.