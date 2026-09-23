# TASK_10_1: HyDE — Hypothetical Document Embeddings

## Problemkontext

Das in TASK_10 dokumentierte Kernproblem des Dense-Retrievals ist ein struktureller **Vocabulary-Mismatch**: Nutzeranfragen verwenden natürlichsprachliches „Frage-Vokabular" (`„Was ist bei der Planung von Software-Tests zu beachten?"`), während die Chunks im Korpus „Antwort-Vokabular" verwenden (`„OPS.1.1.6.A1 Die Rahmenbedingungen für Software-Tests MÜSSEN vor den Tests festgelegt sein."`). Dense Retrieval berechnet die Kosinus-Ähnlichkeit zwischen dem Query-Embedding und den Chunk-Embeddings — aber Frage und Antwort liegen auch bei hoher inhaltlicher Relevanz in unterschiedlichen Regionen des Vektorraums, weil sie grammatikalisch und stilistisch verschieden sind.

Dieser Effekt ist in IT-Grundschutz-Anwendungsfällen besonders ausgeprägt, weil:

- Laienformulierungen kein IT-Grundschutz-Fachvokabular enthalten (Praxisbeispiel 4, TASK_10)
- Anforderungstitel normativ formuliert sind (`„MUSS"`, `„SOLLTE"`) — anders als jede Nutzeranfrage
- Generische Methodik-Begriffe (`„Anforderungen"`, `„Planung"`) in vielen Chunks vorkommen und den Suchvektor zu falschen, aber vokabularnahen Chunks ziehen

---

## Theoretischer Lösungsansatz: HyDE

**HyDE (Hypothetical Document Embeddings)** wurde von Gao et al. (2022) als zero-shot Dense-Retrieval-Verbesserung vorgestellt. Die Kernidee: Statt das Query-Embedding direkt für die Vektorsuche zu verwenden, generiert ein Sprachmodell zunächst einen **hypothetischen Antwortabsatz** auf die Nutzerfrage — ohne Zugriff auf den tatsächlichen Korpus. Dieser hypothetische Absatz wird anschließend eingebettet und als Suchvektor verwendet.

```
Nutzerfrage  →  [LLM: hypothetischen Absatz generieren]  →  [embed]  →  Qdrant-Suche
```

statt:

```
Nutzerfrage  →  [embed]  →  Qdrant-Suche
```

### Warum das funktioniert

Ein hypothetischer Antwortabsatz verwendet dasselbe Vokabular, dieselbe grammatische Struktur und dieselbe Domänensprache wie die tatsächlichen Chunks im Korpus — auch wenn sein Inhalt faktisch ungenau oder unvollständig ist. Das Embedding des hypothetischen Absatzes liegt damit näher an den relevanten Chunk-Embeddings als das Embedding der rohen Nutzerfrage. Gao et al. (2022) zeigen, dass dieses Verfahren auf mehreren Retrieval-Benchmarks (TREC, BEIR) deutliche Verbesserungen gegenüber direktem Query-Embedding erzielt — ohne Finetuning oder annotierte Relevanzurteile.

Entscheidend ist, dass **faktische Korrektheit des hypothetischen Absatzes nicht erforderlich** ist. Ein Absatz, der das richtige Fachvokabular und die richtige Dokumentstruktur imitiert, genügt, um den Suchvektor in die korrekte Region des Vektorraums zu verschieben.

### Bezug zu den dokumentierten Recall-Fehlern (TASK_10)

| Praxisbeispiel | Ursache (Dense) | Erwarteter HyDE-Effekt |
|---|---|---|
| OPS.1.1.6 (Software-Tests) | Methodik-Begriffe überstimmen Fachterm | Hypothetischer Absatz enthält `OPS.1.1.6`, `Software-Tests MÜSSEN` |
| ORP.4.A5–A7 (Zutritt/Zugang/Zugriff) | Semantische Breite des Gefährdungslage-Chunks | Hypothetischer Absatz nennt Anforderungstitel wörtlich |
| APP.3.2 (Webserver) | Vokabularnahe Fremdbausteine dominieren | Hypothetischer Absatz fokussiert auf `APP.3.2`-spezifische Anforderungen |
| Laienformulierung (personenbezogene Daten) | Kein IT-Grundschutz-Vokabular in der Frage | Hypothetischer Absatz übersetzt in Fachsprache (ORP-Schicht) |

Besonders für den vierten Fall — Laienformulierungen ohne Fachvokabular — ist HyDE der wirksamste Hebel, da BM25/Sparse-Retrieval hier ebenfalls versagt (kein Fachterm zum Matchen vorhanden).

---

## Implementierung im vorliegenden System

### HyDE-Prompt (leichtgewichtig, domänenspezifisch)

```python
HYDE_PROMPT = """Generiere einen kurzen Absatz (3–5 Sätze) auf Deutsch, der die folgende Frage
beantwortet. Verwende IT-Grundschutz-Fachvokabular und die normative Sprache des BSI
(MUSS, SOLLTE, DARF NICHT). Inhaltliche Genauigkeit ist nicht erforderlich — der Absatz
dient ausschließlich zur Verbesserung der Dokumentensuche.

Frage: {query}

Absatz:"""
```

### Integration in `rag_tool.py`

```python
async def retrieve_with_hyde(query: str, **kwargs) -> list[RagResult]:
    # Hypothetischen Absatz generieren
    hyde_response = await llm_call(HYDE_PROMPT.format(query=query))
    # Hypothetischen Absatz einbetten statt roher Query
    return await retrieve(query=hyde_response, **kwargs)
```

Der originale `retrieve()`-Aufruf bleibt unverändert; HyDE ist ein vorgelagerter Schritt. Bestehende Filter (`baustein_id`, `schicht_id`) bleiben vollständig erhalten.

### Konfiguration

- `HYDE_ENABLED=true/false` als Feature-Flag in `.env`
- Optional: `HYDE_MODEL` — falls ein kleineres/schnelleres Modell für die Hypothesen-Generierung verwendet werden soll (z. B. llama-8b statt 70b, um Latenz zu reduzieren)

### Latenz-Overhead

Ein zusätzlicher LLM-Aufruf pro Retrieval-Runde: bei llama-70b ca. 1–3 Sekunden. Da `MAX_TOOL_CALL_ROUNDS=12`, aber typische Anfragen 1–2 Retrieval-Runden benötigen, ist der Overhead in der Praxis gering.

---

## Evaluation

### Testfragen (aus TASK_10)

Die vier dokumentierten Recall-Fehler als Mindest-Testset:

1. *„Was ist bei der Auswahl der Planung von Software-Tests zu beachten?"* → erwartet: `OPS.1.1.6.A1` in Top-8
2. *„Wie muss mit Zutritts-, Zugangs- und Zugriffsrechten organisatorisch umgegangen werden?"* → erwartet: `ORP.4.A5/A6/A7` in Top-5
3. *„Welche Anforderungen sollte ich berücksichtigen, wenn ich einen Webserver selbst betreiben möchte?"* → erwartet: ≥8 von 16 `APP.3.2`-Anforderungen in Top-8
4. *„Welche Anforderungen sind zu beachten, wenn man besonders vertrauliche personenbezogene Daten verarbeiten möchte?"* → erwartet: ORP-Chunk in Top-8

### RAGAS-Metriken

- **Context Recall**: Anteil der im Kontext enthaltenen relevanten Informationen — primäre Zielmetrik für HyDE
- **Context Precision**: Anteil relevanter Chunks unter den Top-K — sollte nicht fallen
- **Faithfulness**: Unabhängig von HyDE, sollte stabil bleiben

---

## Wissenschaftliche Einordnung

HyDE gehört zur Klasse der **Query Expansion**-Verfahren, die eine lange Tradition in der Informationsretrieval-Forschung haben (Voorhees, 1994; Rocchio, 1971). Der spezifische Beitrag von Gao et al. (2022) ist die Verwendung von Sprachmodellen zur Generierung hypothetischer Dokumente statt klassischer Term-basierter Expansion — eine Adaptation, die mit dem Aufkommen leistungsfähiger Instruction-folgender LLMs praktisch wurde.

Im RAG-Kontext ist HyDE besonders relevant, weil es das Retrieval verbessert, ohne den Korpus oder das Embedding-Modell anzutasten — eine *query-side-only*-Verbesserung, die unabhängig von Ingest-Pipeline und Collection-Schema ist.

---

## Empirische Motivation: RAGAS-Analyse der Baseline (llama-70b, 43 komplexe Fragen)

Zur Auswahl des nächsten Optimierungsschritts wurde eine systematische Auswertung der RAGAS-Evaluationsergebnisse des Produktionsmodells (Llama-3.3-70B-Instruct) auf dem kuratierten Testset mit 43 komplexen Fragen durchgeführt. Die Analyse liefert die empirische Grundlage für die Entscheidung, HyDE gegenüber einer reinen Prompt-Iteration zu priorisieren.

### Befundlage

Das Modell erreicht im Mittel eine **Faithfulness von 0,907** — bei 30 von 40 ausgewerteten Fragen liegt der Wert bei 1,0. Die Quellengenauigkeit ist damit auf einem hohen Niveau: Das Modell zitiert überwiegend nur, was im Retrieval-Kontext tatsächlich enthalten ist. Demgegenüber beträgt die **Answer Correctness im Mittel 0,506** und weist mit einer Standardabweichung von 0,138 erhebliche Streuung auf. Die Korrelation zwischen Faithfulness und Answer Correctness beträgt −0,07 und ist damit praktisch null — beide Metriken sind statistisch unabhängig voneinander.

Diese Entkopplung verweist auf zwei strukturell verschiedene Fehlerklassen:

**Klasse A — Faithfulness-Fehler (9 von 40 Fragen):** Das Modell ergänzt Inhalte aus seinem Parameterwissen über den abgerufenen Kontext hinaus. Betroffen sind überwiegend Cloud-spezifische Fragen, bei denen das Modell trotz korrekt abgerufener Chunks (Context Precision = 1,0) inhaltlich über den belegbaren Kontext hinausgeht. Diese Klasse ist durch Prompt-Anpassungen partiell adressierbar.

**Klasse B — Retrieval-Scope-Fehler (7 von 40 Fragen):** Faithfulness = 1,0, Answer Correctness < 0,45. Das Modell antwortet vollständig kontexttreu — jedoch zu falsch abgerufenen Chunks. Ein repräsentatives Beispiel: Die Frage *„Welche organisatorischen Risiken bestehen bei fehlender Geräteverwaltung?"* erwartet Inhalte aus dem Baustein ORP.1 (Betriebsmittelmanagement); das Retrieval liefert stattdessen Chunks aus dem IND-Bereich (industrielle Fernwartung), die das Vokabular der Frage semantisch näher abbilden, aber inhaltlich nicht passen. Die generierte Antwort ist kontexttreu und erzielt daher Faithfulness = 1,0 — beantwortet aber die falsche Frage.

### Konsequenz für die Methodenwahl

Klasse B ist durch Prompt-Iteration nicht behebbar: Eine präzisere Anweisung zur Quellennutzung ändert nichts daran, dass die falschen Chunks im Kontext liegen. Der einzige wirksame Hebel ist eine Verbesserung der Retrieval-Qualität selbst. Da Klasse B mit sieben Fällen die häufigere der beiden strukturellen Fehlerklassen darstellt und zudem den größten Beitrag zur Answer-Correctness-Lücke leistet, wird HyDE als vorrangiger nächster Optimierungsschritt gewählt.

HyDE adressiert Klasse B direkt: Indem ein hypothetischer Antwortabsatz in IT-Grundschutz-Fachsprache generiert und als Suchvektor verwendet wird, verschiebt sich das Query-Embedding in die Vektorraum-Region der korrekten Bausteine — unabhängig davon, ob die Nutzerfrage selbst das entsprechende Fachvokabular enthält. Klasse A (Faithfulness-Fehler) bleibt als separater Optimierungsschritt durch Prompt-Iteration adressierbar, sobald der Retrieval-Scope-Fehler behoben ist (vgl. TASK_10_2).

---

## Referenzen

- Gao, L., Ma, X., Lin, J. & Callan, J. (2022). Precise Zero-Shot Dense Retrieval without Relevance Labels. *arXiv preprint* arXiv:2212.10496.
- Voorhees, E. M. (1994). Query expansion using lexical-semantic relations. *Proceedings of the 17th Annual International ACM SIGIR Conference on Research and Development in Information Retrieval*, 61–69.
- Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *Advances in Neural Information Processing Systems*, 33, 9459–9474.
- Chen, J. et al. (2024). BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation. *arXiv preprint* arXiv:2402.03216.
