# Evaluation Results: test_3fragen2

Generated on: 2026-06-14 15:44:30

## Input Data

- **Description**: docling-sections, bge-m3, test
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_123_Einfach.csv`
- **Number of Questions**: 3

## Model Configuration

| Parameter | Value |
|-----------|-------|
| LLM Model | `openai/openai/gpt-oss-120b` |
| Embedding Model | `openai/BAAI/bge-m3` |
| Temperature | 0.0 |
| Seed | 42 |

## Preprocessing & Retrieval

| Parameter | Value |
|-----------|-------|
| Chunk Size | 4000 characters |
| Chunk Overlap | 200 characters |
| Top-K Retrieval | 8 |

## RAGAS Evaluation Metrics

> **Hinweis:** `faithfulness` und `answer_correctness` werden auf dem
> **Hauptteil** der Antwort berechnet – der Anschlussfragen-Block
> (ab `Anschlussfragen:`) wird vor dem Scoring abgetrennt, da Folgefragen
> nicht aus dem Retrieval-Kontext belegbar sind und nicht semantisch mit
> der Referenzantwort übereinstimmen müssen. Die Folgefragen werden
> separat durch Fach-Experten bewertet.

| Metric | Average | Min | Max | Std Dev |
|--------|---------|-----|-----|---------|
| Context Precision | 78.8% | 70.0% | 85.4% | 7.9% |
| Context Recall | 95.2% | 85.7% | 100.0% | 8.2% |
| Faithfulness | 33.3% | 0.0% | 66.7% | 47.1% |
| Answer Correctness | 36.1% | 7.8% | 91.0% | 47.5% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ⚠️ High Precision + Low Faithfulness: Answer doesn't properly use the context

## Output Files

- Full CSV with retrieved contexts: `test_3fragen2.csv`
- Compact CSV without retrieved contexts: `test_3fragen2_compact.csv`
- This README: `test_3fragen2.md`
