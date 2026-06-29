import asyncio
from pathlib import Path
import sys

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.anysearch_client import AnySearchClient  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def test_search_posts_compact_anysearch_payload(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.test",
                        "snippet": "Short",
                        "content": "A" * 2000,
                    }
                ],
                "metadata": {
                    "request_id": "req-1",
                    "search_time_ms": 123,
                    "total_results": 1,
                },
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(
        AnySearchClient().search(
            query="PageChat",
            api_key="as-key",
            max_results=7,
            language="en",
            zone="intl",
            content_types=["web"],
        )
    )

    assert calls[0][0] == "https://api.anysearch.com/v1/search"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer as-key"
    assert calls[0][1]["json"] == {
        "query": "PageChat",
        "max_results": 7,
        "content_types": ["web"],
        "zone": "intl",
        "language": "en",
    }
    assert result["success"] is True
    assert result["metadata"]["request_id"] == "req-1"
    assert len(result["results"][0]["content_preview"]) <= 700
    assert "content" not in result["results"][0]


def test_search_parses_anysearch_data_wrapper(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return FakeResponse(
            200,
            {
                "code": 0,
                "message": "success",
                "data": {
                    "results": [
                        {
                            "title": "北京天气",
                            "url": "https://example.test/weather",
                            "snippet": "北京今日天气。",
                            "content": "北京今日天气晴。",
                        }
                    ],
                    "total_results": 1,
                    "request_id": "req-data",
                    "search_time_ms": 88,
                },
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(AnySearchClient().search(query="北京天气", api_key="as-key"))

    assert result["success"] is True
    assert result["results"] == [
        {
            "title": "北京天气",
            "url": "https://example.test/weather",
            "snippet": "北京今日天气。",
            "content_preview": "北京今日天气晴。",
            "source": "anysearch",
        }
    ]
    assert result["metadata"] == {
        "request_id": "req-data",
        "search_time_ms": 88,
        "total_results": 1,
    }


def test_anonymous_request_omits_authorization_header(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(200, {"results": [], "metadata": {}})

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(AnySearchClient().search(query="PageChat", api_key=None))

    assert result["success"] is True
    assert "Authorization" not in calls[0]["headers"]


def test_search_normalizes_rate_limit_error(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return FakeResponse(
            429,
            {
                "symbol": "rate_limit_exceeded",
                "message": "Too many requests",
                "request_id": "req-rate",
                "data": {"retry_after": 30},
            },
            headers={"Retry-After": "30", "X-RateLimit-Remaining": "0"},
        )

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(AnySearchClient().search(query="PageChat"))

    assert result == {
        "success": False,
        "query": "PageChat",
        "status_code": 429,
        "error_code": "rate_limit_exceeded",
        "message": "Too many requests",
        "request_id": "req-rate",
        "retry_after": "30",
    }


def test_search_normalizes_auth_and_quota_errors(monkeypatch) -> None:
    responses = [
        FakeResponse(401, {"symbol": "invalid_api_key", "request_id": "req-401"}),
        FakeResponse(402, {"symbol": "quota_exhausted", "request_id": "req-402"}),
        FakeResponse(403, {"symbol": "expired_api_key", "request_id": "req-403"}),
        FakeResponse(500, {"symbol": "internal_error", "request_id": "req-500"}),
    ]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("requests.post", fake_post)

    results = [
        asyncio.run(AnySearchClient().search(query="PageChat")) for _ in range(4)
    ]

    assert [item["success"] for item in results] == [False, False, False, False]
    assert [item["error_code"] for item in results] == [
        "invalid_api_key",
        "quota_exhausted",
        "expired_api_key",
        "internal_error",
    ]


def test_search_timeout_returns_safe_error(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(AnySearchClient().search(query="PageChat"))

    assert result["success"] is False
    assert result["error_code"] == "timeout"
    assert "timed out" in result["message"]


def test_search_rejects_invalid_request_arguments() -> None:
    client = AnySearchClient()

    async def run() -> None:
        invalid_cases = [
            {"query": ""},
            {"query": "PageChat", "max_results": 0},
            {"query": "PageChat", "max_results": 11},
            {"query": "PageChat", "zone": "moon"},
            {"query": "PageChat", "content_types": ["video"]},
        ]
        for payload in invalid_cases:
            try:
                await client.search(**payload)
                assert False, f"Expected invalid payload to fail: {payload}"
            except ValueError:
                pass

    asyncio.run(run())


def test_unified_search_extracts_urls_through_mcp(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": kwargs["json"]["id"],
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"url":"https://example.test/page","title":"Example","content":"Full markdown content"}',
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(
        AnySearchClient().unified_search(
            query="read page",
            urls=["https://example.test/page"],
            api_key="as-key",
        )
    )

    assert calls[0][0] == "https://api.anysearch.com/mcp"
    assert calls[0][1]["json"]["method"] == "tools/call"
    assert calls[0][1]["json"]["params"]["name"] == "extract"
    assert calls[0][1]["json"]["params"]["arguments"] == {"url": "https://example.test/page"}
    assert result["success"] is True
    assert result["route"] == "extract"
    assert result["results"][0]["url"] == "https://example.test/page"
    assert result["results"][0]["content_preview"] == "Full markdown content"


def test_unified_search_routes_multi_query_to_batch_search(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"results":[{"title":"A","url":"https://a.test","snippet":"Alpha"},{"title":"B","url":"https://b.test","snippet":"Beta"}]}',
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    result = asyncio.run(
        AnySearchClient().unified_search(
            query="compare",
            queries=["alpha latest", "beta latest"],
            api_key="as-key",
        )
    )

    assert calls[0][0] == "https://api.anysearch.com/mcp"
    assert calls[0][1]["json"]["params"]["name"] == "batch_search"
    assert calls[0][1]["json"]["params"]["arguments"]["queries"] == [
        "alpha latest",
        "beta latest",
    ]
    assert result["success"] is True
    assert result["route"] == "batch_search"
    assert [item["title"] for item in result["results"]] == ["A", "B"]
