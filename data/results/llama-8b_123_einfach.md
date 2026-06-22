# Evaluation Results: llama-8b_123_einfach

Generated on: 2026-06-16 16:38:51

## Input Data

- **Description**: docling-sections, bge-m3, llama-3.1-8b
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_123_Einfach_v22.csv`
- **Number of Questions**: 122

## Model Configuration

| Parameter | Value |
|-----------|-------|
| LLM Model | `openai/meta-llama/Meta-Llama-3.1-8B-Instruct` |
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
| Context Precision | 74.4% | 0.0% | 100.0% | 21.9% |
| Context Recall | 90.3% | 8.3% | 100.0% | 20.3% |
| Faithfulness | 61.1% | 0.0% | 100.0% | 32.6% |
| Answer Correctness | 59.2% | 27.2% | 92.3% | 14.2% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `llama-8b_123_einfach.csv`
- Compact CSV without retrieved contexts: `llama-8b_123_einfach_compact.csv`
- This README: `llama-8b_123_einfach.md`
