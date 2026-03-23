"""Ephemeral in-session RAG for user-uploaded documents.

Uploaded files are chunked, embedded, and stored in cl.user_session for the
duration of the chat.  They are **not** persisted to Qdrant — the vectors live
only in memory and are discarded when the session ends.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ingest_docling import _chunk_text          # reuse existing chunker
from llm import embed                           # reuse existing embedding helper
from rag_tool import RagResult


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EphemeralDoc:
    """A single chunk from an uploaded document, with its embedding."""

    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# File-type text extraction
# ---------------------------------------------------------------------------

def _read_plain_text(path: Path) -> str:
    """Read a plain-text / markdown / csv file."""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf_fast(path: Path) -> tuple[str, bool]:
    """Extract text from a PDF using pypdfium2 (instant, no ML models).

    Also detects whether the PDF likely contains tables by checking for
    repeated tab/column patterns in the extracted text.

    Returns:
        (plain_text, has_tables)
    """
    import pypdfium2 as pdfium
    import logging

    log = logging.getLogger(__name__)

    pdf = pdfium.PdfDocument(str(path))
    pages_text: list[str] = []
    table_hints = 0

    for page in pdf:
        text = page.get_textpage().get_text_range()
        pages_text.append(text)
        # Heuristic: lines with 3+ tab characters suggest tabular data
        for line in text.split("\n"):
            if line.count("\t") >= 3 or line.count("  |  ") >= 2:
                table_hints += 1
    pdf.close()

    full_text = "\n\n".join(pages_text)
    has_tables = table_hints >= 3  # at least 3 table-like lines
    if has_tables:
        log.info("PDF table heuristic: %d table-like lines detected", table_hints)
    return full_text, has_tables


def _read_pdf_docling_heavy(path: Path) -> str:
    """Extract text from a PDF with full Docling pipeline (OCR + table structure)."""
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    pipeline_opts = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
    )
    converter = DocumentConverter(
        format_options={
            "pdf": PdfFormatOption(pipeline_options=pipeline_opts),
        }
    )
    result = converter.convert(str(path))
    return result.document.export_to_markdown()


def _extract_text_from_file(path: Path, mime: str | None = None) -> tuple[str, bool]:
    """Return the full text of a file based on its extension / MIME type.

    Returns:
        (text, needs_heavy) — needs_heavy is True when the document contains
        tables and should be re-processed with the full Docling pipeline.
    """
    suffix = path.suffix.lower()

    # PDFs get fast pypdfium2 extraction; Docling only if tables detected
    if suffix == ".pdf" or (mime and "pdf" in mime):
        return _read_pdf_fast(path)

    # Other Docling-supported formats (use Docling but no two-pass needed)
    docling_suffixes = {".docx", ".doc", ".pptx", ".xlsx", ".html", ".htm"}
    if suffix in docling_suffixes or (mime and ("word" in mime or "html" in mime)):
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(str(path))
        return result.document.export_to_markdown(), False

    if suffix in {".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
                  ".rst", ".ini", ".cfg", ".toml", ".env", ".sh", ".bat", ".ps1",
                  ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".css"}:
        return _read_plain_text(path), False

    # Fallback: try reading as plain text
    return _read_plain_text(path), False


# ---------------------------------------------------------------------------
# Processing pipeline
# ---------------------------------------------------------------------------

CHUNK_MAX_CHARS = 3000
CHUNK_OVERLAP = 300
EMBED_BATCH_SIZE = 64


async def process_upload(
    file_path: str,
    file_name: str,
    mime: str | None = None,
    on_warning: Any | None = None,
) -> list[EphemeralDoc]:
    """Process a single uploaded file into embedded chunks.

    Args:
        file_path: Local path to the uploaded file (Chainlit temp path).
        file_name: Original file name from the user.
        mime: MIME type reported by the browser, if available.
        on_warning: Optional async callable(msg: str) to notify the user
                    (e.g. when heavy processing is needed for tables).

    Returns:
        A list of :class:`EphemeralDoc` ready for in-session retrieval.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Upload file not found: {path}")

    # 1. Extract text (two-pass for PDFs: lightweight first, heavy if tables)
    raw_text, needs_heavy = _extract_text_from_file(path, mime)

    if needs_heavy:
        if on_warning:
            await on_warning(
                f"**{file_name}** enthält Tabellen — die Verarbeitung dauert "
                f"etwas länger, um Tabellenstrukturen korrekt zu erkennen."
            )
        raw_text = _read_pdf_docling_heavy(path)

    if not raw_text or not raw_text.strip():
        return []

    # 2. Chunk
    chunks = list(_chunk_text(raw_text, max_chars=CHUNK_MAX_CHARS, overlap=CHUNK_OVERLAP))
    if not chunks:
        return []

    # 3. Embed in batches
    all_embeddings: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        batch_embeddings = await embed(batch)
        all_embeddings.extend(batch_embeddings)

    # 4. Build EphemeralDoc list
    docs: list[EphemeralDoc] = []
    for idx, (chunk, emb) in enumerate(zip(chunks, all_embeddings)):
        docs.append(
            EphemeralDoc(
                text=chunk,
                embedding=emb,
                metadata={
                    "source": "upload",
                    "file": file_name,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                },
            )
        )
    return docs


# ---------------------------------------------------------------------------
# Ephemeral cosine-similarity search
# ---------------------------------------------------------------------------

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return dot / norm


def search_ephemeral(
    query_embedding: list[float],
    docs: list[EphemeralDoc],
    top_k: int = 5,
    score_threshold: float = 0.0,
) -> list[RagResult]:
    """Search ephemeral docs by cosine similarity and return RagResult objects.

    Args:
        query_embedding: The embedding vector of the user's query.
        docs: Session-scoped list of :class:`EphemeralDoc`.
        top_k: Maximum results to return.
        score_threshold: Minimum cosine similarity to include.

    Returns:
        Sorted list of :class:`RagResult` (highest similarity first).
    """
    if not docs:
        return []

    q_vec = np.asarray(query_embedding, dtype=np.float32)
    scored: list[tuple[float, EphemeralDoc]] = []
    for doc in docs:
        d_vec = np.asarray(doc.embedding, dtype=np.float32)
        sim = _cosine_similarity(q_vec, d_vec)
        if sim >= score_threshold:
            scored.append((sim, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    results: list[RagResult] = []
    for sim, doc in scored[:top_k]:
        results.append(
            RagResult(
                text=doc.text,
                score=sim,
                metadata={**doc.metadata},
            )
        )
    return results
