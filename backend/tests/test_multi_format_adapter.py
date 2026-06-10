from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.multi_format_adapter import generate_multi_format_index


def test_generate_txt_index(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    assert result["format"] == ".txt"
    assert result["page_count"] >= 1
    first = result["structure"][0]
    assert first["source_anchor"]["format"] == "txt"
    assert first["source_anchor"]["unit_type"] == "line"
    assert "text" in first


def test_generate_csv_index(tmp_path: Path) -> None:
    file_path = tmp_path / "table.csv"
    file_path.write_text("city,amount\nbeijing,10\nshanghai,20\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    assert result["format"] == ".csv"
    assert result["page_count"] >= 1
    first = result["structure"][0]
    assert first["source_anchor"]["format"] == "csv"
    assert first["source_anchor"]["unit_type"] == "row_range"
    assert first["source_anchor"]["start_row"] == 1


def _flatten_titles(nodes: list[dict]) -> list[str]:
    titles = []
    for node in nodes:
        titles.append(node.get("title", ""))
        titles.extend(_flatten_titles(node.get("nodes", [])))
    return titles


def test_markdown_atx_headings_include_line_anchor_unit_type(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Intro\n\nalpha\n\n## Detail\n\nbeta\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    titles = _flatten_titles(result["structure"])
    assert "Intro" in titles
    first = result["structure"][0]
    assert first["source_anchor"]["format"] == "markdown"
    assert first["source_anchor"]["unit_type"] == "line"
    assert first["source_anchor"]["start_line"] == 1


def test_markdown_setext_headings_include_line_anchor_unit_type(tmp_path: Path) -> None:
    file_path = tmp_path / "setext.md"
    file_path.write_text("Overview\n========\n\nalpha\n\nDetails\n-------\n\nbeta\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    titles = _flatten_titles(result["structure"])
    assert "Overview" in titles
    assert "Details" in titles
    assert result["structure"][0]["source_anchor"]["unit_type"] == "line"


def test_markdown_code_fence_heading_is_not_toc(tmp_path: Path) -> None:
    file_path = tmp_path / "code.md"
    file_path.write_text("# Real\n\n```python\n# not a heading\n```\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    titles = _flatten_titles(result["structure"])
    assert "Real" in titles
    assert "not a heading" not in titles
    assert result["structure"][0]["source_anchor"]["unit_type"] == "line"


def test_markdown_without_headings_uses_line_based_fallback(tmp_path: Path) -> None:
    file_path = tmp_path / "plain.md"
    file_path.write_text("alpha\n\nbeta\n\ngamma\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result is not None
    first = result["structure"][0]
    assert first["source_anchor"]["format"] == "markdown"
    assert first["source_anchor"]["unit_type"] == "line"
    assert first["source_anchor"]["start_line"] == 1
