from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_should_skip_legacy_toc_detection_when_anchor_toc_exists_and_provider_succeeded():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}
    result = {"items": [{"title": "A"}], "prevalidated": True, "source": "toc_page_text"}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, result) is True


def test_should_not_skip_legacy_toc_detection_without_result():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, None) is False
