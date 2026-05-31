"""
Run RAGAS evaluation on existing answer files using gpt-oss-120b.

This script evaluates pre-generated answers using RAGAS metrics,
using gpt-oss-120b as the evaluation model regardless of which model
generated the answers.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

FOLLOWUP_SPLIT_RE = re.compile(r"\n\s*\**\s*Anschlussfragen:\s*\**\s*\n", re.IGNORECASE)


def _strip_followups(text: str) -> str:
    """Return the main part of an answer, cutting at the 'Anschlussfragen:' header."""
    if not isinstance(text, str) or not text:
        return text or ""
    parts = FOLLOWUP_SPLIT_RE.split(text, maxsplit=1)
    return parts[0].rstrip() if len(parts) == 2 else text.strip()

# Ensure notebooks/ is importable for litellm_client
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"

# Load .env from notebooks/ directory
try:
    from dotenv import load_dotenv
    env_path = NOTEBOOKS_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

if str(NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS_DIR))

from litellm_client import LLMConfig

# RAGAS evaluation model - always use gpt-oss-120b for reliable JSON output
RAGAS_MODEL = "openai/gpt-oss-120b"
EMBEDDING_MODEL = "openai/octen-embedding-8b"


async def _score_row_async(
    row: dict,
    scorers: dict,
    semaphore: asyncio.Semaphore,
    question_idx: int,
    total_questions: int,
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
                response=row["answer"],
                retrieved_contexts=row["contexts"],
            )
            answer_correctness = await scorers["answer_correctness"].ascore(
                user_input=row["question"],
                response=row["answer"],
                reference=row["ground_truth_answer"],
            )
            
            if (question_idx + 1) % 10 == 0:
                print(f"    RAGAS: {question_idx + 1}/{total_questions} questions evaluated...")
            
            # Extract numeric .value from MetricResult objects
            return {
                "context_precision": context_precision.value if hasattr(context_precision, 'value') else float(context_precision),
                "context_recall": context_recall.value if hasattr(context_recall, 'value') else float(context_recall),
                "faithfulness": faithfulness.value if hasattr(faithfulness, 'value') else float(faithfulness),
                "answer_correctness": answer_correctness.value if hasattr(answer_correctness, 'value') else float(answer_correctness),
            }
        except Exception as e:
            print(f"    ⚠ RAGAS failed for question {question_idx + 1}: {str(e)[:200]}")
            # Return NaN values instead of failing completely
            return {
                "context_precision": float('nan'),
                "context_recall": float('nan'),
                "faithfulness": float('nan'),
                "answer_correctness": float('nan'),
            }


def _create_ragas_scorers(llm_cfg: LLMConfig, temperature: float = 0.0):
    """Initialize RAGAS LLM, embeddings and the scorers dict — separate from the
    scoring loop so we can call scorers in chunks and persist after each chunk."""
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

    litellm.api_base = llm_cfg.api_base
    litellm.api_key = llm_cfg.api_key

    client = instructor.from_litellm(litellm.acompletion, mode=instructor.Mode.MD_JSON)
    llm = llm_factory(
        RAGAS_MODEL,
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

    return {
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "faithfulness": Faithfulness(llm=llm),
        "answer_correctness": AnswerCorrectness(llm=llm, embeddings=embeddings),
    }


async def _run_ragas_chunked(
    records: List[dict],
    df: "pd.DataFrame",
    output_path: Path,
    llm_cfg: LLMConfig,
    start_row: int,
    chunk_size: int,
    concurrency: int = 2,
    temperature: float = 0.0,
) -> List[dict]:
    """Score records in chunks and append each chunk to output_path immediately.

    Returns the list of score dicts that were computed in this run (start_row .. end).
    """
    scorers = _create_ragas_scorers(llm_cfg, temperature)
    semaphore = asyncio.Semaphore(concurrency)
    total = len(records)
    score_columns = ["context_precision", "context_recall", "faithfulness", "answer_correctness"]
    new_scores: List[dict] = []

    for chunk_start in range(start_row, total, chunk_size):
        chunk_end = min(chunk_start + chunk_size, total)
        chunk_records = records[chunk_start:chunk_end]
        tasks = [
            asyncio.create_task(
                _score_row_async(rec, scorers, semaphore, chunk_start + i, total)
            )
            for i, rec in enumerate(chunk_records)
        ]
        chunk_scores = await asyncio.gather(*tasks)
        new_scores.extend(chunk_scores)

        # Build chunk dataframe with original columns + score columns
        chunk_df = df.iloc[chunk_start:chunk_end].copy()
        for col in score_columns:
            chunk_df[col] = [s[col] for s in chunk_scores]

        write_header = (chunk_start == 0)
        chunk_df.to_csv(
            output_path,
            sep=";",
            mode="a",
            header=write_header,
            index=False,
            encoding="utf-8-sig",
        )
        successful = sum(1 for s in chunk_scores if not any(pd.isna(v) for v in s.values()))
        print(
            f"  Chunk saved: rows {chunk_start}-{chunk_end - 1} "
            f"({successful}/{len(chunk_scores)} ok) -> {output_path.name}"
        )

    return new_scores


def run_ragas_on_answers_file(
    answers_csv_path: str,
    start_row: int = 0,
    chunk_size: int = 10,
) -> Path:
    """
    Run RAGAS evaluation on an existing answers CSV file.

    Args:
        answers_csv_path: Path to the *_answers.csv file
        start_row: 0-based index of the first row to evaluate. Rows before this
            are assumed to already be present in the existing *_evaluated.csv
            from a previous (interrupted) run. New chunks are appended.
        chunk_size: Number of rows scored per write-cycle. After each chunk
            the current state is flushed to disk, so an abort loses at most
            this many rows.

    Returns:
        Path to the evaluated CSV file.
    """
    answers_path = Path(answers_csv_path)
    if not answers_path.exists():
        raise FileNotFoundError(f"Answers file not found: {answers_path}")

    output_name = answers_path.stem.replace("_answers", "")

    print(f"\n{'='*60}")
    print(f"RAGAS Evaluation: {output_name}")
    print(f"{'='*60}")
    print(f"  Answers file: {answers_path.name}")
    print(f"  RAGAS model: {RAGAS_MODEL}")
    print(f"  Chunk size: {chunk_size}  Start row: {start_row}")
    print()
    
    # Load answers
    df = pd.read_csv(answers_path, sep=";", encoding="utf-8-sig")
    print(f"  Loaded {len(df)} answers")
    
    # Prepare records for RAGAS — prefer pre-stripped (Hauptteil) columns if present,
    # otherwise strip on the fly so Anschlussfragen don't deflate faithfulness/correctness.
    has_main_gen = "Generierte Antwort (Hauptteil)" in df.columns
    has_main_truth = "Antwort (Hauptteil)" in df.columns
    print(f"  Hauptteil-Spalten: generated={has_main_gen}, ground_truth={has_main_truth}")

    records = []
    for _, row in df.iterrows():
        contexts = row["Ermittelte Fundstellen"].split("\n") if pd.notna(row["Ermittelte Fundstellen"]) else []
        gen_answer = row["Generierte Antwort (Hauptteil)"] if has_main_gen and pd.notna(row.get("Generierte Antwort (Hauptteil)")) else _strip_followups(row["Generierte Antwort"])
        truth_answer = row["Antwort (Hauptteil)"] if has_main_truth and pd.notna(row.get("Antwort (Hauptteil)")) else _strip_followups(row["Antwort"])
        records.append({
            "question": row["Frage"],
            "answer": gen_answer,
            "contexts": contexts,
            "ground_truth_answer": truth_answer,
            "ground_truth_context": row["Fundstellen"] if pd.notna(row["Fundstellen"]) else "",
        })
    
    # Configure LLM for RAGAS
    llm_cfg = LLMConfig(
        api_base=os.getenv("LITELLM_BASE_URL"),
        api_key=os.getenv("LITELLM_API_KEY"),
        model=RAGAS_MODEL,
        embedding_model=EMBEDDING_MODEL,
    )

    output_path = answers_path.parent / f"{output_name}_evaluated.csv"

    # Resume / fresh-start handling
    if start_row > 0:
        if not output_path.exists():
            print(f"  WARN: --start-row={start_row} but {output_path.name} does not exist. Starting from 0.")
            start_row = 0
        else:
            print(f"  Resuming: appending rows from index {start_row} to existing {output_path.name}")

    if start_row == 0 and output_path.exists():
        output_path.unlink()
        print(f"  Removed previous {output_path.name} for fresh run.")

    if start_row >= len(records):
        print(f"  start_row={start_row} >= total rows ({len(records)}). Nothing to do.")
        return output_path

    # Run RAGAS evaluation in chunks
    print(f"  Running RAGAS evaluation ({len(records) - start_row} rows in chunks of {chunk_size})...")
    try:
        asyncio.get_running_loop()
        import nest_asyncio
        nest_asyncio.apply()
        new_scores = asyncio.get_event_loop().run_until_complete(
            _run_ragas_chunked(records, df, output_path, llm_cfg, start_row, chunk_size)
        )
    except RuntimeError:
        new_scores = asyncio.run(
            _run_ragas_chunked(records, df, output_path, llm_cfg, start_row, chunk_size)
        )

    successful = sum(1 for s in new_scores if not any(pd.isna(v) for v in s.values()))
    print(f"  RAGAS evaluation complete: {successful}/{len(new_scores)} successful in this run")
    print(f"  Saved: {output_path.name}")

    # Summary statistics over the FULL evaluated file (including resumed rows)
    try:
        final_df = pd.read_csv(output_path, sep=";", encoding="utf-8-sig")
        score_cols = ["context_precision", "context_recall", "faithfulness", "answer_correctness"]
        if all(c in final_df.columns for c in score_cols):
            import statistics
            print()
            print(f"  RAGAS Metrics Summary ({len(final_df)} rows total):")
            for metric in score_cols:
                values = [v for v in final_df[metric].tolist() if not pd.isna(v)]
                if values:
                    avg = statistics.mean(values)
                    print(f"    {metric}: {avg*100:.1f}%  (n={len(values)})")
    except Exception as e:
        print(f"  (could not compute summary: {e})")

    return output_path


def run_all_ragas_evaluations():
    """Run RAGAS evaluation on all existing answer files."""
    results_dir = PROJECT_ROOT / "data" / "results"
    
    # Find all answer files
    answer_files = sorted(results_dir.glob("*_answers.csv"))
    
    print("=" * 70)
    print("RAGAS EVALUATION ON ALL ANSWER FILES")
    print(f"Using evaluation model: {RAGAS_MODEL}")
    print("=" * 70)
    print(f"\nFound {len(answer_files)} answer files to evaluate:\n")
    
    for f in answer_files:
        print(f"  - {f.name}")
    
    print()
    
    successful = []
    failed = []
    
    for answers_file in answer_files:
        try:
            output_path = run_ragas_on_answers_file(str(answers_file))
            successful.append(answers_file.stem.replace("_answers", ""))
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed.append(answers_file.stem.replace("_answers", ""))
    
    # Print final summary
    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"\nSuccessful: {len(successful)}/{len(answer_files)}")
    for name in successful:
        print(f"  ✓ {name}")
    
    if failed:
        print(f"\nFailed: {len(failed)}/{len(answer_files)}")
        for name in failed:
            print(f"  ✗ {name}")
    
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAGAS evaluation on existing *_answers.csv files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--answers-csv",
        default=None,
        help="Path to a specific *_answers.csv to evaluate. "
             "If omitted, all *_answers.csv files in data/results/ are processed.",
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=0,
        help="Resume from this 0-based row index. Requires an existing "
             "*_evaluated.csv to append to. Use 0 (default) for a fresh run.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=10,
        help="Rows scored per write-cycle. On abort, at most this many rows are lost.",
    )
    args = parser.parse_args()

    if args.answers_csv:
        path = Path(args.answers_csv)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Answers file not found: {path}")
        run_ragas_on_answers_file(str(path), start_row=args.start_row, chunk_size=args.chunk_size)
    else:
        if args.start_row != 0:
            print("WARN: --start-row only applies with --answers-csv. Ignored.")
        run_all_ragas_evaluations()


if __name__ == "__main__":
    main()
