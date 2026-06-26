from __future__ import annotations

import asyncio
from typing import Any

import requests


ANYSEARCH_SEARCH_URL = "https://api.anysearch.com/v1/search"
MAX_PAGECHAT_WEB_RESULTS = 10
MAX_CONTENT_PREVIEW_CHARS = 700
MAX_SNIPPET_CHARS = 400
VALID_ZONES = {"cn", "intl"}
VALID_CONTENT_TYPES = {"web", "news"}


class AnySearchClient:
    """Small REST wrapper for AnySearch's unified search endpoint."""

    def __init__(
        self,
        search_url: str = ANYSEARCH_SEARCH_URL,
        timeout_seconds: float = 15,
    ):
        self.search_url = search_url
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        *,
        query: str,
        api_key: str | None = None,
        max_results: int = 5,
        language: str = "zh-CN",
        zone: str = "cn",
        content_types: list[str] | None = None,
        domain: str | None = None,
        tag: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._build_payload(
            query=query,
            max_results=max_results,
            language=language,
            zone=zone,
            content_types=content_types,
            domain=domain,
            tag=tag,
            params=params,
        )
        headers = {"Content-Type": "application/json"}
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        try:
            response = await asyncio.to_thread(
                requests.post,
                self.search_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            return self._error_result(
                query=payload["query"],
                status_code=None,
                error_code="timeout",
                message=str(exc),
            )
        except requests.exceptions.RequestException as exc:
            return self._error_result(
                query=payload["query"],
                status_code=None,
                error_code="request_failed",
                message=str(exc),
            )

        body = self._safe_json(response)
        if response.status_code >= 400:
            return self._error_result(
                query=payload["query"],
                status_code=response.status_code,
                error_code=str(
                    body.get("symbol")
                    or body.get("error_code")
                    or body.get("code")
                    or f"http_{response.status_code}"
                ),
                message=str(
                    body.get("message")
                    or body.get("detail")
                    or body.get("error")
                    or response.text
                ),
                request_id=body.get("request_id")
                or (body.get("metadata") or {}).get("request_id"),
                retry_after=response.headers.get("Retry-After")
                or (body.get("data") or {}).get("retry_after"),
            )

        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        data_metadata = (
            data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        )
        raw_results = body.get("results")
        if raw_results is None:
            raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raw_results = []
        return {
            "success": True,
            "query": payload["query"],
            "results": [
                self._compact_result(item)
                for item in raw_results
                if isinstance(item, dict)
            ],
            "metadata": {
                "request_id": (
                    metadata.get("request_id")
                    or data_metadata.get("request_id")
                    or data.get("request_id")
                    or body.get("request_id")
                ),
                "search_time_ms": metadata.get("search_time_ms")
                or data_metadata.get("search_time_ms")
                or data.get("search_time_ms")
                or body.get("search_time_ms"),
                "total_results": metadata.get("total_results")
                or data_metadata.get("total_results")
                or data.get("total_results")
                or body.get("total_results"),
            },
        }

    @classmethod
    def _build_payload(
        cls,
        *,
        query: str,
        max_results: int,
        language: str,
        zone: str,
        content_types: list[str] | None,
        domain: str | None,
        tag: str | None,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            raise ValueError("query is required")
        if max_results < 1 or max_results > MAX_PAGECHAT_WEB_RESULTS:
            raise ValueError("max_results must be between 1 and 10")
        if zone not in VALID_ZONES:
            raise ValueError(f"Unsupported AnySearch zone: {zone}")

        safe_content_types = content_types or ["web", "news"]
        if (
            not isinstance(safe_content_types, list)
            or not safe_content_types
            or any(item not in VALID_CONTENT_TYPES for item in safe_content_types)
        ):
            raise ValueError("content_types must be a non-empty subset of web/news")

        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "content_types": safe_content_types,
            "zone": zone,
            "language": language or "zh-CN",
        }
        if domain:
            payload["domain"] = domain
        if tag:
            payload["tag"] = tag
        if params:
            payload["params"] = params
        return payload

    @staticmethod
    def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": AnySearchClient._truncate(str(item.get("title") or ""), 240),
            "url": str(item.get("url") or ""),
            "snippet": AnySearchClient._truncate(
                str(item.get("snippet") or ""), MAX_SNIPPET_CHARS
            ),
            "content_preview": AnySearchClient._truncate(
                str(item.get("content") or ""), MAX_CONTENT_PREVIEW_CHARS
            ),
            "source": "anysearch",
        }

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: max(limit - 1, 0)].rstrip() + "…"

    @staticmethod
    def _safe_json(response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _error_result(
        *,
        query: str,
        status_code: int | None,
        error_code: str,
        message: str,
        request_id: str | None = None,
        retry_after: str | int | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "query": query,
            "status_code": status_code,
            "error_code": error_code,
            "message": message,
            "request_id": request_id,
        }
        if retry_after is not None:
            result["retry_after"] = str(retry_after)
        return result
