import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService
from app.services.tool_executor import AGENT_TOOLS, ToolExecutor


class FakePageIndexService:
    pass


class FakeDocumentService:
    pass


def test_base_agent_tools_do_not_include_web_search_contract() -> None:
    tool_names = {tool["function"]["name"] for tool in AGENT_TOOLS}

    assert "web_search" not in tool_names


def test_web_search_is_injected_when_enabled() -> None:
    tool_names = {
        tool["function"]["name"]
        for tool in AgentService._tools_for_request(web_search_enabled=True)
    }

    assert "web_search" in tool_names


def test_web_search_returns_clear_configuration_error_without_document_fallback() -> None:
    async def run() -> None:
        executor = ToolExecutor(
            FakePageIndexService(),
            FakeDocumentService(),
            user_id="user-a",
        )

        result = await executor.execute(
            "web_search",
            {"query": "\u5317\u4eac\u5929\u6c14"},
        )

        assert result["status"] == "error"
        assert result["tool_name"] == "web_search"
        assert result["results"] == []
        assert "configured" in result["error"].lower()

    asyncio.run(run())
