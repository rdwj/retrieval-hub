"""Procedure-aware chunker for aircraft maintenance service bulletins."""

from __future__ import annotations

import logging
import re

import tiktoken

from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.normalize import NormalizedDocument

logger = logging.getLogger(__name__)

_INSTRUCTIONS_RE = re.compile(r"^(?:#+ *)?INSTRUCTIONS\s*:", re.MULTILINE | re.IGNORECASE)
_MATERIALS_RE = re.compile(r"^(?:#+ *)?MATERIAL REQUIRED\s*:", re.MULTILINE | re.IGNORECASE)
_EFFECTIVITY_RE = re.compile(r"^(?:#+ *)?EFFECTIVITY DATE\s*:", re.MULTILINE | re.IGNORECASE)
_STEP_RE = re.compile(r"^(\d+)\.", re.MULTILINE)
_PART_RE = re.compile(r"^(?:#+ *)?(?:Part|PART)\s+(IV|I{1,3})", re.MULTILINE)

_PART_TO_NUM = {"I": "i", "II": "ii", "III": "iii", "IV": "iv"}


def _split_at(text: str, pattern: re.Pattern[str]) -> tuple[str, str | None]:
    """Split text at the first match of pattern. Returns (before, after-including-match)."""
    m = pattern.search(text)
    if m is None:
        return text, None
    return text[: m.start()], text[m.start() :]


def _token_split(
    text: str,
    section_prefix: str,
    chunk_tokens: int,
    encoding: tiktoken.Encoding,
    doc: NormalizedDocument,
    start_index: int,
) -> list[Chunk]:
    """Split text into token-bounded chunks with numbered section suffixes."""
    tokens = encoding.encode(text)
    if len(tokens) <= chunk_tokens:
        return [
            Chunk(
                text=text.strip(),
                token_count=len(tokens),
                chunk_index=start_index,
                doc_url=doc.url,
                doc_title=doc.title,
                doc_section=section_prefix,
            )
        ]

    chunks: list[Chunk] = []
    offset = 0
    part = 1
    while offset < len(tokens):
        window = tokens[offset : offset + chunk_tokens]
        chunk_text = encoding.decode(window).strip()
        chunks.append(
            Chunk(
                text=chunk_text,
                token_count=len(window),
                chunk_index=start_index + len(chunks),
                doc_url=doc.url,
                doc_title=doc.title,
                doc_section=f"{section_prefix}/{part}",
            )
        )
        offset += chunk_tokens
        part += 1
    return chunks


def _parse_steps(instructions_text: str) -> list[tuple[str | None, int, str]]:
    """Parse instruction steps, returning (part_label, step_number, step_text) tuples."""
    current_part: str | None = None
    steps: list[tuple[str | None, int, str]] = []

    lines = instructions_text.split("\n")
    # First pass: find part boundaries
    part_lines: dict[int, str] = {}
    for i, line in enumerate(lines):
        pm = _PART_RE.match(line.strip())
        if pm:
            part_lines[i] = _PART_TO_NUM.get(pm.group(1), pm.group(1).lower())

    # Second pass: collect steps
    current_step_lines: list[str] = []
    current_step_num = 0
    preamble_lines: list[str] = []

    for i, line in enumerate(lines):
        if i in part_lines:
            # Flush any open step before switching parts
            if current_step_lines and current_step_num > 0:
                steps.append((current_part, current_step_num, "\n".join(current_step_lines)))
                current_step_lines = []
            current_part = part_lines[i]
            continue

        sm = _STEP_RE.match(line.strip())
        if sm:
            # Flush previous step
            if current_step_lines and current_step_num > 0:
                steps.append((current_part, current_step_num, "\n".join(current_step_lines)))
            current_step_num = int(sm.group(1))
            current_step_lines = [line]
        elif current_step_num > 0:
            current_step_lines.append(line)
        else:
            preamble_lines.append(line)

    # Flush last step
    if current_step_lines and current_step_num > 0:
        steps.append((current_part, current_step_num, "\n".join(current_step_lines)))

    # Prepend preamble as a pseudo-step if non-empty
    preamble = "\n".join(preamble_lines).strip()
    if preamble:
        steps.insert(0, (None, 0, preamble))

    return steps


def _step_section(part: str | None, step_num: int) -> str:
    """Build the doc_section string for an instruction step."""
    if step_num == 0:
        return "instructions/preamble"
    if part:
        return f"instructions/part-{part}/step-{step_num}"
    return f"instructions/step-{step_num}"


def chunk_procedure_document(
    doc: NormalizedDocument,
    *,
    chunk_tokens: int = 512,
    overlap_tokens: int = 0,
) -> list[Chunk]:
    """Chunk an aircraft SB document aligned to procedure step boundaries."""
    header_text, rest = _split_at(doc.text, _INSTRUCTIONS_RE)

    # Fall back to token-fixed chunking if no SB structure detected
    if rest is None:
        return chunk_document(doc, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)

    encoding = tiktoken.get_encoding("cl100k_base")
    chunks: list[Chunk] = []

    # --- Header ---
    header_text = header_text.strip()
    if header_text:
        chunks.extend(_token_split(header_text, "header", chunk_tokens, encoding, doc, 0))

    # --- Split instructions from materials/tail ---
    instructions_text, materials_rest = _split_at(rest, _MATERIALS_RE)

    # --- Instruction steps ---
    steps = _parse_steps(instructions_text)
    has_parts = any(part is not None for part, _, _ in steps)
    step_count = sum(1 for _, n, _ in steps if n > 0)

    for part, step_num, step_text in steps:
        step_text = step_text.strip()
        if not step_text:
            continue
        section = _step_section(part if has_parts else None, step_num)
        chunks.extend(
            _token_split(step_text, section, chunk_tokens, encoding, doc, len(chunks))
        )

    # --- Materials ---
    if materials_rest is not None:
        mat_text, tail_text = _split_at(materials_rest, _EFFECTIVITY_RE)
        mat_text = mat_text.strip()
        if mat_text:
            chunks.extend(
                _token_split(mat_text, "materials", chunk_tokens, encoding, doc, len(chunks))
            )
        # --- Tail ---
        if tail_text is not None:
            tail_text = tail_text.strip()
            if tail_text:
                chunks.extend(
                    _token_split(tail_text, "tail", chunk_tokens, encoding, doc, len(chunks))
                )

    # Re-index sequentially (defensive, since _token_split already does this)
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i

    logger.info(
        "procedure.chunk_procedure_document url=%s chunks=%d steps=%d parts=%d",
        doc.url,
        len(chunks),
        step_count,
        len(set(p for p, _, _ in steps if p is not None)),
    )
    return chunks
