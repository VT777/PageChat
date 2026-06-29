from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.content_extraction_service import ContentExtractionService
from app.services.multi_format_adapter import generate_multi_format_index


def _line_anchor_contains(parent: dict, child: dict) -> bool:
    return (
        parent["format"] == child["format"]
        and parent["unit_type"] == child["unit_type"]
        and parent["start_line"] <= child["start_line"] <= child["end_line"] <= parent["end_line"]
    )


def _row_anchor_contains(parent: dict, child: dict) -> bool:
    return (
        parent["format"] == child["format"]
        and parent["unit_type"] == child["unit_type"]
        and parent.get("sheet") in {None, child.get("sheet"), "sales"}
        and parent["start_row"] <= child["start_row"] <= child["end_row"] <= parent["end_row"]
    )


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_preview_and_index_use_same_text_line_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("alpha\nbeta\n", encoding="utf-8")

    index = generate_multi_format_index(file_path)
    preview = ContentExtractionService().extract_content(file_path)

    assert preview["metadata"]["adapter"] == "canonical_text"
    assert _line_anchor_contains(
        index["structure"][0]["source_anchor"],
        preview["blocks"][0]["source_anchor"],
    )


def test_preview_and_index_use_same_csv_row_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.csv"
    file_path.write_text("city,amount\nbeijing,10\n", encoding="utf-8")

    index = generate_multi_format_index(file_path)
    preview = ContentExtractionService().extract_content(file_path)

    assert preview["metadata"]["adapter"] == "canonical_table"
    assert _row_anchor_contains(
        index["structure"][0]["source_anchor"],
        preview["blocks"][0]["source_anchor"],
    )


def test_preview_and_index_use_same_docx_paragraph_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "contract.docx"
    _write_zip(
        file_path,
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Clause</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        },
    )

    index = generate_multi_format_index(file_path)
    preview = ContentExtractionService().extract_content(file_path)

    assert preview["metadata"]["adapter"] == "canonical_docx"
    assert preview["blocks"][0]["source_anchor"] == index["structure"][0]["source_anchor"]


def test_preview_and_index_use_same_pptx_slide_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "deck.pptx"
    _write_zip(
        file_path,
        {"ppt/slides/slide1.xml": "<p:sld xmlns:p='p'><a:t xmlns:a='a'>Intro</a:t></p:sld>"},
    )

    index = generate_multi_format_index(file_path)
    preview = ContentExtractionService().extract_content(file_path)

    assert preview["metadata"]["adapter"] == "canonical_pptx"
    assert preview["blocks"][0]["source_anchor"] == index["structure"][0]["source_anchor"]
