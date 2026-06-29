import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

pytest.skip(
    "legacy v1 page_index flow replaced by unified TOC state machine",
    allow_module_level=True,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import page_index as page_index_module
from app.services.pageindex_service import PageIndexService


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_balanced_meta_processor_process_no_toc_skips_rule_route(monkeypatch) -> None:
    called = {"process_no_toc": 0}

    monkeypatch.setattr(
        page_index_module,
        "process_no_toc",
        lambda *_a, **_k: [
            {"structure": "1", "title": "A", "physical_index": 2},
            {"structure": "2", "title": "B", "physical_index": 6},
        ],
    )
    monkeypatch.setattr(
        page_index_module,
        "extract_sections_by_rules",
        lambda *_a, **_k: [{"structure": "1", "title": "RULE", "physical_index": 1}],
    )
    monkeypatch.setattr(
        page_index_module, "is_rule_toc_reliable", lambda *_a, **_k: True
    )

    def _wrap_process_no_toc(*args, **kwargs):
        called["process_no_toc"] += 1
        return [
            {"structure": "1", "title": "A", "physical_index": 2},
            {"structure": "2", "title": "B", "physical_index": 6},
        ]

    monkeypatch.setattr(page_index_module, "process_no_toc", _wrap_process_no_toc)
    monkeypatch.setattr(
        page_index_module,
        "validate_and_truncate_physical_indices",
        lambda x, *_a, **_k: x,
    )

    async def _fake_verify(*_a, **_k):
        return 1.0, []

    monkeypatch.setattr(page_index_module, "verify_toc", _fake_verify)

    opt = SimpleNamespace(
        index_mode="balanced", model="qwen3.6-flash", toc_check_page_num=8
    )
    page_list = [("page1", 10), ("page2", 10)]

    out = asyncio.run(
        page_index_module.meta_processor(
            page_list,
            mode="process_no_toc",
            start_index=1,
            opt=opt,
            logger=_Logger(),
        )
    )

    assert called["process_no_toc"] == 1
    assert out[0]["title"] == "A"


@pytest.mark.skip(reason="v1 integration test, needs rewrite for v2 flow")
def test_generate_index_balanced_skips_service_side_structure_rewrite(tmp_path) -> None:
    import app.services.pageindex_service as svc_module

    service = PageIndexService()
    original_indexes_dir = svc_module.INDEXES_DIR
    original_page_index_main = svc_module.page_index_main
    original_page_index_main_with_page_list = svc_module.page_index_main_with_page_list
    original_get_page_tokens = svc_module.get_page_tokens
    original_build_opt = service._build_opt
    original_run_ocr = service._run_full_pdf_ocr_by_images
    original_pre_analyze = service._pre_analyze_pdf
    original_repair = service._repair_structure_titles
    original_enhance = service._enhance_balanced_fallback_with_visual
    try:
        svc_module.INDEXES_DIR = tmp_path
        fake_result = {
            "doc_name": "demo.pdf",
            "page_count": 6,
            "structure": [
                {
                    "node_id": "0001",
                    "title": "风险提示",
                    "start_index": 2,
                    "end_index": 6,
                    "nodes": [],
                }
            ],
        }
        svc_module.page_index_main = lambda *_a, **_k: fake_result
        svc_module.page_index_main_with_page_list = lambda *_a, **_k: fake_result
        svc_module.get_page_tokens = lambda *_a, **_k: [("p1", 1)] * 6
        service._build_opt = lambda mode_override=None: SimpleNamespace(  # type: ignore
            index_mode=mode_override or "balanced",
            model="qwen3.6-flash",
            if_add_node_summary="yes",
            if_add_doc_description="yes",
            if_add_node_text="yes",
            if_add_node_id="yes",
            toc_check_page_num=8,
        )

        async def _fake_ocr(*_a, **_k):
            return {
                "ocr_pages": [{"page_num": 1, "text": "p1", "ok": True}],
                "ocr_coverage": 1.0,
                "ocr_missing_pages": [],
            }

        service._run_full_pdf_ocr_by_images = _fake_ocr  # type: ignore
        service._pre_analyze_pdf = lambda _p: {  # type: ignore
            "page_count": 6,
            "unparseable_pages": 0,
            "unparseable_ratio": 0.0,
            "vlm_needed_pages": [1],
            "preferred_parser": "PyPDF2",
            "parser_quality": {"PyPDF2": 1.0, "PyMuPDF": 0.8},
            "image_pages": 1,
        }

        def _fail_repair(*_a, **_k):
            raise AssertionError("service-side repair should be disabled in balanced")

        async def _fail_enhance(*_a, **_k):
            raise AssertionError(
                "service-side visual enhance should be disabled in balanced"
            )

        service._repair_structure_titles = _fail_repair  # type: ignore
        service._enhance_balanced_fallback_with_visual = _fail_enhance  # type: ignore

        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        out = asyncio.run(
            service.generate_index(
                str(pdf_path), "doc_balanced", mode_override="balanced"
            )
        )
        structure = out["structure"].get("structure", [])
        assert structure[0]["title"] == "风险提示"
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
        service._run_full_pdf_ocr_by_images = original_run_ocr  # type: ignore
        service._pre_analyze_pdf = original_pre_analyze  # type: ignore
        service._repair_structure_titles = original_repair  # type: ignore
        service._enhance_balanced_fallback_with_visual = original_enhance  # type: ignore
