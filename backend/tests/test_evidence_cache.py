from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.evidence_cache import build_cache_key, make_cache_record


def test_build_cache_key_includes_document_page_provider_and_versions():
    key = build_cache_key(
        doc_id="doc-1",
        file_sha256="abc123",
        page=2,
        render_dpi=150,
        provider="page_title_vlm",
        prompt_version="v1",
        model_version="qwen-vl",
    )

    assert key == build_cache_key(
        doc_id="doc-1",
        file_sha256="abc123",
        page=2,
        render_dpi=150,
        provider="page_title_vlm",
        prompt_version="v1",
        model_version="qwen-vl",
    )
    assert "doc-1" in key
    assert "p2" in key
    assert "page_title_vlm" in key


def test_make_cache_record_marks_low_confidence_fallback():
    record = make_cache_record(
        cache_type="PageTitleCandidate",
        key="k",
        payload={"title": "A"},
        confidence=0.2,
        fallback_reason="vlm_timeout",
    )

    assert record["cache_type"] == "PageTitleCandidate"
    assert record["confidence"] == 0.2
    assert record["fallback_reason"] == "vlm_timeout"
    assert record["is_fallback"] is True
