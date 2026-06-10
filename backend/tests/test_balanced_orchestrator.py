from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.balanced_orchestrator import (
    ProviderRegistry,
    build_balanced_state,
)
from pageindex.contracts import (
    make_outline_candidate,
    make_toc_skeleton_context,
)


class StubProvider:
    def __init__(self, name, priority, result=None):
        self.name = name
        self.priority = priority
        self.result = result
        self.calls = 0

    def can_run(self, analysis):
        return True

    def run(self, analysis):
        self.calls += 1
        return self.result


def test_registry_runs_providers_by_priority():
    low = StubProvider(
        "low",
        20,
        make_outline_candidate(
            source="text_heading",
            items=[{"title": "Low", "start_index": 1}],
        ),
    )
    high = StubProvider(
        "high",
        10,
        make_outline_candidate(
            source="slide_outline",
            items=[{"title": "High", "start_index": 1}],
        ),
    )

    results = ProviderRegistry([low, high]).run_all({})

    assert [result["provider"] for result in results] == ["high", "low"]
    assert high.calls == 1
    assert low.calls == 1


def test_orchestrator_prefers_valid_skeleton_over_outline_candidate():
    skeleton = make_toc_skeleton_context(
        source="toc_page",
        items=[
            {"title": "A", "level": 1, "page": 1},
            {"title": "B", "level": 1, "page": 8},
        ],
        has_page_numbers=True,
    )
    candidate = make_outline_candidate(
        source="slide_outline",
        items=[{"title": "Slide A", "start_index": 1}],
    )

    state = build_balanced_state(
        {},
        ProviderRegistry(
            [
                StubProvider("candidate", 10, candidate),
                StubProvider("skeleton", 5, skeleton),
            ]
        ),
    )

    assert state["selected_source"] == "toc_page"
    assert state["frozen"] is True
    assert state["skeleton"]["source"] == "toc_page"
    assert state["candidates"][0]["source"] == "slide_outline"


def test_orchestrator_uses_candidate_when_no_skeleton_exists():
    candidate = make_outline_candidate(
        source="agenda_outline",
        items=[{"title": "Agenda A", "start_index": 3}],
    )

    state = build_balanced_state(
        {},
        ProviderRegistry([StubProvider("candidate", 10, candidate)]),
    )

    assert state["selected_source"] == "agenda_outline"
    assert state["top_level_frozen"] is True
    assert state["allow_child_expansion"] is True
    assert state["frozen"] is True
    assert state["skeleton"] is None
    assert len(state["candidates"]) == 1


def test_orchestrator_selects_best_candidate_by_score_not_priority():
    weak_high_priority = make_outline_candidate(
        source="agenda_outline",
        items=[{"title": "Weak", "start_index": 1}],
        confidence=0.2,
        coverage=0.2,
        risk_flags=["weak_mapping"],
    )
    strong_low_priority = make_outline_candidate(
        source="slide_outline",
        items=[
            {"title": "A", "start_index": 1},
            {"title": "B", "start_index": 5},
            {"title": "C", "start_index": 9},
        ],
        confidence=0.9,
        coverage=0.9,
        mapping_strategy="existing",
    )

    state = build_balanced_state(
        {"page_count": 12},
        ProviderRegistry(
            [
                StubProvider("weak", 1, weak_high_priority),
                StubProvider("strong", 50, strong_low_priority),
            ]
        ),
    )

    assert state["selected_source"] == "slide_outline"
    assert state["diagnostics"]["selected_reason"] == "candidate_score"
    scores = state["diagnostics"]["provider_scores"]
    assert scores[0]["source"] == "slide_outline"
    assert scores[0]["final_score"] > scores[1]["final_score"]


def test_provider_errors_are_collected_without_stopping_other_providers():
    class FailingProvider(StubProvider):
        def run(self, analysis):
            self.calls += 1
            raise RuntimeError("boom")

    candidate = make_outline_candidate(
        source="text_heading",
        items=[{"title": "Heading", "start_index": 1}],
    )

    state = build_balanced_state(
        {},
        ProviderRegistry(
            [
                FailingProvider("bad", 1),
                StubProvider("good", 2, candidate),
            ]
        ),
    )

    assert state["selected_source"] == "text_heading"
    assert state["diagnostics"]["provider_errors"][0]["provider"] == "bad"
