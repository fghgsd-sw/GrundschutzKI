# Ingest, Chunking und Retrieval — Ist-Stand und Verbesserungspotenzial

Stand: 2026-06-30. Beschreibt den aktuell produktiven Ingest- und Retrieval-Mechanismus (`apps/chainlit/ingest.py`, `apps/chainlit/rag_tool.py`) sowie Ansatzpunkte zur Verbesserung, von sofort nutzbar bis grundlegend neu.

---

## 1. Überblick

| Komponente | Aktuell |
|---|---|
| Vektordatenbank | Qdrant, Collection `grundschutz_bge_m3` |
| Embedding-Modell | `BAAI/bge-m3` (1024 Dimensionen, Cosine-Distanz), via IONOS |
| Chat-Modell | `gpt-oss-120b`, via IONOS |
| Retrieval-Art | **ausschließlich Dense-Vector-Retrieval** (kein Sparse/BM25, kein Re-Ranking) |
| Score-Schwellwert | `SCORE_THRESHOLD=0.3` (env, Default im Code: `0.0`) |
| Top-K pro Anfrage | `TOP_K=8` Standard, `MAX_TOP_K=16` Obergrenze (env) |
| Tool-Call-Runden | max. 12 pro Antwort (`MAX_TOOL_CALL_ROUNDS`) |

---

## 2. Datenquellen und Ingest-Pipeline

`ingest.py` verarbeitet zwei unabhängige Quellen über `--source {grundschutz,standards,all}`:

### 2.1 IT-Grundschutz-Kompendium (`_grundschutz_docs`)

Quelle: strukturiertes JSON (`grundschutz_with_pages.json` bzw. `grundschutz.json`), bereits in Schichten → Bausteine → Anforderungen gegliedert. Kein Chunking im klassischen Sinn — **jede inhaltliche Einheit wird zu genau einem Chunk**:

- **Pro Baustein:** ein `baustein_beschreibung`-Chunk (Einleitungskapitel) und ein `baustein_gefaehrdungslage`-Chunk (Gefährdungslage-Kapitel), falls vorhanden.
- **Pro Anforderung:** ein eigener `anforderung`-Chunk (Titel + Volltext), für alle drei Stufen (`basis`, `standard`, `erhoeht`). Als „ENTFALLEN" markierte Anforderungen werden übersprungen.
- **Elementare Gefährdungen:** ein Chunk pro Gefährdung (eigener, von Bausteinen unabhängiger Katalog).

Die Seitenzahlen werden aus einer Liste einzelner Seitenzahlen (`page_mapping`) auf den **dichtesten zusammenhängenden Cluster** reduziert (`_extract_page_range`), um große, durch vereinzelte Ausreißer verzerrte Bereiche zu vermeiden.

### 2.2 BSI-Standards 200-1 bis 200-4 (`_standards_docs_from_docling_json`)

Quelle: Docling-geparste JSON-Dumps (`data_docling_json_ocr/standard_200_*.json`). Chunking erfolgt **nicht zeichenbasiert**, sondern anhand erkannter Layout-Label (`section_header`, `title`, `chapter_title`) — ein neuer Abschnitt beginnt, sobald ein solches Label erkannt wird. Abschnitte unter 80 Zeichen Inhalt werden verworfen. Es existiert ein Fallback auf vorverarbeitete JSON-Dateien (`_standards_docs_from_preprocessed`), falls keine Docling-Daten vorliegen.

> **Hinweis zu einer früheren Fehlannahme dieser Session:** In den Auswertungsberichten unter `data/results/*.md` taucht „Chunk Size: 4000 Zeichen" auf. Das ist ein Dokumentations-Artefakt aus einem kopierten Beispielaufruf in `scripts/run_evaluation.py` und beschreibt **nicht** die tatsächliche Chunking-Logik — siehe `docs/eval_vorgehen.md`, Abschnitt 13.2.

---

## 3. Metadatenschema (Payload je `doc_type`)

| Feld | `anforderung` | `baustein_beschreibung`/`-gefaehrdungslage` | `standard_abschnitt` | Genutzt für Filter? |
|---|:---:|:---:|:---:|---|
| `doc_type` | ✓ | ✓ | ✓ | ✗ (ungenutzt, aber indiziert) |
| `schicht_id` (ORP, APP, SYS, NET, INF, CON, OPS, DER, IND, ISMS) | ✓ | ✓ | ✗ | ✓ **(heute ergänzt)** |
| `schicht_name` | ✓ | ✓ | ✗ | ✗ |
| `baustein_id` | ✓ | ✓ | ✗ | ✓ (bereits zuvor) |
| `baustein_titel` | ✓ | ✓ | ✗ | ✗ |
| `anforderung_id` | ✓ | ✗ | ✗ | ✗ (nur für Zitations-Auflösung, nicht als Such-Filter) |
| `anforderung_level` (basis/standard/erhoeht) | ✓ | ✗ | ✗ | ✗ (indiziert, ungenutzt) |
| `anforderung_typ` (B/S/H) | ✓ | ✗ | ✗ | ✗ (indiziert, ungenutzt) |
| `verantwortliche` (Rollen) | ✓ | ✗ | ✗ | ✗ |
| `zustaendigkeiten` | ✓ | ✗ | ✗ | ✗ |
| `modal_verben` (z. B. `["MUSS"]`) | ✓ | ✗ | ✗ | ✗ |
| `standard_id` (standard_200_1…4) | ✗ | ✗ | ✓ | ✓ (bereits zuvor, `source_scope`-ähnlich) |
| `section_title` | ✗ | ✗ | ✓ | ✗ |
| `page_start` / `page_end` | ✓ | ✓ | ✓ | ✗ (nur für Zitate, nicht als Filter) |

`ingest.py` legt für `doc_type`, `schicht_id`, `baustein_id`, `anforderung_typ`, `anforderung_level` bereits **Keyword-Indizes** in Qdrant an (`_ensure_collection`) — das heißt, gefilterte Abfragen auf diesen Feldern sind technisch bereits performant möglich, auch wenn aktuell nur zwei davon (`baustein_id`, `schicht_id`) tatsächlich von `rag_retrieve` genutzt werden.

---

## 4. Aktuell genutzte Retrieval-Mechanismen

**Frage „über Metadaten-Filter — machen wir das nicht gerade?"** — Ja, teilweise. Konkret implementiert in `rag_tool.py::retrieve()`:

1. **`baustein_id`-Filter** — schränkt auf einen einzelnen Baustein ein (z. B. `OPS.1.1.3`). Wird vom LLM nur gesetzt, wenn die ID wörtlich in der aktuellen Nutzernachricht steht (Prompt-Regel + Code-Absicherung in `app.py`).
2. **`schicht_id`-Filter** *(heute ergänzt)* — schränkt auf eine ganze Schicht ein (z. B. `ORP`), wenn deren Kürzel wörtlich genannt wird, aber kein spezifischer Baustein.
3. **`standard_id`-Filter** — schränkt auf einen der vier BSI-Standards ein.
4. **`source_scope`-Filter** — Unterscheidung Kompendium vs. Standards (nicht aktiv über das LLM steuerbar, nur intern verwendet).

Alle vier sind **reine Gleichheits-Filter** (`FieldCondition`/`MatchValue`), die das Suchergebnis VOR der Ähnlichkeitsbewertung einschränken — kein Re-Ranking, kein Boosting. Außerhalb dieser vier Felder findet **keine** weitere Metadatennutzung im Retrieval statt: `anforderung_typ`, `anforderung_level`, `modal_verben`, `verantwortliche` werden trotz vorhandenem Index und reichhaltigem Inhalt nicht abgefragt.

Ergänzend nachgelagert (nicht Teil des Retrievals, sondern der Antwortverarbeitung):
- **Citation-Canonicalizer** (`_canonicalize_citations`) korrigiert Zitate nachträglich anhand von Seiten-/ID-Übereinstimmung und IDF-gewichtetem Wortabgleich gegen den tatsächlichen Chunk-Text.
- **Multi-Round Tool-Calling**: Das Modell kann bis zu 12 Mal `rag_retrieve` mit variierender Query/Filter aufrufen; Ergebnisse werden über alle Runden aggregiert.

---

## 5. Bekannte Schwächen

Ausführlich mit Belegen in `docs/TASK_10_Hybrid_Retrieval_BGE-M3.md` (vier Praxisbeispiele) dokumentiert. Kurzfassung der identifizierten Mechanismen:

- **Dense-Embedding bevorzugt Wortpräsenz über fachliche Relevanz** — exaktes Vokabular in einem inhaltlich falschen Chunk (z. B. „vertrauliche personenbezogene Daten" in einem Fahrzeug-Gefährdungs-Chunk) kann höher scoren als der inhaltlich richtige, aber lexikalisch andere Chunk.
- **Meta-Ebenen-Verwechslung**: Chunks, die *über* das Konzept „Anforderung" sprechen, werden mit Fragen verwechselt, die *nach* Anforderungen fragen.
- **Kurze, informationsarme Chunks** (z. B. einzelne Beispielsätze) streuen instabil über viele Anfragen.
- **Ohne literal genannte ID/Schicht** (Laienformulierungen) greift kein Metadaten-Filter — das System fällt vollständig auf ungefiltertes Dense-Retrieval zurück.

---

## 6. Verbesserungsmöglichkeiten — gestaffelt nach Aufwand

### Stufe 0 — sofort nutzbar, kein Re-Ingest nötig (Stunden)

**6.1 Bereits indizierte, aber ungenutzte Metadatenfelder als Filter/Boost einsetzen.**
- `anforderung_typ` (B/S/H): Fragen wie „Was MUSS ich tun" vs. „Was SOLLTE ich zusätzlich tun" könnten gezielt auf Basis- bzw. Standard-Anforderungen filtern.
- `modal_verben`: ähnlich, aber granularer (Liste statt Einzelwert).
- `doc_type`: bei Fragen nach „Gefährdungen" gezielt auf `baustein_gefaehrdungslage` einschränken statt auf `anforderung`-Chunks zu hoffen.
- **Aufwand:** gering — Indizes existieren bereits, nur Tool-Parameter + Prompt-Anweisung wie bei `baustein_id`/`schicht_id` ergänzen.
- **Risiko:** gering, gleiche Architektur wie die heute gebauten Filter.

**6.2 Score-Threshold und Top-K feinjustieren.** Aktuell pauschal `0.3`/`8`. Eine pro-Fragetyp-Differenzierung (z. B. niedrigerer Threshold bei Schicht-/Baustein-gefilterten Anfragen, da der Filter bereits Rauschen ausschließt) könnte Recall verbessern, ohne Precision zu opfern.
- **Aufwand:** sehr gering (Konfiguration/Heuristik).

### Stufe 1 — moderater Aufwand, kein Re-Ingest nötig

**6.3 Contextual Chunk Enrichment** (Technik nach Anthropic, „Contextual Retrieval"): Jedem Anforderungs-Chunk wird vor dem Embedding ein kurzer, generierter Kontextsatz vorangestellt (z. B. „Diese Anforderung ORP.4.A2 gehört zum Baustein ORP.4 Identitäts- und Berechtigungsmanagement, Schicht Organisation und Personal."). Das stärkt das Embedding-Signal genau an der Stelle, wo aktuell Kontext zwischen Anforderung und übergeordnetem Thema verloren geht (Mechanismus B in TASK_10).
- **Aufwand:** mittel — einmaliger LLM-Durchlauf über alle Chunks beim Ingest, dann Re-Embedding.
- **Risiko:** gering, additiv, kein Strukturbruch.

**6.4 Cross-Encoder Re-Ranking** (bereits in TASK_10 skizziert): Nach dem initialen Dense-Retrieval (z. B. Top-20) bewertet ein Cross-Encoder (`bge-reranker-v2-m3`) jedes Paar (Frage, Chunk) gemeinsam neu — präziser als Embedding-Ähnlichkeit allein, da Frage und Chunk nicht unabhängig kodiert werden.
- **Aufwand:** mittel — zusätzlicher Modell-Aufruf nach Retrieval, kein Re-Ingest.
- **Risiko:** gering (isolierter Schritt), zusätzliche Latenz pro Anfrage.

### Stufe 2 — höherer Aufwand, Re-Ingest erforderlich

**6.5 Hybrid Retrieval (Dense + Sparse/BM25, Reciprocal Rank Fusion)** — ausführlich in TASK_10 behandelt, dort auch die Erkenntnis, dass BGE-M3s natives Sparse-Signal über die aktuelle gehostete API vermutlich nicht zugänglich ist; klassisches BM25 lokal berechnet ist der pragmatischere Weg. Adressiert Mechanismus A und B aus Abschnitt 5 direkt, da exakte Terminologie unabhängig von semantischer Verdünnung hoch gewichtet wird.
- **Aufwand:** ca. 2–4 Personentage (siehe TASK_10 für Details).

**6.6 Multi-Query / Query Expansion.** Bei Laienformulierungen ohne Fachvokabular (z. B. „vertrauliche personenbezogene Daten" statt „ORP") könnte das LLM vor dem eigentlichen Retrieval mehrere alternative, fachsprachliche Umformulierungen der Frage generieren (inkl. Akronym-Auflösung, z. B. IAM → Identitäts- und Berechtigungsmanagement → ORP.4) und die Ergebnisse mehrerer Embedding-Suchen fusionieren. Würde gezielt das in Abschnitt 5 letztgenannte Problem (keine Filter-Trigger bei Laienformulierung) adressieren, ohne dass der Nutzer Fachbegriffe kennen muss.
- **Aufwand:** mittel — zusätzlicher LLM-Call vor Retrieval, kein Re-Ingest, aber Latenz- und Kostenzuwachs pro Anfrage.

### Stufe 3 — grundlegende Architekturänderung

**6.7 Ontologie-/Graph-gestütztes Retrieval.** Das IT-Grundschutz-Kompendium hat bereits eine **explizite, im Text vorhandene Struktur**, die aktuell nicht als Graph genutzt wird: Bausteine verweisen aufeinander („siehe Baustein APP.6 Allgemeine Software"), Anforderungen sind Schichten/Bausteinen/Stufen zugeordnet, elementare Gefährdungen sind bausteinübergreifend verknüpft. Ein Graph (z. B. Neo4j oder ein einfaches In-Memory-Graphmodell über die bereits vorhandenen `baustein_id`/`schicht_id`-Metadaten) könnte:
- explizite Querverweise zwischen Bausteinen als zusätzlichen Retrieval-Pfad nutzen (nicht nur „ähnlich", sondern „verweist auf"),
- bei Vergleichsfragen („Wie unterscheiden sich X und Y") gezielt beide Bausteine samt ihrer Beziehung abrufen, statt auf zufällige Embedding-Nähe zu hoffen.
- **Aufwand:** hoch — Extraktion der Querverweise aus dem Kompendium-Text (Regex/LLM-gestützt), neue Speicher-/Abfrageschicht, Integration in `rag_retrieve`.
- **Risiko:** mittel-hoch — neue Infrastrukturkomponente, Pflegeaufwand bei Kompendium-Updates.

**6.8 Vollständiges GraphRAG** (im Sinne von Microsoft GraphRAG): LLM-gestützte Entitäts- und Beziehungsextraktion aus dem gesamten Korpus, Community-Detection über den resultierenden Graphen, LLM-generierte Zusammenfassungen pro Community als zusätzliche, grobkörnige Retrieval-Ebene neben den feingranularen Anforderungs-Chunks. Würde Mechanismus B (Meta-Ebenen-Fragen, „Welche Anforderungen insgesamt zu Thema X") strukturell besser bedienen als Einzel-Chunk-Retrieval, da GraphRAG für genau diesen Fragetyp (globale, themenübergreifende Synthese) entwickelt wurde.
- **Aufwand:** sehr hoch — vollständige Neuentwicklung der Ingest- und Retrieval-Pipeline, hoher Tooling- und Rechenaufwand (viele LLM-Calls für Extraktion/Summarization beim Ingest).
- **Risiko:** hoch — Komplexität, Wartbarkeit, Kosten; für ein Pilotprojekt dieser Größe vermutlich unverhältnismäßig, eher relevant bei deutlich größerem Korpus oder wenn Stufe 1–2 nachweislich nicht ausreichen.

### Priorisierungsempfehlung

Reihenfolge nach Aufwand/Nutzen-Verhältnis: **6.1 → 6.2 → 6.6 (Query Expansion, adressiert das Laienformulierungs-Problem direkt) → 6.4 (Re-Ranking) → 6.3 (Contextual Enrichment) → 6.5 (Hybrid Retrieval) → 6.7 (Graph) → 6.8 (GraphRAG)**. Stufe 0 sollte vor der Evaluierung noch machbar sein; alles ab Stufe 2 ist ein Folgevorhaben.

---

## 8. Für die wissenschaftliche Arbeit: Methodik-Abschnitt „Ingest und Metadatenmodell"

*Direkt übernehmbarer Fließtext, formuliert für die Methodik-/Systembeschreibung. Sprachlich an den übrigen Stil von `eval_vorgehen.md` angeglichen.*

### 8.1 Datengrundlage und Vorverarbeitung

Die Wissensbasis des Systems setzt sich aus zwei strukturell unterschiedlichen Quellkorpora zusammen: dem IT-Grundschutz-Kompendium des BSI (Edition 2023) und den vier BSI-Standards der 200er-Reihe (200-1 bis 200-4). Beide Korpora durchlaufen getrennte, auf ihre jeweilige Dokumentstruktur zugeschnittene Vorverarbeitungspfade, werden jedoch in derselben Vektordatenbank-Collection zusammengeführt und sind über ein gemeinsames Metadatenschema (Abschnitt 8.3) durchsuchbar.

**Kompendium.** Das Kompendium liegt nicht als Fließtext-PDF, sondern als bereits strukturiertes JSON-Dokument vor, das die hierarchische Gliederung des BSI-Originals — Schicht → Baustein → Anforderung — explizit abbildet. Da diese Struktur bereits auf Aussagenebene granular ist (jede Anforderung ist im Quelldokument eine in sich abgeschlossene normative Einheit mit eindeutiger Kennung, z. B. `ORP.4.A2`), wird auf ein nachträgliches, größenbasiertes Chunking-Verfahren verzichtet. Stattdessen wird jede strukturelle Einheit des Quelldokuments unverändert in eine Indexeinheit (im Folgenden: *Chunk*) überführt:

- Pro Baustein wird die Einleitung (*Beschreibung*) und, sofern vorhanden, das Gefährdungslage-Kapitel je zu einem eigenen Chunk.
- Pro Anforderung wird Titel und Volltext zu einem Chunk zusammengeführt. Als „entfallen" gekennzeichnete Anforderungen — redaktionelle Platzhalter für im Zuge von Kompendium-Revisionen gestrichene Anforderungen — werden ausgeschlossen.
- Elementare Gefährdungen (ein vom Bausteinkatalog unabhängiges Verzeichnis allgemeiner Bedrohungsursachen) werden analog als eigene Chunks abgelegt.

Diese Entscheidung — Beibehaltung der Quellstruktur statt zeichen- oder token-basierter Segmentierung — stellt sicher, dass jede normative Einzelaussage exakt einem Chunk und damit einer eindeutig referenzierbaren Quellenangabe entspricht. Sie ist Voraussetzung für die in Abschnitt 4 beschriebenen, auf einzelne Anforderungen bezogenen Zitationsmechanismen.

**BSI-Standards.** Die Standards 200-1 bis 200-4 liegen als Fließtext-PDF vor und folgen keiner vergleichbar granularen, maschinell auswertbaren Struktur. Sie werden mittels der Open-Source-Bibliothek *Docling* layoutanalytisch in maschinenlesbares JSON überführt, wobei Layoutelemente (u. a. Abschnittsüberschriften, Fließtext, Tabellen) klassifiziert und mit Seitenzuordnung versehen werden. Die anschließende Segmentierung orientiert sich an den erkannten Überschriften-Labels: Ein neuer Chunk beginnt mit jeder erkannten Abschnitts- oder Kapitelüberschrift; der zugehörige Fließtext wird bis zur nächsten Überschrift akkumuliert. Abschnitte mit weniger als 80 Zeichen Inhalt — typischerweise Layout-Artefakte ohne inhaltlichen Wert — werden verworfen. Diese layoutbasierte Segmentierung ist gröber und inhaltlich heterogener als die Anforderungs-Chunks des Kompendiums, da die Standards selbst keine vergleichbar feingranulare normative Struktur aufweisen.

### 8.2 Vektorisierung und Speicherung

Beide Korpora werden mit demselben Embedding-Modell (`BAAI/bge-m3`, 1024-dimensionale Dense-Vektoren, Kosinus-Distanz) vektorisiert und in einer gemeinsamen Qdrant-Collection abgelegt. Die Einbettung erfolgt auf Chunk-Ebene: Der vollständige Chunk-Text (bei Anforderungen: Titel und normativer Volltext) wird als zusammenhängende Eingabe an das Embedding-Modell übergeben. Für häufig gefilterte Metadatenfelder (Abschnitt 8.3) werden zusätzlich Keyword-Indizes angelegt, die eine performante kombinierte Filter- und Ähnlichkeitssuche ermöglichen.

### 8.3 Metadatenmodell

Jeder Chunk wird beim Ingest mit einem dokumenttyp-abhängigen Satz strukturierter Metadaten versehen, die über das reine Retrieval hinaus für Quellenzuordnung, Zitationsauflösung und gefilterte Suche genutzt werden (Tabelle 8.1).

**Tabelle 8.1 — Metadatenfelder nach Dokumenttyp**

| Feld | Anforderung | Baustein­einleitung/-gefährdungslage | Standard­abschnitt | Semantik |
|---|:---:|:---:|:---:|---|
| `doc_type` | ✓ | ✓ | ✓ | Strukturtyp des Chunks |
| `schicht_id` | ✓ | ✓ | — | Übergeordnete Themenschicht (z. B. `ORP`) |
| `baustein_id` | ✓ | ✓ | — | Eindeutige Baustein-Kennung |
| `anforderung_id` | ✓ | — | — | Eindeutige Anforderungs-Kennung |
| `anforderung_level` | ✓ | — | — | Verbindlichkeitsstufe (Basis/Standard/Erhöht) |
| `anforderung_typ` | ✓ | — | — | Kodierte Verbindlichkeit (B/S/H) |
| `verantwortliche` | ✓ | — | — | Zuständige Rolle(n) lt. Kompendium |
| `modal_verben` | ✓ | — | — | Im Anforderungstext verwendete Modalverben |
| `standard_id` | — | — | ✓ | Zugehöriger BSI-Standard (200-1…4) |
| `page_start` / `page_end` | ✓ | ✓ | ✓ | Seitenbereich im Quelldokument |

Dieses Metadatenmodell bildet die Grundlage für eine hybride Retrieval-Strategie, die dichte semantische Ähnlichkeitssuche mit strukturierter Filterung kombiniert (vgl. Abschnitt 4 und 6.1) — eine Eigenschaft, die bei rein zeichenbasiertem Chunking ohne Bezug zur Quellstruktur nicht in vergleichbarer Präzision realisierbar wäre.

---

## 9. Für die wissenschaftliche Arbeit: Ausblick

*Direkt übernehmbarer Fließtext für ein Ausblick-Kapitel. Baut auf der Maßnahmenliste in Abschnitt 6 auf, formuliert als zusammenhängende Diskussion mit Priorisierungslogik statt als technische Aufzählung.*

Die in dieser Arbeit identifizierten Schwächen des eingesetzten Retrieval-Verfahrens — eine Tendenz dichter Embedding-Repräsentationen, lexikalische Präsenz mit fachlicher Relevanz zu verwechseln, sowie eine unzureichende Differenzierung zwischen Anfragen auf Einzelaussagen- und auf Themenebene — eröffnen mehrere, in Aufwand und Eingriffstiefe deutlich unterscheidbare Weiterentwicklungsrichtungen.

Kurzfristig und ohne Eingriff in die bestehende Indexstruktur ließe sich das bereits vorhandene, aber bislang nur teilweise ausgeschöpfte Metadatenmodell (Abschnitt 8.3) konsequenter für die Filterung nutzen: Felder wie die Verbindlichkeitsstufe einer Anforderung oder die darin verwendeten Modalverben sind bereits indiziert, werden jedoch von der aktuellen Retrieval-Logik nicht abgefragt. Eine Erweiterung in diese Richtung erscheint mit vertretbarem Aufwand kurzfristig umsetzbar und stellt insofern den naheliegendsten nächsten Schritt dar.

Mittelfristig erscheinen zwei Ansätze besonders vielversprechend, die methodisch unabhängig voneinander und ohne grundlegende Neuarchitektur umsetzbar sind: Zum einen eine Anreicherung der Anforderungs-Chunks um expliziten Kontext vor der Einbettung (*Contextual Retrieval*, vgl. Anthropic, 2024), die dem beobachteten Verlust thematischer Einordnung beim isolierten Embedding einzelner, kurzer Anforderungstexte entgegenwirken soll. Zum anderen eine Umformulierung von Nutzeranfragen in fachsprachliche Varianten vor der eigentlichen Suche (*Query Expansion*), die insbesondere bei Anfragen ohne explizite Nennung von Baustein- oder Schichtkennungen — etwa bei Formulierungen durch fachfremde Nutzende — eine gezieltere Eingrenzung des Suchraums ermöglichen könnte, ohne dass hierfür Fachwissen seitens der fragenden Person vorausgesetzt wird.

Als robustere, jedoch mit höherem Implementierungsaufwand verbundene Erweiterung bietet sich eine hybride Retrieval-Architektur an, die die bestehende dichte Ähnlichkeitssuche um ein term-basiertes Verfahren (BM25 oder vergleichbar) ergänzt und beide Rankings mittels Reciprocal Rank Fusion kombiniert [vgl. Cormack et al., 2009]. Ein solches Verfahren adressiert gezielt die in dieser Arbeit dokumentierten Fälle, in denen exakte fachliche Terminologie von semantisch näherliegenden, aber sachlich falschen Textstellen verdrängt wird, da term-basierte Verfahren Begriffshäufigkeit und -spezifität unabhängig von semantischer Nachbarschaft gewichten.

Langfristig wäre eine grundlegendere Neuausrichtung der Wissensrepräsentation denkbar, die über chunk-basiertes Retrieval hinausgeht: Das IT-Grundschutz-Kompendium verfügt über eine im Text bereits angelegte, jedoch bislang nicht maschinell erschlossene Verweisstruktur zwischen Bausteinen. Eine graphbasierte Modellierung dieser Beziehungen — bis hin zu einem vollständigen, durch automatisierte Entitäts- und Relationsextraktion gestützten Wissensgraphen nach dem GraphRAG-Paradigma [vgl. Edge et al., 2024] — könnte insbesondere bei Anfragen mit Querschnittscharakter, die in der durchgeführten Modellevaluation (vgl. `eval_vorgehen.md`, Abschnitt 10) durchgängig schwächere Ergebnisse zeigten als thematisch fokussierte Einzelanfragen, eine strukturell angemessenere Antwortgrundlage bieten als die Aggregation einzeln abgerufener Chunks. Angesichts des damit verbundenen Implementierungs- und Pflegeaufwands erscheint eine solche Erweiterung jedoch erst dann gerechtfertigt, wenn die kurz- und mittelfristig skizzierten Maßnahmen ausgeschöpft sind und sich weiterhin als unzureichend erweisen.

---

## 10. Referenzen

- `docs/TASK_10_Hybrid_Retrieval_BGE-M3.md` — vier dokumentierte Praxisbeispiele für Dense-Retrieval-Schwächen, Hybrid-Retrieval-Umsetzungsplan.
- `docs/TASK_12_Citation_und_Retrieval_Fixes.md` — Zitations-Korrektur-Logik, `baustein_id`/`schicht_id`-Filter-Implementierung.
- `docs/eval_vorgehen.md` — quantitative Modellvergleichsdaten (RAGAS), Abschnitt 13 zum Abgleich mit Live-Beobachtungen.
- Anthropic (2024). *Introducing Contextual Retrieval.* — Grundlage für Vorschlag 6.3.
- Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods.* SIGIR '09 — Grundlage für Vorschlag 6.5 (Hybrid Retrieval, RRF).
- Edge, D. et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* Microsoft Research — Grundlage für Vorschlag 6.8 (GraphRAG).
