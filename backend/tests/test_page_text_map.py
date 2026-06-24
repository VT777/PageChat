import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_page_text_map_preserves_page_metadata_and_page_list() -> None:
    from pageindex.page_text_map import PageTextEntry, PageTextMap

    page_map = PageTextMap(
        [
            PageTextEntry(
                physical_page=1,
                text="PDF text",
                source="pdf_text",
                quality="reliable",
                ocr_used=False,
            ),
            PageTextEntry(
                physical_page=2,
                text="OCR text",
                source="ocr",
                quality="reliable",
                ocr_used=True,
            ),
            PageTextEntry(
                physical_page=3,
                text="Merged text",
                source="mixed",
                quality="partial",
                ocr_used=True,
                diagnostics={"reason": "garbled_text"},
            ),
        ]
    )

    assert page_map.page_count == 3
    assert page_map.page_texts() == ["PDF text", "OCR text", "Merged text"]
    assert page_map.ocr_page_numbers() == [2, 3]
    assert page_map.to_page_list()[1][0] == "OCR text"
    assert page_map.to_page_list()[1][1] > 0
    assert page_map.to_diagnostics()["sources"] == {
        "pdf_text": 1,
        "ocr": 1,
        "mixed": 1,
    }


def test_fill_node_text_accepts_page_text_map() -> None:
    from pageindex.node_filler import fill_node_text
    from pageindex.page_text_map import PageTextEntry, PageTextMap

    page_map = PageTextMap(
        [
            PageTextEntry(physical_page=1, text="第一页", source="pdf_text"),
            PageTextEntry(physical_page=2, text="第二页", source="ocr", ocr_used=True),
        ]
    )
    tree = [{"title": "A", "start_index": 1, "end_index": 2, "nodes": []}]

    fill_node_text(tree, page_map)

    assert tree[0]["text"] == "第一页\n第二页"


def test_preprocess_text_document_uses_pdf_text_without_ocr() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fail_ocr(*_args, **_kwargs):
        raise AssertionError("text documents should not call OCR")

    analysis = {
        "page_count": 2,
        "page_list": [("Page 1", 2), ("Page 2", 2)],
        "text_coverage": 1.0,
        "image_coverage": 0.0,
        "image_only_pages": [],
        "garbled_pages": [],
        "text_layer_quality": "reliable",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "doc.pdf",
            analysis,
            ocr_pages_fn=fail_ocr,
        )
    )

    assert page_map.page_texts() == ["Page 1", "Page 2"]
    assert [entry.source for entry in page_map.entries] == ["pdf_text", "pdf_text"]
    assert page_map.ocr_page_numbers() == []


def test_infer_content_type_keeps_reliable_text_with_sparse_edge_images_as_text() -> None:
    from pageindex.preprocess_page_text import infer_content_type

    analysis = {
        "page_count": 85,
        "text_coverage": 0.97,
        "image_coverage": 1.0,
        "image_only_pages": [0, 84],
        "garbled_pages": [],
        "is_image_only_pdf": False,
        "is_garbled_pdf": False,
        "text_layer_quality": "reliable",
        "layout_type": "native_text_report",
        "structure_policy": "text_allowed",
    }

    assert infer_content_type(analysis) == "text"


def test_preprocess_scanned_document_ocr_all_pages() -> None:
    from pageindex.preprocess_page_text import PAGE_TEXT_OCR_PROMPT, preprocess_page_text_map

    calls = []

    async def fake_ocr(file_path, page_indices, *, prompt, analysis):
        calls.append(
            {
                "file_path": str(file_path),
                "page_indices": list(page_indices),
                "prompt": prompt,
                "analysis": analysis,
            }
        )
        return [
            {"page_num": 1, "text": "OCR page 1"},
            {"page_num": 2, "text": "OCR page 2"},
        ]

    analysis = {
        "page_count": 2,
        "page_list": [("", 1), ("", 1)],
        "text_coverage": 0.0,
        "image_coverage": 1.0,
        "image_only_pages": [0, 1],
        "garbled_pages": [],
        "is_image_only_pdf": True,
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "scan.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    assert calls[0]["page_indices"] == [0, 1]
    assert calls[0]["prompt"] == PAGE_TEXT_OCR_PROMPT
    assert page_map.page_texts() == ["OCR page 1", "OCR page 2"]
    assert [entry.source for entry in page_map.entries] == ["ocr", "ocr"]
    assert page_map.ocr_page_numbers() == [1, 2]


def test_preprocess_hybrid_document_ocrs_all_image_pages() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0, 1, 2]
        return {
            1: "OCR text page",
            2: "OCR image page",
            3: "OCR garbled page",
        }

    analysis = {
        "page_count": 3,
        "page_list": [("good text", 2), ("", 1), ("bad layer", 2)],
        "text_coverage": 0.67,
        "image_coverage": 0.67,
        "pages": [
            {"index": 0, "type": "text", "text_len": 9, "image_count": 2},
            {"index": 1, "type": "image_only", "text_len": 0, "image_count": 1},
            {"index": 2, "type": "garbled", "text_len": 9, "image_count": 1},
        ],
        "image_only_pages": [1],
        "garbled_pages": [2],
        "is_image_only_pdf": False,
        "is_garbled_pdf": False,
        "text_layer_quality": "partial",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "hybrid.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    assert page_map.page_texts() == ["OCR text page", "OCR image page", "OCR garbled page"]
    assert [entry.source for entry in page_map.entries] == ["ocr", "ocr", "ocr"]
    assert page_map.ocr_page_numbers() == [1, 2, 3]


def test_preprocess_ocr_document_does_not_fall_back_to_garbled_text() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0, 1]
        return {1: "Clean OCR page 1"}

    analysis = {
        "page_count": 2,
        "page_list": [("Clean-looking but garbled layer", 2), ("妘熎絔悞鶯隠㚵蔠裮", 2)],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0, 1],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    assert page_map.page_texts() == ["Clean OCR page 1", ""]
    assert page_map.entries[1].quality == "low"


def test_preprocess_ocr_document_prepends_recoverable_text_layer_heading() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {
            1: "sig\n\ntype table\n\nThe purpose of this lecture is to explain the static semantics."
        }

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x03\nThe\nStatic\nSeman\ntics\nof\nMo\ndules\n"
                "The\npurp\nose\nof\nthis\nlecture\nis\nto\nexplain",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("3 The Static Semantics of Modules\n")
    assert "sig\n\ntype table" in text
    assert page_map.entries[0].diagnostics["text_layer_heading_supplemented"] is True


def test_preprocess_ocr_document_prepends_fragmented_appendix_heading() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {
            1: "The following files are available in the directory /usr/cheops/mads/course"
        }

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "App\nendix\nB:\nFiles\n"
                "The\nfollo\nwing\nfiles\nare\navailable\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("Appendix B: Files\n")
    assert "The following files are available" in text
    assert page_map.entries[0].diagnostics["text_layer_heading_supplemented"] is True


def test_preprocess_ocr_document_recovers_fragmented_numbered_heading_words() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "It is good practice to keep signatures as small as possible."}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x02.\x09\nGo\no\nd\nSt\nyle\n"
                "It\nis\ngo\no\nd\npractice\nto\nkeep\nsignatures\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("2.9 Good Style\n")
    assert page_map.entries[0].diagnostics["text_layer_heading_supplemented"] is True


def test_preprocess_ocr_document_recovers_short_numbered_heading() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "structure Stack = struct\nbody"}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x03.\x02\nNames\n"
                "structure\nStack\n=\nstruct\ntype\nelt\n=\nint\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("3.2 Names\n")
    assert page_map.entries[0].diagnostics["text_layer_heading_supplemented"] is True


def test_preprocess_ocr_document_recovers_version_heading_without_body_text() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "The first version is just able to type check integer constants."}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x04.\x01\nVERSION\n1:\nThe\nbare\nT\nyp\nec\nhec\nk\ner\n"
                "(App\nendix\nA)\nThe\nfirst\nversion\nis\njust\nable\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("4.1 VERSION 1: The bare Typechecker\n")
    assert "The first version is just able" in text


def test_preprocess_ocr_document_recovers_heading_with_split_inner_word() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "The purpose of this lecture is to show a worked example."}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x04\nImplemen\nting\nan\nIn\nterpreter\nin\nML\n"
                "The\npurp\nose\nof\nthis\nlecture\nis\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("4 Implementing an Interpreter in ML\n")


def test_preprocess_ocr_document_recovers_heading_with_single_letter_fragment() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "Dynamically, the body of a functor is not evaluated."}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x03.\x08\nDecorating\nF\nunctors\nDynamically\n,\n"
                "the\nb\no\ndy\nof\na\nfunctor\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text.startswith("3.8 Decorating Functors Dynamically\n")


def test_preprocess_ocr_document_ignores_large_integer_body_fragments() -> None:
    from pageindex.preprocess_page_text import preprocess_page_text_map

    async def fake_ocr(_file_path, page_indices, *, prompt, analysis):
        assert list(page_indices) == [0]
        return {1: "Let my type be a sample expression."}

    analysis = {
        "page_count": 1,
        "page_list": [
            (
                "\x12\nLet\nmy\ntype\nbe\na\nsample\nexpression\n",
                2,
            )
        ],
        "text_coverage": 1.0,
        "image_coverage": 0.2,
        "image_only_pages": [],
        "garbled_pages": [0],
        "is_image_only_pdf": False,
        "is_garbled_pdf": True,
        "text_layer_quality": "garbled",
    }

    page_map = asyncio.run(
        preprocess_page_text_map(
            "garbled.pdf",
            analysis,
            ocr_pages_fn=fake_ocr,
        )
    )

    text = page_map.page_texts()[0]
    assert text == "Let my type be a sample expression."
    assert "text_layer_heading_supplemented" not in page_map.entries[0].diagnostics
