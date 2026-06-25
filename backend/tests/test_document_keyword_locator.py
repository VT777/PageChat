from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_keyword_locator import locate_keywords_in_index


def test_keyword_locator_prefers_exact_phrase_over_loose_terms() -> None:
    index = {
        "pages": [
            {"page": 1, "text": "华东收入增长来自渠道调整，复购率保持稳定。"},
            {"page": 2, "text": "收入稳定增长，但未提到华东这个地区。"},
        ],
        "structure": [],
    }

    result = locate_keywords_in_index(
        index_data=index,
        query="在哪一页提到了华东收入增长？",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )

    assert result["search_method"] == "keyword_exact"
    assert result["matches"][0]["page"] == 1
    assert result["matches"][0]["matched_terms"]
    assert result["matches"][0]["match_type"] in {"exact_phrase", "keyword"}
    assert "华东收入增长" in result["matches"][0]["snippet"]


def test_keyword_locator_uses_ocr_text_for_matching_but_omits_visual_snippet() -> None:
    index = {
        "pages": [
            {
                "page": 3,
                "text": "OCR text: 华东收入增长 20%",
                "images": [{"image_path": "page://doc-a/3", "page": 3}],
                "ocr_used": True,
            }
        ],
        "page_text_map_ocr_pages": [3],
        "structure": [],
    }

    result = locate_keywords_in_index(
        index_data=index,
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="scan.pdf",
    )

    match = result["matches"][0]
    assert match["page"] == 3
    assert match["match_type"] == "ocr_keyword"
    assert match["visual_evidence_required"] is True
    assert match["text_omitted_reason"] == "visual_evidence_required"
    assert "snippet" not in match
    assert "OCR text" not in str(result)
    assert match["image_refs"][0]["image_path"] == "page://doc-a/3"
    assert match["next_tool"] == "get_page_image"


def test_keyword_locator_returns_empty_matches_without_semantic_fallback() -> None:
    result = locate_keywords_in_index(
        index_data={"pages": [{"page": 1, "text": "完全无关"}], "structure": []},
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )

    assert result["matches"] == []
    assert result["search_method"] == "keyword_exact"
