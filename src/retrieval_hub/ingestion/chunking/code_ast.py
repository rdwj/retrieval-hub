"""AST-aware code chunker using tree-sitter.

Implements the cAST algorithm: recursive AST splitting with sibling merging.
Each chunk carries a scope ancestry header so the embedding model knows where
the code lives within the file structure.

Designed for the ``code`` source family.  Produces the same ``Chunk``
dataclass as the token-fixed chunker so downstream stages (embed, store) are
unaware of the chunking strategy.
"""

from __future__ import annotations

import logging

import tiktoken
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())
DEFAULT_CHUNK_TOKENS = 512
DEFAULT_ENCODING_NAME = "cl100k_base"
_SCOPE_TYPES = frozenset({"function_definition", "class_definition"})
_RawChunk = tuple[str, int, str | None]  # (text, token_count, doc_section)


def _count_tokens(text: str, enc: tiktoken.Encoding) -> int:
    return len(enc.encode(text))


def _extract_name(node) -> str | None:
    """Return the identifier name for a scope-introducing node, or None."""
    if node.type not in _SCOPE_TYPES:
        return None
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode()
    return None


def _scope_header(file_path: str, ancestors: list[str]) -> str:
    header = f"# File: {file_path}"
    if ancestors:
        header += f"\n# Scope: {' > '.join(ancestors)}"
    return header + "\n\n"


def _make_chunk(
    code: str, file_path: str, ancestors: list[str], enc: tiktoken.Encoding,
) -> _RawChunk:
    """Build chunk text with scope header; return (text, token_count, section)."""
    full = _scope_header(file_path, ancestors) + code
    section = ".".join(ancestors) if ancestors else None
    return full, _count_tokens(full, enc), section


def _split_by_lines(
    text: str, ancestors: list[str], fp: str, enc: tiktoken.Encoding, budget: int,
) -> list[_RawChunk]:
    """Fall back to line-based splitting when a leaf node exceeds the budget."""
    code_budget = max(budget - _count_tokens(_scope_header(fp, ancestors), enc), 64)
    lines = text.split("\n")
    chunks: list[_RawChunk] = []
    buf: list[str] = []
    buf_tokens = 0
    for line in lines:
        lt = _count_tokens(line + "\n", enc)
        if buf and buf_tokens + lt > code_budget:
            chunks.append(_make_chunk("\n".join(buf), fp, ancestors, enc))
            buf, buf_tokens = [], 0
        buf.append(line)
        buf_tokens += lt
    if buf:
        chunks.append(_make_chunk("\n".join(buf), fp, ancestors, enc))
    return chunks


def _flush_buffer(
    src: bytes, nodes: list, ancestors: list[str],
    fp: str, enc: tiktoken.Encoding, budget: int,
) -> list[_RawChunk]:
    """Merge buffered sibling nodes into one chunk, preserving inter-node text."""
    if not nodes:
        return []
    text = src[nodes[0].start_byte : nodes[-1].end_byte].decode()
    header_t = _count_tokens(_scope_header(fp, ancestors), enc)
    if _count_tokens(text, enc) + header_t <= budget:
        return [_make_chunk(text, fp, ancestors, enc)]
    return _split_by_lines(text, ancestors, fp, enc, budget)


def _chunk_node(
    node, src: bytes, ancestors: list[str],
    fp: str, enc: tiktoken.Encoding, budget: int,
) -> list[_RawChunk]:
    """Recursively split an AST node into budget-sized chunks."""
    text = src[node.start_byte : node.end_byte].decode()
    header_t = _count_tokens(_scope_header(fp, ancestors), enc)

    if _count_tokens(text, enc) + header_t <= budget:
        return [_make_chunk(text, fp, ancestors, enc)]

    # For class/function definitions, skip signature children and recurse
    # directly into the body block.  The scope header names the construct.
    if node.type in _SCOPE_TYPES:
        block = next((c for c in node.children if c.type == "block"), None)
        if block:
            return _chunk_node(block, src, ancestors, fp, enc, budget)

    children = node.named_children
    if not children:
        return _split_by_lines(text, ancestors, fp, enc, budget)

    result: list[_RawChunk] = []
    buf_nodes: list = []
    buf_t = 0

    for child in children:
        ct = _count_tokens(src[child.start_byte : child.end_byte].decode(), enc)
        if ct + header_t > budget:
            if buf_nodes:
                result.extend(_flush_buffer(src, buf_nodes, ancestors, fp, enc, budget))
                buf_nodes, buf_t = [], 0
            name = _extract_name(child)
            new_anc = [*ancestors, name] if name else ancestors
            result.extend(_chunk_node(child, src, new_anc, fp, enc, budget))
        elif buf_t + ct + header_t > budget:
            result.extend(_flush_buffer(src, buf_nodes, ancestors, fp, enc, budget))
            buf_nodes, buf_t = [child], ct
        else:
            buf_nodes.append(child)
            buf_t += ct

    if buf_nodes:
        result.extend(_flush_buffer(src, buf_nodes, ancestors, fp, enc, budget))
    return result


def chunk_code_file(
    source: str,
    file_path: str,
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    encoding_name: str = DEFAULT_ENCODING_NAME,
) -> list[Chunk]:
    """Split a Python source file into AST-aware chunks.

    Uses tree-sitter to parse the source, then recursively splits large AST
    nodes while merging small siblings.  Each chunk is prefixed with a scope
    ancestry header showing the file path and enclosing class/function.
    """
    if not source.strip():
        logger.info("chunk.chunk_code_file path=%s empty_source", file_path)
        return []

    enc = tiktoken.get_encoding(encoding_name)
    parser = Parser(PY_LANGUAGE)
    src = source.encode()
    raw = _chunk_node(parser.parse(src).root_node, src, [], file_path, enc, chunk_tokens)

    chunks = [
        Chunk(
            text=text, token_count=tc, chunk_index=i,
            doc_url=file_path, doc_title=file_path, doc_section=section,
        )
        for i, (text, tc, section) in enumerate(raw)
    ]
    logger.info("chunk.chunk_code_file path=%s chunks=%d", file_path, len(chunks))
    return chunks


def chunk_code_files(
    files: list[tuple[str, str]],
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    encoding_name: str = DEFAULT_ENCODING_NAME,
) -> list[Chunk]:
    """Chunk multiple files into a flat list with sequential ``chunk_index``.

    Each entry in *files* is a ``(source, file_path)`` tuple.
    """
    all_chunks: list[Chunk] = []
    for source, path in files:
        for chunk in chunk_code_file(
            source, path, chunk_tokens=chunk_tokens, encoding_name=encoding_name,
        ):
            chunk.chunk_index = len(all_chunks)
            all_chunks.append(chunk)
    return all_chunks
