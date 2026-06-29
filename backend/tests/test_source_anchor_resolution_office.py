from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.source_anchor_resolver import resolve_source_anchor


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_resolve_docx_paragraph_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "contract.docx"
    _write_zip(
        file_path,
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>First</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second</w:t></w:r></w:p>
                <w:p><w:r><w:t>Third</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        },
    )

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="contract.docx",
        anchor={
            "format": "docx",
            "unit_type": "paragraph",
            "start_paragraph": 2,
            "end_paragraph": 3,
        },
    )

    assert result["status"] == "success"
    assert result["content"] == "Second\nThird"
    assert result["display_label"] == "contract.docx paragraphs 2-3"


def test_resolve_xlsx_sheet_row_range_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.xlsx"
    _write_zip(
        file_path,
        {
            "xl/workbook.xml": """
            <workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Sheet1" sheetId="1"/></sheets>
            </workbook>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet>
              <sheetData>
                <row r="1"><c r="A1" t="inlineStr"><is><t>city</t></is></c></row>
                <row r="2"><c r="A2" t="inlineStr"><is><t>beijing</t></is></c><c r="B2"><v>10</v></c></row>
                <row r="3"><c r="A3" t="inlineStr"><is><t>shanghai</t></is></c><c r="B3"><v>20</v></c></row>
              </sheetData>
            </worksheet>
            """,
        },
    )

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="sales.xlsx",
        anchor={
            "format": "xlsx",
            "unit_type": "row_range",
            "sheet": "Sheet1",
            "start_row": 2,
            "end_row": 3,
        },
    )

    assert result["status"] == "success"
    assert "row 2: A=beijing, B=10" in result["content"]
    assert "row 3: A=shanghai, B=20" in result["content"]
    assert result["display_label"] == "sales.xlsx Sheet1 rows 2-3"


def test_resolve_pptx_slide_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "deck.pptx"
    _write_zip(
        file_path,
        {
            "ppt/slides/slide1.xml": "<p:sld xmlns:p='p'><a:t xmlns:a='a'>Intro</a:t></p:sld>",
            "ppt/slides/slide2.xml": "<p:sld xmlns:p='p'><a:t xmlns:a='a'>Roadmap</a:t></p:sld>",
        },
    )

    result = resolve_source_anchor(
        file_path=file_path,
        document_name="deck.pptx",
        anchor={
            "format": "pptx",
            "unit_type": "slide",
            "start_slide": 2,
            "end_slide": 2,
        },
    )

    assert result["status"] == "success"
    assert result["content"] == "Roadmap"
    assert result["display_label"] == "deck.pptx slide 2"
