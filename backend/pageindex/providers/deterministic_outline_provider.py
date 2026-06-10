"""Provider adapters for deterministic slide/agenda/text outline builders."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from pageindex.contracts import make_outline_candidate


class DeterministicOutlineProvider:
    def __init__(
        self,
        *,
        name: str,
        priority: int,
        candidate_flag: str,
        builder: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
        evidence_type: str,
        granularity: str,
    ) -> None:
        self.name = name
        self.priority = priority
        self.candidate_flag = candidate_flag
        self.builder = builder
        self.evidence_type = evidence_type
        self.granularity = granularity

    def can_run(self, analysis: Dict[str, Any]) -> bool:
        return bool(analysis.get(self.candidate_flag))

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.can_run(analysis):
            return None
        result = self.builder(analysis)
        if not result or result.get("source") != self.name:
            return None
        items = result.get("toc_items") or []
        if not items:
            return None

        return make_outline_candidate(
            source=self.name,
            items=items,
            confidence=float(result.get("confidence") or 0.8),
            evidence_type=self.evidence_type,
            coverage=float(result.get("coverage") or 1.0),
            granularity=self.granularity,
            skeleton_frozen=False,
            semi_frozen=bool(result.get("semi_frozen", True)),
            mapping_strategy="existing" if result.get("mapped") else "estimated",
            debug={"raw": {k: v for k, v in result.items() if k != "toc_items"}},
        )


def default_slide_outline_provider() -> DeterministicOutlineProvider:
    from pageindex.slide_outline_extractor import build_slide_outline

    return DeterministicOutlineProvider(
        name="slide_outline",
        priority=30,
        candidate_flag="slide_outline_candidate",
        builder=build_slide_outline,
        evidence_type="slide_titles",
        granularity="page",
    )


def default_agenda_outline_provider() -> DeterministicOutlineProvider:
    from pageindex.agenda_outline_extractor import build_agenda_outline

    return DeterministicOutlineProvider(
        name="agenda_outline",
        priority=40,
        candidate_flag="agenda_outline_candidate",
        builder=build_agenda_outline,
        evidence_type="agenda_outline",
        granularity="chapter",
    )
