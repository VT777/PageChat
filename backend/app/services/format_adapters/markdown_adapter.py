from __future__ import annotations

import re
from pathlib import Path

from app.services.format_adapters.base import ContentBlock, DocumentContent, IndexNode

MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE = 12000


def _summary(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_len else clean[: max_len - 1] + "..."


def _block_for_line(idx: int, line: str) -> ContentBlock:
    stripped = line.strip()
    if stripped.startswith("#"):
        level = len(stripped) - len(stripped.lstrip("#"))
        return ContentBlock(
            id=f"line_{idx}",
            type="heading",
            content=stripped[level:].strip(),
            metadata={"line_number": idx, "level": level, "raw": line},
            source_anchor={"format": "markdown", "unit_type": "line", "start_line": idx, "end_line": idx},
        )
    return ContentBlock(
        id=f"line_{idx}",
        type="text",
        content=line,
        metadata={"line_number": idx},
        source_anchor={"format": "markdown", "unit_type": "line", "start_line": idx, "end_line": idx},
    )


def _nest(nodes: list[IndexNode]) -> list[IndexNode]:
    roots: list[IndexNode] = []
    stack: list[IndexNode] = []
    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].nodes.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def parse_markdown(file_path: Path) -> DocumentContent:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    blocks = [_block_for_line(idx, line) for idx, line in enumerate(lines, start=1)]

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    setext_pattern = re.compile(r"^\s*(=+|-+)\s*$")
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_code = False

    def close(end_line: int) -> None:
        nonlocal current
        if current is None:
            return
        lines_in_section = list(current.get("lines", []))
        trailing_blank_count = 0
        expected_last_line = int(current["start_line"]) + len(lines_in_section) - 1
        if end_line >= expected_last_line:
            for item in reversed(lines_in_section):
                if str(item).strip():
                    break
                trailing_blank_count += 1
        current["end_line"] = max(int(current["start_line"]), end_line - trailing_blank_count)
        sections.append(current)
        current = None

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        opening_or_closing_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if opening_or_closing_fence:
            if current is None:
                current = {"title": "Document start", "level": 1, "start_line": idx, "lines": []}
            current["lines"].append(line)
            in_code = not in_code
            continue
        if in_code:
            if current is None:
                current = {"title": "Document start", "level": 1, "start_line": idx, "lines": []}
            current["lines"].append(line)
            continue

        match = heading_pattern.match(line)
        if match:
            close(idx - 1)
            current = {
                "title": match.group(2).strip(),
                "level": len(match.group(1)),
                "start_line": idx,
                "lines": [line],
            }
            continue

        if idx > 1 and setext_pattern.match(line) and lines[idx - 2].strip():
            if current is not None:
                current_lines = list(current.get("lines", []))
                if current_lines and current_lines[-1] == lines[idx - 2]:
                    current_lines.pop()
                    current["lines"] = current_lines
            close(idx - 3)
            current = {
                "title": lines[idx - 2].strip(),
                "level": 1 if stripped.startswith("=") else 2,
                "start_line": idx - 1,
                "lines": [lines[idx - 2], line],
            }
            continue

        if current is None:
            current = {"title": "Document start", "level": 1, "start_line": idx, "lines": []}
        current["lines"].append(line)

    close(len(lines) if lines else 1)

    flat: list[IndexNode] = []
    for idx, section in enumerate(sections, start=1):
        section_lines = list(section["lines"])
        body = "\n".join(section_lines).strip()
        if not body:
            continue
        start = int(section["start_line"])
        end = int(section["end_line"])
        flat.append(
            IndexNode(
                node_id=f"line_{start}_{end}",
                title=str(section["title"]),
                summary=_summary(body),
                text=body[:MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE],
                start_index=start,
                end_index=end,
                source_anchor={"format": "markdown", "unit_type": "line", "start_line": start, "end_line": end},
                level=max(1, min(int(section["level"]), 6)),
            )
        )

    if not flat and lines:
        flat.append(
            IndexNode(
                node_id="line_1",
                title="Markdown block 1",
                summary=_summary(text),
                text=text[:MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE],
                start_index=1,
                end_index=len(lines),
                source_anchor={"format": "markdown", "unit_type": "line", "start_line": 1, "end_line": len(lines)},
            )
        )
    if len(flat) == 1 and flat[0].title == "Document start":
        flat[0].title = "Markdown block 1"

    return DocumentContent(
        format="markdown",
        title=file_path.name,
        doc_description=_summary(text) or f"Markdown document: {file_path.name}",
        unit_type="line",
        unit_count=len(lines),
        nodes=_nest(flat),
        blocks=blocks,
        metadata={"adapter": "canonical_markdown", "char_count": len(text)},
    )
