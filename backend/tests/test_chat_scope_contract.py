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
        web_search_requested=True,
        web_search_enabled=True,
    )

    assert request.folder_id == "folder-a"
    assert request.include_subfolders is True
    assert request.strict_scope is False
    assert request.web_search_requested is True
    assert request.web_search_enabled is True


def test_chat_request_accepts_structured_web_search_flag() -> None:
    request = ChatRequest(question="search latest policy", web_search=True)
    assert request.web_search is True


def test_chat_request_defaults_web_search_to_false() -> None:
    request = ChatRequest(question="ordinary document question")
    assert request.web_search is False


def test_chat_request_accepts_attachment_ids() -> None:
    request = ChatRequest(question="look at this screenshot", attachment_ids=["att-a"])
    assert request.attachment_ids == ["att-a"]


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


def test_agent_does_not_inject_folder_filter_when_scope_is_non_strict() -> None:
    patched = AgentService._inject_default_doc_id(
        "browse_documents",
        {"query": "alpha"},
        document_ids=["doc-a", "doc-b"],
        preferred_document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=False,
    )

    assert "document_ids" not in patched
    assert "folder_id" not in patched
    assert "recursive" not in patched


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


class FakeChatFolderService:
    async def get_folder(self, folder_id, user_id=None):
        if folder_id == "folder-a":
            return SimpleNamespace(id="folder-a")
        return None


class CapturingAgent:
    def __init__(self):
        self.calls = []

    async def run_agent_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield 'event: answer_delta\ndata: {"content":"ok"}\n\n'


class CapturingAttachmentService:
    def __init__(self):
        self.model_calls = []
        self.bind_calls = []
        self.metadata = [
            {
                "attachment_id": "att-a",
                "original_name": "screen.png",
                "mime_type": "image/png",
                "size_bytes": 70,
                "width": 1,
                "height": 1,
            }
        ]
        self.model_payload = [
            {
                "attachment_id": "att-a",
                "original_name": "screen.png",
                "mime_type": "image/png",
                "data_base64": "AAAA",
                "width": 1,
                "height": 1,
            }
        ]

    async def attachments_for_model(self, user_id, attachment_ids):
        self.model_calls.append(
            {"user_id": user_id, "attachment_ids": list(attachment_ids or [])}
        )
        return self.model_payload

    async def bind_to_message(
        self, user_id, attachment_ids, conversation_id, message_id
    ):
        self.bind_calls.append(
            {
                "user_id": user_id,
                "attachment_ids": list(attachment_ids or []),
                "conversation_id": conversation_id,
                "message_id": message_id,
            }
        )
        return self.metadata


class FakeRunRepository:
    def __init__(self):
        self.events = []

    async def create_run(self, **kwargs):
        return None

    async def append_run_event(self, run_id, event_type, payload):
        self.events.append((run_id, event_type, payload))
        return len(self.events)

    async def complete_run(self, *args, **kwargs):
        return None

    async def fail_run(self, *args, **kwargs):
        return None

    async def cancel_run(self, *args, **kwargs):
        return None


def _chat_service_with_agent(agent: CapturingAgent) -> ChatService:
    service = ChatService.__new__(ChatService)
    service.db = None
    service.document_service = FakeChatDocumentService()
    service.folder_service = FakeChatFolderService()
    service.run_repository = FakeRunRepository()
    service._get_agent_service = lambda: agent

    async def ensure_conversation(conversation_id, user_id=None):
        return conversation_id or "conv-1"

    async def save_message(*args, **kwargs):
        role = args[1] if len(args) > 1 else kwargs.get("role", "message")
        return f"{role}-message-1"

    async def update_message(*args, **kwargs):
        return None

    async def get_history_messages(*args, **kwargs):
        return []

    service.ensure_conversation = ensure_conversation
    service.save_message = save_message
    service.update_message = update_message
    service.get_history_messages = get_history_messages
    return service


def _chat_service_with_agent_and_attachments(
    agent: CapturingAgent, attachment_service: CapturingAttachmentService
) -> ChatService:
    service = _chat_service_with_agent(agent)
    saved_messages = []

    async def save_message(
        conversation_id,
        role,
        content,
        thinking_content="",
        agent_steps="[]",
        status="completed",
        attachments=None,
        run_id=None,
    ):
        message_id = f"{role}-message-{len(saved_messages) + 1}"
        saved_messages.append(
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "attachments": attachments or [],
                "run_id": run_id,
            }
        )
        return message_id

    service.save_message = save_message
    service.saved_messages = saved_messages
    service._get_attachment_service = lambda: attachment_service
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


def test_chat_service_does_not_inject_user_library_without_explicit_scope() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(question="hello", user_id="user-a")
        ]

        assert events
        assert agent.calls[0]["document_ids"] is None
        assert agent.calls[0]["preferred_document_ids"] is None
        assert agent.calls[0]["strict_scope"] is None

    asyncio.run(run())


def test_chat_service_empty_document_scope_does_not_expand_to_user_library() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="hello",
                document_ids=[],
                strict_scope=False,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] is None
        assert agent.calls[0]["preferred_document_ids"] is None
        assert agent.calls[0]["suppress_user_library_fallback"] is True

    asyncio.run(run())


def test_chat_service_invalid_document_scope_does_not_expand_to_user_library() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="summarize selected document",
                document_ids=["missing-doc"],
                strict_scope=False,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] is None
        assert agent.calls[0]["preferred_document_ids"] == []
        assert agent.calls[0]["suppress_user_library_fallback"] is True

    asyncio.run(run())


def test_chat_service_invalid_folder_scope_does_not_expand_to_user_library() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="summarize selected folder",
                folder_id="missing-folder",
                strict_scope=False,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] is None
        assert agent.calls[0]["folder_id"] is None
        assert agent.calls[0]["suppress_user_library_fallback"] is True

    asyncio.run(run())


def test_chat_service_empty_semantic_folder_scope_is_not_selected_scope() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="hello",
                folder_id="root",
                include_subfolders=True,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["folder_id"] is None
        assert agent.calls[0]["suppress_user_library_fallback"] is False

    asyncio.run(run())


def test_chat_service_passes_web_search_flags_to_agent() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="web search Beijing weather",
                web_search_requested=True,
                web_search_enabled=True,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["web_search_requested"] is True
        assert agent.calls[0]["web_search_enabled"] is True
        assert agent.calls[0]["document_ids"] is None

    asyncio.run(run())


def test_chat_service_legacy_web_search_flag_maps_to_requested_flag() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        service = _chat_service_with_agent(agent)

        events = [
            event
            async for event in service.stream_chat(
                question="search latest material",
                document_ids=["doc-a"],
                strict_scope=True,
                web_search=True,
                user_id="user-a",
            )
        ]

        assert events
        assert agent.calls[0]["document_ids"] == ["doc-a"]
        assert agent.calls[0]["web_search_requested"] is True

    asyncio.run(run())


def test_chat_service_binds_attachments_to_user_message() -> None:
    async def run() -> None:
        agent = CapturingAgent()
        attachment_service = CapturingAttachmentService()
        service = _chat_service_with_agent_and_attachments(agent, attachment_service)

        events = [
            event
            async for event in service.stream_chat(
                question="look at this screenshot",
                attachment_ids=["att-a"],
                user_id="user-a",
            )
        ]

        assert events
        assert attachment_service.model_calls == [
            {"user_id": "user-a", "attachment_ids": ["att-a"]}
        ]
        assert attachment_service.bind_calls == [
            {
                "user_id": "user-a",
                "attachment_ids": ["att-a"],
                "conversation_id": "conv-1",
                "message_id": "user-message-1",
            }
        ]
        assert service.saved_messages[0]["attachments"][0]["attachment_id"] == "att-a"
        assert agent.calls[0]["request_attachments"] == attachment_service.model_payload

    asyncio.run(run())


def test_tool_catalog_response_includes_web_search_when_requested() -> None:
    async def run() -> None:
        service = _chat_service_with_agent(CapturingAgent())

        events = [
            event
            async for event in service.stream_chat(
                question="what tools are available",
                web_search=True,
                user_id="user-a",
            )
        ]

        assert "web_search" in "".join(events)

    asyncio.run(run())
