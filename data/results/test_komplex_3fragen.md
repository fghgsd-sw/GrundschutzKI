# Evaluation Results: test_komplex_3fragen

Generated on: 2026-06-14 18:01:47

## Input Data

- **Description**: docling-sections, bge-m3, gpt-oss-120b
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_43_Komplex_v22.csv`
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
| Context Precision | 85.3% | 61.0% | 100.0% | 21.2% |
| Context Recall | 62.5% | 37.5% | 100.0% | 33.1% |
| Faithfulness | 93.3% | 85.7% | 100.0% | 7.2% |
| Answer Correctness | 44.7% | 33.2% | 63.7% | 16.6% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `test_komplex_3fragen.csv`
- Compact CSV without retrieved contexts: `test_komplex_3fragen_compact.csv`
- This README: `test_komplex_3fragen.md`
