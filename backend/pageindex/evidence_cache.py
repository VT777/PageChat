"""Cache key and record helpers for OCR/layout evidence."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, Optional


def build_cache_key(
    *,
    doc_id: str,
    file_sha256: str,
    page: int,
    render_dpi: int,
    provider: str,
    prompt_version: str,
    model_version: str,
) -> str:
    """Build a stable, inspectable cache key for page evidence."""
    prefix = "_".join(
        [
            _safe_token(doc_id),
            f"p{int(page)}",
            f"dpi{int(render_dpi)}",
            _safe_token(provider),
        ]
    )
    raw = "|".join(
        [
            str(doc_id),
            str(file_sha256),
            str(page),
            str(render_dpi),
            str(provider),
            str(prompt_version),
            str(model_version),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def make_cache_record(
    *,
    cache_type: str,
    key: str,
    payload: Dict[str, Any],
    confidence: float,
    fallback_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured cache record without deciding persistence."""
    return {
        "cache_type": str(cache_type),
        "key": str(key),
        "payload": dict(payload or {}),
        "confidence": float(confidence or 0.0),
        "fallback_reason": fallback_reason,
        "is_fallback": bool(fallback_reason),
        "created_at": time.time(),
    }


def _safe_token(value: Any) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    return token.strip("_") or "unknown"
