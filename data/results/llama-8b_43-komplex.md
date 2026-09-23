# Evaluation Results: llama-8b_43-komplex

Generated on: 2026-06-15 16:00:01

## Input Data

- **Description**: docling-sections, bge-m3, llama-3.1-8b
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_43_Komplex_v22.csv`
- **Number of Questions**: 42

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
| Context Precision | 59.7% | 0.0% | 100.0% | 28.0% |
| Context Recall | 84.5% | 28.9% | 100.0% | 23.3% |
| Faithfulness | 53.8% | 0.0% | 100.0% | 32.9% |
| Answer Correctness | 58.9% | 28.4% | 87.8% | 15.5% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `llama-8b_43-komplex.csv`
- Compact CSV without retrieved contexts: `llama-8b_43-komplex_compact.csv`
- This README: `llama-8b_43-komplex.md`
