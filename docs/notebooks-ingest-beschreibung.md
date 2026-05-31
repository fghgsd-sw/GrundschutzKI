# Realisierung der Ingest-Pipeline (Verzeichnis `notebooks/`)

**Stand:** 2026-05-08
**Bezug:** [notebooks/](../notebooks/), [data/](../data/)
**Referenzartefakt:** Vektor-Collection `grundschutz_json` (Qdrant)

---

## 1. Übersicht und Zweck des Verzeichnisses

Das Verzeichnis [notebooks/](../notebooks/) bündelt die experimentelle Vor- und Hauptverarbeitung der IT-Grundschutz-Quellen sowie die Evaluierung der RAG-Pipeline (Retrieval Augmented Generation). Es bildet die *Build-Time*-Seite des Gesamtsystems ab: Es überführt die Rohdokumente des BSI in eine durchsuchbare Vektorrepräsentation, die zur Laufzeit von der Chainlit-Anwendung ([apps/chainlit/](../apps/chainlit/)) konsumiert wird.

Die Notebooks gliedern sich nach Verantwortlichkeiten und stellen damit die methodische **Strukturierung** des Lösungsentwurfs sicher:

| Notebook | Aufgabe | Ergebnis |
|----------|---------|----------|
| [00_upper_bound.ipynb](../notebooks/00_upper_bound.ipynb) | Obergrenzen-Evaluation mit „Real-Context" (Ground Truth) | Referenzwerte für RAGAS-Metriken |
| [01_rag_baseline.ipynb](../notebooks/01_rag_baseline.ipynb) | Basisvariante: XML → Zeichen-Chunking → Qdrant | Collection `grundschutz_xml` |
| [02_dspy_rag.ipynb](../notebooks/02_dspy_rag.ipynb) | DSPy-basierte Prompt-Optimierung der Antwortgenerierung | Optimierte Pipeline |
| [02_run_evaluation_example.ipynb](../notebooks/02_run_evaluation_example.ipynb) | Beispiel für eine einzelne Evaluations­ausführung | Metrik-Report (CSV) |
| [03_multi_run_evaluation_example.ipynb](../notebooks/03_multi_run_evaluation_example.ipynb) | Vorlage für Mehrfach­durchläufe mit Modellvergleich | Vergleichs­report |
| [05_json_preprocessing.ipynb](../notebooks/05_json_preprocessing.ipynb) | Produktive Variante: JSON → Anforderungs-Chunking → Qdrant | Collection `grundschutz_json` |

Ergänzend werden bereitgestellt:

- [notebooks/litellm_client.py](../notebooks/litellm_client.py) – gemeinsame Helfer­funktionen (LLM-, Embedding-, Qdrant-Zugriff)
- [notebooks/.env.example](../notebooks/.env.example) – Konfigurationsschablone (LiteLLM-Proxy, Embedding-Modell, Vektor­datenbank)
- [notebooks/README.md](../notebooks/README.md), [notebooks/Results.md](../notebooks/Results.md) – Dokumentation und Auswertung

### 1.1 Begründung der Gliederung

Die Trennung in *nummerierte, eigen­ständig lauffähige* Notebooks folgt dem Prinzip **„one notebook, one purpose"**. Dies hat drei Vorteile:

1. **Reproduzier­barkeit** – jede Variante (Baseline, JSON, DSPy) ist isoliert nachvollziehbar.
2. **Modularität** – gemeinsame Funktionalität ist in [litellm_client.py](../notebooks/litellm_client.py) gekapselt; Notebooks bleiben schlank.
3. **Vergleichbarkeit** – die Evaluations­notebooks erlauben einen direkten Metrik­vergleich zwischen Lösungs­varianten (siehe [notebooks/Results.md](../notebooks/Results.md)).

---

## 2. Architektur der Ingest-Pipeline

### 2.1 Datenfluss

```
data/data_raw/                  data/data_docling_json_ocr/        data/data_preprocessed/
┌───────────────────────┐       ┌──────────────────────┐           ┌──────────────────────┐
│ XML_Kompendium_       │       │ IT_Grundschutz_      │           │ grundschutz.json     │
│ 2023.xml              │──┐    │ Kompendium_2023.json │──┐        │ (Hierarchie:         │
│ standard_200_{1..4}.  │  │    │ standard_200_*.json  │  │        │  10 Schichten,       │
│ pdf                   │  │    └──────────────────────┘  │        │  111 Bausteine,      │
│ krt2023_Excel.xlsx    │  │              ▲               │        │  1.978 Anforderungen)│
└───────────────────────┘  │              │               │        │ grundschutz_with_    │
                           │      Docling (OCR/Layout)    │        │ pages.json           │
                           │              │               │        │ glossar.json         │
                           ▼              │               ▼        └──────────────────────┘
                  parse_grundschutz.py    │     map_grundschutz_pages_docling.py
                  (lxml / DocBook 5.0)    │              │
                           │              │              │
                           └──────────────┴──────────────┘
                                          │
                                          ▼
                  ┌───────────────────────────────────────────────┐
                  │  05_json_preprocessing.ipynb                  │
                  │   build_retrieval_docs(gs) →                  │
                  │   1.978 Dokumente {id, text, meta}            │
                  └───────────────────────────────────────────────┘
                                          │
                                          ▼ get_embeddings(batch_size=256)
                  ┌───────────────────────────────────────────────┐
                  │  LiteLLM-Proxy                                │
                  │  Modell: openai/octen-embedding-8b            │
                  │  Dimension: 4.096, float32                    │
                  └───────────────────────────────────────────────┘
                                          │
                                          ▼ client.upsert(batch_size=128)
                  ┌───────────────────────────────────────────────┐
                  │  Qdrant Vektor-Collection                     │
                  │  Name: grundschutz_json                       │
                  │  Distanz: COSINE,  Größe: 4.096               │
                  │  Payload: text + strukturierte Metadaten      │
                  └───────────────────────────────────────────────┘
```

### 2.2 Verantwortlichkeits­trennung

Die Pipeline trennt drei Stufen klar voneinander, was eine **fachspezifische Modularisierung** entlang des klassischen ETL-Musters (*Extract – Transform – Load*) widerspiegelt:

| Stufe | Verantwortlich | Artefakt |
|-------|----------------|----------|
| **Extract** | [parse_grundschutz.py](../scripts/parse_grundschutz.py) (XML), Docling (PDF) | Rohstrukturen in JSON |
| **Transform** | [05_json_preprocessing.ipynb](../notebooks/05_json_preprocessing.ipynb) (`build_retrieval_docs`) | Chunks mit Metadaten |
| **Load** | [litellm_client.py::get_embeddings](../notebooks/litellm_client.py), Qdrant `upsert` | Vektor-Collection |

Diese Trennung ermöglicht, jede Stufe unabhängig auszutauschen – beispielsweise das Embedding-Modell, ohne die Vorverarbeitung erneut anstoßen zu müssen.

---

## 3. Vorverarbeitung der Quellen

### 3.1 Quellmaterial

Im Verzeichnis [data/data_raw/](../data/data_raw/) liegen folgende autoritativen Quellen:

| Datei | Typ | Größe | Inhalt |
|-------|-----|-------|--------|
| `XML_Kompendium_2023.xml` | DocBook 5.0 | 3,1 MB | Strukturierte Quelle des Grundschutz­kompendiums |
| `IT_Grundschutz_Kompendium_Edition2023.pdf` | PDF | 5,5 MB | Druckfassung des Kompendiums |
| `standard_200_{1..4}.pdf` | PDF | 1,4 – 12 MB | BSI-Standards 200-1 bis 200-4 |
| `krt2023_Excel.xlsx` | Excel | 364 KB | Kreuzreferenztabelle |

### 3.2 XML-Parsing (autoritative Hauptquelle)

Das Skript [scripts/parse_grundschutz.py](../scripts/parse_grundschutz.py) parst `XML_Kompendium_2023.xml` mit `lxml` und dem DocBook-5.0-Namespace und erzeugt die kanonische JSON-Repräsentation `grundschutz.json`. Die Hierarchie spiegelt die Domänen­struktur des IT-Grundschutzes wider:

```
grundschutz.json
├── meta            (Quelle, Parse-Zeitstempel, Statistik)
├── rollen          (29 Rollendefinitionen)
├── elementare_gefaehrdungen   (47 Einträge: G 0.1 … G 0.47)
└── schichten       (10 Schichten: ISMS, ORP, CON, OPS, DER, APP, SYS, IND, NET, INF)
    └── bausteine   (111 Bausteine, z. B. ISMS.1)
        ├── beschreibung
        ├── gefaehrdungslage
        └── anforderungen
            ├── basis      (verpflichtende Maßnahmen)
            ├── standard   (Standard-Maßnahmen)
            └── erhoeht    (Maßnahmen bei erhöhtem Schutzbedarf)
                └── {id: "ISMS.1.A7", inhalt, typ, modal_verben: [...]}
```

**Entwurfs­entscheidung:** Die XML-Quelle wird als *autoritativ* gewählt, weil sie die semantischen Beziehungen (Rollen, Querverweise, Anforderungs­stufen) explizit kodiert. PDF-OCR liefert nur Fließtext und würde diese Strukturen verlieren.

### 3.3 PDF-Vorverarbeitung mit Docling (Fallback und Seitenmapping)

[Docling](https://github.com/DS4SD/docling) wird zur Erzeugung von [data/data_docling_json_ocr/](../data/data_docling_json_ocr/) verwendet. Die Konfiguration setzt deutsches OCR (`lang=['deu']`) und optionale Beschleunigung über `AcceleratorOptions` (CPU/CUDA). Daraus entsteht je PDF eine JSON-Repräsentation mit Seiten-, Layout- und Tabellen­informationen. Über [scripts/map_grundschutz_pages_docling.py](../scripts/map_grundschutz_pages_docling.py) wird daraus `grundschutz_with_pages.json` abgeleitet, das jeder Anforderung eine PDF-Seitenzahl zuordnet – Grundlage für die Quellen­anzeige in der Chainlit-Anwendung.

**Begründung der Wahl von Docling:** Docling vereinheitlicht die Behandlung nativer und gescannter PDFs, extrahiert Layout- und Tabellen­informationen und liefert ein portables JSON-Modell. Alternative Bibliotheken (`pypdf`, `pdfplumber`) liefern nur Text ohne Strukturen und keinen integrierten OCR-Pfad.

---

## 4. Chunking-Strategien

Es werden zwei Chunking-Verfahren implementiert und vergleichend evaluiert.

### 4.1 Variante A – Anforderungs-granular (produktiv)

Implementiert in [05_json_preprocessing.ipynb](../notebooks/05_json_preprocessing.ipynb), Funktion `build_retrieval_docs(gs)`:

```python
def build_retrieval_docs(gs):
    docs = []
    for schicht in gs.get('schichten', []):
        schicht_name = schicht.get('name')
        for b in schicht.get('bausteine', []):
            for level, reqs in (b.get('anforderungen') or {}).items():
                for req in reqs:
                    docs.append({
                        'id':   req.get('id'),               # z. B. "ISMS.1.A7"
                        'text': req.get('inhalt', ''),
                        'meta': {
                            'schicht':         schicht_name,
                            'baustein_id':     b.get('id'),
                            'baustein_titel':  b.get('titel'),
                            'level':           level,         # basis/standard/erhoeht
                            'typ':             req.get('typ'),
                            'modal_verben':    req.get('modal_verben', []),
                            'beschreibung':    (b.get('beschreibung') or {}).get('text', ''),
                            'gefaehrdungslage':(b.get('gefaehrdungslage') or {}).get('text', ''),
                        }
                    })
    return docs
```

**Eigenschaften:**

- **Granularität:** eine Anforderung = ein Chunk (≈ 100 – 500 Tokens)
- **Überlappung:** keine (semantisch abgeschlossene Einheiten)
- **Anzahl:** 1.978 Chunks
- **Metadaten:** reichhaltig (Schicht, Baustein, Anforderungs­stufe, Modal­verben)

**Begründung:** Anforderungen sind im IT-Grundschutz die kleinsten *normativen Einheiten*. Ein Chunking auf dieser Ebene wahrt die semantischen Grenzen, ermöglicht spätere Filterung nach `level` (Pflicht vs. Empfehlung) und erlaubt die Auswertung von Modal­verben (MUSS, SOLLTE, DARF) zur Klassifikation der Verbindlichkeit.

### 4.2 Variante B – Zeichen-basiertes Sliding-Window (Baseline)

Implementiert in [01_rag_baseline.ipynb](../notebooks/01_rag_baseline.ipynb):

```python
CHUNK_SIZE = 2000        # Zeichen
CHUNK_OVERLAP = 200      # Zeichen (10 %)
chunks, start = [], 0
while start < len(joined):
    end = start + CHUNK_SIZE
    chunks.append(joined[start:end])
    start = end - CHUNK_OVERLAP
```

**Eigenschaften:**

- 2.000 Zeichen Fenstergröße, 200 Zeichen Überlappung
- 2.077 Chunks aus dem konkatenierten XML-Text
- Keine strukturellen Metadaten

**Begründung der Beibehaltung als Baseline:** Variante B dient als Referenz, gegen die die strukturierte Variante A in den RAGAS-Metriken vergleichbar gemacht werden kann.

### 4.3 Bewertung im Vergleich

[notebooks/Results.md](../notebooks/Results.md) dokumentiert für vier Konfigurationen die RAGAS-Kennzahlen `context_precision`, `context_recall`, `faithfulness` und `answer_correctness`. Die JSON-basierte Variante mit `top_k = 6` erreicht mit **60,57 %** die höchste Antwort­korrektheit und wird als produktive Variante übernommen.

---

## 5. Embedding-Stufe

### 5.1 Modellwahl und Konfiguration

Das Embedding-Modell wird über die Umgebungs­variable `EMBEDDING_MODEL` festgelegt (Beispiel: `openai/octen-embedding-8b`) und über einen lokalen LiteLLM-Proxy angesprochen. Der Aufruf erfolgt aus­schließlich über den Helper [`get_embeddings`](../notebooks/litellm_client.py#L127-L152):

```python
def get_embeddings(texts, config=None, batch_size=32):
    from litellm import embedding
    cfg = config or load_llm_config()
    _ensure_litellm_model_costs(cfg)
    all_texts = list(texts)
    embeddings = []
    for start in range(0, len(all_texts), batch_size):
        batch = all_texts[start : start + batch_size]
        response = embedding(
            model=cfg.embedding_model,
            input=batch,
            encoding_format="float",
            api_key=cfg.api_key,
            api_base=cfg.api_base,
        )
        embeddings.extend([item["embedding"] for item in response["data"]])
    return embeddings
```

**Vektor­dimension:** 4.096 (float32)
**Batch-Größe:** Default 32, in den Notebooks bis 256 – 512

**Entwurfsentscheidung – LiteLLM als Abstraktions­schicht:** Die Anbindung erfolgt nicht direkt an einen Anbieter, sondern über LiteLLM. Damit werden Modell­wechsel (anderer Embedding-Anbieter, lokal gehostetes Modell) ohne Code­änderung möglich – nur die `.env`-Variable wird angepasst. Dies erfüllt das Prinzip der **lockeren Kopplung** und schützt das Projekt vor Vendor-Lock-in.

### 5.2 Kostenregistrierung

Da `octen-embedding-8b` kein bei LiteLLM hinterlegtes Modell ist, registriert [`_ensure_litellm_model_costs`](../notebooks/litellm_client.py#L65-L113) die Modellnamen mit Null­kosten, um Laufzeit-Warnungen zu vermeiden. Diese defensive Registrierung erfolgt einmalig pro Prozess (Idempotenz via `_MODEL_COSTS_REGISTERED`).

---

## 6. Vektordatenbank: Aufbau und Befüllung

### 6.1 Anbindung an Qdrant

Der Qdrant-Client wird zentral über [`get_qdrant_client`](../notebooks/litellm_client.py#L168-L175) erzeugt; URL und API-Schlüssel kommen aus der Konfiguration (`VECTORDB_URL` / `QDRANT_URL`):

```python
def get_qdrant_client(config=None):
    from qdrant_client import QdrantClient
    cfg = config or load_vectordb_config()
    return QdrantClient(url=_require(cfg.url, "VECTORDB_URL or QDRANT_URL"),
                        api_key=cfg.api_key)
```

### 6.2 Collection-Schema

```python
from qdrant_client.http import models as qmodels

client.recreate_collection(
    collection_name="grundschutz_json",
    vectors_config=qmodels.VectorParams(
        size=4096,
        distance=qmodels.Distance.COSINE,
    ),
)
```

**Entwurfsentscheidung – COSINE-Distanz:** Für textuelle Embeddings ist die Kosinus­ähnlichkeit der Standard; sie ist skaleninvariant und korreliert empirisch besser mit semantischer Nähe als die euklidische Distanz.

**Entwurfsentscheidung – `recreate_collection` in Notebooks:** Notebook-Läufe legen die Collection bewusst jedes Mal neu an, um Reproduzier­barkeit zu garantieren. In einem produktiven Pipeline-Skript wäre ein inkrementelles Upsert vorzuziehen.

### 6.3 Aufbau der Punkte (PointStruct)

```python
points = [
    qmodels.PointStruct(
        id=idx,
        vector=vec,
        payload={"text": text, **meta},
    )
    for idx, (text, vec, meta) in enumerate(zip(chunks, embeddings, metas))
]
```

Pro Punkt werden Vektor (4.096 Dim.) und ein flaches Payload-Dictionary mit den unter Abschnitt 4.1 beschriebenen Metadaten gespeichert. Die ID ist eine fortlaufende Ganzzahl; das ermöglicht deterministische `upsert`-Aufrufe und einfache Wiederverwendung.

### 6.4 Stapelweises Upsert

```python
BATCH_SIZE = 128
for start in range(0, len(points), BATCH_SIZE):
    client.upsert(
        collection_name="grundschutz_json",
        points=points[start : start + BATCH_SIZE],
    )
```

**Begründung der Batch-Größe:** 128 Punkte pro Aufruf vermeiden Timeouts bei größeren Payloads, ohne unnötigen HTTP-Overhead zu verursachen.

---

## 7. Konfigurations­management

Sämtliche Laufzeit­parameter werden über die `.env`-Datei im Notebook-Verzeichnis bezogen ([notebooks/.env.example](../notebooks/.env.example)):

```env
LITELLM_API_BASE=http://10.127.129.0:4000/v1/
LITELLM_API_KEY=sk-***
LLM_MODEL=openai/gpt-oss-120b
EMBEDDING_MODEL=openai/octen-embedding-8b
VECTORDB_PROVIDER=qdrant
VECTORDB_URL=http://localhost:6333
VECTORDB_COLLECTION=grundschutz_json
```

Das Laden erfolgt defensiv: `python-dotenv` wird in einem `try`-Block importiert; fehlt das Paket, fällt der Code auf reine Prozess­umgebungs­variablen zurück ([litellm_client.py](../notebooks/litellm_client.py#L12-L22)).

**Entwurfsentscheidung – `.env` außerhalb der Quellen:** Geheime Schlüssel (LLM-API-Key) liegen nicht im Repository, sondern in einer ignorierten Datei. Die Vorlage `.env.example` dokumentiert die erwarteten Schlüssel ohne Werte.

---

## 8. Auswertungs­ergebnisse

Die in [notebooks/Results.md](../notebooks/Results.md) protokollierten Mess­ergebnisse rechtfertigen die produktive Konfiguration:

| Variante | `context_precision` | `context_recall` | `faithfulness` | `answer_correctness` |
|----------|--------------------:|-----------------:|---------------:|---------------------:|
| Original-Pipeline | **95,59 %** | 87,02 % | **86,55 %** | 59,29 % |
| JSON, `top_k = 3` | 93,22 % | 84,69 % | 76,47 % | 55,38 % |
| **JSON, `top_k = 6`** | 92,89 % | 88,64 % | 77,92 % | **60,57 %** |
| JSON, `top_k = 8` | 87,62 % | **91,85 %** | 74,86 % | 58,10 % |

Die Konfiguration *JSON, `top_k = 6`* maximiert die Antwort­korrektheit bei akzeptablem Precision/Recall-Trade-off und wird daher in der produktiven Pipeline verwendet.

---

## 9. Zusammenfassung der Entwurfsentscheidungen

| Entscheidung | Begründung | Beleg im Code |
|--------------|------------|---------------|
| Anforderungs-granulares Chunking | Wahrung semantischer Grenzen; ermöglicht Filterung nach Verbindlichkeitsstufe | [`build_retrieval_docs`](../notebooks/05_json_preprocessing.ipynb) |
| XML als autoritative Quelle | Erhalt struktureller Metadaten (Schicht, Baustein, Anforderungs-ID) | [scripts/parse_grundschutz.py](../scripts/parse_grundschutz.py) |
| Docling für PDFs | Vereinheitlichte Behandlung von OCR/Layout für Seitenmapping | [data/data_docling_json_ocr/](../data/data_docling_json_ocr/) |
| JSON als Zwischenformat | Entkopplung von Extraktion und Embedding; Portabilität | `grundschutz.json`, `grundschutz_with_pages.json` |
| LiteLLM-Proxy | Vendor-neutrale Abstraktion; Modell­wechsel ohne Code­änderung | [litellm_client.py](../notebooks/litellm_client.py) |
| Qdrant + COSINE + 4.096 Dim. | Standard für Text-Embeddings; skaleninvariant | `VectorParams(distance=Distance.COSINE)` |
| Stapel­weises Embedden/Upserten | API-Effizienz, Robustheit gegen Timeouts | `batch_size=256` (Embed), `BATCH_SIZE=128` (Upsert) |
| `recreate_collection` in Notebooks | Reproduzier­bare Experimente | Aufruf in [05_json_preprocessing.ipynb](../notebooks/05_json_preprocessing.ipynb) |
| Gemeinsame Helfer in `litellm_client.py` | Modularisierung, DRY-Prinzip | Import in allen Notebooks |
| `.env`-basierte Konfiguration | Trennung von Konfiguration und Code; Geheimnis­schutz | [`load_llm_config`](../notebooks/litellm_client.py#L50-L63) |

---

## 10. Kontext zur Laufzeit­anwendung

Die in den Notebooks aufgebaute Qdrant-Collection `grundschutz_json` wird zur Laufzeit von der Chainlit-Anwendung in [apps/chainlit/rag_tool.py](../apps/chainlit/rag_tool.py) konsumiert:

- Die Funktion `retrieve(query, top_k)` führt eine analoge Embedding-Anfrage über LiteLLM aus.
- Sie ruft denselben Collection-Namen auf, der hier befüllt wurde.
- Sie liest dieselben Payload-Felder (`text`, `baustein_id`, `schicht`, …) und transformiert sie in die `RagResult`-Datenstruktur, die der Chat-Frontend rendert.

Die Notebooks bilden damit den vollständig nachvollziehbaren *Vorlauf* zur produktiven Anwendung; die Reproduzier­barkeit der Wissens­basis ist über die im Repository abgelegten Quellen, Skripte und Notebooks vollständig gewahrt.
