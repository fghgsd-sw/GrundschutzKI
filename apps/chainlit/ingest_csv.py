#!/usr/bin/env python3
"""Ingest CSV files into Qdrant collection.

Usage:
    python ingest_csv.py data/my_table.csv
    python ingest_csv.py data/csv_folder/  # all CSVs in folder
    python ingest_csv.py file1.csv file2.csv --collection grundschutz
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from llm import embed
from settings import QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL


@dataclass
class Doc:
    id: str
    text: str
    payload: dict[str, Any]


def _point_id(doc_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, doc_id))


def _docs_from_csv(csv_path: Path, delimiter: str = ",") -> Iterable[Doc]:
    """Generate Doc objects from a CSV file."""
    with open(csv_path, encoding="utf-8", newline="") as f:
        # Sniff delimiter if not specified
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            actual_delimiter = dialect.delimiter
        except csv.Error:
            actual_delimiter = delimiter

        reader = csv.DictReader(f, delimiter=actual_delimiter)
        for row_idx, row in enumerate(reader):
            # Build structured text from row
            parts = [f"{col}: {val}" for col, val in row.items() if val and val.strip()]
            if not parts:
                continue
            text = " | ".join(parts)
            doc_id = f"{csv_path.stem}-row-{row_idx}"
            yield Doc(
                id=doc_id,
                text=text,
                payload={
                    "file": csv_path.name,
                    "row": row_idx,
                    "doc_type": "csv",
                    "source": csv_path.name,
                },
            )


def _collect_csv_files(paths: list[Path]) -> list[Path]:
    """Expand paths to list of CSV files."""
    csv_files: list[Path] = []
    for p in paths:
        if p.is_dir():
            csv_files.extend(sorted(p.glob("*.csv")))
        elif p.suffix.lower() == ".csv":
            csv_files.append(p)
    return csv_files


def _ensure_collection(client: QdrantClient, name: str, vector_size: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


async def _ingest(
    docs: list[Doc],
    collection: str,
    batch_size: int = 64,
    max_batch_chars: int = 20000,
) -> None:
    if not docs:
        print("No documents to ingest.")
        return

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

    # Get vector size from first embedding
    first_vec = await embed(docs[0].text)
    _ensure_collection(client, collection, len(first_vec))

    # Batch and upsert
    batch: list[Doc] = []
    batch_chars = 0
    total_upserted = 0

    for doc in docs:
        doc_chars = len(doc.text)
        if batch and (len(batch) >= batch_size or batch_chars + doc_chars > max_batch_chars):
            vectors = await embed([d.text for d in batch])
            points = [
                PointStruct(id=_point_id(d.id), vector=v, payload=d.payload)
                for d, v in zip(batch, vectors)
            ]
            client.upsert(collection_name=collection, points=points)
            total_upserted += len(points)
            print(f"  Upserted {total_upserted} documents...")
            batch = []
            batch_chars = 0

        batch.append(doc)
        batch_chars += doc_chars

    # Final batch
    if batch:
        vectors = await embed([d.text for d in batch])
        points = [
            PointStruct(id=_point_id(d.id), vector=v, payload=d.payload)
            for d, v in zip(batch, vectors)
        ]
        client.upsert(collection_name=collection, points=points)
        total_upserted += len(points)

    print(f"Done! Ingested {total_upserted} documents into '{collection}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CSV files into Qdrant.")
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="CSV file(s) or folder(s) containing CSVs.",
    )
    parser.add_argument(
        "--collection",
        default=QDRANT_COLLECTION,
        help=f"Target Qdrant collection (default: {QDRANT_COLLECTION}).",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="CSV delimiter (default: auto-detect, fallback to comma).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Max embedding batch size.",
    )
    parser.add_argument(
        "--max-batch-chars",
        type=int,
        default=20000,
        help="Max total characters per embedding request.",
    )
    args = parser.parse_args()

    csv_files = _collect_csv_files(args.paths)
    if not csv_files:
        print("No CSV files found.")
        return

    print(f"Found {len(csv_files)} CSV file(s):")
    for f in csv_files:
        print(f"  - {f}")

    docs: list[Doc] = []
    for csv_file in csv_files:
        file_docs = list(_docs_from_csv(csv_file, args.delimiter))
        print(f"  {csv_file.name}: {len(file_docs)} rows")
        docs.extend(file_docs)

    print(f"\nTotal: {len(docs)} documents to ingest")
    asyncio.run(_ingest(docs, args.collection, args.batch_size, args.max_batch_chars))


if __name__ == "__main__":
    main()
