"""
Evaluation script for generating CSV files with LLM answers and RAGAS metrics.

This script runs a full RAG evaluation pipeline on the IT-Grundschutz question-answer dataset,
generating both a CSV with all results and a README documenting the experiment configuration.

Usage as CLI:
    python scripts/run_evaluation.py \\
        --llm openai/gpt-oss-120b \\
        --embedding-model openai/BAAI/bge-m3 \\
        --input-data-description "XML Kompendium 2023, char-based chunking (4000/200)" \\
        --chunk-size 4000 --chunk-overlap 200 --top-k 5 \\
        --temperature 0.2 \\
        --output-name gpt-oss_kompendium-xml

Usage as library (e.g. from a notebook):
    from scripts.run_evaluation import generate_evaluation_results
    generate_evaluation_results(llm=..., embedding_model=..., ...)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd

# Ensure notebooks/ is importable for litellm_client
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"

# Load .env from notebooks/ directory
try:
    from dotenv import load_dotenv
    env_path = NOTEBOOKS_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    pass

if str(NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS_DIR))

from litellm_client import (
    LLMConfig,
    VectorDBConfig,
    chat_completion,
    get_embeddings,
    get_qdrant_client,
    load_llm_config,
    load_vectordb_config,
)


JUDGE_MODEL_DEFAULT = "openai/meta-llama/Llama-3.3-70B-Instruct"

JUDGE_SYSTEM_PROMPT = """\
Du bist Evaluator für ein RAG-Chatbot-System über das IT-Grundschutz-Kompendium des BSI.

Bewerte eine generierte Anschlussfrage anhand zweier Kriterien:

1. **Beantwortbarkeit** (answerability): Ist die Anschlussfrage durch die \
IT-Grundschutz-Dokumente beantwortbar?
   - 2 = Vollständig durch IT-Grundschutz abgedeckt
   - 1 = Teilweise abgedeckt oder nur indirekt
   - 0 = Nicht durch IT-Grundschutz abgedeckt

2. **Relevanz** (relevance): Ist die Anschlussfrage thematisch passend zur Ausgangsfrage?
   - 2 = Direkt relevant und sinnvolle Vertiefung
   - 1 = Tangential relevant
   - 0 = Nicht relevant oder thematisch weit entfernt

Antworte ausschließlich als JSON-Objekt, ohne weitere Erklärung:
{"answerability": <0|1|2>, "relevance": <0|1|2>, "reason": "<Begründung, max. 30 Wörter>"}\
"""

FOLLOWUP_ITEM_EXTRACT_RE = re.compile(r"^\s*\d+\.\s+(.+\?)\s*$", re.MULTILINE)


@dataclass
class EvaluationConfig:
    """Configuration for the evaluation run."""

    # Required parameters
    llm: str
    embedding_model: str
    input_data_description: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    output_name: str
    temperature: float

    # Optional parameters with defaults
    seed: int = 42
    eval_csv_path: str = "data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen.csv"
    judge_model: str = JUDGE_MODEL_DEFAULT
    evaluate_followups: bool = True
    limit: Optional[int] = None
    resume: bool = False


def _set_seed(seed: int) -> None:
    """Set random seed for reproducibility."""
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass


def _retrieve_contexts(
    question: str,
    top_k: int,
    client,
    collection_name: str,
    llm_cfg: LLMConfig,
) -> List[str]:
    """Retrieve top-k context chunks from Qdrant for a given question."""
    query_emb = get_embeddings([question], llm_cfg, batch_size=1)[0]
    results = client.query_points(
        collection_name=collection_name,
        query=query_emb,
        limit=top_k,
    ).points
    return [res.payload.get("text", "") for res in results]


SYSTEM_MD_PATH = PROJECT_ROOT / "system.md"

FOLLOWUP_SPLIT_RE = re.compile(r"\n\s*\**\s*Anschlussfragen:\s*\**\s*\n", re.IGNORECASE)
FOLLOWUP_ITEM_RE = re.compile(r"^\s*\d+\.\s+.+\?\s*$", re.MULTILINE)


def _load_system_prompt(path: Path = SYSTEM_MD_PATH) -> str:
    return path.read_text(encoding="utf-8")


def _strip_followups(text: str) -> tuple[str, str]:
    """Split an answer at the 'Anschlussfragen:' header.

    Returns (main_part, followups_block). If no header is found, the entire
    text is returned as main_part and followups_block is empty.
    """
    if not text:
        return "", ""
    parts = FOLLOWUP_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].rstrip(), parts[1].strip()
    return text.strip(), ""


def _count_followups(followups_block: str) -> int:
    if not followups_block:
        return 0
    return len(FOLLOWUP_ITEM_RE.findall(followups_block))


def _extract_followup_list(followups_block: str) -> List[str]:
    """Extract individual follow-up question strings from the followups block."""
    if not followups_block:
        return []
    return [m.strip() for m in FOLLOWUP_ITEM_EXTRACT_RE.findall(followups_block) if m.strip()]


def _judge_followup(
    original_question: str,
    followup_question: str,
    contexts: List[str],
    llm_cfg: LLMConfig,
    judge_model: str,
) -> dict:
    """Run LLM-as-judge for a single follow-up question.

    Returns a dict with keys: answerability (0-2), relevance (0-2), reason (str).
    On failure returns answerability=-1, relevance=-1.
    """
    contexts_text = "\n\n".join(f"[{i+1}] {c[:600]}" for i, c in enumerate(contexts))
    user_content = (
        f"Ausgangsfrage: {original_question}\n\n"
        f"Anschlussfrage: {followup_question}\n\n"
        f"Relevante IT-Grundschutz-Abschnitte (Top-3 Retrieval):\n{contexts_text}"
    )

    judge_cfg = LLMConfig(
        api_base=llm_cfg.api_base,
        api_key=llm_cfg.api_key,
        model=judge_model,
        embedding_model=llm_cfg.embedding_model,
    )
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        response = chat_completion(messages, judge_cfg, temperature=0.0)
        content = (
            response["choices"][0]["message"]["content"]
            if isinstance(response, dict)
            else response.choices[0].message.content
        )
        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            return {
                "answerability": max(0, min(2, int(parsed.get("answerability", 0)))),
                "relevance": max(0, min(2, int(parsed.get("relevance", 0)))),
                "reason": str(parsed.get("reason", ""))[:200],
            }
    except Exception as exc:
        print(f"  [WARN] Judge failed for '{followup_question[:60]}': {exc}")

    return {"answerability": -1, "relevance": -1, "reason": "evaluation_failed"}


def _run_followup_evaluation(
    records: List[dict],
    llm_cfg: LLMConfig,
    judge_model: str,
    qdrant_client: Any,
    collection_name: str,
) -> List[List[dict]]:
    """Run LLM-as-judge for every follow-up question in every record.

    Returns a list (one entry per record) of lists (one entry per follow-up).
    Each entry: {followup, answerability, relevance, reason}.
    """
    all_results: List[List[dict]] = []
    print(f"  Judge model: {judge_model}")

    for i, record in enumerate(records):
        followups = _extract_followup_list(record["answer_followups"])[:3]
        record_scores: List[dict] = []

        for fq in followups:
            contexts = _retrieve_contexts(fq, 3, qdrant_client, collection_name, llm_cfg)
            score = _judge_followup(record["question"], fq, contexts, llm_cfg, judge_model)
            score["followup"] = fq
            record_scores.append(score)

        all_results.append(record_scores)

        if (i + 1) % 10 == 0:
            print(f"  Judged follow-ups for {i+1}/{len(records)} questions...")

    return all_results


def _build_messages(
    question: str,
    contexts: List[str],
    system_prompt: str,
) -> List[dict]:
    """Build chat messages for the LLM using the production system prompt."""
    context_text = "\n\n".join(contexts)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Frage: {question}\n\nKontext:\n{context_text}"},
    ]


def _generate_answer(
    messages: List[dict],
    llm_cfg: LLMConfig,
    temperature: float,
    seed: int,
) -> str:
    """Generate an answer using the LLM."""
    response = chat_completion(messages, llm_cfg, temperature=temperature, seed=seed)
    
    # Extract content from response
    if isinstance(response, dict):
        return response["choices"][0]["message"]["content"]
    if hasattr(response, "choices"):
        return response.choices[0].message.content
    raise TypeError(f"Unexpected response type: {type(response)}")


async def _score_row_async(
    row: dict,
    scorers: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Score a single row with all RAGAS metrics asynchronously."""
    async with semaphore:
        try:
            context_precision = await scorers["context_precision"].ascore(
                user_input=row["question"],
                reference=row["ground_truth_context"],
                retrieved_contexts=row["contexts"],
            )
            context_recall = await scorers["context_recall"].ascore(
                user_input=row["question"],
                reference=row["ground_truth_context"],
                retrieved_contexts=row["contexts"],
            )
            faithfulness = await scorers["faithfulness"].ascore(
                user_input=row["question"],
                response=row["answer_main"],
                retrieved_contexts=row["contexts"],
            )
            answer_correctness = await scorers["answer_correctness"].ascore(
                user_input=row["question"],
                response=row["answer_main"],
                reference=row["ground_truth_answer_main"],
            )
            
            return {
                "context_precision": context_precision.value,
                "context_recall": context_recall.value,
                "faithfulness": faithfulness.value,
                "answer_correctness": answer_correctness.value,
            }
        except Exception as e:
            print(
                f"  [WARN] RAGAS failed for '{row['question'][:80]}': "
                f"{type(e).__name__}: {str(e)[:200]}"
            )
            return {
                "context_precision": float("nan"),
                "context_recall": float("nan"),
                "faithfulness": float("nan"),
                "answer_correctness": float("nan"),
            }


async def _run_ragas_evaluation(
    records: List[dict],
    llm_cfg: LLMConfig,
    temperature: float,
    concurrency: int = 2,
) -> List[dict]:
    """Run RAGAS evaluation on all records."""
    # Import RAGAS dependencies
    try:
        from ragas.llms import llm_factory
        from ragas.embeddings.litellm_provider import LiteLLMEmbeddings
        from ragas.metrics.collections import (
            ContextPrecision,
            ContextRecall,
            Faithfulness,
            AnswerCorrectness,
        )
        import instructor
        import litellm
    except ImportError as e:
        raise ImportError(
            "RAGAS dependencies not installed. Please install with:\n"
            "  pip install ragas instructor litellm datasets"
        ) from e

    # Configure LiteLLM
    litellm.api_base = llm_cfg.api_base
    litellm.api_key = llm_cfg.api_key

    # Create RAGAS LLM and embeddings
    client = instructor.from_litellm(litellm.acompletion, mode=instructor.Mode.MD_JSON)
    llm = llm_factory(
        llm_cfg.model,
        client=client,
        adapter="litellm",
        model_args={"temperature": temperature},
    )
    embeddings = LiteLLMEmbeddings(
        model=llm_cfg.embedding_model,
        api_key=llm_cfg.api_key,
        api_base=llm_cfg.api_base,
        encoding_format="float",
    )

    # Create scorers
    scorers = {
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "faithfulness": Faithfulness(llm=llm),
        "answer_correctness": AnswerCorrectness(llm=llm, embeddings=embeddings),
    }

    # Score all records
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        asyncio.create_task(_score_row_async(record, scorers, semaphore))
        for record in records
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    scores = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  [WARN] Task {i} raised: {type(r).__name__}: {str(r)[:200]}")
            scores.append({
                "context_precision": float("nan"),
                "context_recall": float("nan"),
                "faithfulness": float("nan"),
                "answer_correctness": float("nan"),
            })
        else:
            scores.append(r)
    return scores


def _compute_statistics(values: List[float]) -> dict:
    """Compute statistics for a list of values, ignoring NaN."""
    import math
    clean = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    if not clean:
        return {"avg": float("nan"), "min": float("nan"), "max": float("nan"), "std": 0.0}
    return {
        "avg": statistics.mean(clean),
        "min": min(clean),
        "max": max(clean),
        "std": statistics.stdev(clean) if len(clean) > 1 else 0.0,
    }


def _generate_readme(
    config: EvaluationConfig,
    stats: dict,
    num_questions: int,
    timestamp: str,
) -> str:
    """Generate README content documenting the evaluation run."""
    
    readme = f"""# Evaluation Results: {config.output_name}

Generated on: {timestamp}

## Input Data

- **Description**: {config.input_data_description}
- **Evaluation Dataset**: `{config.eval_csv_path}`
- **Number of Questions**: {num_questions}

## Model Configuration

| Parameter | Value |
|-----------|-------|
| LLM Model | `{config.llm}` |
| Embedding Model | `{config.embedding_model}` |
| Temperature | {config.temperature} |
| Seed | {config.seed} |

## Preprocessing & Retrieval

| Parameter | Value |
|-----------|-------|
| Chunk Size | {config.chunk_size} characters |
| Chunk Overlap | {config.chunk_overlap} characters |
| Top-K Retrieval | {config.top_k} |

## RAGAS Evaluation Metrics

> **Hinweis:** `faithfulness` und `answer_correctness` werden auf dem
> **Hauptteil** der Antwort berechnet – der Anschlussfragen-Block
> (ab `Anschlussfragen:`) wird vor dem Scoring abgetrennt, da Folgefragen
> nicht aus dem Retrieval-Kontext belegbar sind und nicht semantisch mit
> der Referenzantwort übereinstimmen müssen. Die Folgefragen werden
> separat durch Fach-Experten bewertet.

| Metric | Average | Min | Max | Std Dev |
|--------|---------|-----|-----|---------|
| Context Precision | {stats['context_precision']['avg']*100:.1f}% | {stats['context_precision']['min']*100:.1f}% | {stats['context_precision']['max']*100:.1f}% | {stats['context_precision']['std']*100:.1f}% |
| Context Recall | {stats['context_recall']['avg']*100:.1f}% | {stats['context_recall']['min']*100:.1f}% | {stats['context_recall']['max']*100:.1f}% | {stats['context_recall']['std']*100:.1f}% |
| Faithfulness | {stats['faithfulness']['avg']*100:.1f}% | {stats['faithfulness']['min']*100:.1f}% | {stats['faithfulness']['max']*100:.1f}% | {stats['faithfulness']['std']*100:.1f}% |
| Answer Correctness | {stats['answer_correctness']['avg']*100:.1f}% | {stats['answer_correctness']['min']*100:.1f}% | {stats['answer_correctness']['max']*100:.1f}% | {stats['answer_correctness']['std']*100:.1f}% |

## Metrics Interpretation

- **Context Precision**: How much of the retrieved context is actually relevant (higher = less noise)
- **Context Recall**: How much of the relevant information is captured in the context (higher = better retrieval)
- **Faithfulness**: How well the answer is grounded in the provided context (higher = less hallucination)
- **Answer Correctness**: Semantic similarity between generated and ground truth answers (higher = more accurate)

### Rule of Thumb Analysis

"""
    
    # Add rule of thumb hints
    precision_avg = stats['context_precision']['avg']
    recall_avg = stats['context_recall']['avg']
    faithfulness_avg = stats['faithfulness']['avg']
    
    HIGH = 0.75
    LOW = 0.5
    
    hints = []
    if recall_avg >= HIGH and precision_avg <= LOW:
        hints.append("- ⚠️ High Recall + Low Precision: Too much context or poor answer formulation")
    if precision_avg >= HIGH and faithfulness_avg <= LOW:
        hints.append("- ⚠️ High Precision + Low Faithfulness: Answer doesn't properly use the context")
    if precision_avg <= LOW and recall_avg >= HIGH:
        hints.append("- ⚠️ Low Precision + High Recall: Retrieval returns a lot but imprecisely")
    
    if not hints:
        hints.append("- ✅ No concerning patterns detected in the metrics")
    
    readme += "\n".join(hints)
    
    readme += """

## Output Files

- Full CSV with retrieved contexts: `{output_name}.csv`
- Compact CSV without retrieved contexts: `{output_name}_compact.csv`
- This README: `{output_name}.md`
""".format(output_name=config.output_name)
    
    return readme


def generate_evaluation_results(
    llm: str,
    embedding_model: str,
    input_data_description: str,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    output_name: str,
    temperature: float,
    seed: int = 42,
    eval_csv_path: str = "data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen.csv",
    judge_model: str = JUDGE_MODEL_DEFAULT,
    evaluate_followups: bool = True,
    limit: Optional[int] = None,
    resume: bool = False,
) -> Path:
    """
    Generate evaluation CSV and README files.
    
    This function runs the complete RAG evaluation pipeline:
    1. Loads questions from the evaluation CSV
    2. Retrieves context chunks for each question
    3. Generates answers using the specified LLM
    4. Evaluates answers using RAGAS metrics
    5. Saves results to CSV and generates documentation README
    
    Args:
        llm: LLM model identifier (e.g., "openai/gpt-oss-120b")
        embedding_model: Embedding model identifier (e.g., "openai/octen-embedding-8b")
        input_data_description: Free-text description of input data and preprocessing
        chunk_size: Character size of chunks in vector database
        chunk_overlap: Character overlap between chunks
        top_k: Number of chunks to retrieve per question
        output_name: Base name for output files (without extension)
        temperature: LLM temperature setting
        seed: Random seed for reproducibility (default: 42)
        eval_csv_path: Path to evaluation CSV file (default: standard location)
    
    Returns:
        Path to the generated CSV file
    
    Raises:
        RuntimeError: If RAGAS evaluation fails for any question
        FileNotFoundError: If evaluation CSV does not exist
        ValueError: If required environment variables are not set
    """
    
    # Create configuration
    config = EvaluationConfig(
        llm=llm,
        embedding_model=embedding_model,
        input_data_description=input_data_description,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        top_k=top_k,
        output_name=output_name,
        temperature=temperature,
        seed=seed,
        eval_csv_path=eval_csv_path,
        judge_model=judge_model,
        evaluate_followups=evaluate_followups,
        limit=limit,
        resume=resume,
    )
    
    # Set seed for reproducibility
    _set_seed(config.seed)
    
    print(f"Starting evaluation: {config.output_name}")
    print(f"  LLM: {config.llm}")
    print(f"  Embedding: {config.embedding_model}")
    print(f"  Temperature: {config.temperature}, Seed: {config.seed}")
    print()
    
    # Resolve paths
    if not os.path.isabs(config.eval_csv_path):
        eval_csv_full = PROJECT_ROOT / config.eval_csv_path
    else:
        eval_csv_full = Path(config.eval_csv_path)
    
    if not eval_csv_full.exists():
        raise FileNotFoundError(f"Evaluation CSV not found: {eval_csv_full}")
    
    # Load evaluation data
    print(f"Loading evaluation data from: {eval_csv_full}")
    df = pd.read_csv(eval_csv_full, sep=";", encoding="utf-8-sig")
    print(f"  Loaded {len(df)} questions")
    print()
    
    # Load LLM and VectorDB config from environment
    llm_cfg = LLMConfig(
        api_base=os.getenv("LITELLM_BASE_URL"),
        api_key=os.getenv("LITELLM_API_KEY"),
        model=config.llm,
        embedding_model=config.embedding_model,
    )
    vec_cfg = load_vectordb_config()
    qdrant_client = get_qdrant_client(vec_cfg)
    collection_name = vec_cfg.collection or "grundschutz_xml"
    
    # Load production system prompt (system.md)
    system_prompt = _load_system_prompt()
    print(f"Loaded system prompt: {SYSTEM_MD_PATH} ({len(system_prompt)} chars)")

    # Prefer v2-production ground truth column if present (regenerated answers
    # aligned with system.md format). Falls back to legacy 'Antwort' column.
    truth_col = "Antwort_v2_production" if "Antwort_v2_production" in df.columns else "Antwort"
    print(f"Using ground truth column: {truth_col}")

    # Build records for all questions (skip first row to keep historical row-count parity)
    print("Retrieving contexts and generating answers...")
    output_dir = PROJECT_ROOT / "data" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_path = output_dir / f"{config.output_name}_answers.csv"

    _ANSWERS_FIELDNAMES = [
        "Frage", "Antwort", "Antwort (Hauptteil)", "Fundstellen",
        "Generierte Antwort", "Generierte Antwort (Hauptteil)",
        "Generierte Anschlussfragen", "followup_count_generated",
        "followup_count_truth", "Ermittelte Fundstellen",
    ]

    # Resume support: skip questions already in _answers.csv when --resume is set
    done_questions: set[str] = set()
    if config.resume and intermediate_path.exists():
        existing_df = pd.read_csv(intermediate_path, sep=";", encoding="utf-8-sig")
        done_questions = set(existing_df["Frage"].dropna().tolist())
        print(f"  Resuming: {len(done_questions)} questions already done, skipping.")

    ans_file_mode = "a" if done_questions else "w"
    ans_file = intermediate_path.open(ans_file_mode, encoding="utf-8-sig", newline="")
    import csv as _csv
    ans_writer = _csv.DictWriter(ans_file, fieldnames=_ANSWERS_FIELDNAMES, delimiter=";")
    if ans_file_mode == "w":
        ans_writer.writeheader()

    records = []
    checkpoint_size = 10
    checkpoint_buf: list[dict] = []

    rows = df.iloc[1:]
    if config.limit:
        rows = rows.head(config.limit)

    try:
        for i, (idx, row) in enumerate(rows.iterrows(), start=1):
            question = row["Frage"]
            if question in done_questions:
                continue

            ground_truth_answer = row[truth_col]
            ground_truth_context = row["Fundstellen im IT-Grundschutz-Kompendium 2023"]

            contexts = _retrieve_contexts(
                question, config.top_k, qdrant_client, collection_name, llm_cfg
            )

            messages = _build_messages(question, contexts, system_prompt)
            answer = _generate_answer(messages, llm_cfg, config.temperature, config.seed)

            answer_main, answer_followups = _strip_followups(answer)
            gt_main, gt_followups = _strip_followups(ground_truth_answer)

            record = {
                "question": question,
                "answer": answer,
                "answer_main": answer_main,
                "answer_followups": answer_followups,
                "followup_count_generated": _count_followups(answer_followups),
                "contexts": contexts,
                "ground_truth_answer": ground_truth_answer,
                "ground_truth_answer_main": gt_main,
                "ground_truth_followups": gt_followups,
                "followup_count_truth": _count_followups(gt_followups),
                "ground_truth_context": ground_truth_context,
            }
            records.append(record)
            checkpoint_buf.append({
                "Frage": question,
                "Antwort": ground_truth_answer,
                "Antwort (Hauptteil)": gt_main,
                "Fundstellen": ground_truth_context,
                "Generierte Antwort": answer,
                "Generierte Antwort (Hauptteil)": answer_main,
                "Generierte Anschlussfragen": answer_followups,
                "followup_count_generated": record["followup_count_generated"],
                "followup_count_truth": record["followup_count_truth"],
                "Ermittelte Fundstellen": "\n".join(contexts),
            })

            if len(checkpoint_buf) >= checkpoint_size:
                ans_writer.writerows(checkpoint_buf)
                ans_file.flush()
                checkpoint_buf.clear()
                print(f"  [checkpoint] {i} questions written to {intermediate_path.name}")
            elif i % 10 == 0:
                print(f"  Processed {i}/{len(rows)} questions...")

        if checkpoint_buf:
            ans_writer.writerows(checkpoint_buf)
            ans_file.flush()
            checkpoint_buf.clear()
    finally:
        ans_file.close()

    print(f"  Generated {len(records)} answers")
    print(f"  Saved intermediate answers: {intermediate_path}")
    print()
    
    # Run RAGAS evaluation
    print("Running RAGAS evaluation...")
    
    # Handle async execution (works in both Jupyter and script contexts)
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context (e.g., Jupyter)
        import nest_asyncio
        nest_asyncio.apply()
        scores = asyncio.get_event_loop().run_until_complete(
            _run_ragas_evaluation(records, llm_cfg, config.temperature)
        )
    except RuntimeError:
        # No running event loop, create a new one
        scores = asyncio.run(
            _run_ragas_evaluation(records, llm_cfg, config.temperature)
        )
    
    print("  RAGAS evaluation complete")
    print()

    # Follow-up question evaluation (LLM-as-judge)
    followup_results: List[List[dict]] = []
    if config.evaluate_followups:
        print("Running follow-up question evaluation (LLM-as-judge)...")
        followup_results = _run_followup_evaluation(
            records, llm_cfg, config.judge_model, qdrant_client, collection_name
        )
        print("  Follow-up evaluation complete")
        print()
    else:
        followup_results = [[] for _ in records]

    # Compute statistics
    stats = {
        metric: _compute_statistics([s[metric] for s in scores])
        for metric in ["context_precision", "context_recall", "faithfulness", "answer_correctness"]
    }

    # Follow-up aggregate stats (only valid scores >= 0)
    all_ans = [s["answerability"] for fq_list in followup_results for s in fq_list if s.get("answerability", -1) >= 0]
    all_rel = [s["relevance"] for fq_list in followup_results for s in fq_list if s.get("relevance", -1) >= 0]
    followup_stats = {
        "answerability": _compute_statistics(all_ans) if all_ans else {},
        "relevance": _compute_statistics(all_rel) if all_rel else {},
        "n_evaluated": len(all_ans),
    }
    
    # Create output directory
    output_dir = PROJECT_ROOT / "data" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare CSV data
    # Use newline as delimiter for retrieved contexts (same as Fundstellen)
    csv_records = []
    for record, score, fq_scores in zip(records, scores, followup_results):
        row: dict = {
            "Frage": record["question"],
            "Antwort": record["ground_truth_answer"],
            "Antwort (Hauptteil)": record["ground_truth_answer_main"],
            "Fundstellen": record["ground_truth_context"],
            "Generierte Antwort": record["answer"],
            "Generierte Antwort (Hauptteil)": record["answer_main"],
            "Generierte Anschlussfragen": record["answer_followups"],
            "followup_count_generated": record["followup_count_generated"],
            "followup_count_truth": record["followup_count_truth"],
            "Ermittelte Fundstellen": "\n".join(record["contexts"]),
            "context_precision": score["context_precision"],
            "context_recall": score["context_recall"],
            "faithfulness": score["faithfulness"],
            "answer_correctness": score["answer_correctness"],
        }
        # Per-follow-up judge scores (up to 3)
        for j, fq in enumerate(fq_scores, 1):
            row[f"followup_q{j}"] = fq.get("followup", "")
            row[f"followup_q{j}_answerability"] = fq.get("answerability", "")
            row[f"followup_q{j}_relevance"] = fq.get("relevance", "")
            row[f"followup_q{j}_reason"] = fq.get("reason", "")
        # Row-level averages
        valid_ans = [fq["answerability"] for fq in fq_scores if fq.get("answerability", -1) >= 0]
        valid_rel = [fq["relevance"] for fq in fq_scores if fq.get("relevance", -1) >= 0]
        row["followup_avg_answerability"] = round(statistics.mean(valid_ans), 3) if valid_ans else None
        row["followup_avg_relevance"] = round(statistics.mean(valid_rel), 3) if valid_rel else None
        csv_records.append(row)
    
    # Write full CSV (with retrieved contexts)
    csv_path = output_dir / f"{config.output_name}.csv"
    csv_df = pd.DataFrame(csv_records)
    csv_df.to_csv(csv_path, sep=";", index=False, encoding="utf-8-sig", decimal=".")
    print(f"Saved full CSV: {csv_path}")
    
    # Write compact CSV (without retrieved contexts)
    csv_compact_path = output_dir / f"{config.output_name}_compact.csv"
    csv_compact_df = csv_df.drop(columns=["Ermittelte Fundstellen"])
    csv_compact_df.to_csv(csv_compact_path, sep=";", index=False, encoding="utf-8-sig", decimal=".")
    print(f"Saved compact CSV: {csv_compact_path}")
    
    # Generate and write README
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    readme_content = _generate_readme(config, stats, len(records), timestamp)
    readme_path = output_dir / f"{config.output_name}.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"Saved README: {readme_path}")
    
    # Print summary
    print()
    print("=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Context Precision:  {stats['context_precision']['avg']*100:.1f}% (±{stats['context_precision']['std']*100:.1f}%)")
    print(f"Context Recall:     {stats['context_recall']['avg']*100:.1f}% (±{stats['context_recall']['std']*100:.1f}%)")
    print(f"Faithfulness:       {stats['faithfulness']['avg']*100:.1f}% (±{stats['faithfulness']['std']*100:.1f}%)")
    print(f"Answer Correctness: {stats['answer_correctness']['avg']*100:.1f}% (±{stats['answer_correctness']['std']*100:.1f}%)")
    if followup_stats["n_evaluated"] > 0:
        fa = followup_stats["answerability"]
        fr = followup_stats["relevance"]
        print(f"Followup Answerability: {fa['avg']:.2f}/2.0 (±{fa['std']:.2f}, n={followup_stats['n_evaluated']})")
        print(f"Followup Relevance:     {fr['avg']:.2f}/2.0 (±{fr['std']:.2f})")
    print("=" * 60)
    
    return csv_path


def _build_arg_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run the full RAG evaluation pipeline (retrieval + answer generation + "
            "RAGAS scoring) on the IT-Grundschutz QA dataset."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--llm", required=True,
                        help="LLM model identifier, e.g. 'openai/gpt-oss-120b'")
    parser.add_argument("--embedding-model", required=True,
                        help="Embedding model identifier, e.g. 'openai/BAAI/bge-m3'")
    parser.add_argument("--input-data-description", required=True,
                        help="Free-text description of input data / preprocessing")
    parser.add_argument("--chunk-size", type=int, required=True,
                        help="Chunk size (characters) used during ingestion")
    parser.add_argument("--chunk-overlap", type=int, required=True,
                        help="Chunk overlap (characters) used during ingestion")
    parser.add_argument("--top-k", type=int, required=True,
                        help="Number of chunks to retrieve per question")
    parser.add_argument("--output-name", required=True,
                        help="Base name for output files (CSV/README) — no extension")
    parser.add_argument("--temperature", type=float, required=True,
                        help="LLM temperature for answer generation")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument(
        "--eval-csv-path",
        default="data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen2.csv",
        help="Path to evaluation CSV (relative to project root or absolute)",
    )
    parser.add_argument(
        "--judge-model",
        default=JUDGE_MODEL_DEFAULT,
        help=f"Model for LLM-as-judge follow-up evaluation (default: {JUDGE_MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N questions (for testing)",
    )
    parser.add_argument(
        "--skip-followup-eval",
        action="store_true",
        help="Skip follow-up question evaluation (faster, no judge LLM calls)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip questions already present in the existing _answers.csv (resume after abort)",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    generate_evaluation_results(
        llm=args.llm,
        embedding_model=args.embedding_model,
        input_data_description=args.input_data_description,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        top_k=args.top_k,
        output_name=args.output_name,
        temperature=args.temperature,
        seed=args.seed,
        eval_csv_path=args.eval_csv_path,
        judge_model=args.judge_model,
        evaluate_followups=not args.skip_followup_eval,
        limit=args.limit,
        resume=args.resume,
    )
