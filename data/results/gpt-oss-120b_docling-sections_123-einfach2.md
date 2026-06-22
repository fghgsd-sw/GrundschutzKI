# Evaluation Results: gpt-oss-120b_docling-sections_123-einfach2

Generated on: 2026-05-24 12:11:11

## Input Data

- **Description**: Docling-JSON, Section-Chunking (heading-driven)
- **Evaluation Dataset**: `data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen2.csv`
- **Number of Questions**: 9

## Model Configuration

| Parameter | Value |
|-----------|-------|
| LLM Model | `gpt-oss-120b` |
| Embedding Model | `octen-embedding-8b` |
| Temperature | 0.2 |
| Seed | 42 |

## Preprocessing & Retrieval

| Parameter | Value |
|-----------|-------|
| Chunk Size | 0 characters |
| Chunk Overlap | 0 characters |
| Top-K Retrieval | 5 |

## RAGAS Evaluation Metrics

| Metric | Average | Min | Max | Std Dev |
|--------|---------|-----|-----|---------|
| Context Precision | 96.0% | 80.4% | 100.0% | 8.0% |
| Context Recall | 100.0% | 100.0% | 100.0% | 0.0% |
| Faithfulness | 81.1% | 50.0% | 100.0% | 20.7% |
| Answer Correctness | 72.0% | 36.2% | 99.4% | 20.9% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

- ✅ No concerning patterns detected in the metrics

## Output Files

- Full CSV with retrieved contexts: `gpt-oss-120b_docling-sections_123-einfach2.csv`
- Compact CSV without retrieved contexts: `gpt-oss-120b_docling-sections_123-einfach2_compact.csv`
- This README: `gpt-oss-120b_docling-sections_123-einfach2.md`
