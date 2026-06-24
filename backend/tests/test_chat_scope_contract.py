from pathlib import Path
import sys
from types import SimpleNamespace
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import ChatRequest
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService


def test_chat_request_accepts_folder_scope_fields() -> None:
    request = ChatRequest(
        question="Summarize this folder",
        document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=False,
    )

    assert request.folder_id == "folder-a"
    assert request.include_subfolders is True
    assert request.strict_scope is False


def test_agent_injects_folder_scope_into_browse_documents() -> None:
    patched = AgentService._inject_default_doc_id(
        "browse_documents",
        {"query": "alpha"},
        document_ids=["doc-a", "doc-b"],
        preferred_document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=True,
    )

    assert patched["document_ids"] == ["doc-a"]
    assert patched["folder_id"] == "folder-a"
    assert patched["recursive"] is True


def test_agent_injects_selected_doc_into_document_navigation_tools() -> None:
    for tool_name, args in [
        ("get_document_structure", {}),
        ("get_page_content", {"pages": "2"}),
        ("get_page_image", {"page": 2}),
        ("search_within_document", {"query": "alpha"}),
    ]:
        patched = AgentService._inject_default_doc_id(
            tool_name,
            args,
            document_ids=["doc-a"],
            preferred_document_ids=None,
        )

        assert patched["doc_id"] == "doc-a"


def test_agent_scope_cache_key_differs_by_folder_scope() -> None:
    doc_scope = AgentService._conversation_state_key(
        "conv-1", user_id="user-a", document_ids=["doc-a"]
    )
    folder_scope = AgentService._conversation_state_key(
        "conv-1",
        user_id="user-a",
        document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=True,
    )

    assert doc_scope != folder_scope


class FakeChatDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-a"), SimpleNamespace(id="doc-b")]


class CapturingAgent:
    def __init__(self):
        self.calls = []

    async def run_agent_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield "event: content\ndata: {\"content\":\"ok\"}\n\n"
        yield "event: done\ndata: {}\n\n"


def _chat_service_with_agent(agent: CapturingAgent) -> ChatService:
    service = ChatService.__new__(ChatService)
    service.db = None
    service.document_service = FakeChatDocumentService()
    service._get_agent_service = lambda: agent

    async def ensure_conversation(conversation_id, user_id=None):
        return conversation_id or "conv-1"

    async def save_message(*args, **kwargs):
        return "message-1"

    async def update_message(*args, **kwargs):
        return None

    async def get_history_messages(*args, **kwargs):
        return []

    service.ensure_conversation = ensure_conversation
    service.save_message = save_message
    service.update_message = update_message
    service.get_history_messages = get_history_messages
    return service


def test_chat_service_keeps_selected_documents_as_strict_agent_scope() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="summarize selected doc",
                document_ids=["doc-a"],
                strict_scope=True,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] == ["doc-a"]
        assert agent.calls[0]["preferred_document_ids"] == ["doc-a"]

    asyncio.run(run())


def test_chat_service_expands_to_user_library_only_when_strict_scope_false() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="find related docs",
                document_ids=["doc-a"],
                strict_scope=False,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] == ["doc-a", "doc-b"]
        assert agent.calls[0]["preferred_document_ids"] == ["doc-a"]

    asyncio.run(run())
