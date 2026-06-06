"""Ephemeral in-session context from user-uploaded documents.

Text is extracted with pypdfium2 (no OCR, no ML models), chunked, embedded,
and stored in cl.user_session for the duration of the chat. Nothing is written
to Qdrant — vectors live only in memory and are discarded when the session ends.
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
# Text extraction
# ---------------------------------------------------------------------------

def _extract_pdf(path: Path) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    pages = [page.get_textpage().get_text_range() for page in pdf]
    pdf.close()
    return "\n\n".join(pages)


def _extract_text(path: Path, mime: str | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or (mime and "pdf" in mime):
        return _extract_pdf(path)
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > CHUNK_MAX_CHARS:
            if current:
                chunks.append(current)
            # Overlap: carry last CHUNK_OVERLAP chars into next chunk
            current = current[-CHUNK_OVERLAP:] + "\n\n" + para if current else para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        chunks.append(current)
    return chunks


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

    raw_text = _extract_text(path, mime)
    if not raw_text.strip():
        return []

    chunks = _chunk(raw_text)
    if not chunks:
        return []

    docs: list[EphemeralDoc] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        embeddings = await embed(batch)
        for idx, (chunk, emb) in enumerate(zip(batch, embeddings)):
            docs.append(
                EphemeralDoc(
                    text=chunk,
                    embedding=emb,
                    metadata={
                        "source": "upload",
                        "file": file_name,
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
