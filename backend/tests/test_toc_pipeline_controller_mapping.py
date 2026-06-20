from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.pipeline.toc_pipeline_controller import TOCPipelineController


def test_controller_verifies_llm_toc_printed_pages_with_ordinal_mapping():
    candidate = {
        "candidate_id": "llm_toc_page_001",
        "source": "llm_toc_page",
        "raw_confidence": 0.72,
        "items": [
            {"title": f"Case {index:02d}", "level": 2, "page": logical_page}
            for index, logical_page in enumerate([1, 3, 5, 7, 9, 11], start=1)
        ],
    }
    analysis = {
        "toc_pages": [2],
        "ocr_text_map": {
            1: "Cover",
            2: "Contents\nCase 01 01\nCase 02 03\nCase 03 05\nCase 04 07\nCase 05 09\nCase 06 11",
            3: "Case 01\nBody",
            4: "Case 02\nBody",
            5: "Body without a clean heading",
            6: "Case 04\nBody",
            7: "Body without a clean heading",
            8: "Case 06\nBody",
        },
    }

    result = TOCPipelineController().generate(
        pdf_path="dummy.pdf",
        mode="smart",
        analysis=analysis,
        candidates=[candidate],
        page_count=8,
        budget={"allow_code_toc": False},
    )

    assert result["status"] == "ok"
    assert result["source"] == "llm_toc_page"
    assert [item["physical_index"] for item in result["items"]] == [3, 4, 5, 6, 7, 8]
    assert result["evidence"]["content_mapping"]["strategy"] == "printed_page_offset"
