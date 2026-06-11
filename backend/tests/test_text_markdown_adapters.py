from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.format_adapters.markdown_adapter import parse_markdown
from app.services.format_adapters.text_adapter import parse_text
from app.services.multi_format_adapter import generate_multi_format_index


def _flatten(nodes):
    for node in nodes:
        yield node
        yield from _flatten(node.nodes)


def test_text_adapter_emits_line_anchors_and_blocks(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\n\nbeta\ngamma\n", encoding="utf-8")

    content = parse_text(file_path)

    assert content.format == "txt"
    assert content.unit_type == "line"
    assert content.unit_count == 4
    assert content.nodes[0].source_anchor["unit_type"] == "line"
    assert content.nodes[0].source_anchor["start_line"] == 1
    assert content.blocks[0].source_anchor["start_line"] == 1


def test_text_adapter_handles_non_utf8_input(tmp_path: Path) -> None:
    file_path = tmp_path / "latin.txt"
    file_path.write_bytes("caf\xe9\nsecond".encode("latin-1"))

    content = parse_text(file_path)

    assert "cafe" in content.nodes[0].text or "café" in content.nodes[0].text
    assert content.metadata["encoding"]


def test_markdown_adapter_keeps_headings_setext_and_code_fences(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text(
        "# Intro\n\nalpha\n\nDetails\n-------\n\n```python\n# not heading\n```\n",
        encoding="utf-8",
    )

    content = parse_markdown(file_path)
    titles = [node.title for node in _flatten(content.nodes)]

    assert "Intro" in titles
    assert "Details" in titles
    assert "not heading" not in titles
    assert content.nodes[0].source_anchor == {
        "format": "markdown",
        "unit_type": "line",
        "start_line": 1,
        "end_line": 3,
    }


def test_markdown_without_headings_uses_line_fallback(tmp_path: Path) -> None:
    file_path = tmp_path / "plain.md"
    file_path.write_text("alpha\n\nbeta\n", encoding="utf-8")

    content = parse_markdown(file_path)

    assert content.nodes[0].title == "Markdown block 1"
    assert content.nodes[0].source_anchor["start_line"] == 1


def test_facade_delegates_text_and_markdown_to_canonical_adapters(tmp_path: Path) -> None:
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    md_path = tmp_path / "notes.md"
    md_path.write_text("# Intro\nbody\n", encoding="utf-8")

    text_result = generate_multi_format_index(text_path)
    md_result = generate_multi_format_index(md_path)

    assert text_result["unit_type"] == "line"
    assert text_result["metadata"]["adapter"] == "canonical_text"
    assert md_result["unit_type"] == "line"
    assert md_result["metadata"]["adapter"] == "canonical_markdown"
