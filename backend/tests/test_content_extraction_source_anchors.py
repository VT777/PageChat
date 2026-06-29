from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.content_extraction_service import ContentExtractionService


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_text_preview_blocks_include_line_source_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("one\ntwo\n", encoding="utf-8")

    result = ContentExtractionService().extract_content(file_path)

    first = result["blocks"][0]
    assert first["content"] == "one"
    assert first["metadata"]["line_number"] == 1
    assert first["source_anchor"] == {
        "format": "txt",
        "unit_type": "line",
        "start_line": 1,
        "end_line": 1,
    }


def test_markdown_preview_blocks_include_line_source_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Title\nbody\n", encoding="utf-8")

    result = ContentExtractionService().extract_content(file_path)

    first = result["blocks"][0]
    assert first["type"] == "heading"
    assert first["source_anchor"]["format"] == "markdown"
    assert first["source_anchor"]["unit_type"] == "line"
    assert first["source_anchor"]["start_line"] == 1


def test_csv_preview_blocks_include_row_source_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.csv"
    file_path.write_text("city,amount\nbeijing,10\n", encoding="utf-8")

    result = ContentExtractionService().extract_content(file_path)

    row = result["blocks"][1]
    assert row["content"] == ["beijing", "10"]
    assert row["source_anchor"] == {
        "format": "csv",
        "unit_type": "row_range",
        "start_row": 2,
        "end_row": 2,
    }


def test_xlsx_preview_blocks_include_sheet_row_source_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.xlsx"
    _write_zip(
        file_path,
        {
            "xl/workbook.xml": """
            <workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Sales" sheetId="1"/></sheets>
            </workbook>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet>
              <sheetData>
                <row r="1"><c r="A1" t="inlineStr"><is><t>city</t></is></c></row>
                <row r="2"><c r="A2" t="inlineStr"><is><t>beijing</t></is></c><c r="B2"><v>10</v></c></row>
              </sheetData>
            </worksheet>
            """,
        },
    )

    result = ContentExtractionService().extract_content(file_path)

    sheet = result["blocks"][0]
    assert sheet["content"]["name"] == "Sales"
    assert sheet["content"]["rows"][0]["cells"][0]["value"] == "city"
    assert sheet["content"]["rows"][1]["cells"][0]["value"] == "beijing"
    assert sheet["source_anchor"] == {
        "format": "xlsx",
        "unit_type": "row_range",
        "sheet": "Sales",
        "start_row": 1,
        "end_row": 2,
    }


def test_docx_preview_blocks_include_paragraph_source_anchor(tmp_path: Path) -> None:
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

    result = ContentExtractionService().extract_content(file_path)

    block = result["blocks"][0]
    assert block["content"] == "Clause"
    assert block["source_anchor"] == {
        "format": "docx",
        "unit_type": "paragraph",
        "start_paragraph": 1,
        "end_paragraph": 1,
    }


def test_pptx_preview_blocks_include_slide_source_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "deck.pptx"
    _write_zip(
        file_path,
        {"ppt/slides/slide1.xml": "<p:sld xmlns:p='p'><a:t xmlns:a='a'>Intro</a:t></p:sld>"},
    )

    result = ContentExtractionService().extract_content(file_path)

    block = result["blocks"][0]
    assert block["content"]["text"] == "Intro"
    assert block["source_anchor"] == {
        "format": "pptx",
        "unit_type": "slide",
        "start_slide": 1,
        "end_slide": 1,
    }
