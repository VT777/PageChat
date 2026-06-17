"""Compatibility shim for legacy TOC quality imports.

The deterministic TOC quality checker now lives in ``index_quality`` and the
runtime router lives in ``router``. Older regression tests still import this
module and expect the historical branch labels.
"""

from __future__ import annotations

from typing import Any, Dict

from pageindex.index_quality import TocQualityChecker, build_index_quality_report


def decide_extraction_path(
    toc_quality: Dict[str, Any],
    official_quality: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return the legacy quality-branch decision for compatibility tests."""
    official_quality = official_quality or {}
    if bool(toc_quality.get("is_valid") or toc_quality.get("skeleton_valid")):
        return {"path": "BRANCH_A", "reason": "toc_quality_accepted"}
    if bool(official_quality.get("is_valid")):
        return {"path": "BRANCH_B", "reason": "official_quality_accepted"}
    return {"path": "REPAIR", "reason": "quality_repair_required"}


__all__ = ["TocQualityChecker", "build_index_quality_report", "decide_extraction_path"]

