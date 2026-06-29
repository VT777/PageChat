"""Wrapper for the official/native-text PageIndex chain."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class OfficialBaselineRunner:
    """Adapt native-text PageIndex results into the candidate contract."""

    def run_result(self, result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not result:
            return None
        items = result.get("toc_items") or result.get("structure") or []
        if not isinstance(items, list) or not items:
            return None
        return {
            "candidate_id": "official_baseline",
            "source": "official_baseline",
            "cost_level": "medium",
            "items": items,
            "raw_confidence": float(result.get("confidence") or 0.75),
            "evidence": {
                "native_text": True,
                "page_count": result.get("page_count"),
            },
        }

    def run_page_list(self, page_list: List[Any], result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        candidate = self.run_result(result)
        if candidate:
            candidate["evidence"]["page_list_count"] = len(page_list or [])
        return candidate
