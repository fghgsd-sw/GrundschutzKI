"""Ephemeral in-session context from user-uploaded documents.

Text is extracted with pypdfium2 (no OCR, no ML models), chunked page-aware,
embedded, and stored in cl.user_session for the duration of the chat. Nothing
is written to Qdrant — vectors live only in memory and are discarded when the
session ends. PDFs are also saved to UPLOAD_SERVE_DIR so they can be opened in
the sidebar viewer via /sources/upload/<session_id>/<filename>.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from llm import embed
from rag_tool import RagResult

CHUNK_MAX_CHARS = 2000
CHUNK_OVERLAP = 200
EMBED_BATCH_SIZE = 32


@dataclass
class EphemeralDoc:
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text extraction — returns list of (page_text, page_number) tuples
# ---------------------------------------------------------------------------

def _extract_pdf_pages(path: Path) -> list[tuple[str, int]]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    pages = []
    for page_idx, page in enumerate(pdf, start=1):
        text = page.get_textpage().get_text_range().strip()
        if text:
            pages.append((text, page_idx))
    pdf.close()
    return pages


def extract_text(file_path: str, mime: str | None = None) -> str:
    """Extract full text from a file as a single string."""
    pages = _extract_text_pages(Path(file_path), mime)
    return "\n\n".join(text for text, _ in pages)


def _extract_text_pages(path: Path, mime: str | None = None) -> list[tuple[str, int]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or (mime and "pdf" in mime):
        return _extract_pdf_pages(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(text, 1)]


# ---------------------------------------------------------------------------
# Chunking — respects page boundaries, tracks page in each chunk
# ---------------------------------------------------------------------------

def _chunk_pages(pages: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Chunk page-annotated text. Returns (chunk_text, page_number) tuples."""
    results: list[tuple[str, int]] = []
    for page_text, page_num in pages:
        paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > CHUNK_MAX_CHARS:
                if current:
                    results.append((current, page_num))
                current = current[-CHUNK_OVERLAP:] + "\n\n" + para if current else para
            else:
                current = current + "\n\n" + para if current else para
        if current:
            results.append((current, page_num))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def process_upload(
    file_path: str,
    file_name: str,
    mime: str | None = None,
) -> list[EphemeralDoc]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    pages = _extract_text_pages(path, mime)
    if not pages:
        return []

    chunks = _chunk_pages(pages)
    if not chunks:
        return []

    docs: list[EphemeralDoc] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch_chunks = chunks[start : start + EMBED_BATCH_SIZE]
        texts = [c for c, _ in batch_chunks]
        embeddings = await embed(texts)
        for idx, ((chunk_text, page_num), emb) in enumerate(zip(batch_chunks, embeddings)):
            docs.append(
                EphemeralDoc(
                    text=chunk_text,
                    embedding=emb,
                    metadata={
                        "source": "upload",
                        "file": file_name,
                        "page": page_num,
                        "chunk_index": start + idx,
                    },
                )
            )
    return docs


def search_ephemeral(
    query_embedding: list[float],
    docs: list[EphemeralDoc],
    top_k: int = 3,
) -> list[RagResult]:
    if not docs:
        return []
    q = np.asarray(query_embedding, dtype=np.float32)
    scored: list[tuple[float, EphemeralDoc]] = []
    for doc in docs:
        d = np.asarray(doc.embedding, dtype=np.float32)
        norm = float(np.linalg.norm(q) * np.linalg.norm(d))
        sim = float(np.dot(q, d)) / norm if norm else 0.0
        scored.append((sim, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        RagResult(text=doc.text, score=sim, metadata=dict(doc.metadata))
        for sim, doc in scored[:top_k]
    ]
