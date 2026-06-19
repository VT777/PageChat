"""Verified low-cost TOC path for PDF outline/bookmark/link metadata."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pageindex.code_toc_quality import evaluate_code_toc


class CodeTOCFastPath:
    """Build a deterministic TOC candidate from pre-extracted code_toc data."""

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        code_toc = analysis.get("code_toc") or {}
        source = str(code_toc.get("source") or "").strip()
        evidence = evaluate_code_toc(analysis)
        items = list(evidence.pop("items", []) or [])
        reasons = list(evidence.get("reasons") or [])
        early_return = bool(evidence.get("accepted"))
        if not items or not source:
            return None

        return {
            "candidate_id": f"code_toc_{source}",
            "source": "code_toc",
            "code_toc_source": source,
            "cost_level": "low",
            "items": items,
            "raw_confidence": 0.92 if early_return else 0.62,
            "score": 0.92 if early_return else 0.62,
            "early_return_allowed": early_return,
            "evidence": {
                **evidence,
                "early_return_allowed": early_return,
                "code_toc_source": source,
            },
            "reasons": reasons,
        }
