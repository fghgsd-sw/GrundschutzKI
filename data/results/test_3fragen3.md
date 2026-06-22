# Evaluation Results: test_3fragen3

Generated on: 2026-06-14 16:15:56

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
| Context Precision | 70.3% | 55.4% | 85.4% | 15.0% |
| Context Recall | 82.7% | 75.0% | 87.5% | 6.8% |
| Faithfulness | 66.7% | 0.0% | 100.0% | 57.7% |
| Answer Correctness | 55.6% | 9.6% | 91.0% | 41.7% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `test_3fragen3.csv`
- Compact CSV without retrieved contexts: `test_3fragen3_compact.csv`
- This README: `test_3fragen3.md`
