from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.source_anchor_resolver import resolve_source_anchor


def test_resolve_text_line_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="notes.txt",
        anchor={"format": "txt", "unit_type": "line", "start_line": 2, "end_line": 3},
    )

    assert result["status"] == "success"
    assert result["content"] == "two\nthree"
    assert result["display_label"] == "notes.txt lines 2-3"


def test_resolve_markdown_line_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Title\n\nalpha\nbeta\n", encoding="utf-8")

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="notes.md",
        anchor={
            "format": "markdown",
            "unit_type": "line",
            "start_line": 1,
            "end_line": 3,
        },
    )

    assert result["status"] == "success"
    assert result["content"] == "# Title\n\nalpha"
    assert result["display_label"] == "notes.md lines 1-3"


def test_resolve_csv_row_range_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.csv"
    file_path.write_text("city,amount\nbeijing,10\nshanghai,20\n", encoding="utf-8")

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="sales.csv",
        anchor={"format": "csv", "unit_type": "row_range", "start_row": 2, "end_row": 3},
    )

    assert result["status"] == "success"
    assert result["content"] == "beijing,10\nshanghai,20"
    assert result["display_label"] == "sales.csv rows 2-3"


def test_resolve_unknown_anchor_returns_error(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\n", encoding="utf-8")

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="notes.txt",
        anchor={"format": "txt", "unit_type": "cell", "cell": "A1"},
    )

    assert result["status"] == "error"
    assert "Unsupported source anchor" in result["reason"]
