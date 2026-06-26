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

    async def list_documents(
        self,
        page=1,
        page_size=500,
        folder_id=None,
        include_subfolders=False,
        user_id=None,
    ):
        assert folder_id == "folder-a"
        docs = [
            SimpleNamespace(id="doc-folder-a"),
            SimpleNamespace(id="doc-folder-b"),
        ]
        start = (page - 1) * page_size
        end = start + page_size
        return docs[start:end], len(docs)


class FakeFolderService:
    async def get_folder(self, folder_id, user_id=None):
        if folder_id == "folder-a":
            return SimpleNamespace(id="folder-a")
        return None


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
    agent.folder_service = FakeFolderService()
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


def test_agent_skips_initial_retrieval_for_general_greeting() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="\u4f60\u597d",
            tool_executor=executor,
            preferred_document_ids=None,
            folder_id=None,
            include_subfolders=False,
            strict_scope=None,
        )

        assert evidence == []
        assert executor.calls == []

    asyncio.run(run())


def test_agent_initial_retrieval_prefers_explicit_web_search() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="\u7f51\u9875\u641c\u7d22\u5317\u4eac\u5929\u6c14",
            tool_executor=executor,
            preferred_document_ids=None,
            folder_id=None,
            include_subfolders=False,
            strict_scope=None,
            web_search_requested=True,
            web_search_enabled=True,
        )

        assert executor.calls == [
            (
                "web_search",
                {"query": "\u7f51\u9875\u641c\u7d22\u5317\u4eac\u5929\u6c14"},
            )
        ]
        assert evidence[0]["tool_name"] == "web_search"
        assert evidence[0]["retrieval_plan_route"] == "web_search"

    asyncio.run(run())


def test_agent_initial_retrieval_ignores_empty_semantic_folder_scope() -> None:
    async def run() -> None:
        executor = FakeToolExecutor()

        evidence = await AgentService._execute_initial_retrieval_plan(
            question="\u4f60\u597d",
            tool_executor=executor,
            preferred_document_ids=None,
            folder_id="root",
            include_subfolders=True,
            strict_scope=None,
        )

        assert evidence == []
        assert executor.calls == []

    asyncio.run(run())


def test_agent_general_greeting_uses_simple_chat_without_tools(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_async_chat_completion(**kwargs):
            calls.append(kwargs)
            return FakeChatStream("hello")

        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_async_chat_completion)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="\u4f60\u597d",
                user_id="user-a",
            )
        ]

        assert any("hello" in event for event in events)
        assert calls
        assert all(not call.get("tools") for call in calls)

    asyncio.run(run())


def test_agent_empty_document_scope_greeting_uses_simple_chat_without_tools(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_async_chat_completion(**kwargs):
            calls.append(kwargs)
            return FakeChatStream("hello")

        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_async_chat_completion)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="\u4f60\u597d",
                document_ids=[],
                suppress_user_library_fallback=True,
                user_id="user-a",
            )
        ]

        assert any("hello" in event for event in events)
        assert calls
        assert all(not call.get("tools") for call in calls)

    asyncio.run(run())


def test_agent_invalid_document_scope_greeting_uses_simple_chat_without_tools(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_async_chat_completion(**kwargs):
            calls.append(kwargs)
            return FakeChatStream("hello")

        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_async_chat_completion)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="\u4f60\u597d",
                document_ids=["missing-doc"],
                user_id="user-a",
            )
        ]

        assert any("hello" in event for event in events)
        assert calls
        assert all(not call.get("tools") for call in calls)

    asyncio.run(run())


def test_agent_invalid_folder_scope_greeting_uses_simple_chat_without_tools(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_async_chat_completion(**kwargs):
            calls.append(kwargs)
            return FakeChatStream("hello")

        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_async_chat_completion)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="\u4f60\u597d",
                folder_id="missing-folder",
                user_id="user-a",
            )
        ]

        assert any("hello" in event for event in events)
        assert calls
        assert all(not call.get("tools") for call in calls)

    asyncio.run(run())


def test_agent_hides_web_search_tool_when_not_requested(monkeypatch) -> None:
    async def run() -> None:
        agent = _agent_with_fake_services()
        calls = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            calls.append(kwargs)
            return FakeChatStream("document answer")

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="summarize uploaded document",
                document_ids=["doc-a"],
                user_id="user-a",
            )
        ]

        assert any("document answer" in event for event in events)
        tool_names = {
            tool["function"]["name"]
            for tool in calls[0]["tools"]
        }
        assert "browse_documents" in tool_names
        assert "web_search" not in tool_names

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


def test_strict_folder_scope_uses_folder_documents_as_executor_boundary(monkeypatch) -> None:
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
            return FakeChatStream("folder answer")

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
                question="summarize this folder",
                folder_id="folder-a",
                include_subfolders=True,
                strict_scope=True,
                user_id="user-a",
            )
        ]

        assert executor_inits == [
            {
                "user_id": "user-a",
                "allowed_doc_ids": ["doc-folder-a", "doc-folder-b"],
            }
        ]
        assert any("folder answer" in event for event in events)

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
