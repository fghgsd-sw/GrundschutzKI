# TASK_07: Falsche Quellenzuordnung / Citation Hallucination

## Problem

Zwei beobachtete Ausprägungen:

**1. Falsches Dokument** — Der LLM nennt korrekte IT-Grundschutz-Bausteine aus seinem Trainingswissen, zitiert aber Chunks aus dem falschen Dokument:

> IND.2.2 Speicherprogrammierbare Steuerung (SPS) – ...
> **Quelle 3: 8.1.6 Erhebung der ICS-Systeme (S.95-96)** ← Standard 200-2 statt Kompendium

**2. Citation Hallucination** — Der LLM generiert inhaltlich korrekte Aussagen aus Parameterwissen und hängt einen thematisch passenden, aber inhaltlich unzutreffenden Chunk als Quelle an:

> Schritte der Basis-Absicherung: Festlegung des Geltungsbereichs, Auswahl und Priorisierung...
> **Quelle 1: Basis-Absicherung (S.35)** ← Glossareintrag, nicht die Prozessbeschreibung

Seite 35 enthält nur die Definition: *"Die Basis-Absicherung ermöglicht es, als Einstieg..."* — nicht die zitierten Prozessschritte. Diese stammen aus dem LLM-Trainingswissen, nicht aus dem retrieval.

## Einordnung: Retrieval-Score ≠ Zitierwahrscheinlichkeit

Eine verwandte, davon konzeptionell zu trennende Beobachtung betrifft das Verhältnis zwischen Retrieval-Ranking und tatsächlicher Zitierung in der Antwort.

Semantische Ähnlichkeitssuche (Dense Retrieval) ordnet Chunks nach ihrer Cosinus-Ähnlichkeit zum Query-Embedding. Dieser Score misst die *semantische Nähe* zum Fragetext, nicht den *Erklärungswert* des Chunks für die Antwort. Der am höchsten gerankte Treffer muss daher nicht zwingend in die generierte Antwort eingehen.

**Beobachtetes Beispiel:** Auf die Frage *„Was ist ein IT-Grundschutz-Baustein und wie ist er aufgebaut?"* rangierte Chunk [1] „2.7 Anwendung des IT-Grundschutz-Kompendiums" (Standard 200-2, S. 17) mit score=0.634 an erster Stelle — vor Chunks, die in der Antwort tatsächlich zitiert wurden (score=0.603–0.579). Der Chunk blieb unzitiert.

**Ursache:** Das Embedding des Abschnittstitels „Anwendung des IT-Grundschutz-Kompendiums" liegt im Vektorraum nahe am Query, weil beide denselben Themenbereich adressieren. Der Abschnitt beschreibt jedoch die *Vorgehensweise beim Einsatz* des Kompendiums, nicht die innere Struktur eines Bausteins. Das LLM bewertet alle zurückgegebenen Chunks kontextuell und entscheidet unabhängig vom Retrieval-Ranking, welche Passagen die gestellte Frage tatsächlich beantworten — Chunks mit geringerem Score, aber höherem Erklärungswert werden dabei bevorzugt zitiert.

Dieses Verhalten ist ein strukturelles Merkmal von RAG-Architekturen: Dense Retrieval optimiert auf *Semantic Proximity*, während die Generierungskomponente auf *Answer Utility* optimiert. Beide Ziele korrelieren in der Praxis häufig, sind jedoch nicht identisch. Eine Erhöhung der Top-K-Trefferzahl kann die Recall-Rate verbessern, löst aber das grundlegende Mismatch zwischen den beiden Optimierungszielen nicht auf. Re-Ranking-Verfahren (z. B. Cross-Encoder-basiertes Re-Ranking) adressieren dieses Problem, indem sie nach dem initialen Retrieval einen zweiten, aufwändigeren Relevanzschritt einführen, der den tatsächlichen Antwortgehalt eines Chunks bewertet (siehe TASK_10).

## Ursache (Citation Hallucination)

Die Vektordatenbank enthält sowohl das IT-Grundschutz-Kompendium als auch den BSI-Standard 200-2. Bei thematischen Überschneidungen haben Chunks ähnliche Embedding-Scores, unabhängig davon ob der Inhalt die Aussage tatsächlich belegt. Der LLM verknüpft Parameterwissen mit dem nächstverfügbaren Retrieval-Treffer statt nur zu zitieren, was im Chunk tatsächlich steht.

## Lösungsansätze

### 1. Dokument-Label im Ingest *(mittlerer Aufwand, hohe Wirkung)*

Beim Ingesten jedes Chunks das Quelldokument als Metadatum speichern:

```python
metadata = {
    "document_type": "kompendium",  # oder "standard_200_2", "standard_200_1" etc.
    "document": "IT-Grundschutz-Kompendium 2023",
    ...
}
```

Der LLM erhält im Kontext dann klar gekennzeichnete Quellen und kann unterscheiden.

### 2. Metadaten-Filter im Retrieval *(mittlerer Aufwand)*

`rag_tool.py` `retrieve()` um optionalen Filter erweitern:

```python
results = await retrieve(
    query=query,
    top_k=top_k,
    filter={"document_type": "kompendium"},  # nur Kompendium-Chunks
)
```

Nachteil: Standard 200-2 steht dann nicht mehr als Quelle zur Verfügung, auch wenn er relevanter wäre.

### 3. Score-Threshold erhöhen *(einfach, sofort umsetzbar)*

In `.env` `SCORE_THRESHOLD` von `0.0` auf z.B. `0.4` anheben — schlechtere, nur thematisch verwandte Treffer werden ausgeschlossen.

**Risiko:** Für seltene Themen werden ggf. zu wenige Treffer gefunden.

### 4. Separate Qdrant-Collections *(aufwändig, sauberste Lösung)*

Kompendium und Standards in getrennten Collections speichern. Je nach Fragestellung gezielt eine oder beide Collections abfragen.

**Aufwand:** Re-Ingest, Anpassung `rag_tool.py` und `.env`

### 5. Re-Ranking nach Dokumenttyp *(mittlerer Aufwand)*

Nach dem Retrieval: Treffer aus dem Kompendium bei gleicher Treffergüte bevorzugen (Boost auf `document_type == "kompendium"`).

## Empfehlung

| Maßnahme | Aufwand | Wirkung |
|---|---|---|
| Score-Threshold erhöhen | minimal | moderat |
| Dokument-Label im Ingest | mittel | hoch |
| Re-Ranking nach Dokumenttyp | mittel | hoch |
| Separate Collections | hoch | sehr hoch |

**Kurzfristig:** Score-Threshold auf 0.3–0.4 testen.
**Mittelfristig:** Dokument-Label beim Re-Ingest ergänzen + Re-Ranking implementieren.
