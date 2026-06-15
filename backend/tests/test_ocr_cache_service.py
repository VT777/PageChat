from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_cache_service import OCRCacheService, build_ocr_cache_key  # noqa: E402
from app.services.ocr_engines.contracts import OCRDocumentResult, OCRPageResult  # noqa: E402


def test_cache_key_includes_engine_profile_version_and_options() -> None:
    base = build_ocr_cache_key(
        file_hash="file-a",
        page_num=3,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v1",
        options={"dpi": 150},
    )
    changed_profile = build_ocr_cache_key(
        file_hash="file-a",
        page_num=3,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v2",
        options={"dpi": 150},
    )
    changed_options = build_ocr_cache_key(
        file_hash="file-a",
        page_num=3,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v1",
        options={"dpi": 200},
    )

    assert base == build_ocr_cache_key(
        file_hash="file-a",
        page_num=3,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v1",
        options={"dpi": 150},
    )
    assert base != changed_profile
    assert base != changed_options
    assert "p3" in base
    assert "toc_page" in base


def test_raw_response_cache_round_trip() -> None:
    cache = OCRCacheService(max_size=10)
    key = build_ocr_cache_key(
        file_hash="file-a",
        page_num=1,
        task="page_text",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        profile_version="v1",
        options={},
    )

    cache.set_raw_response(key, {"provider": "raw"})

    assert cache.get_raw_response(key) == {"provider": "raw"}
    assert cache.get_raw_response(key + "-miss") is None


def test_normalized_result_cache_round_trip() -> None:
    cache = OCRCacheService(max_size=10)
    result = OCRDocumentResult(
        task="page_text",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        pages=[OCRPageResult(page_num=1, evidence_level="text_only", markdown="Text")],
        profile_version="v1",
    )
    key = build_ocr_cache_key(
        file_hash="file-a",
        page_num=1,
        task="page_text",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        profile_version="v1",
        options={},
    )

    cache.set_normalized_result(key, result)

    cached = cache.get_normalized_result(key)
    assert cached is not None
    assert cached["pages"][0]["markdown"] == "Text"


def test_cache_invalidation_by_profile_version_and_options_hash() -> None:
    cache = OCRCacheService(max_size=10)
    key_v1 = build_ocr_cache_key(
        file_hash="file-a",
        page_num=1,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v1",
        options={"a": 1},
    )
    key_v2 = build_ocr_cache_key(
        file_hash="file-a",
        page_num=1,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v2",
        options={"a": 1},
    )
    key_options = build_ocr_cache_key(
        file_hash="file-a",
        page_num=1,
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        profile_version="v1",
        options={"a": 2},
    )

    cache.set_raw_response(key_v1, {"hit": True})


    assert cache.get_raw_response(key_v1) == {"hit": True}
    assert cache.get_raw_response(key_v2) is None
    assert cache.get_raw_response(key_options) is None
