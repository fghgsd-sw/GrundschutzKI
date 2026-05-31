"""
Regenerate the 'Antwort'-column of the GSKI evaluation CSV so that the
reference answers follow the production system prompt (system.md).

The ground truth (Fundstellen) stays untouched. The script uses the
*labeled* Fundstellen as context (not the RAG retriever), so the new
gold standard is not coupled to retrieval quality.

Optionally adds Kap. 1.3 "Abgrenzung und Modellierung" of the relevant
Baustein as additional context for follow-up question generation.

Usage:
    python scripts/regenerate_ground_truth_answers.py \\
        --input-csv data/data_evaluation/GSKI_Fragen-Antworten-Fundstellen_123_Einfach.csv \\
        --model openai/meta-llama/Llama-3.3-70B-Instruct \\
        --temperature 0.2 \\
        --include-baustein-1-3 \\
        --limit 5
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"

try:
    from dotenv import load_dotenv
    env_path = NOTEBOOKS_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

if str(NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(NOTEBOOKS_DIR))

from litellm_client import LLMConfig, chat_completion


SYSTEM_MD_PATH = PROJECT_ROOT / "system.md"
GRUNDSCHUTZ_JSON_PATH = PROJECT_ROOT / "data" / "data_preprocessed" / "grundschutz.json"

BAUSTEIN_ID_RE = re.compile(r"\b([A-Z]{2,5}(?:\.\d+){1,3})\.A\d+", re.IGNORECASE)
BAUSTEIN_ONLY_RE = re.compile(r"\b([A-Z]{2,5}(?:\.\d+){1,3})\b")

FORBIDDEN_BRACKET_PATTERNS = [
    re.compile(r"\[[A-Z]{2,5}(?:\.\d+){1,3}(?:\.A\d+)?[^\]]*\]"),
    re.compile(r"【\s*Quelle"),
    re.compile(r"\[\s*Quelle"),
    re.compile(r"\(\s*Quelle"),
]


def load_baustein_index(path: Path) -> dict[str, dict[str, Any]]:
    """Return mapping baustein_id -> baustein dict, flattened across schichten."""
    data = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, dict[str, Any]] = {}
    for schicht in data.get("schichten", []):
        for baustein in schicht.get("bausteine", []):
            bid = baustein.get("id")
            if bid:
                index[bid] = baustein
    return index


def extract_baustein_ids(fundstellen: str) -> list[str]:
    """Extract all distinct parent Baustein IDs from a Fundstelle text, preserving order.

    Prefers IDs found via the Anforderungs-pattern (e.g. 'APP.3.2' from 'APP.3.2.A1 ...').
    Falls back to bare Baustein references if no Anforderung-style match is found.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for m in BAUSTEIN_ID_RE.finditer(fundstellen):
        bid = m.group(1)
        if bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    if ordered:
        return ordered
    for m in BAUSTEIN_ONLY_RE.finditer(fundstellen):
        bid = m.group(1)
        if bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    return ordered


def get_abgrenzungen(
    baustein_index: dict[str, dict[str, Any]],
    baustein_ids: list[str],
) -> list[tuple[str, str, str]]:
    """For each Baustein ID, return (id, titel, abgrenzung_text) if Kap. 1.3 exists."""
    out: list[tuple[str, str, str]] = []
    for bid in baustein_ids:
        baustein = baustein_index.get(bid)
        if not baustein:
            continue
        text = (baustein.get("beschreibung") or {}).get("abgrenzung_und_modellierung")
        if not text:
            continue
        titel = baustein.get("titel") or ""
        out.append((bid, titel, text))
    return out


def build_messages(
    system_prompt: str,
    question: str,
    fundstelle: str,
    abgrenzungen: list[tuple[str, str, str]],
) -> list[dict[str, str]]:
    context_blocks = [f"## Fundstelle (Ground Truth)\n{fundstelle}"]
    for bid, titel, text in abgrenzungen:
        header = f"## Kap. 1.3 Abgrenzung und Modellierung – {bid} {titel}".rstrip()
        context_blocks.append(f"{header}\n{text}")
    user_content = (
        f"Frage: {question}\n\n"
        f"Kontext (ausschließlich diesen verwenden):\n\n"
        + "\n\n".join(context_blocks)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def validate_format(answer: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    word_count = len(answer.split())
    if word_count > 250:
        issues.append(f"word_count={word_count} (>250)")

    if "Anschlussfragen:" not in answer:
        issues.append("missing_header 'Anschlussfragen:'")
    else:
        after_header = answer.split("Anschlussfragen:", 1)[1]
        numbered = re.findall(r"^\s*\d+\.\s+.+\?\s*$", after_header, re.MULTILINE)
        if len(numbered) != 3:
            issues.append(f"followup_count={len(numbered)} (expected 3)")

    for pat in FORBIDDEN_BRACKET_PATTERNS:
        if pat.search(answer):
            issues.append(f"forbidden_pattern: {pat.pattern}")
            break

    return (len(issues) == 0), issues


def generate_answer(
    messages: list[dict[str, str]],
    llm_cfg: LLMConfig,
    temperature: float,
    seed: int,
) -> str:
    response = chat_completion(messages, llm_cfg, temperature=temperature, seed=seed)
    if isinstance(response, dict):
        return response["choices"][0]["message"]["content"]
    if hasattr(response, "choices"):
        return response.choices[0].message.content
    raise TypeError(f"Unexpected response type: {type(response)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate reference answers in GSKI eval CSV aligned with system.md.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-csv", required=True,
                        help="Path to GSKI_Fragen-Antworten-Fundstellen*.csv")
    parser.add_argument("--output-csv", default=None,
                        help="Output CSV path (default: <input>_v2-production.csv)")
    parser.add_argument("--model", required=True,
                        help="LiteLLM model id, e.g. openai/meta-llama/Llama-3.3-70B-Instruct")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-baustein-1-3", action="store_true", default=True,
                        help="Append Kap. 1.3 of the parent Baustein as context")
    parser.add_argument("--no-baustein-1-3", dest="include_baustein_1_3",
                        action="store_false")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N rows (for testing)")
    parser.add_argument("--system-md", default=str(SYSTEM_MD_PATH),
                        help="Path to system.md")
    parser.add_argument("--grundschutz-json", default=str(GRUNDSCHUTZ_JSON_PATH),
                        help="Path to structured grundschutz.json")
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.is_absolute():
        input_path = (PROJECT_ROOT / input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    if args.output_csv:
        output_path = Path(args.output_csv)
        if not output_path.is_absolute():
            output_path = (PROJECT_ROOT / output_path).resolve()
    else:
        output_path = input_path.with_name(input_path.stem + "_v2-production.csv")

    system_prompt = Path(args.system_md).read_text(encoding="utf-8")
    baustein_index = load_baustein_index(Path(args.grundschutz_json))
    print(f"Loaded {len(baustein_index)} Bausteine from {args.grundschutz_json}")

    llm_cfg = LLMConfig(
        api_base=os.getenv("LITELLM_BASE_URL"),
        api_key=os.getenv("LITELLM_API_KEY"),
        model=args.model,
        embedding_model=os.getenv("EMBEDDING_MODEL", ""),
    )
    if not llm_cfg.api_base:
        raise ValueError("LITELLM_BASE_URL not set in environment")

    print(f"Reading: {input_path}")
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)
    print(f"  {len(rows)} rows total")

    fundstellen_col = "Fundstellen im IT-Grundschutz-Kompendium 2023"
    if fundstellen_col not in rows[0]:
        candidates = [c for c in rows[0] if "Fundstellen" in c]
        if not candidates:
            raise KeyError(f"Could not find 'Fundstellen' column. Got: {list(rows[0])}")
        fundstellen_col = candidates[0]
        print(f"  Using column: {fundstellen_col}")

    if args.limit:
        rows = rows[: args.limit]
        print(f"  Processing first {len(rows)} (--limit)")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_rows: list[dict[str, Any]] = []
    valid_count = 0

    for i, row in enumerate(rows, start=1):
        frage = row["Frage"]
        fundstelle = row[fundstellen_col]
        baustein_ids = extract_baustein_ids(fundstelle)
        abgrenzungen: list[tuple[str, str, str]] = []
        if args.include_baustein_1_3 and baustein_ids:
            abgrenzungen = get_abgrenzungen(baustein_index, baustein_ids)

        messages = build_messages(system_prompt, frage, fundstelle, abgrenzungen)

        print(
            f"[{i}/{len(rows)}] {frage[:80]}...  "
            f"(Bausteine={','.join(baustein_ids) or '-'}, Kap1.3={len(abgrenzungen)})"
        )
        try:
            answer = generate_answer(messages, llm_cfg, args.temperature, args.seed)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            answer = ""

        is_valid, issues = (False, ["generation_failed"]) if not answer else validate_format(answer)
        if is_valid:
            valid_count += 1
        else:
            print(f"  format issues: {issues}")

        out_rows.append({
            **row,
            "Antwort_v2_production": answer,
            "Baustein_IDs": ",".join(baustein_ids),
            "Kap_1_3_count": len(abgrenzungen),
            "format_valid": "true" if is_valid else "false",
            "format_issues": "; ".join(issues),
            "model_used": args.model,
            "temperature": args.temperature,
            "seed": args.seed,
            "timestamp": timestamp,
        })

    fieldnames = list(rows[0].keys()) + [
        "Antwort_v2_production",
        "Baustein_IDs",
        "Kap_1_3_count",
        "format_valid",
        "format_issues",
        "model_used",
        "temperature",
        "seed",
        "timestamp",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(out_rows)

    print()
    print("=" * 60)
    print(f"Wrote: {output_path}")
    print(f"  Rows: {len(out_rows)}")
    print(f"  Format-valid: {valid_count}/{len(out_rows)}")
    print(f"  Manual review needed: {len(out_rows) - valid_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
