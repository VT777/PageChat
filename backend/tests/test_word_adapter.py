from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.format_adapters.word_adapter import parse_docx
from app.services.multi_format_adapter import generate_multi_format_index


def _write_zip(path: Path, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_docx_adapter_emits_paragraph_anchors_and_table_blocks(tmp_path: Path) -> None:
    file_path = tmp_path / "contract.docx"
    _write_zip(
        file_path,
        {
            "word/styles.xml": """
            <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
            </w:styles>
            """,
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Scope</w:t></w:r></w:p>
                <w:p><w:r><w:t>Clause text</w:t></w:r></w:p>
                <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Key</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
              </w:body>
            </w:document>
            """,
        },
    )

    content = parse_docx(file_path)

    assert content.format == "docx"
    assert content.nodes[0].title == "Scope"
    assert content.nodes[0].source_anchor["unit_type"] == "paragraph"
    assert any(block.type == "table" for block in content.blocks)


def test_docx_visual_heavy_document_sets_flag(tmp_path: Path) -> None:
    file_path = tmp_path / "visual.docx"
    _write_zip(
        file_path,
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:drawing/></w:r></w:p></w:body>
            </w:document>
            """,
            "word/media/image1.png": b"fake",
        },
    )

    content = parse_docx(file_path)

    assert content.metadata["needs_visual_enhancement"] is True
    assert "visual_reason" in content.metadata


def test_docx_no_heading_document_uses_paragraph_fallback(tmp_path: Path) -> None:
    file_path = tmp_path / "plain.docx"
    _write_zip(
        file_path,
        {
            "word/document.xml": """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        },
    )

    content = parse_docx(file_path)

    assert content.nodes[0].title == "Document start"
    assert content.nodes[0].source_anchor["start_paragraph"] == 1
    assert content.nodes[0].source_anchor["end_paragraph"] == 2


def test_docx_long_section_is_bounded(tmp_path: Path) -> None:
    file_path = tmp_path / "long.docx"
    long_text = "x" * 13000
    _write_zip(
        file_path,
        {
            "word/document.xml": f"""
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>{long_text}</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        },
    )

    content = parse_docx(file_path)

    assert len(content.nodes[0].text) <= 12000
    assert content.nodes[0].source_anchor["unit_type"] == "paragraph"


def test_corrupt_docx_returns_controlled_error(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.docx"
    file_path.write_text("not a zip", encoding="utf-8")

    content = parse_docx(file_path)

    assert content.nodes == []
    assert content.metadata["parse_status"] == "error"


def test_facade_delegates_docx_to_canonical_adapter(tmp_path: Path) -> None:
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

    result = generate_multi_format_index(file_path)

    assert result["metadata"]["adapter"] == "canonical_docx"
    assert result["unit_type"] == "paragraph"
