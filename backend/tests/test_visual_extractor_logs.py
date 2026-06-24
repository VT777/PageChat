from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.skip(
    "legacy visual_extractor v1 module was removed by the unified TOC state machine",
    allow_module_level=True,
)


def test_long_visual_doc_log_uses_anchored_pipeline_terms(monkeypatch, capsys):
    from pageindex import visual_extractor

    async def fake_build_balanced_toc_visual(**kwargs):
        return {
            "toc_items": [{"title": "Chapter 1", "physical_index": 1}],
            "source": "vlm_toc_skeleton",
            "confidence": 0.9,
            "mapped": True,
            "semi_frozen": True,
            "prevalidated": True,
        }

    monkeypatch.setattr(
        "pageindex.balanced_toc.build_balanced_toc_visual",
        fake_build_balanced_toc_visual,
    )

    import asyncio

    result = asyncio.run(
        visual_extractor.extract_visual_toc(
            file_path="demo.pdf",
            analysis={"page_count": 43},
            model="test-model",
            anchors={"toc_pages": [2]},
        )
    )

    out = capsys.readouterr().out

    assert result["source"] == "vlm_toc_skeleton"
    assert "anchored TOC skeleton pipeline" in out
    assert "not fully implemented" not in out
    assert "legacy visual extraction" not in out
