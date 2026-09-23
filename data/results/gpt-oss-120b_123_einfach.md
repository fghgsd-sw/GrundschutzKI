# Evaluation Results: gpt-oss-120b_123_einfach

Generated on: 2026-06-18 21:02:44

## Input Data

- **Description**: docling-sections, bge-m3, gpt-oss-120b
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_123_Einfach_v22.csv`
- **Number of Questions**: 122

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
| Context Precision | 77.2% | 0.0% | 100.0% | 23.4% |
| Context Recall | 82.3% | 0.0% | 100.0% | 27.3% |
| Faithfulness | 62.2% | 0.0% | 100.0% | 35.4% |
| Answer Correctness | 52.2% | 8.1% | 99.5% | 27.1% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `gpt-oss-120b_123_einfach.csv`
- Compact CSV without retrieved contexts: `gpt-oss-120b_123_einfach_compact.csv`
- This README: `gpt-oss-120b_123_einfach.md`
