from __future__ import annotations

from pathlib import Path

from app.services.format_adapters.base import ContentBlock, DocumentContent, IndexNode

MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE = 12000


def _decode_text(file_path: Path) -> tuple[str, str]:
    data = file_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def _summary(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_len else clean[: max_len - 1] + "..."


def _line_blocks(lines: list[str], fmt: str) -> list[ContentBlock]:
    return [
        ContentBlock(
            id=f"line_{idx}",
            type="text",
            content=line,
            metadata={"line_number": idx},
            source_anchor={
                "format": fmt,
                "unit_type": "line",
                "start_line": idx,
                "end_line": idx,
            },
        )
        for idx, line in enumerate(lines, start=1)
    ]


def parse_text(file_path: Path) -> DocumentContent:
    text, encoding = _decode_text(file_path)
    lines = text.splitlines() or ([text] if text else [])
    blocks = _line_blocks(lines, "txt")

    chunks: list[tuple[int, int, str]] = []
    paragraph_start = 1
    paragraph_lines: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if line.strip():
            if not paragraph_lines:
                paragraph_start = idx
            paragraph_lines.append(line)
            continue
        if paragraph_lines:
            chunks.append((paragraph_start, idx - 1, "\n".join(paragraph_lines)))
            paragraph_lines = []
    if paragraph_lines:
        chunks.append((paragraph_start, paragraph_start + len(paragraph_lines) - 1, "\n".join(paragraph_lines)))
    if not chunks and lines:
        chunks.append((1, len(lines), "\n".join(lines)))

    nodes: list[IndexNode] = []
    for idx, (start, end, chunk_text) in enumerate(chunks, start=1):
        limited = chunk_text[:MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE]
        nodes.append(
            IndexNode(
                node_id=f"line_{start}_{end}",
                title=f"Text block {idx}",
                summary=_summary(limited),
                text=limited,
                start_index=start,
                end_index=end,
                source_anchor={
                    "format": "txt",
                    "unit_type": "line",
                    "start_line": start,
                    "end_line": end,
                },
            )
        )

    return DocumentContent(
        format="txt",
        title=file_path.name,
        doc_description=_summary(text) or f"Text file: {file_path.name}",
        unit_type="line",
        unit_count=len(lines),
        nodes=nodes,
        blocks=blocks,
        metadata={"adapter": "canonical_text", "encoding": encoding, "char_count": len(text)},
    )
