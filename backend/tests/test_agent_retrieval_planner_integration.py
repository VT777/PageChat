import asyncio
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {"status": "success", "data": {"tool": tool_name, "args": arguments}}


class FakeDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-a"), SimpleNamespace(id="doc-b")]


class FakePageIndexService:
    pass


class FakeChatChunk:
    def __init__(self, content: str):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]


class FakeChatStream:
    def __init__(self, content: str = "answer"):
        self.content = content

    def __aiter__(self):
        self._sent = False
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return FakeChatChunk(self.content)


def _agent_with_fake_services() -> AgentService:
    agent = AgentService.__new__(AgentService)
    agent.db = None
    agent.pageindex_service = FakePageIndexService()
    agent.document_service = FakeDocumentService()
    return agent


def test_agent_executes_retrieval_planner_first_step_for_selected_document() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="summarize renewal risk",
            tool_executor=executor,
            preferred_document_ids=["doc-a"],
            folder_id=None,
            include_subfolders=False,
            strict_scope=None,
        )

        assert executor.calls == [
            ("get_document_structure", {"doc_id": "doc-a", "compact": True})
        ]
        assert evidence[0]["tool_name"] == "get_document_structure"
        assert evidence[0]["result"]["status"] == "success"

    asyncio.run(run())


def test_agent_executes_keyword_locator_first_for_selected_document_locating_query() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="在哪一页提到了华东收入增长？",
            tool_executor=executor,
            preferred_document_ids=["doc-a"],
            folder_id=None,
            include_subfolders=False,
            strict_scope=True,
        )

        assert executor.calls == [
            (
                "search_within_document",
                {"doc_id": "doc-a", "query": "在哪一页提到了华东收入增长？"},
            )
        ]
        assert evidence[0]["tool_name"] == "search_within_document"

    asyncio.run(run())


def test_agent_executes_retrieval_planner_first_step_for_folder_scope() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="find renewal risk",
            tool_executor=executor,
            preferred_document_ids=None,
            folder_id="folder-a",
            include_subfolders=True,
            strict_scope=True,
        )

        assert executor.calls == [
            (
                "browse_documents",
                {
                    "query": "find renewal risk",
                    "folder_id": "folder-a",
                    "recursive": True,
                    "sort": "relevance",
                },
            )
        ]
        assert evidence[0]["tool_name"] == "browse_documents"

    asyncio.run(run())


def test_folder_only_chat_uses_retrieval_planner_instead_of_simple_chat(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            calls.append(kwargs)
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeChatStream("folder answer")

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="summarize this folder",
                folder_id="folder-a",
                include_subfolders=True,
                strict_scope=True,
                user_id="user-a",
            )
        ]

        assert calls
        assert calls[0]["folder_id"] == "folder-a"
        assert any("folder answer" in event for event in events)

    asyncio.run(run())


def test_strict_scope_false_uses_user_library_executor_boundary(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        executor_inits = []

        class CapturingToolExecutor(FakeToolExecutor):
            def __init__(self, pageindex_service, document_service, user_id=None, allowed_doc_ids=None):
                super().__init__()
                executor_inits.append(
                    {"user_id": user_id, "allowed_doc_ids": allowed_doc_ids}
                )

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeChatStream("expanded answer")

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", CapturingToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="find related risk",
                document_ids=["doc-a"],
                strict_scope=False,
                user_id="user-a",
            )
        ]

        assert executor_inits == [{"user_id": "user-a", "allowed_doc_ids": None}]
        assert any("expanded answer" in event for event in events)

    asyncio.run(run())


def test_planner_evidence_history_does_not_add_orphan_tool_message(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        seen_messages = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return [
                {
                    "tool_name": "browse_documents",
                    "arguments": {"query": "alpha"},
                    "result": {"status": "success", "data": {"documents": []}},
                    "retrieval_plan_route": "user_library",
                }
            ]

        async def fake_chat_by_scenario(**kwargs):
            seen_messages.append(kwargs["messages"])
            return FakeChatStream("answer")

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="find alpha",
                document_ids=["doc-a"],
                user_id="user-a",
            )
        ]

        assert seen_messages
        assert not any(message.get("role") == "tool" for message in seen_messages[0])
        assert any(
            message.get("role") == "assistant"
            and "Initial retrieval evidence" in str(message.get("content"))
            for message in seen_messages[0]
        )
        assert any("answer" in event for event in events)

    asyncio.run(run())
