"""OCR cache helpers keyed by engine profile and recognition options."""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Any, Dict, Optional

from app.services.ocr_engines.contracts import OCRDocumentResult


def build_ocr_cache_key(
    *,
    file_hash: str,
    page_num: int,
    task: str,
    engine_type: str,
    model: str,
    profile_version: str,
    options: Dict[str, Any],
) -> str:
    options_hash = _hash_json(options or {})
    raw = "|".join(
        [
            str(file_hash),
            str(page_num),
            str(task),
            str(engine_type),
            str(model),
            str(profile_version),
            options_hash,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    prefix = "_".join(
        [
            _safe_token(task),
            f"p{int(page_num)}",
            _safe_token(engine_type),
            _safe_token(model),
        ]
    )
    return f"{prefix}_{digest}"


class OCRCacheService:
    def __init__(self, *, max_size: int = 1000) -> None:
        self._raw_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._normalized_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_size = max(1, int(max_size))

    def get_raw_response(self, key: str) -> Optional[Dict[str, Any]]:
        return self._get(self._raw_cache, key)

    def set_raw_response(self, key: str, value: Dict[str, Any]) -> None:
        self._set(self._raw_cache, key, dict(value or {}))

    def get_normalized_result(self, key: str) -> Optional[Dict[str, Any]]:
        return self._get(self._normalized_cache, key)

    def set_normalized_result(self, key: str, value: OCRDocumentResult | Dict[str, Any]) -> None:
        if isinstance(value, OCRDocumentResult):
            payload = value.to_dict()
        else:
            payload = dict(value or {})
        self._set(self._normalized_cache, key, payload)

    def clear(self) -> None:
        self._raw_cache.clear()
        self._normalized_cache.clear()

    def _get(self, cache: OrderedDict[str, Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
        if key not in cache:
            return None
        cache.move_to_end(key)
        return dict(cache[key])

    def _set(self, cache: OrderedDict[str, Dict[str, Any]], key: str, value: Dict[str, Any]) -> None:
        cache[key] = dict(value)
        cache.move_to_end(key)
        while len(cache) > self._max_size:
            cache.popitem(last=False)


def _hash_json(value: Dict[str, Any]) -> str:
    text = json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _safe_token(value: Any) -> str:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    return token.strip("_") or "unknown"


ocr_cache_service = OCRCacheService()

