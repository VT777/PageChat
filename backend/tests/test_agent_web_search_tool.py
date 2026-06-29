import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService  # noqa: E402
from app.services.citation_binding_service import collect_web_sources  # noqa: E402
from app.services.tool_executor import AGENT_TOOLS  # noqa: E402
from app.services.web_search_tool import execute_web_search_tool  # noqa: E402


def _tool_names(tools: list[dict]) -> set[str]:
    return {tool["function"]["name"] for tool in tools}


def test_web_search_tool_is_not_in_base_document_navigation_tools() -> None:
    assert "web_search" not in _tool_names(AGENT_TOOLS)


def test_runtime_tools_include_web_search_when_enabled() -> None:
    tools = AgentService._tools_for_request(web_search_enabled=True)

    assert "web_search" in _tool_names(tools)


def test_runtime_tools_omit_web_search_when_disabled() -> None:
    tools = AgentService._tools_for_request(web_search_enabled=False)

    assert "web_search" not in _tool_names(tools)


def test_execute_web_search_tool_returns_compact_results() -> None:
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def unified_search(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "success": True,
                "route": "search",
                "query": kwargs["query"],
                "results": [{"title": "A", "url": "https://example.test"}],
            }

    async def run() -> None:
        client = FakeClient()
        result = await execute_web_search_tool(
            arguments={"query": "latest PageChat", "max_results": 3},
            settings={
                "enabled": True,
                "api_key": "as-key",
                "max_results": 5,
                "language": "zh-CN",
                "zone": "cn",
                "content_types": ["web", "news"],
            },
            client=client,
        )

        assert result["success"] is True
        assert result["results"][0]["title"] == "A"
        assert client.calls[0]["query"] == "latest PageChat"
        assert client.calls[0]["api_key"] == "as-key"
        assert client.calls[0]["max_results"] == 3

    asyncio.run(run())


def test_execute_web_search_tool_forwards_unified_router_arguments() -> None:
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def unified_search(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "route": "batch_search", "results": []}

    async def run() -> None:
        client = FakeClient()
        result = await execute_web_search_tool(
            arguments={
                "query": "compare",
                "intent": "compare",
                "queries": ["a latest", "b latest"],
                "urls": ["https://example.test/a"],
                "domain": "news",
                "tag": "finance",
            },
            settings={
                "enabled": True,
                "api_key": "as-key",
                "max_results": 5,
                "language": "zh-CN",
                "zone": "cn",
                "content_types": ["web", "news"],
            },
            client=client,
        )

        assert result["route"] == "batch_search"
        assert client.calls[0]["intent"] == "compare"
        assert client.calls[0]["queries"] == ["a latest", "b latest"]
        assert client.calls[0]["urls"] == ["https://example.test/a"]
        assert client.calls[0]["domain"] == "news"
        assert client.calls[0]["tag"] == "finance"

    asyncio.run(run())


def test_execute_web_search_tool_respects_disabled_settings() -> None:
    class FakeClient:
        async def unified_search(self, **kwargs):
            raise AssertionError("disabled web_search must not call AnySearch")

    async def run() -> None:
        result = await execute_web_search_tool(
            arguments={"query": "latest PageChat"},
            settings={"enabled": False},
            client=FakeClient(),
        )

        assert result["success"] is False
        assert result["error_code"] == "web_search_disabled"

    asyncio.run(run())


def test_collect_web_sources_from_anysearch_results() -> None:
    sources = collect_web_sources(
        [
            {
                "tool_name": "web_search",
                "result": {
                    "results": [
                        {
                            "title": "Beijing weather",
                            "url": "https://weather.example/beijing",
                            "snippet": "Sunny and warm.",
                            "content_preview": "Detailed forecast preview.",
                            "source": "anysearch",
                        }
                    ]
                },
            }
        ]
    )

    assert sources == [
        {
            "type": "web",
            "source_id": "web-1",
            "title": "Beijing weather",
            "display_label": "Beijing weather",
            "url": "https://weather.example/beijing",
            "domain": "weather.example",
            "snippet": "Sunny and warm.",
            "content_preview": "Detailed forecast preview.",
            "provider": "anysearch",
        }
    ]
