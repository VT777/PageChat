from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_toc_detector_single_prompt_requests_typed_sections() -> None:
    from app.prompts.pageindex_prompts import TOC_DETECTOR_SINGLE_PROMPT

    prompt = TOC_DETECTOR_SINGLE_PROMPT.lower()

    assert "sections" in prompt
    assert "primary_kind" in prompt
    assert "mixed_toc" in prompt
    assert "figure_toc" in prompt
    assert "table_toc" in prompt
    assert "not toc pages" not in prompt
