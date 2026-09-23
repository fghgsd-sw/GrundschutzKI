# TASK_10: Hybrid Retrieval mit BGE-M3 (Dense + Sparse)

## Kontext

Das aktuelle RAG-System nutzt BGE-M3 ausschließlich für **Dense-Retrieval** (1024-dimensionale Embedding-Vektoren, Kosinus-Ähnlichkeit in Qdrant). BGE-M3 generiert beim Encoding jedoch gleichzeitig drei Vektortypen:

| Vektortyp | Beschreibung | Aktuell genutzt |
|---|---|---|
| **Dense** | 1024-dim Embedding, semantische Ähnlichkeit | ✓ |
| **Sparse** | Token-Gewichte (ähnlich BM25), exakte Terminologie | ✗ |
| **ColBERT** | Multi-Vektor, Late Interaction | ✗ |

Der Sparse-Vektor wird beim Ingest aktuell nicht berechnet bzw. nicht in Qdrant gespeichert. Gerade für IT-Grundschutz-Anforderungen mit präzisen Bezeichnungen (z. B. `SYS.1.2.A5`, `APP.3.2`, `ORP.4`) ist Sparse-Retrieval besonders relevant, da diese exakten Ausdrücke durch rein semantisches Embedding nicht zuverlässig priorisiert werden.

Empfehlung aus der BGE-M3-Dokumentation (HuggingFace):
> *„Hybrid retrieval leverages the strengths of various methods, offering higher accuracy and stronger generalization capabilities. [...] You can try to use BGE-M3, which supports both embedding and sparse retrieval. This allows you to obtain token weights (similar to BM25) without any additional cost when generating dense embeddings."*

### Praxisbeispiel 1: beobachteter Recall-Fehler (2026-06-29)

Frage: *„Was ist bei der Auswahl der Planung von Software-Tests zu beachten?"*

Erwarteter Treffer: Baustein **OPS.1.1.6 „Software-Tests und -Freigaben"**, insbesondere `OPS.1.1.6.A1` — Titel wörtlich **„Planung der Software-Tests"**, Text beginnt mit „Die Rahmenbedingungen für Software-Tests MÜSSEN vor den Tests innerhalb der Institution entsprechend der Schutzbedarfe... festgelegt sein." Ein nahezu perfekter lexikalischer **und** semantischer Treffer.

Tatsächliches Retrieval-Ergebnis (Top-8, dense-only, drei Versuche mit leicht variierter Query): **keiner der 16 OPS.1.1.6-Chunks** war darunter. Stattdessen dominierten `standard_abschnitt`-Chunks aus Standard 200-2/200-3 mit eng beieinanderliegenden Scores (0,62–0,67) — generische Methodik-Kapitel wie „6.2.4 Ermittlung konkreter Maßnahmen aus Anforderungen" oder „8.3 Modellierung eines Informationsverbunds".

Plausible Erklärung: Die Frage enthält sowohl den spezifischen Fachbegriff („Software-Tests") als auch dominante generische Methodik-Begriffe („Auswahl", „Planung", „zu beachten"). Da der Korpus sehr viele, sich stark ähnelnde Standard-200-2-Methodik-Chunks enthält, zieht dieser große, homogene Cluster den Dense-Vektor der Anfrage zu sich; der seltenere, aber exakt passende Fachbegriff geht im gemittelten Satzvektor unter — obwohl er wortwörtlich im Titel des richtigen Chunks steht. Das LLM hat in der Folge aus Parameterwissen geantwortet (inkl. falsch erinnerter Baustein-ID `APP.3.3` statt `OPS.1.1.6`) und die – inhaltlich nicht passenden – tatsächlich abgerufenen Standard-200-2-Chunks als Zitate verwendet.

Dieser Fall ist ein Lehrbuchbeispiel für die in der Einleitung beschriebene Schwäche: Sparse-/BM25-Signal hätte den exakten Term „Software-Tests" unabhängig von der semantischen Verdünnung durch die Methodik-Begriffe hochgewichtet.

### Praxisbeispiel 2: Recall-Fehler trotz nahezu wörtlicher Übereinstimmung (2026-06-29)

Frage: *„Wie muss mit Zutritts-, Zugangs- und Zugriffsrechten organisatorisch umgegangen werden?"*

Erwarteter Treffer: `ORP.4.A5 "Vergabe von Zutrittsberechtigungen"`, `ORP.4.A6 "Vergabe von Zugangsberechtigungen"`, `ORP.4.A7 "Vergabe von Zugriffsrechten"` — die drei Anforderungstitel enthalten **wortwörtlich** exakt die drei in der Frage genannten Begriffe (Zutritt, Zugang, Zugriff).

Tatsächliches Retrieval-Ergebnis (Top-5, dense-only, ohne `baustein_id`-Filter): Keiner der drei ORP.4-Treffer erscheint. Stattdessen führt `OPS.1.2.4 Gefaehrdungslage` (Telearbeit, Score 0,687) deutlich vor `INF.5.A3` (0,634), `OPS.3.2.A17` (0,634), `IND.1.A7` (0,629) und erst danach `OPS.1.2.4.A2` (0,628) — ORP.4 fehlt komplett unter den Top-5.

Dieser Fall ist besonders aufschlussreich, weil er zeigt, dass selbst eine **nahezu perfekte lexikalische Übereinstimmung** (drei exakte Fachbegriffe im Anforderungstitel) gegen einen thematisch breiteren, vokabularreichen Gefährdungslage-Chunk verlieren kann. Reines Dense-Retrieval hat hier keinen Mechanismus, exakte Terminologie-Treffer gegenüber genereller semantischer Themennähe zu privilegieren — exakt die Lücke, die Sparse-/BM25-Gewichtung schließen würde.

**Hinweis zur Fehlerkette:** In den ersten Testläufen zu dieser Frage setzte das Modell zusätzlich eigenständig `baustein_id="OPS.1.2.4"` (vermutlich aus dem Kontext der unmittelbar vorangegangenen Telearbeit-Frage übernommen), obwohl die ID nirgends im aktuellen Fragetext vorkam — ein Verstoß gegen die System-Prompt-Regel. Dies wurde durch einen zusätzlichen Code-Check behoben (`baustein_id` wird nur noch akzeptiert, wenn sie wörtlich in der aktuellen Nutzernachricht steht, app.py `main()`). Nach diesem Fix blieb der Recall-Fehler jedoch unverändert bestehen — er ist nicht durch die `baustein_id`-Logik verursacht, sondern liegt, wie oben beschrieben, im reinen Dense-Retrieval selbst.

### Praxisbeispiel 3: Nur 2 von 16 Anforderungen gefunden (2026-06-29)

Frage: *„Welche Anforderungen sollte ich berücksichtigen, wenn ich einen Webserver in meiner Organisation selbst betreiben möchte?"*

Baustein `APP.3.2 "Webserver"` umfasst 16 Anforderungen (A1–A20, u. a. Konfiguration, Dateischutz, TLS-Verschlüsselung, Sicherheitsrichtlinie, DoS-Schutz, Penetrationstests). Tatsächliches Retrieval-Ergebnis (Top-8, dense-only, ohne `baustein_id`-Filter, nur eine Tool-Runde): Nur `APP.3.2.A1` (Score 0,551) und `APP.3.2.A2` (Score 0,528) erscheinen — die übrigen sechs Top-8-Plätze gehen an `baustein_beschreibung`/`baustein_gefaehrdungslage`-Chunks **anderer, thematisch nur locker verwandter Bausteine** (Webanwendungen und Webservices, Webbrowser, Fileserver), die wegen der gemeinsamen Vokabel „Web"/„Server" hoch scoren, ohne inhaltlich zur Frage zu passen.

Ergebnis: Die Antwort behandelt nur 2 von 16 tatsächlich relevanten Anforderungen — nicht weil die anderen 14 nicht existieren oder nicht zitierfähig wären, sondern weil sie beim Retrieval gegen vokabularnahe, aber falsche Bausteine verlieren. Dieser Fall zeigt eine andere Ausprägung derselben Schwäche als Beispiel 1 und 2: Hier verdrängen nicht generische Methodik-Chunks, sondern **andere, oberflächlich ähnlich benannte Bausteine** die korrekten, spezifischeren Treffer.

### Praxisbeispiel 4: Drei nachweisbare Mechanismen für irreführende Scores (2026-06-30)

Frage (Laienformulierung ohne IT-Grundschutz-Fachvokabular): *„Welche Anforderungen sind zu beachten, wenn man in einer Anwendung besonders vertrauliche personenbezogene Daten verarbeiten möchte?"*

Erwarteter thematischer Bereich: Schicht `ORP` (Organisation und Personal). Tatsächliches Retrieval-Ergebnis: Top-Treffer u. a. `baustein_beschreibung`/`baustein_gefaehrdungslage` von **INF.11 „Allgemeines Fahrzeug"** (Score 0,40–0,40), ein Satz aus einem Notfall-Meldeformular („Meldestelle Führungskraft Personal", Score 0,429) sowie generische Methodik-Chunks zu „Anforderungen" als Konzept — keine ORP-Anforderung unter den Top-Treffern. Anhand der tatsächlichen Chunk-Texte ließen sich drei unterschiedliche, jeweils belegbare Ursachen identifizieren:

**Mechanismus A — echte, aber kontextfremde Wortübereinstimmung:** Der Gefährdungslage-Chunk von INF.11 enthält wortwörtlich „...können **vertrauliche Informationen** offengelegt werden... könnten schützenswerte Informationen wie **personenbezogene Daten** offengelegt werden" — exakt das Vokabular der Frage, nur im Kontext eines WLAN/Bluetooth-Datenlecks bei Fahrzeugen, nicht als allgemeine Anforderung. Dense-Embeddings unterscheiden nicht zwischen „Text behandelt dieses Thema zentral" und „Text erwähnt diese Begriffe beiläufig in einem Gefahren-Szenario".

**Mechanismus B — Meta-Ebenen-Treffer auf das Wort „Anforderungen" selbst:** Chunks wie „Sicherheitsanforderungen" (Standard 200-2, p.133: „Die Anforderungen sind in drei Kategorien unterteilt: Basis-Anforderungen... Standard-Anforderungen...") oder `NET.1.1.A3` („...MUSS eine Anforderungsspezifikation erstellt werden") reden über das **Konzept** „Anforderung", nicht über inhaltliche Anforderungen zum gefragten Thema — ziehen die Suche aber an, weil die Frage „Welche Anforderungen..." lautet. Strukturell identisch zu Beispiel 1.

**Mechanismus C — sehr kurze, informationsarme Chunks streuen instabil:** Der komplette Text des Chunks „Meldestelle Führungskraft Personal" lautet: „Sobald mindestens eine Frage mit JA beantwortet werden kann, bitte umgehend an die Stabsleitung melden: Telefon 1234567890" — ein Satz aus einem Beispiel-Meldeformular im Notfallmanagement, fachlich irrelevant. Sehr kurze, inhaltsarme Chunks erzeugen Embedding-Vektoren mit wenig semantischem Anker und landen dadurch in weniger trennscharfen Bereichen des Vektorraums — sie können gegen viele unterschiedliche Anfragen mittelmäßig hoch scoren, ohne zu einer davon wirklich zu passen.

**Einordnung:** Alle drei Mechanismen bestätigen dieselbe Grundschwäche, aber Mechanismus A ist der schärfste Beleg: Selbst **exaktes Vokabular** im Chunk-Text führt nicht zuverlässig zu inhaltlich passenden Treffern. Ein Sparse-/BM25-Signal würde Mechanismus B und C anders gewichten (Begriffshäufigkeit/-dichte im Chunk spielt eine Rolle, die Dense-Embeddings fehlt), bei Mechanismus A allein würde aber auch Sparse-Retrieval den falschen Chunk hochgewichten — hier wäre zusätzlich Re-Ranking (Cross-Encoder, siehe unten) oder Schicht-/Baustein-Filterung wirksam. Ein neuer `schicht_id`-Filter (analog zu `baustein_id`, app.py/rag_tool.py) wurde ergänzt, der bei wörtlicher Nennung eines Schichtkürzels (z. B. „ORP") greift — hilft aber nicht bei Laienformulierungen wie dieser, die kein Schichtkürzel nennen.

---

## Optimierungspotenzial

### 1. Sparse Retrieval (BGE-M3 Sparse Vectors)

BGE-M3 gibt beim Encoding neben dem Dense-Vektor ein Dictionary aus Token-IDs und zugehörigen Gewichten zurück. Diese Sparse-Repräsentation verhält sich wie ein gelerntes BM25: Häufige, generische Tokens erhalten niedrige Gewichte, seltene, domänenspezifische Terme hohe. Qdrant unterstützt Sparse Vectors nativ als eigenständigen Vektortyp (`SparseVector`).

**Erwarteter Gewinn:** Höhere Context Precision bei Anfragen mit exakten Baustein-IDs oder Anforderungskennzeichen.

### 2. Hybrid Search (Dense + Sparse, Reciprocal Rank Fusion)

Qdrant bietet Hybrid Search mit **Reciprocal Rank Fusion (RRF)**: Die Rankinglisten aus Dense- und Sparse-Retrieval werden fusioniert, sodass Chunks, die in beiden Listen weit oben stehen, bevorzugt werden. Dies kombiniert semantisches Verständnis (Dense) mit Termgenauigkeit (Sparse).

**Erwarteter Gewinn:** Robustere Retrieval-Qualität über unterschiedliche Fragetypen; besonders bei Fragen, die sowohl semantisch vage als auch terminologisch spezifisch sind.

### 3. Re-Ranking mit Cross-Encoder (bge-reranker-v2)

Nach dem initialen Retrieval (Top-K Kandidaten) kann ein Cross-Encoder die Kandidaten neu bewerten. Cross-Encoder sind deutlich präziser als Bi-Encoder-Embeddings, da sie Frage und Chunk gemeinsam kodieren. BGE-Reranker-v2 ist kompatibel mit BGE-M3.

**Erwarteter Gewinn:** Höhere Precision bei gleichbleibendem Recall; reduziert irrelevante Chunks im LLM-Kontext.

---

## Aufwandsabschätzung

| Maßnahme | Implementierungsaufwand | Infrastrukturaufwand | Priorisierung |
|---|---|---|---|
| Sparse Retrieval (BGE-M3) | mittel — Ingest-Skript anpassen | Neu-Ingest der Collection | hoch |
| Hybrid Search in Qdrant (RRF) | gering — Query-Seite anpassen | keine | hoch |
| Cross-Encoder Re-Ranking | mittel — eigener Aufruf nach Retrieval | Modell lokal oder eigener Endpunkt | mittel |

### Vorab-Klärung: Optionen für Sparse-Vektoren (Stand 2026-07-10)

Da das Embedding über IONOS' OpenAI-kompatible REST-API läuft (`EMBED_MODEL=openai/BAAI/bge-m3`, Aufruf via `litellm.aembedding()` in `llm.py`), wurden drei Optionen zur Beschaffung von Sparse-Vektoren geprüft:

#### Option A — IONOS-Endpunkt auf proprietäre Sparse-Erweiterung testen ✗ abgeschlossen

Testaufruf gegen `https://openai.inference.de-txl.ionos.com/v1/embeddings` mit Modell `BAAI/bge-m3` (2026-07-10):

```
Top-level keys: ['object', 'data', 'model', 'usage', 'id', 'created']
data[0] keys: ['object', 'embedding', 'index']
embedding length: 1024
```

**Ergebnis:** Die Antwort entspricht exakt dem Standard-OpenAI-Schema — ein 1024-dimensionaler Dense-Vektor, keine weiteren Felder. IONOS macht BGE-M3-Sparse-Output nicht zugänglich. Option A scheidet aus.

#### Option B — BM25 lokal als Sparse-Ersatz ← gewählter Ansatz

`bm25s` (reines Python, keine GPU) berechnet Sparse-Vektoren aus dem Chunk-Text anhand von TF-IDF-Gewichten über den Gesamtkorpus. Das Ergebnis ist ein Dictionary `{token_id: weight}` pro Chunk, das als `SparseVector` in Qdrant gespeichert wird. Zur Laufzeit wird die Query mit denselben IDF-Gewichten tokenisiert — der BM25-Index wird beim Start aus einer serialisierten Datei geladen, kein API-Aufruf nötig.

**Qualität:** Regelbasiert, deterministisch. Exakte Terme wie `OPS.1.1.6` oder `Planung der Software-Tests` erhalten hohe Gewichte, weil sie selten im Gesamtkorpus sind. Schwächer als BGE-M3-Sparse bei Morphologie-Varianten, aber für die dokumentierten Recall-Fehler (exakte ID- und Titel-Treffer) ausreichend. Kein Infrastrukturaufwand zur Laufzeit.

#### Option C — BGE-M3 lokal via FlagEmbedding (Ollama)

`FlagEmbedding.BGEM3FlagModel` lädt das vollständige BGE-M3-Modell (~2,3 GB) und gibt beim `encode()`-Aufruf gleichzeitig Dense-, Sparse- und ColBERT-Vektoren zurück. Die gelernten Sparse-Gewichte (Lexical Weights) erfassen Synonyme und Morphologie besser als BM25. **Aber:** Das Modell muss auch zur Laufzeit verfügbar sein (nicht nur beim Ingest), da die Query-Seite ebenfalls einen Sparse-Vektor benötigt — IONOS liefert diesen nicht. Das erfordert entweder das Modell dauerhaft im Container (~4–6 GB RAM) oder einen separaten Embedding-Dienst parallel zur IONOS-API. Deutlich größerer Infrastrukturaufwand als Option B.

| | Option A | Option B (BM25) | Option C (BGE-M3 Sparse) |
|---|---|---|---|
| Sparse-Quelle | IONOS-API | bm25s lokal | FlagEmbedding lokal |
| Machbar | ✗ (kein Support) | ✓ | ✓ (mit Mehraufwand) |
| Sparse-Qualität | — | regelbasiert, gut für exakte Terme | neuronal, besser bei Varianten |
| Laufzeit-Infrastruktur | keine Änderung | BM25-Index-Datei, ~ms | Modell im Container, ~4–6 GB |
| Aufwand gesamt | — | ~1 Arbeitstag | ~2–3 Arbeitstage |
| Methodische Sauberkeit (MA) | — | „pragmatische Alternative" | „state-of-the-art per Chen et al. 2024" |

**Entscheidung:** Option B wird umgesetzt. Option C bleibt als Ausblick dokumentiert.

---

## Umsetzungsplan Option B — BM25 Hybrid Retrieval

### Ausgangslage

- `ingest.py` upserted einen Dense-Vektor pro Chunk in Collection `grundschutz_bge_m3`
- `rag_tool.py`: `embed(query)` → `client.query_points(query=dense_vec)` — kein Sparse-Pfad
- Qdrant-Collection kennt nur einen Vektortyp (`dense`, 1024-dim)

### Schritt 1: Dependency

`bm25s` in `requirements.txt` / `pyproject.toml` ergänzen. Kein Modell-Download, keine GPU-Abhängigkeit.

### Schritt 2: Ingest erweitern (`ingest.py`)

Nach dem Sammeln aller `Doc`-Objekte:

1. BM25-Korpus über alle `doc.text` aufbauen
2. BM25-Index serialisieren → `bm25_index/` (bm25s eigene `save()`-API)
3. Sparse-Vektor pro Chunk berechnen: `{token_id: weight}` → `SparseVector`
4. Neue Collection `grundschutz_bge_m3_hybrid` anlegen:

```python
from qdrant_client.models import SparseVectorParams, SparseIndexParams

client.recreate_collection(
    collection_name="grundschutz_bge_m3_hybrid",
    vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
    sparse_vectors_config={
        "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
    },
)
```

5. Upsert mit `vectors={"dense": dense_vec}` und `sparse_vectors={"sparse": SparseVector(...)}`.

Bestehende Collection `grundschutz_bge_m3` bleibt bis zur Umschaltung erhalten.

### Schritt 3: Query-Seite (`rag_tool.py`)

1. BM25-Index beim Start laden (analog `_citation_map`, einmalig gecacht)
2. In `retrieve()`: Query tokenisieren → BM25-Sparse-Vektor berechnen
3. `client.query_points()` auf Hybrid-Query umstellen:

```python
from qdrant_client.models import Prefetch, FusionQuery, Fusion, SparseVector

results = client.query_points(
    collection_name=QDRANT_COLLECTION,
    prefetch=[
        Prefetch(query=dense_vec, using="dense", limit=top_k * 2),
        Prefetch(query=SparseVector(indices=..., values=...), using="sparse", limit=top_k * 2),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=top_k,
    query_filter=query_filter,  # baustein_id / schicht_id-Filter bleiben unverändert
)
```

**Hinweis:** `SCORE_THRESHOLD` gilt nicht für RRF-Scores (andere Skala, ~0–1 nach RRF-Normierung). Threshold für Hybrid-Queries deaktivieren oder separat über `HYBRID_SCORE_THRESHOLD` konfigurieren.

### Schritt 4: Konfiguration (`.env` / `settings.py`)

- `QDRANT_COLLECTION=grundschutz_bge_m3_hybrid` nach Umschaltung
- `BM25_INDEX_PATH=./bm25_index`
- Optional: `HYBRID_RETRIEVAL=true` als Feature-Flag für parallelen A/B-Betrieb

### Schritt 5: Validierung

Die vier Recall-Fehler aus den Praxisbeispielen oben als Testfragen durchspielen:

| Testfrage | Erwarteter Treffer | Bisheriges Ergebnis |
|---|---|---|
| „Was ist bei der Planung von Software-Tests zu beachten?" | `OPS.1.1.6.A1` | nicht in Top-8 |
| „Wie muss mit Zutritts-, Zugangs- und Zugriffsrechten umgegangen werden?" | `ORP.4.A5/A6/A7` | nicht in Top-5 |
| „Anforderungen für selbst betriebenen Webserver?" | 16 `APP.3.2`-Chunks | nur 2 von 16 |
| „Anforderungen für Verarbeitung personenbezogener Daten?" (Laienformulierung) | ORP-Schicht | kein ORP-Treffer in Top-K |

Erwartung: Sparse-Signal hebt exakte Terme (`OPS.1.1.6`, `Zutrittsberechtigungen`, `APP.3.2`) gegenüber thematisch ähnlichen, aber falschen Chunks an. Bei Laienformulierungen (Beispiel 4, kein Fachvokabular) ist der Gewinn durch BM25 allein begrenzt — dort bleibt Schicht-Filterung oder Re-Ranking der wirksamere Hebel.

### Aufwand

| Schritt | Aufwand |
|---|---|
| Dependency + BM25-Index-Aufbau im Ingest | 2–3 h |
| Neue Collection + Re-Ingest | ~1 h Laufzeit |
| Query-Seite (Prefetch + RRF) | 2–3 h |
| Validierung | 1–2 h |
| **Gesamt** | **~1 Arbeitstag** |

---

## Bezug zur laufenden Evaluation

Die abgeschlossenen Evaluationsläufe (vier Modelle, 43 Komplexe Fragen) verwenden ausschließlich Dense-Retrieval und bilden damit die **Baseline**. Hybrid Retrieval wäre eine eigenständige Evaluationsbedingung (`docling-sections + bge-m3-hybrid`) und erlaubt eine direkte Vergleichsaussage:

> *„Verbessert Hybrid Retrieval die Context Precision gegenüber reinem Dense-Retrieval — bei gleichem LLM und gleichen Fragen?"*

Dies eignet sich als Ausblick oder separate Untersuchung in einer wissenschaftlichen Arbeit, da die Retrieval-Komponente als unabhängige Variable isoliert betrachtet wird.

---

## Nachtrag (2026-07-21): Reichweite über `retrieve()` hinaus + Schwellenwert-Risiko

Bei einer Aufwands-/Risikoabschätzung im Rahmen von TASK_14 (Zitier-Treue) kamen zwei Punkte hinzu, die der Plan oben (Schritt 3) noch nicht abdeckt:

**1. Weitere Dense-only-Abfragen außerhalb von `retrieve()`.** Mindestens `detect_baustein_scope()` (Layer-3-Routing, Baustein-Erkennung über `baustein_beschreibung`-Chunks) macht ebenfalls eine reine Dense-Query gegen Qdrant. Für ein konsistentes Ergebnis müsste auch dieser Pfad (und ggf. die Dokument-Routing-Logik aus TASK_13) auf Hybrid umgestellt werden — sonst verbessert sich nur der Haupt-Retrieval-Pfad, während die Routing-Vorauswahl weiterhin an derselben Dense-only-Schwäche leidet, die z. B. beim Basis-/Standard-Absicherung-Fall beobachtet wurde.

**2. Schwellenwert-Rekalibrierung ist größer als der Hinweis in Schritt 3 nahelegt.** Der bestehende Plan merkt an, `SCORE_THRESHOLD` müsse für RRF-Scores "deaktiviert oder separat konfiguriert" werden — das betrifft aber nicht nur diesen einen Wert. `SCORE_THRESHOLD_SCOPED`, `DOC_ROUTING_THRESHOLD`, `BAUSTEIN_ROUTING_THRESHOLD` und `WEAK_RETRIEVAL_HINT_THRESHOLD` wurden alle empirisch gegen die reine Kosinus-Skala kalibriert (siehe TASK_13, mehrtägiger Kalibrierungsaufwand). RRF-Fusionsscores liegen auf einer anderen, rang-basierten Skala — nach der Umstellung müssten alle diese Werte im Prinzip neu getestet werden, nicht nur einmalig anders gesetzt werden. Das ist der eigentlich unterschätzte Kostenpunkt, nicht die reine Implementierung (die bei ~1 Arbeitstag bleibt, wie oben geschätzt).

**Einordnung:** Ändert nichts an der Grundsatzentscheidung (Option B), aber die realistische Gesamt-Aufwandsspanne liegt eher bei 1 Arbeitstag Implementierung + zusätzlicher, schwer vorab bezifferbarer Kalibrierungszeit (Erfahrungswert aus TASK_13: mehrere Tage iteratives Testen), nicht bei einem einmaligen Nachmittag.

## Referenzen

- BGE-M3 HuggingFace: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- Qdrant Hybrid Search: [qdrant.tech/documentation/concepts/hybrid-queries](https://qdrant.tech/documentation/concepts/hybrid-queries/)
- BGE-Reranker: [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- Chen et al. (2024): *BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation*
