# TASK 01 – Qdrant erweitern für Metadatensuche

## Klärung: Was tatsächlich verwendet wird

`parse_grundschutz.py` wird nicht direkt vom Ingest aufgerufen – aber sein **Ergebnis** (`grundschutz.json`) ist die Quelle der Pipeline:

```
parse_grundschutz.py          map_grundschutz_pages_docling.py        apps/chainlit/ingest.py
       ↓                                  ↓                                    ↓
grundschutz.json    →    grundschutz_with_pages.json    →    Qdrant-Collection "grundschutz"
```

Das heißt: **Der Großteil der strukturellen Metadaten ist bereits in der Collection.** [apps/chainlit/ingest.py](../apps/chainlit/ingest.py) liest `grundschutz_with_pages.json` (Fallback: `grundschutz.json`) und schreibt diese Felder pro Anforderung ins Payload:

```
schicht_id, schicht_name, baustein_id, baustein_titel,
anforderung_id, anforderung_level, anforderung_typ, anforderung_typ_lang,
verantwortliche, zustaendigkeiten, modal_verben,
page_start, page_end, file, source, doc_type, document_id
```

## Was möglicherweise fehlt

Trotzdem gibt es **vier Bereiche**, in denen `parse_grundschutz.py` mehr extrahiert, als heute im Payload landet:

| # | Was fehlt | Wo es entstünde | Wert für die App |
|---|-----------|-----------------|------------------|
| 1 | **`cross_references`** (Verweise wie `["ORP.1", "CON.1"]`) | parse erzeugt es bereits | Verwandte Bausteine im Citation-Footer / „siehe auch" |
| 2 | **`rollen`** als eigene Dokumente (29 Rollen­definitionen) | Wird heute gar nicht ingestiert | Antworten auf „Was macht ein ISB?" |
| 3 | **Strukturierte Beschreibungs-Subsections** (`einleitung`, `zielsetzung`, `abgrenzung_und_modellierung`) | Heute als ein Block zusammen­gefasst | Feinere Retrieval-Treffer auf konkrete Aspekte |
| 4 | **`glossar.json`-Einträge** (Begriffsdefinitionen) | Datei existiert, wird nicht ingestiert | Antworten auf reine Begriffsfragen |

## Empfohlene Strategie: Additiv erweitern in dieselbe Collection

Drei Optionen, hier kurz gegenübergestellt:

- **Option A – Additiv in der vorhandenen Collection**: neue Payload-Felder ergänzen, neue `doc_type`-Werte einführen. Bestehende Felder bleiben unverändert.
  *Vorteil:* keine App-Änderung nötig, kein Cut-over.
  *Nachteil:* die alten Punkte enthalten die neuen Felder erst nach einem Re-Ingest.

- **Option B – Zweite Collection** (`grundschutz_v2`).
  *Vorteil:* sauberer Schnitt, A/B-Test möglich.
  *Nachteil:* App müsste umgeschaltet werden; doppelter Storage.

- **Option C – Kompletter Neu-Ingest** (recreate).
  *Vorteil:* sauberster Zustand.
  *Nachteil:* harter Cut, kein Fallback.

**Empfehlung: Option A mit *parallel* aufgebauter Collection als Sicherheits­netz** – also additive Schema-Erweiterung, aber zuerst gegen eine Test-Collection geschrieben, dann produktive Collection neu aufgebaut.

## Konkretes Vorgehen ohne Bruch

### Schritt 1 – Inventur der aktuellen Collection

Verifizieren, was tatsächlich drin ist, damit klar ist, was *nicht* dupliziert wird:

```python
# In Python-Konsole oder einem Cell:
from qdrant_client import QdrantClient
c = QdrantClient(url="http://localhost:6333")
# Stichprobe pro doc_type
for dt in ["anforderung", "baustein_beschreibung", "baustein_gefaehrdungslage",
           "elementare_gefaehrdung", "standard_abschnitt"]:
    pts, _ = c.scroll("grundschutz", limit=1,
                      scroll_filter={"must":[{"key":"doc_type","match":{"value":dt}}]},
                      with_payload=True)
    print(dt, "→", list(pts[0].payload.keys()) if pts else "—")
```

### Schritt 2 – Erweiterung in `_grundschutz_docs()` (rückwärts­kompatibel)

In [apps/chainlit/ingest.py](../apps/chainlit/ingest.py) drei *neue* Felder bzw. Dokumenttypen ergänzen, **ohne** ein bestehendes Feld zu ändern:

```python
# In _grundschutz_docs(): innerhalb der Anforderungs-Schleife
payload["cross_references"] = req.get("cross_references") or []

# Neue Dokumenttypen unterhalb der Bausteine
for sub_name in ("einleitung", "zielsetzung", "abgrenzung_und_modellierung"):
    sub_text = (b.get("beschreibung") or {}).get(sub_name)
    if not sub_text:
        continue
    yield Doc(
        text=sub_text,
        payload={
            **base_baustein_payload,
            "doc_type": "baustein_beschreibung_section",
            "section_name": sub_name,
            "page_start": ..., "page_end": ...,   # aus page_mapping_beschreibung.sections[sub_name]
        },
    )

# Neue Top-Level-Quellen
yield from _rollen_docs(gs.get("rollen", []))          # neue Funktion
yield from _glossar_docs(load_glossar())                # neue Funktion, doc_type="glossar_eintrag"
```

**Wichtig für Rückwärts­kompatibilität:**

- Keine Umbenennung. Alle alten Felder bleiben unverändert.
- Neue `doc_type`-Werte filtert die App nicht – `retrieve()` arbeitet ohne `doc_type`-Filter, weil die `query_filter`-Parameter `source_scope` und `standard_id` heißen, nicht `doc_type`.
- Index-Felder ergänzen: `client.create_payload_index(..., field_name="cross_references", field_schema=PayloadSchemaType.KEYWORD)`.

### Schritt 3 – Sicheres Roll-out

```bash
# 1. Ingest in eine separate Test-Collection
QDRANT_COLLECTION=grundschutz_v2 python -m apps.chainlit.ingest --recreate

# 2. Stichproben gegen die alte Collection vergleichen
#    (gleiche Query → sind die Top-K für anforderung_id stabil?)

# 3. Chainlit lokal gegen v2 testen
QDRANT_COLLECTION=grundschutz_v2 chainlit run apps/chainlit/app.py

# 4. Wenn ok: produktive Collection neu aufbauen
QDRANT_COLLECTION=grundschutz python -m apps.chainlit.ingest --recreate

# 5. Test-Collection abräumen
```

Die [apps/chainlit/rag_tool.py::format_citations()](../apps/chainlit/rag_tool.py) muss nicht angefasst werden – sie liest robust mit `.get()` und reagiert nicht negativ auf zusätzliche Felder. Der PDF-Viewer bleibt funktionsfähig, weil `file`, `page_start`, `page_end`, `baustein_id` und `anforderung_id` unverändert bestehen bleiben.

### Schritt 4 – Optional, falls Cross-References angezeigt werden sollen

Erst *nachdem* der Ingest die Daten liefert, kann in `format_citations()` eine Zeile ergänzt werden:

```python
if meta.get("cross_references"):
    lines.append("Siehe auch: " + ", ".join(meta["cross_references"]))
```

Das ist ein eigener, sehr kleiner PR – ohne Risiko für den Ingest.

## Zusammenfassung

- Es gibt **keine fehlenden Pflicht-Metadaten** für PDF-Viewer und Citations – diese funktionieren weiterhin.
- Was fehlt, sind die *Zusatz*-Felder `cross_references`, eigene Rollen-/Glossar-Dokumente und feinere Beschreibungs-Subsections.
- Die saubere Erweiterung erfolgt **additiv** im vorhandenen [apps/chainlit/ingest.py](../apps/chainlit/ingest.py), getestet zunächst gegen `grundschutz_v2`, danach produktiv per Re-Ingest in `grundschutz`.
- Kein App-Code muss geändert werden, solange nur neue Felder/Doc-Types ergänzt werden; eine Anzeige-Erweiterung (Querverweise im Citation-Footer) ist ein separater, optionaler Schritt.
