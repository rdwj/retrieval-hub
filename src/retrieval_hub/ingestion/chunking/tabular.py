"""Tabular data chunker.

Renders each row of a JSONL file as a natural-language paragraph,
producing one chunk per row. Rows that exceed the token budget are
split with the token-fixed splitter.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import tiktoken

from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)


def _render_row(row: dict, row_index: int) -> tuple[str, str]:
    """Render a tabular row as natural language text.

    Returns (rendered_text, doc_section_id).
    """
    row_id = row.get("nct_id") or row.get("id") or str(row_index)
    doc_section = f"row/{row_id}"

    parts = []
    for key, value in row.items():
        if value is None or value == "" or value == []:
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        parts.append(f"{label}: {value}")

    text = "\n".join(parts)
    return text, doc_section


def chunk_tabular_data(
    data_dir: Path,
    *,
    chunk_tokens: int = 512,
    overlap_tokens: int = 0,
    doc_title: str = "tabular",
    doc_url: str = "",
) -> list[Chunk]:
    """Chunk JSONL files in data_dir, one chunk per row.

    Each row is rendered to natural language. Rows exceeding the token
    budget are split using the token-fixed splitter.
    """
    encoding = tiktoken.get_encoding("cl100k_base")
    chunks: list[Chunk] = []

    jsonl_files = sorted(data_dir.glob("*.jsonl"))
    if not jsonl_files:
        raise ValueError(f"No .jsonl files found in {data_dir}")

    row_index = 0
    for jsonl_path in jsonl_files:
        file_title = jsonl_path.stem
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                text, doc_section = _render_row(row, row_index)
                tokens = encoding.encode(text)

                if len(tokens) <= chunk_tokens:
                    chunks.append(Chunk(
                        text=text,
                        token_count=len(tokens),
                        chunk_index=len(chunks),
                        doc_url=doc_url or f"file://{jsonl_path.resolve()}",
                        doc_title=file_title,
                        doc_section=doc_section,
                    ))
                else:
                    offset = 0
                    part = 1
                    while offset < len(tokens):
                        window = tokens[offset:offset + chunk_tokens]
                        chunk_text = encoding.decode(window).strip()
                        chunks.append(Chunk(
                            text=chunk_text,
                            token_count=len(window),
                            chunk_index=len(chunks),
                            doc_url=doc_url or f"file://{jsonl_path.resolve()}",
                            doc_title=file_title,
                            doc_section=f"{doc_section}/{part}",
                        ))
                        offset += chunk_tokens
                        part += 1

                row_index += 1

    logger.info(
        "tabular.chunk_tabular_data dir=%s rows=%d chunks=%d",
        data_dir, row_index, len(chunks),
    )
    return chunks
