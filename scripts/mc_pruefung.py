"""Multiple-Choice-Pruefung (IT-GS-Praktiker) gegen alle 5 Vergleichsmodelle.

- CHAT_MODEL_1-4: RAG (Retrieval gegen die bestehende Qdrant-Wissensbasis
  grundschutz_bge_m3 + generierte Antwort mit Kontext), ueber IONOS.
- GPT-4o: OHNE RAG, reines Parameterwissen, direkt ueber OpenAI (aus
  Embedding-Kompatibilitaetsgruenden nicht gegen dieselbe Collection nutzbar,
  siehe Chat-Verlauf).

Fragenkatalog wird OHNE 'correct'/'correct_options'/'raw' an die Modelle
geschickt - diese Felder dienen ausschliesslich der lokalen Auswertung.

Ergebnis: CSV im Long-Format, eine Zeile je Frage x Modell. Nach jeder
einzelnen Antwort sofort geschrieben (crash-safe); bereits vorhandene
(Nr, Modell)-Kombinationen in der Ziel-CSV werden beim Neustart uebersprungen.

Verwendung:
    cd apps/chainlit && eval "$(python3 ionosCon.py --export)"   # Variablen setzen
    cd .. && python3 scripts/mc_pruefung.py
"""
import csv
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = REPO_ROOT / "data/data_evaluation/08_IT-GS-Praktiker-Pruefungsfragen.json"
OUT_CSV = REPO_ROOT / "data/results/mc_pruefung_ergebnisse.csv"
CSV_FIELDS = ["Nr", "Frage", "Antwort-Optionen", "Richtige Antworten", "Modell", "Gegebene Antwort", "Richtig/Falsch"]

sys.path.insert(0, str(REPO_ROOT / "notebooks"))
from litellm_client import (  # noqa: E402
    LLMConfig,
    VectorDBConfig,
    chat_completion,
    get_embeddings,
    get_qdrant_client,
)

TOP_K = 7
SCORE_THRESHOLD = 0.4


def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"Fehler: Umgebungsvariable {name} ist nicht gesetzt.", file=sys.stderr)
        print('Vorher ausfuehren: eval "$(python3 apps/chainlit/ionosCon.py --export)"', file=sys.stderr)
        sys.exit(1)
    return val


def build_rag_configs() -> dict[str, LLMConfig]:
    base_url = require_env("LITELLM_BASE_URL")
    api_key = require_env("LITELLM_API_KEY")
    embedding_model = require_env("EMBEDDING_MODEL")
    configs = {}
    for i in range(1, 5):
        model = require_env(f"CHAT_MODEL_{i}")
        configs[f"Modell_{i}_RAG"] = LLMConfig(api_base=base_url, api_key=api_key, model=model, embedding_model=embedding_model)
    return configs


def build_openai_config() -> LLMConfig | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("Hinweis: OPENAI_API_KEY nicht gesetzt - GPT-4o wird uebersprungen.", file=sys.stderr)
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("CHAT_MODEL_5", "gpt-4o")
    return LLMConfig(api_base=base_url, api_key=key, model=model, embedding_model="")


def load_questions() -> list[dict]:
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


def format_options(options: list[dict]) -> str:
    return "\n".join(f"{o['letter']}) {o['text']}" for o in options)


def build_mc_prompt(question: dict, context_block: str | None) -> str:
    options_text = format_options(question["options"])
    multi_hint = "(Mehrere Antworten koennen korrekt sein.)" if len(question.get("correct", [])) > 1 else "(Genau eine Antwort ist korrekt.)"
    parts = []
    if context_block:
        parts.append(f"Kontext:\n{context_block}\n")
    parts.append(
        f"Frage: {question['question']}\n{options_text}\n{multi_hint}\n"
        "Antworte AUSSCHLIESSLICH mit den Buchstaben der zutreffenden Optionen, "
        "kommagetrennt (z. B. 'A' oder 'A, C'). Kein weiterer Text."
    )
    return "\n".join(parts)


def retrieve_context(query: str, cfg: LLMConfig) -> str:
    vec = get_embeddings([query], cfg)[0]
    qdb_cfg = VectorDBConfig(
        provider="qdrant",
        url=require_env("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        collection=os.getenv("QDRANT_COLLECTION", "grundschutz_bge_m3"),
    )
    client = get_qdrant_client(qdb_cfg)
    response = client.query_points(
        collection_name=qdb_cfg.collection,
        query=vec,
        limit=TOP_K,
        score_threshold=SCORE_THRESHOLD,
        with_payload=True,
    )
    chunks = []
    for i, point in enumerate(response.points or [], start=1):
        payload = point.payload or {}
        text = ""
        for key in ("text", "content", "chunk", "body"):
            v = payload.get(key)
            if isinstance(v, str) and v.strip():
                text = v
                break
        if text:
            chunks.append(f"[Quelle {i}] {text}")
    return "\n\n".join(chunks)


def extract_answer_text(response) -> str:
    if isinstance(response, dict):
        return response["choices"][0]["message"]["content"] or ""
    return response.choices[0].message.content or ""


def parse_letters(answer_text: str, valid_letters: set[str]) -> list[str]:
    found = set(re.findall(r"\b([A-Z])\b", answer_text.upper()))
    return sorted(found & valid_letters)


def main():
    out_csv = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_CSV
    if not out_csv.is_absolute():
        out_csv = REPO_ROOT / out_csv

    questions = load_questions()
    rag_configs = build_rag_configs()
    openai_cfg = build_openai_config()

    all_configs = dict(rag_configs)
    if openai_cfg:
        all_configs["GPT-4o"] = openai_cfg

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    already_done: set[tuple[str, str]] = set()
    if out_csv.exists():
        with open(out_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                already_done.add((row["Nr"], row["Modell"]))
        print(f"Fortsetzen: {len(already_done)} Frage/Modell-Kombinationen bereits vorhanden, werden uebersprungen.")

    write_header = not out_csv.exists()
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
        if write_header:
            writer.writeheader()

        total = len(questions) * len(all_configs)
        done = 0
        for q in questions:
            nr = str(q["id"])
            options_text = format_options(q["options"])
            correct_text = ", ".join(q["correct"])
            valid_letters = {o["letter"] for o in q["options"]}

            for model_label, cfg in all_configs.items():
                done += 1
                if (nr, model_label) in already_done:
                    continue
                print(f"[{done}/{total}] Frage {nr} -> {model_label}", flush=True)

                try:
                    context_block = None
                    if model_label != "GPT-4o":
                        context_block = retrieve_context(q["question"], cfg)
                    prompt = build_mc_prompt(q, context_block)
                    response = chat_completion(
                        [{"role": "user", "content": prompt}],
                        cfg,
                        temperature=0.0,
                    )
                    answer_text = extract_answer_text(response)
                    given_letters = parse_letters(answer_text, valid_letters)
                except Exception as e:  # noqa: BLE001
                    print(f"  FEHLER bei Frage {nr}/{model_label}: {e}", file=sys.stderr)
                    given_letters = []
                    answer_text = f"FEHLER: {e}"

                is_correct = given_letters == sorted(q["correct"])
                writer.writerow({
                    "Nr": nr,
                    "Frage": q["question"],
                    "Antwort-Optionen": options_text,
                    "Richtige Antworten": correct_text,
                    "Modell": model_label,
                    "Gegebene Antwort": ", ".join(given_letters) if given_letters else answer_text[:200],
                    "Richtig/Falsch": "richtig" if is_correct else "falsch",
                })
                f.flush()

    print(f"\nFertig. Ergebnisse in: {out_csv}")


if __name__ == "__main__":
    main()
