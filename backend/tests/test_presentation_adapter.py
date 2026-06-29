from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.format_adapters.presentation_adapter import parse_pptx
from app.services.multi_format_adapter import generate_multi_format_index


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_pptx_adapter_emits_slide_anchors_and_table_text(tmp_path: Path) -> None:
    file_path = tmp_path / "deck.pptx"
    _write_zip(
        file_path,
        {
            "ppt/slides/slide1.xml": """
            <p:sld xmlns:p='p' xmlns:a='a'>
              <a:t>Intro</a:t><a:t>Revenue</a:t><a:t>100</a:t>
            </p:sld>
            """,
            "ppt/notesSlides/notesSlide1.xml": "<p:notes xmlns:p='p' xmlns:a='a'><a:t>Speaker note</a:t></p:notes>",
        },
    )

    content = parse_pptx(file_path)

    assert content.format == "pptx"
    assert content.nodes[0].source_anchor == {
        "format": "pptx",
        "unit_type": "slide",
        "start_slide": 1,
        "end_slide": 1,
    }
    assert "Speaker note" in content.nodes[0].text


def test_pptx_visual_heavy_slide_sets_flag(tmp_path: Path) -> None:
    file_path = tmp_path / "visual.pptx"
    _write_zip(
        file_path,
        {
            "ppt/slides/slide1.xml": "<p:sld xmlns:p='p'><p:pic/><p:pic/></p:sld>",
        },
    )

    content = parse_pptx(file_path)

    assert content.metadata["needs_visual_enhancement"] is True
    assert content.blocks[0].metadata["needs_visual_enhancement"] is True


def test_pptx_empty_slide_keeps_slide_anchor(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.pptx"
    _write_zip(
        file_path,
        {"ppt/slides/slide1.xml": "<p:sld xmlns:p='p'></p:sld>"},
    )

    content = parse_pptx(file_path)

    assert content.nodes[0].title == "Slide 1"
    assert content.nodes[0].source_anchor["start_slide"] == 1


def test_pptx_slide_limit_is_enforced(tmp_path: Path) -> None:
    file_path = tmp_path / "many.pptx"
    files = {
        f"ppt/slides/slide{i}.xml": f"<p:sld xmlns:p='p'><a:t xmlns:a='a'>Slide {i}</a:t></p:sld>"
        for i in range(1, 203)
    }
    _write_zip(file_path, files)

    content = parse_pptx(file_path)

    assert content.unit_count == 200
    assert content.nodes[-1].source_anchor["start_slide"] == 200


def test_corrupt_pptx_returns_controlled_error(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.pptx"
    file_path.write_text("not a zip", encoding="utf-8")

    content = parse_pptx(file_path)

    assert content.nodes == []
    assert content.metadata["parse_status"] == "error"


def test_facade_delegates_pptx_to_canonical_adapter(tmp_path: Path) -> None:
    file_path = tmp_path / "deck.pptx"
    _write_zip(
        file_path,
        {"ppt/slides/slide1.xml": "<p:sld xmlns:p='p'><a:t xmlns:a='a'>Intro</a:t></p:sld>"},
    )

    result = generate_multi_format_index(file_path)

    assert result["metadata"]["adapter"] == "canonical_pptx"
    assert result["unit_type"] == "slide"
