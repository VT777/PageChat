from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.providers.deterministic_outline_provider import (
    DeterministicOutlineProvider,
)


def test_slide_outline_provider_returns_candidate(monkeypatch):
    def fake_builder(analysis):
        return {
            "source": "slide_outline",
            "toc_items": [{"title": "Slide topic", "start_index": 3}],
            "mapped": True,
            "semi_frozen": True,
        }

    provider = DeterministicOutlineProvider(
        name="slide_outline",
        priority=30,
        candidate_flag="slide_outline_candidate",
        builder=fake_builder,
        evidence_type="slide_titles",
        granularity="page",
    )

    result = provider.run({"slide_outline_candidate": True})

    assert result["type"] == "outline_candidate"
    assert result["source"] == "slide_outline"
    assert result["semi_frozen"] is True
    assert result["skeleton_frozen"] is False
    assert result["mapping_strategy"] == "existing"


def test_outline_provider_does_not_run_without_candidate_flag():
    provider = DeterministicOutlineProvider(
        name="agenda_outline",
        priority=40,
        candidate_flag="agenda_outline_candidate",
        builder=lambda analysis: {"source": "agenda_outline", "toc_items": [{"title": "A"}]},
        evidence_type="agenda",
        granularity="chapter",
    )

    assert provider.can_run({"agenda_outline_candidate": False}) is False
    assert provider.run({"agenda_outline_candidate": False}) is None
