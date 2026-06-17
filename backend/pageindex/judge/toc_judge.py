"""Rank and select normalized TOC candidates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


SOURCE_PRIORITY = {
    "code_toc": 0,
    "official_baseline": 1,
    "toc_page": 2,
    "text_heading": 2,
    "slide_outline": 2,
    "agenda_outline": 2,
    "page_heading_outline": 2,
    "ocr_toc_page": 2,
    "toc_page_layout": 2,
    "llm_toc_page": 2,
    "hierarchical": 3,
    "batch": 3,
    "fast_text": 3,
    "llm_text": 3,
    "text_tree": 3,
    "targeted_vlm": 4,
    "vlm": 4,
    "segment_fallback": 6,
}

SOURCE_SCORE_CAP = {
    "code_toc": 0.99,
    "official_baseline": 0.97,
    "toc_page": 0.9,
    "text_heading": 0.9,
    "slide_outline": 0.9,
    "agenda_outline": 0.9,
    "page_heading_outline": 0.86,
    "ocr_toc_page": 0.88,
    "toc_page_layout": 0.88,
    "llm_toc_page": 0.86,
    "hierarchical": 0.8,
    "batch": 0.8,
    "fast_text": 0.78,
    "llm_text": 0.78,
    "text_tree": 0.8,
    "targeted_vlm": 0.7,
    "vlm": 0.68,
    "segment_fallback": 0.45,
}

EVIDENCE_LEVEL_SCORE = {
    "line_box": 0.98,
    "text_only": 0.9,
    "model_inferred": 0.82,
}

CONTENT_MAPPING_PENDING_CAP = 0.49
CONTENT_MAPPING_PENDING_NON_OVERFLOW_CAP = 0.62
MIN_ACCEPT_SCORE = 0.5


class TOCJudge:
    def select(
        self,
        candidates: List[Dict[str, Any]],
        *,
        budget: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        accepted: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for candidate in candidates:
            if not candidate or not candidate.get("items"):
                rejected.append(
                    {
                        "candidate_id": candidate.get("candidate_id") if isinstance(candidate, dict) else None,
                        "source": str(candidate.get("source") or "") if isinstance(candidate, dict) else "",
                        "score": 0.0,
                        "reasons": ["empty_items"],
                    }
                )
                continue

            scored = self._score(candidate)
            if scored.get("hard_fail"):
                rejected.append(
                    {
                        "candidate_id": scored.get("candidate_id"),
                        "source": scored.get("source"),
                        "score": scored["final_score"],
                        "reasons": scored.get("reasons", []),
                    }
                )
                continue

            accepted.append(scored)

        if not accepted:
            rejected.sort(key=lambda item: (-_bounded_float(item.get("score")), SOURCE_PRIORITY.get(str(item.get("source") or ""), 50), str(item.get("source") or "")))
            return {
                "status": "low_confidence",
                "source": "",
                "items": [],
                "confidence": 0.0,
                "evidence": {},
                "rejected_candidates": rejected,
                "reason": "all_candidates_rejected" if rejected else "no_candidates",
            }

        non_fallback = [item for item in accepted if item.get("source") != "segment_fallback"]
        if non_fallback:
            fallback_items = [item for item in accepted if item.get("source") == "segment_fallback"]
            for item in fallback_items:
                reasons = sorted(set(list(item.get("reasons") or []) + ["segment_fallback_last_resort"]))
                rejected.append(
                    {
                        "candidate_id": item.get("candidate_id"),
                        "source": item.get("source"),
                        "score": item["final_score"],
                        "reasons": reasons,
                    }
                )
            accepted = non_fallback

        accepted.sort(
            key=lambda item: (
                -item["final_score"],
                item["priority"],
                -item["source_cap"],
                str(item.get("source") or ""),
            )
        )
        winner = accepted[0]
        rejected.extend(
            {
                "candidate_id": item.get("candidate_id"),
                "source": item.get("source"),
                "score": item["final_score"],
                "reasons": item.get("reasons", []),
            }
            for item in accepted[1:]
        )
        rejected.sort(key=lambda item: (-_bounded_float(item.get("score")), SOURCE_PRIORITY.get(str(item.get("source") or ""), 50), str(item.get("source") or "")))
        return {
            "status": "ok" if winner["final_score"] >= MIN_ACCEPT_SCORE else "low_confidence",
            "source": winner["source"],
            "items": winner["items"],
            "confidence": winner["final_score"],
            "evidence": winner.get("evidence") or {},
            "rejected_candidates": rejected,
        }

    def _score(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        source = str(candidate.get("source") or "")
        evidence = dict(candidate.get("evidence") or {})
        reasons = list(candidate.get("reasons") or [])
        if source == "segment_fallback":
            reasons.append("last_resort_source")

        raw_confidence = _bounded_float(candidate.get("raw_confidence"))
        source_cap = SOURCE_SCORE_CAP.get(source, 0.75)
        evidence_score = _evidence_score(candidate, evidence)
        content_score, content_status, content_reasons = _content_mapping_score(candidate, evidence)
        if content_reasons:
            reasons.extend(content_reasons)

        if evidence.get("page_monotonic") is False:
            reasons.append("page_mapping_non_monotonic")
        if evidence.get("pages_in_range") is False:
            reasons.append("page_mapping_out_of_range")

        if evidence.get("page_monotonic") is False or evidence.get("pages_in_range") is False:
            return {
                **candidate,
                "priority": SOURCE_PRIORITY.get(source, 50),
                "source_cap": source_cap,
                "final_score": 0.0,
                "hard_fail": True,
                "reasons": sorted(set(reasons)),
            }

        if content_status == "failed":
            return {
                **candidate,
                "priority": SOURCE_PRIORITY.get(source, 50),
                "source_cap": source_cap,
                "final_score": 0.0,
                "hard_fail": True,
                "reasons": sorted(set(reasons)),
            }

        final_score = min(raw_confidence, source_cap, evidence_score)
        if content_score is not None:
            final_score = min(final_score, content_score)
        if evidence.get("mapping_pending"):
            pending_cap = (
                CONTENT_MAPPING_PENDING_CAP
                if evidence.get("logical_overflow")
                else CONTENT_MAPPING_PENDING_NON_OVERFLOW_CAP
            )
            final_score = min(final_score, pending_cap)
            reasons.append("mapping_pending")
        if content_status == "ok":
            reasons.append("content_mapping_ok")
        if source_cap < raw_confidence:
            reasons.append("source_tier_cap")
        if evidence.get("evidence_level") == "model_inferred":
            reasons.append("weaker_evidence_level")

        return {
            **candidate,
            "priority": SOURCE_PRIORITY.get(source, 50),
            "source_cap": source_cap,
            "final_score": round(max(0.0, min(1.0, final_score)), 4),
            "hard_fail": False,
            "reasons": sorted(set(reasons)),
        }


def _content_mapping_score(candidate: Dict[str, Any], evidence: Dict[str, Any]) -> tuple[Optional[float], str, List[str]]:
    reasons: List[str] = []
    mapping = evidence.get("content_mapping")
    if not isinstance(mapping, dict):
        mapping = candidate.get("content_mapping") if isinstance(candidate.get("content_mapping"), dict) else None

    if isinstance(mapping, dict):
        status = str(mapping.get("status") or "").strip().lower()
        if status == "failed":
            reasons.append("content_mapping_failed")
            return 0.0, "failed", reasons
        score = _bounded_float(mapping.get("page_mapping_score"))
        title_match = _bounded_float(mapping.get("title_match_rate"))
        if status == "ok":
            return max(score, title_match, 0.5), "ok", reasons
        if status:
            score = max(score, title_match)
            if score:
                return score, status, reasons

    score = _bounded_float(evidence.get("page_mapping_score") or candidate.get("page_mapping_score"))
    if evidence.get("mapping_pending"):
        pending_cap = (
            CONTENT_MAPPING_PENDING_CAP
            if evidence.get("logical_overflow")
            else CONTENT_MAPPING_PENDING_NON_OVERFLOW_CAP
        )
        pending_score = score or pending_cap
        if not evidence.get("logical_overflow"):
            pending_score = max(pending_score, MIN_ACCEPT_SCORE)
        return min(pending_score, pending_cap), "pending", reasons
    if score:
        return score, "unknown", reasons
    return None, "unknown", reasons


def _evidence_score(candidate: Dict[str, Any], evidence: Dict[str, Any]) -> float:
    evidence_level = str(evidence.get("evidence_level") or candidate.get("evidence_level") or "").strip()
    return EVIDENCE_LEVEL_SCORE.get(evidence_level, 0.88)


def _bounded_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))
