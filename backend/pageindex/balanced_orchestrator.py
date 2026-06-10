"""Provider registry and lightweight orchestration for balanced TOC v4.2."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Protocol

from pageindex.contracts import make_build_state


class OutlineProvider(Protocol):
    name: str
    priority: int

    def can_run(self, analysis: Dict[str, Any]) -> bool:
        ...

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ...


class ProviderRegistry:
    def __init__(self, providers: Iterable[OutlineProvider]):
        self.providers = sorted(
            list(providers),
            key=lambda provider: (getattr(provider, "priority", 100), getattr(provider, "name", "")),
        )

    def run_all(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for provider in self.providers:
            if not provider.can_run(analysis):
                continue
            try:
                result = provider.run(analysis)
            except Exception as exc:
                results.append(
                    {
                        "provider": provider.name,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue
            if not result:
                continue
            results.append({"provider": provider.name, "result": result})
        return results


def build_balanced_state(
    analysis: Dict[str, Any],
    registry: ProviderRegistry,
) -> Dict[str, Any]:
    provider_results = registry.run_all(analysis)
    skeleton = None
    candidates: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for entry in provider_results:
        if "error" in entry:
            errors.append(entry)
            continue
        result = entry["result"]
        result_type = result.get("type")
        if result_type == "toc_skeleton" and skeleton is None:
            skeleton = result
            continue
        if result_type == "outline_candidate":
            candidates.append(result)

    provider_scores: List[Dict[str, Any]] = []
    selected_source = None
    frozen = False
    selected_candidate = None
    if skeleton is not None:
        selected_source = skeleton.get("source")
        frozen = bool(skeleton.get("freeze_top_level", True))
    elif candidates:
        ranked = _rank_candidates(candidates)
        provider_scores = ranked
        selected_source = ranked[0]["source"]
        selected_candidate = next(
            (candidate for candidate in candidates if candidate.get("source") == selected_source),
            None,
        )
        frozen = bool(
            selected_candidate
            and selected_candidate.get("top_level_frozen", selected_candidate.get("semi_frozen", False))
        )

    state = make_build_state(
        skeleton=skeleton,
        candidates=candidates,
        page_mapping=None,
        selected_source=selected_source,
        frozen=frozen,
        diagnostics={
            "provider_errors": errors,
            "provider_count": len(registry.providers),
            "result_count": len(provider_results),
            "provider_scores": provider_scores,
            "selected_reason": "toc_skeleton" if skeleton is not None else ("candidate_score" if candidates else "none"),
        },
        top_level_frozen=frozen,
        top_level_source=selected_source if frozen else None,
        allow_child_expansion=bool(
            selected_candidate.get("allow_child_expansion", True)
            if selected_candidate
            else True
        ),
    )
    return state


def _rank_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scored = [_score_candidate(candidate) for candidate in candidates]
    return sorted(
        scored,
        key=lambda item: (-item["final_score"], item["priority_hint"], item["source"]),
    )


def _score_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    confidence = _bounded_float(candidate.get("confidence"))
    coverage = _bounded_float(candidate.get("coverage"))
    title_quality = _title_quality(candidate.get("items") or [])
    risk_penalty = min(1.0, len(candidate.get("risk_flags") or []) * 0.25)
    preselect_score = (
        confidence * 0.35
        + coverage * 0.25
        + title_quality * 0.20
        - risk_penalty * 0.20
    )
    mapping_quality = _mapping_probe(candidate)
    conflict_score = 1.0 - risk_penalty
    range_coverage = coverage
    final_score = (
        preselect_score * 0.55
        + mapping_quality * 0.25
        + conflict_score * 0.10
        + range_coverage * 0.10
    )
    return {
        "source": candidate.get("source") or "",
        "preselect_score": round(preselect_score, 4),
        "mapping_quality": round(mapping_quality, 4),
        "final_score": round(final_score, 4),
        "priority_hint": 0 if candidate.get("mapping_strategy") == "existing" else 1,
    }


def _mapping_probe(candidate: Dict[str, Any]) -> float:
    items = candidate.get("items") or []
    if not items:
        return 0.0
    if candidate.get("mapping_strategy") == "existing":
        mapped = sum(1 for item in items if _positive_int(item.get("start_index") or item.get("physical_index") or item.get("page")))
        return mapped / max(1, len(items))
    mapped = sum(1 for item in items if _positive_int(item.get("physical_index") or item.get("page")))
    return max(0.2, mapped / max(1, len(items)))


def _title_quality(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 0.0
    good = 0
    for item in items:
        title = str(item.get("title") or "").strip()
        if 2 <= len(title) <= 80:
            good += 1
    return good / max(1, len(items))


def _bounded_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
