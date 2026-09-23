# TASK_10_2: Evaluationsgetriebene Prompt-Iteration

## Problemkontext

Selbst bei korrektem Retrieval — d. h. wenn die relevanten Chunks tatsächlich im Kontext des LLM vorliegen — können Antwortfehler entstehen, die auf das Generierungsverhalten des Modells zurückzuführen sind, nicht auf das Retrieval. Im vorliegenden System wurden folgende Kategorien beobachtet:

**1. Citation Hallucination (vgl. TASK_07):** Das Modell generiert inhaltlich korrekte Aussagen aus seinem Parameterwissen und hängt einen thematisch passenden, aber inhaltlich unzutreffenden Chunk als Quelle an — statt ausschließlich aus dem Retrieval-Kontext zu zitieren.

**2. Falsche Quellenspezifität:** Bei Anfragen zu einzelnen Anforderungen (A1, A2 ...) zitiert das Modell die allgemeine Baustein-Beschreibung als Sammelquelle, anstatt den chunk-spezifischen Anforderungstext (`TASK_07: gleiche Bausteinbeschreibung als Sammelquelle für mehrere unterschiedliche Anforderungen`).

**3. Modalverb-Drift:** Anforderungen des IT-Grundschutzes sind modal differenziert (`MUSS`, `SOLLTE`, `DARF NICHT`). Das Modell paraphrasiert statt zu zitieren und verwischt dadurch normativ relevante Unterschiede.

**4. Erschöpfende Aufzählungen:** Bei breiten Anfragen tendiert das Modell dazu, alle im Kontext verfügbaren Punkte aufzulisten, anstatt eine kuratierte, strukturierte Auswahl zu treffen.

Diese Fehlerklassen sind **nicht retrieval-bedingt** — sie treten auch dann auf, wenn die richtigen Chunks im Kontext sind, und lassen sich durch gezielte Prompt-Anpassungen adressieren.

---

## Theoretischer Lösungsansatz: Evaluationsgetriebene Prompt-Iteration

### Grundprinzip

Prompt-Engineering bezeichnet die systematische Gestaltung von Eingabeanweisungen, um das Ausgabeverhalten großer Sprachmodelle zu steuern (Brown et al., 2020; Wei et al., 2022). Im RAG-Kontext betrifft dies insbesondere den System-Prompt, der das Modell über seine Rolle, die Nutzung des Retrieval-Kontexts und das Ausgabeformat instruiert.

Evaluationsgetriebene Iteration bedeutet, dass Prompt-Anpassungen nicht intuitiv, sondern **datengestützt** vorgenommen werden: Antwortfehler werden systematisch auf einem kuratierten Testset gemessen, auf Muster untersucht und durch präzise Prompt-Ergänzungen adressiert. Anschließend wird erneut gemessen, um Regression und Verbesserung zu quantifizieren. Dieses Vorgehen entspricht dem in der Literatur beschriebenen Konzept des **Prompt Optimization** (Zhou et al., 2022) und ist für domänenspezifische RAG-Systeme gut belegt (Es et al., 2023).

### Verhältnis zu Retrieval-Verbesserungen

Prompt-Iteration und Retrieval-Verbesserung (HyDE, Hybrid Retrieval) wirken an unterschiedlichen Stellen der RAG-Pipeline und sind deshalb komplementär, nicht alternativ:

```
Nutzerfrage → [Retrieval] → Chunks im Kontext → [Generierung] → Antwort
                  ↑                                     ↑
            HyDE / Hybrid                       Prompt-Iteration
```

Lewis et al. (2020) zeigen in der grundlegenden RAG-Arbeit, dass Retrievalqualität und Generierungsqualität voneinander unabhängige Verbesserungsdimensionen sind. Fehler in der Generierungskomponente lassen sich durch besseres Retrieval allein nicht beheben.

---

## Iterationsprozess

### Schritt 1: Baseline-Evaluation

Evaluation des aktuellen System-Prompts auf dem vorhandenen kuratierten Testset (123 einfache bzw. 43 komplexe Fragen) mit RAGAS-Metriken:

- **Faithfulness**: Anteil der Aussagen in der Antwort, die durch den Retrieval-Kontext belegbar sind — primäre Zielmetrik für citation-bezogene Fehler
- **Answer Relevancy**: Wie gut beantwortet die Antwort die gestellte Frage
- **Context Precision / Recall**: Qualität des Retrievals (Kontrollgröße — sollte durch Prompt-Iteration nicht beeinflusst werden)

### Schritt 2: Fehleranalyse

Qualitative Analyse der 10–15 schlechtesten Antworten (niedrigste Faithfulness-Scores). Klassifikation nach Fehlertyp:

| Fehlertyp | Erkennungsmerkmal | Prompt-Adressierung |
|---|---|---|
| Citation Hallucination | Quelle-Token verweist auf Chunk ohne belegenden Inhalt | Explizite Negativ-Instruktion: „Setze kein Quelle:-Token, wenn der Inhalt nicht wörtlich im Chunk steht" |
| Falsche Quellenspezifität | Baustein-Beschreibung als Quelle für einzelne Anforderung | Positive Instruktion: „Zitiere für jede Anforderung exakt den Chunk, aus dem ihr Inhalt stammt" |
| Modalverb-Drift | `MUSS` → `sollte` / `empfiehlt sich` | „Modalverben exakt aus den Dokumenten übernehmen (MUSS, SOLLTE, DARF NICHT)" |
| Erschöpfende Listen | >5 Punkte ohne Priorisierung | „Maximal 5 Punkte, bewusste Auswahl, Anschlussfrage ob weitere gewünscht" |

### Schritt 3: Gezielte Prompt-Anpassung

Jede Anpassung adressiert **genau einen** Fehlertyp und wird isoliert formuliert, um bei der Neu-Evaluation Wirkung und Nebenwirkungen getrennt beurteilen zu können. Bsharat et al. (2023) zeigen empirisch, dass präzise, aufgabenspezifische Anweisungen im System-Prompt zuverlässiger wirken als generische Formulierungen.

Bewährte Prinzipien für Instruktions-Formulierungen im IT-Grundschutz-Kontext:

- **Positiv + Negativ**: Nicht nur beschreiben was das Modell tun soll, sondern explizit, was es nicht tun darf (`„Niemals eine Fundstelle verwenden, die den zitierten Inhalt nicht enthält"`)
- **Beispiele im Prompt**: Pflichtbeispiele für korrektes Zitierformat reduzieren Format-Fehler messbar (Wei et al., 2022, Few-Shot Prompting)
- **Reihenfolge**: Kritische Regeln nahe am Ende des System-Prompts platzieren — LLM-Attention ist zum Antwortbeginn auf den Promptende fokussiert (Liu et al., 2023)

### Schritt 4: Neu-Evaluation und Vergleich

Evaluation desselben Testsets nach Anpassung. Ziel: Faithfulness steigt, Answer Relevancy bleibt stabil oder steigt, Context Precision/Recall unverändert.

---

## Methodische Einordnung für die Masterarbeit

Prompt-Iteration ist in der akademischen Literatur als eigenständige Forschungsmethode anerkannt. Für die Masterarbeit ergibt sich folgende Einordnung:

Die im System-Prompt formulierten Regeln zur Quellenangabe (`Quelle:`-Format, Inline-Platzierung, Negativ-Instruktionen) entsprechen dem Konzept der **Task Decomposition** in Instruktions-Prompts (Wei et al., 2022): komplexe Verhaltensanforderungen werden in atomare, überprüfbare Teilanforderungen zerlegt. Die Wirksamkeit dieser Zerlegung lässt sich durch den Faithfulness-Score vor und nach Anpassung quantifizieren, was einen sauberen empirischen Vergleichspunkt für die Arbeit liefert.

Die Kombination aus RAGAS-Evaluation und manueller Fehleranalyse entspricht dem **Mixed-Methods-Ansatz** in der NLP-Evaluationsforschung: automatische Metriken identifizieren Ausreißer, manuelle Analyse erklärt deren Ursache (Es et al., 2023).

---

## Kombinierbarkeit mit HyDE (vgl. TASK_10_1)

HyDE und Prompt-Iteration sind sequenziell kombinierbar, sollten aber **getrennt eingeführt und gemessen** werden:

1. Baseline (aktueller Stand)
2. + HyDE → Messung: Δ Context Recall
3. + Prompt-Iteration → Messung: Δ Faithfulness

Dieses Vorgehen erzeugt zwei klar attributierbare Datenpunkte und entspricht dem Prinzip der **Controlled Ablation** in der Systemevaluation — jede Komponente wird isoliert bewertet, bevor die kombinierte Wirkung gemessen wird.

---

## Referenzen

- Brown, T. et al. (2020). Language Models are Few-Shot Learners. *Advances in Neural Information Processing Systems*, 33, 1877–1901.
- Wei, J. et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. *Advances in Neural Information Processing Systems*, 35, 24824–24837.
- Zhou, Y. et al. (2022). Large Language Models Are Human-Level Prompt Engineers. *arXiv preprint* arXiv:2211.01910.
- Bsharat, S. M., Myrzakhan, A. & Shen, Z. (2023). Principled Instructions Are All You Need for Questioning LLaMA-1/2, GPT-3.5/4. *arXiv preprint* arXiv:2312.16171.
- Liu, N. F. et al. (2023). Lost in the Middle: How Language Models Use Long Contexts. *Transactions of the Association for Computational Linguistics*, 12, 157–173.
- Lewis, P. et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *Advances in Neural Information Processing Systems*, 33, 9459–9474.
- Es, S. et al. (2023). RAGAS: Automated Evaluation of Retrieval Augmented Generation. *arXiv preprint* arXiv:2309.15217.
