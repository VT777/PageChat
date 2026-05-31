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
    assert first["source_anchor"]["start_row"] == 1
