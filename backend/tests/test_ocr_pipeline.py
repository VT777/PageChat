import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_service import OCRService
from app.services.ocr_engines.contracts import OCRDocumentResult, OCRPageResult
from app.services.pageindex_service import PageIndexService
from app.services.ocr_engines.task_prompts import (
    PAGE_TEXT_PROMPT,
    TOC_PAGE_PROMPT,
    default_task_prompt,
)


def test_page_text_prompt_is_short_reading_order_command() -> None:
    assert PAGE_TEXT_PROMPT == "Recognize all readable text in natural reading order."


def test_toc_page_prompt_is_generic_vlm_ocr_command() -> None:
    assert TOC_PAGE_PROMPT == PAGE_TEXT_PROMPT
    prompt, prompt_name = default_task_prompt("toc_page")
    assert prompt == PAGE_TEXT_PROMPT
    assert prompt_name == "toc_page_text_reading_order_v1"


def test_ocr_service_extract_text_prefers_markdown() -> None:
    payload = {
        "md_results": "# 标题\n这是识别结果",
        "layout_details": [
            [
                {"label": "text", "content": "不应被优先采用"},
            ]
        ],
    }
    text = OCRService._extract_text_from_response(payload)
    assert "标题" in text
    assert "不应被优先采用" not in text


def test_build_page_list_with_ocr_overlay_replaces_by_page_position() -> None:
    base = [("原始第1页", 10), ("原始第2页", 10), ("原始第3页", 10)]
    ocr_pages = [
        {"page_num": 2, "text": "OCR第2页"},
        {"page_num": 3, "text": "OCR第3页"},
    ]
    merged = PageIndexService._build_page_list_with_ocr_overlay(
        base, ocr_pages, "qwen3.6-flash"
    )
    assert merged[0][0] == "原始第1页"
    assert merged[1][0] == "OCR第2页"
    assert merged[2][0] == "OCR第3页"


def test_selected_page_ocr_renders_only_requested_pages(monkeypatch, tmp_path) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()
    rendered_calls = []
    ocr_calls = []

    def fake_render_pages_to_images(file_path, page_indices, *, dpi=150):
        rendered_calls.append(list(page_indices))
        return [
            {
                "page_index": page_index,
                "image_base64": f"image-{page_index}",
                "image_mime_type": "image/jpeg",
            }
            for page_index in page_indices
        ]

    async def fake_ocr_image(image_base64, page_num, analysis=None, prompt=None, image_mime_type=None):
        ocr_calls.append(
            {
                "image_base64": image_base64,
                "page_num": page_num,
                "prompt": prompt,
                "analysis": analysis,
                "image_mime_type": image_mime_type,
            }
        )
        return SimpleNamespace(text=f"OCR page {page_num}", ok=True)

    monkeypatch.setattr(
        svc_module,
        "OCR_MAX_CONCURRENCY",
        20,
    )
    monkeypatch.setitem(
        sys.modules,
        "pageindex.layout.page_renderer",
        SimpleNamespace(render_pages_to_images=fake_render_pages_to_images),
    )
    service._ocr_image_with_resolver = fake_ocr_image  # type: ignore[method-assign]

    analysis = {"page_count": 5}
    result = asyncio.run(
        service._run_pdf_ocr_pages_by_images(
            tmp_path / "demo.pdf",
            [1, 3],
            analysis=analysis,
            prompt=PAGE_TEXT_PROMPT,
        )
    )

    assert rendered_calls == [[1, 3]]
    assert [call["page_num"] for call in ocr_calls] == [2, 4]
    assert {call["prompt"] for call in ocr_calls} == {PAGE_TEXT_PROMPT}
    assert {call["image_mime_type"] for call in ocr_calls} == {"image/jpeg"}
    assert result["ocr_pages"] == [
        {"page_num": 2, "text": "OCR page 2", "ok": True, "ocr_image_targets": 1, "ocr_image_hits": 1, "error": ""},
        {"page_num": 4, "text": "OCR page 4", "ok": True, "ocr_image_targets": 1, "ocr_image_hits": 1, "error": ""},
    ]
    assert result["overlay_all_pages"] is False


def test_page_text_ocr_writes_per_page_diagnostics(monkeypatch, tmp_path) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()
    monkeypatch.setattr(svc_module, "DATA_DIR", tmp_path / "data")

    class FakeAdapter:
        async def recognize(self, image_url, *, task, options):
            assert image_url.startswith("data:image/png;base64,")
            assert task == "page_text"
            assert options["prompt"] == PAGE_TEXT_PROMPT
            return OCRDocumentResult(
                task="page_text",
                engine_type="openai_compatible_ocr",
                model="qwen-vl-ocr",
                pages=[
                    OCRPageResult(
                        page_num=1,
                        evidence_level="text_only",
                        markdown="Detected OCR body",
                    )
                ],
                diagnostics={
                    "prompt_text": PAGE_TEXT_PROMPT,
                    "prompt_sha256": "abc123",
                    "prompt_chars": len(PAGE_TEXT_PROMPT),
                    "elapsed_ms": 42,
                    "input_type": "data_url",
                },
                raw={"content": "Detected OCR body"},
            )

        async def aclose(self):
            return None

    async def fake_resolve(_task):
        return SimpleNamespace(
            route={
                "source": "profile",
                "engine_type": "openai_compatible_ocr",
                "model": "qwen-vl-ocr",
                "options": {},
            },
            adapter=FakeAdapter(),
        )

    service._resolve_ocr_engine = fake_resolve  # type: ignore[method-assign]
    analysis = {"doc_id": "doc-ocr"}

    result = asyncio.run(
        service._ocr_image_with_resolver(
            "base64-page-payload",
            2,
            analysis=analysis,
            prompt=PAGE_TEXT_PROMPT,
        )
    )

    assert result.ok is True
    assert result.text == "Detected OCR body"
    diagnostic_path = tmp_path / "data" / "ocr_diagnostics" / "doc-ocr" / "page_text-0002.json"
    assert diagnostic_path.exists()
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert payload["task"] == "page_text"
    assert payload["page_num"] == 2
    assert payload["diagnostics"]["model"] == "qwen-vl-ocr"
    assert payload["diagnostics"]["prompt_text"] == PAGE_TEXT_PROMPT
    assert payload["output"]["text_preview"] == "Detected OCR body"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "base64-page-payload" not in serialized
    assert "data:image" not in serialized

    assert "prompt_text" not in analysis["ocr_calls"][0]
    assert analysis["ocr_calls_summary"]["page_text"]["diagnostics_dir"].endswith(
        "ocr_diagnostics/doc-ocr"
    )


def test_ocr_diagnostics_doc_id_preserves_unicode_file_stem() -> None:
    doc_id = PageIndexService._ocr_diagnostics_doc_id(
        {"file_path": r"D:\docs\2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"}
    )

    assert doc_id == "2025年度重庆市人工智能应用场景典型案例集_压缩版"


def test_page_text_ocr_main_log_is_compact(monkeypatch, tmp_path, capsys) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()
    rendered_calls = []

    def fake_render_pages_to_images(file_path, page_indices, *, dpi=150):
        rendered_calls.append(list(page_indices))
        return [
            {
                "page_index": page_index,
                "image_base64": f"image-{page_index}",
                "image_mime_type": "image/jpeg",
            }
            for page_index in page_indices
        ]

    async def fake_ocr_image(image_base64, page_num, analysis=None, prompt=None, image_mime_type=None):
        PageIndexService._record_ocr_call(
            analysis,
            {
                "task": "page_text",
                "engine_type": "openai_compatible_ocr",
                "model": "qwen-vl-ocr",
                "prompt_text": prompt,
                "elapsed_ms": 10,
            },
            page_num=page_num,
            status="ok",
        )
        return SimpleNamespace(text=f"OCR page {page_num}", ok=True)

    monkeypatch.setattr(svc_module, "OCR_MAX_CONCURRENCY", 20)
    monkeypatch.setitem(
        sys.modules,
        "pageindex.layout.page_renderer",
        SimpleNamespace(render_pages_to_images=fake_render_pages_to_images),
    )
    service._ocr_image_with_resolver = fake_ocr_image  # type: ignore[method-assign]

    analysis = {"doc_id": "doc-log"}
    asyncio.run(
        service._run_pdf_ocr_pages_by_images(
            tmp_path / "demo.pdf",
            [0, 1],
            analysis=analysis,
            prompt=PAGE_TEXT_PROMPT,
        )
    )

    captured = capsys.readouterr()
    assert rendered_calls == [[0, 1]]
    assert "[TOC-OCR] task=page_text model=qwen-vl-ocr pages=2 concurrency=20" in captured.out
    assert "primary_model" not in captured.out
    assert PAGE_TEXT_PROMPT not in captured.out
    assert "OCR page 1" not in captured.out


@pytest.mark.skip(reason="v1 integration test, needs rewrite for v2 flow")
def test_generate_index_fast_to_balanced_reuses_ocr_page_list(tmp_path) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()

    original_indexes_dir = svc_module.INDEXES_DIR
    original_page_index_main = svc_module.page_index_main
    original_page_index_main_with_page_list = svc_module.page_index_main_with_page_list
    original_get_page_tokens = svc_module.get_page_tokens
    original_build_opt = service._build_opt
    original_pre_analyze = service._pre_analyze_pdf
    original_run_ocr = service._run_full_pdf_ocr_by_images
    try:
        svc_module.INDEXES_DIR = tmp_path

        calls = {"with_page_list": 0, "last_page_list": None}

        def fake_page_index_main_with_page_list(
            doc_name, page_list, opt=None, **kwargs
        ):
            calls["with_page_list"] += 1
            calls["last_page_list"] = list(page_list)
            mode = getattr(opt, "index_mode", "balanced")
            if mode == "fast":
                return {
                    "doc_name": doc_name,
                    "page_count": 2,
                    "structure": [
                        {
                            "node_id": "0001",
                            "title": "章节A",
                            "start_index": 1,
                            "end_index": None,
                            "summary": "",
                            "nodes": [],
                        }
                    ],
                }
            return {
                "doc_name": doc_name,
                "page_count": 2,
                "structure": [
                    {
                        "node_id": "0001",
                        "title": "章节A",
                        "start_index": 1,
                        "end_index": 2,
                        "summary": "",
                        "nodes": [],
                    }
                ],
            }

        svc_module.page_index_main = lambda *_a, **_k: {
            "structure": [],
            "page_count": 2,
        }
        svc_module.page_index_main_with_page_list = fake_page_index_main_with_page_list
        svc_module.get_page_tokens = lambda *_a, **_k: [("原始1", 1), ("原始2", 1)]

        service._build_opt = lambda mode_override=None: SimpleNamespace(  # type: ignore
            index_mode=mode_override or "smart",
            model="qwen3.6-flash",
            if_add_node_summary="yes"
            if (mode_override or "smart") == "balanced"
            else "no",
            if_add_doc_description="yes"
            if (mode_override or "smart") == "balanced"
            else "no",
            if_add_node_text="yes",
            if_add_node_id="yes",
        )
        service._pre_analyze_pdf = lambda _p: {  # type: ignore
            "page_count": 2,
            "unparseable_pages": 0,
            "unparseable_ratio": 0.0,
            "vlm_needed_pages": [1, 2],
            "preferred_parser": "PyPDF2",
            "parser_quality": {"PyPDF2": 1.0, "PyMuPDF": 0.8},
            "image_pages": 2,
        }

        async def fake_ocr(*_a, **_k):
            return {
                "ocr_pages": [
                    {"page_num": 1, "text": "OCR文本1", "ok": True},
                    {"page_num": 2, "text": "OCR文本2", "ok": True},
                ],
                "ocr_coverage": 1.0,
                "ocr_missing_pages": [],
            }

        service._run_full_pdf_ocr_by_images = fake_ocr  # type: ignore

        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        out = asyncio.run(
            service.generate_index(str(pdf_path), "doc1", mode_override="smart")
        )

        # With new flow: fast TOC extraction fails for fake PDF → smart escalates to balanced
        # run_pageindex calls page_index_main_with_page_list once (for balanced)
        assert calls["with_page_list"] >= 1
        assert calls["last_page_list"][0][0] == "OCR文本1"
        assert calls["last_page_list"][1][0] == "OCR文本2"
        assert out["structure"].get("ocr_used") is True
        assert (
            out["structure"].get("route_decision", {}).get("execution_mode")
            == "balanced"
        )
    finally:
        svc_module.INDEXES_DIR = original_indexes_dir
        svc_module.page_index_main = original_page_index_main
        svc_module.page_index_main_with_page_list = (
            original_page_index_main_with_page_list
        )
        svc_module.get_page_tokens = original_get_page_tokens
        service._build_opt = original_build_opt  # type: ignore
        service._pre_analyze_pdf = original_pre_analyze  # type: ignore
        service._run_full_pdf_ocr_by_images = original_run_ocr  # type: ignore


@pytest.mark.skip(reason="v1 integration test, needs rewrite for v2 flow")
def test_generate_index_fast_mode_does_not_auto_escalate(tmp_path) -> None:
    import app.services.pageindex_service as svc_module
    from unittest.mock import AsyncMock, patch

    service = PageIndexService()

    original_indexes_dir = svc_module.INDEXES_DIR
    original_page_index_main = svc_module.page_index_main
    original_page_index_main_with_page_list = svc_module.page_index_main_with_page_list
    original_get_page_tokens = svc_module.get_page_tokens
    original_build_opt = service._build_opt
    original_pre_analyze = service._pre_analyze_pdf
    original_should_escalate = service._should_escalate_fast_by_toc_quality
    original_run_ocr = service._run_full_pdf_ocr_by_images
    try:
        svc_module.INDEXES_DIR = tmp_path

        calls = {"with_page_list": 0}

        def fake_page_index_main_with_page_list(
            doc_name, page_list, opt=None, **kwargs
        ):
            calls["with_page_list"] += 1
            return {
                "doc_name": doc_name,
                "page_count": 2,
                "structure": [
                    {
                        "node_id": "0001",
                        "title": "章节A",
                        "start_index": 1,
                        "end_index": 2,
                        "summary": "",
                        "nodes": [],
                    }
                ],
            }

        svc_module.page_index_main = lambda *_a, **_k: {
            "structure": [],
            "page_count": 2,
        }
        svc_module.page_index_main_with_page_list = fake_page_index_main_with_page_list
        svc_module.get_page_tokens = lambda *_a, **_k: [("原始1", 1), ("原始2", 1)]

        service._build_opt = lambda mode_override=None: SimpleNamespace(  # type: ignore
            index_mode=mode_override or "fast",
            model="qwen3.6-flash",
            if_add_node_summary="no",
            if_add_doc_description="no",
            if_add_node_text="yes",
            if_add_node_id="yes",
        )
        service._pre_analyze_pdf = lambda _p: {  # type: ignore
            "page_count": 2,
            "unparseable_pages": 0,
            "unparseable_ratio": 0.0,
            "vlm_needed_pages": [1, 2],
            "preferred_parser": "PyPDF2",
            "parser_quality": {"PyPDF2": 1.0, "PyMuPDF": 0.8},
            "image_pages": 2,
        }
        service._should_escalate_fast_by_toc_quality = lambda _s: True  # type: ignore

        async def fake_ocr(*_a, **_k):
            return {
                "ocr_pages": [
                    {"page_num": 1, "text": "OCR文本1", "ok": True},
                    {"page_num": 2, "text": "OCR文本2", "ok": True},
                ],
                "ocr_coverage": 1.0,
                "ocr_missing_pages": [],
            }

        service._run_full_pdf_ocr_by_images = fake_ocr  # type: ignore

        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        # Mock fast TOC extraction to return a valid result so fast mode succeeds
        fake_toc_items = [
            {"structure": "1", "title": "章节A", "physical_index": 1},
            {"structure": "2", "title": "章节B", "physical_index": 2},
        ]
        with (
            patch(
                "pageindex.page_index.extract_toc_code_only",
                return_value=(fake_toc_items, "bookmarks"),
            ),
            patch(
                "pageindex.page_index.validate_and_finalize_toc",
                new_callable=AsyncMock,
                return_value={
                    "toc_items": fake_toc_items,
                    "source": "bookmarks",
                    "valid": True,
                },
            ),
        ):
            out = asyncio.run(
                service.generate_index(str(pdf_path), "doc_fast", mode_override="fast")
            )

        assert (
            out["structure"].get("route_decision", {}).get("execution_mode") == "fast"
        )
        assert (
            out["structure"].get("route_decision", {}).get("requested_mode") == "fast"
        )
    finally:
        svc_module.INDEXES_DIR = original_indexes_dir
        svc_module.page_index_main = original_page_index_main
        svc_module.page_index_main_with_page_list = (
            original_page_index_main_with_page_list
        )
        svc_module.get_page_tokens = original_get_page_tokens
        service._build_opt = original_build_opt  # type: ignore
        service._pre_analyze_pdf = original_pre_analyze  # type: ignore
        service._should_escalate_fast_by_toc_quality = original_should_escalate  # type: ignore
        service._run_full_pdf_ocr_by_images = original_run_ocr  # type: ignore


@pytest.mark.skip(reason="v1 integration test, needs rewrite for v2 flow")
def test_generate_index_fast_mode_errors_when_toc_ranges_incomplete(tmp_path) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()

    original_indexes_dir = svc_module.INDEXES_DIR
    original_page_index_main = svc_module.page_index_main
    original_page_index_main_with_page_list = svc_module.page_index_main_with_page_list
    original_get_page_tokens = svc_module.get_page_tokens
    original_build_opt = service._build_opt
    original_pre_analyze = service._pre_analyze_pdf
    original_run_ocr = service._run_full_pdf_ocr_by_images
    try:
        svc_module.INDEXES_DIR = tmp_path

        def fake_page_index_main_with_page_list(
            doc_name, page_list, opt=None, **kwargs
        ):
            return {
                "doc_name": doc_name,
                "page_count": 3,
                "structure": [
                    {
                        "node_id": "0001",
                        "title": "章节A",
                        "start_index": 1,
                        "end_index": None,
                        "summary": "",
                        "nodes": [],
                    }
                ],
            }

        svc_module.page_index_main = lambda *_a, **_k: {
            "structure": [],
            "page_count": 3,
        }
        svc_module.page_index_main_with_page_list = fake_page_index_main_with_page_list
        svc_module.get_page_tokens = lambda *_a, **_k: [
            ("原始1", 1),
            ("原始2", 1),
            ("原始3", 1),
        ]

        service._build_opt = lambda mode_override=None: SimpleNamespace(  # type: ignore
            index_mode=mode_override or "fast",
            model="qwen3.6-flash",
            if_add_node_summary="no",
            if_add_doc_description="no",
            if_add_node_text="yes",
            if_add_node_id="yes",
        )
        service._pre_analyze_pdf = lambda _p: {  # type: ignore
            "page_count": 3,
            "unparseable_pages": 0,
            "unparseable_ratio": 0.0,
            "vlm_needed_pages": [1, 2, 3],
            "preferred_parser": "PyPDF2",
            "parser_quality": {"PyPDF2": 1.0, "PyMuPDF": 0.8},
            "image_pages": 1,
        }

        async def fake_ocr(*_a, **_k):
            return {
                "ocr_pages": [{"page_num": 1, "text": "OCR文本1", "ok": True}],
                "ocr_coverage": 1.0,
                "ocr_missing_pages": [],
            }

        service._run_full_pdf_ocr_by_images = fake_ocr  # type: ignore

        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        with pytest.raises(ValueError, match="FAST_TOC_INCOMPLETE"):
            asyncio.run(
                service.generate_index(
                    str(pdf_path), "doc_fast_bad", mode_override="fast"
                )
            )
    finally:
        svc_module.INDEXES_DIR = original_indexes_dir
        svc_module.page_index_main = original_page_index_main
        svc_module.page_index_main_with_page_list = (
            original_page_index_main_with_page_list
        )
        svc_module.get_page_tokens = original_get_page_tokens
        service._build_opt = original_build_opt  # type: ignore
        service._pre_analyze_pdf = original_pre_analyze  # type: ignore
        service._run_full_pdf_ocr_by_images = original_run_ocr  # type: ignore


@pytest.mark.skip(reason="v1 integration test, needs rewrite for v2 flow")
def test_generate_index_smart_falls_back_to_balanced_when_fast_toc_incomplete(
    tmp_path,
) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()

    original_indexes_dir = svc_module.INDEXES_DIR
    original_page_index_main = svc_module.page_index_main
    original_page_index_main_with_page_list = svc_module.page_index_main_with_page_list
    original_get_page_tokens = svc_module.get_page_tokens
    original_build_opt = service._build_opt
    original_pre_analyze = service._pre_analyze_pdf
    original_run_ocr = service._run_full_pdf_ocr_by_images
    try:
        svc_module.INDEXES_DIR = tmp_path
        calls = {"fast": 0, "balanced": 0}

        def fake_page_index_main_with_page_list(
            doc_name, page_list, opt=None, **kwargs
        ):
            mode = getattr(opt, "index_mode", "balanced")
            if mode == "fast":
                calls["fast"] += 1
                return {
                    "doc_name": doc_name,
                    "page_count": 3,
                    "structure": [
                        {
                            "node_id": "0001",
                            "title": "章节A",
                            "start_index": 1,
                            "end_index": None,
                            "summary": "",
                            "nodes": [],
                        }
                    ],
                }
            calls["balanced"] += 1
            return {
                "doc_name": doc_name,
                "page_count": 3,
                "structure": [
                    {
                        "node_id": "0001",
                        "title": "章节A",
                        "start_index": 1,
                        "end_index": 3,
                        "summary": "",
                        "nodes": [],
                    }
                ],
            }

        svc_module.page_index_main = lambda *_a, **_k: {
            "structure": [],
            "page_count": 3,
        }
        svc_module.page_index_main_with_page_list = fake_page_index_main_with_page_list
        svc_module.get_page_tokens = lambda *_a, **_k: [
            ("原始1", 1),
            ("原始2", 1),
            ("原始3", 1),
        ]

        service._build_opt = lambda mode_override=None: SimpleNamespace(  # type: ignore
            index_mode=mode_override or "smart",
            model="qwen3.6-flash",
            if_add_node_summary="yes"
            if (mode_override or "smart") == "balanced"
            else "no",
            if_add_doc_description="yes"
            if (mode_override or "smart") == "balanced"
            else "no",
            if_add_node_text="yes",
            if_add_node_id="yes",
        )
        service._pre_analyze_pdf = lambda _p: {  # type: ignore
            "page_count": 3,
            "unparseable_pages": 0,
            "unparseable_ratio": 0.0,
            "vlm_needed_pages": [1, 2, 3],
            "preferred_parser": "PyPDF2",
            "parser_quality": {"PyPDF2": 1.0, "PyMuPDF": 0.8},
            "image_pages": 1,
        }

        async def fake_ocr(*_a, **_k):
            return {
                "ocr_pages": [{"page_num": 1, "text": "OCR文本1", "ok": True}],
                "ocr_coverage": 1.0,
                "ocr_missing_pages": [],
            }

        service._run_full_pdf_ocr_by_images = fake_ocr  # type: ignore

        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        out = asyncio.run(
            service.generate_index(
                str(pdf_path), "doc_smart_bad", mode_override="smart"
            )
        )

        # With new flow: fast TOC code extraction fails → smart escalates to balanced
        # page_index_main_with_page_list is only called for balanced (fast path is code-only now)
        assert calls["fast"] == 0  # fast no longer calls page_index_main
        assert calls["balanced"] == 1
        assert (
            out["structure"].get("route_decision", {}).get("execution_mode")
            == "balanced"
        )
    finally:
        svc_module.INDEXES_DIR = original_indexes_dir
        svc_module.page_index_main = original_page_index_main
        svc_module.page_index_main_with_page_list = (
            original_page_index_main_with_page_list
        )
        svc_module.get_page_tokens = original_get_page_tokens
        service._build_opt = original_build_opt  # type: ignore
        service._pre_analyze_pdf = original_pre_analyze  # type: ignore
        service._run_full_pdf_ocr_by_images = original_run_ocr  # type: ignore
