import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.agent_service as agent_service_module
from app.services.agent_service import AgentService


def test_sanitize_tool_result_removes_nested_base64_fields() -> None:
    raw = {
        "status": "success",
        "data": {
            "doc_id": "x",
            "image_base64": "AAAA",
            "nested": {"page_image_base64": "BBBB", "keep": 1},
        },
        "page_image_base64": "CCCC",
        "ok": True,
    }

    cleaned = AgentService._sanitize_tool_result_for_history(raw)
    assert "page_image_base64" not in cleaned
    assert "image_base64" not in cleaned["data"]
    assert "page_image_base64" not in cleaned["data"]["nested"]
    assert cleaned["data"]["nested"]["keep"] == 1
    assert cleaned["ok"] is True


def test_sanitize_tool_result_omits_top_level_image_payload() -> None:
    raw = {
        "success": True,
        "type": "image",
        "mimeType": "image/jpeg",
        "data": "AAAA",
        "image_path": "report.pdf/img-1.jpeg",
    }

    history = AgentService._sanitize_tool_result_for_history(raw)
    client = AgentService._sanitize_tool_result_for_client(raw)

    assert history["data"] == "[omitted-base64-image]"
    assert client["data"] == "[omitted-base64-image]"
    assert history["mimeType"] == "image/jpeg"
    assert client["image_path"] == "report.pdf/img-1.jpeg"


def test_sanitize_tool_result_omits_anysearch_raw_content() -> None:
    raw = {
        "success": True,
        "query": "PageChat",
        "results": [
            {
                "title": "Result",
                "url": "https://example.test",
                "snippet": "Short",
                "content": "A" * 5000,
                "content_preview": "A" * 700,
                "source": "anysearch",
            }
        ],
    }

    history = AgentService._sanitize_tool_result_for_history(raw)
    client = AgentService._sanitize_tool_result_for_client(raw)

    assert "content" not in history["results"][0]
    assert "content" not in client["results"][0]
    assert history["results"][0]["content_preview"] == "A" * 700
    assert "A" * 701 not in str(history)
    assert "A" * 701 not in str(client)


def test_vision_message_supports_embedded_and_full_page_image_shapes() -> None:
    embedded = AgentService._vision_message_for_tool_result(
        "get_document_image",
        {
            "type": "image",
            "mimeType": "image/png",
            "data": "AAAA",
            "doc_name": "report.pdf",
            "image_path": "report.pdf/img-1.png",
            "page": 2,
        },
    )
    page = AgentService._vision_message_for_tool_result(
        "get_page_image",
        {
            "status": "success",
            "data": {
                "mimeType": "image/jpeg",
                "image_base64": "BBBB",
                "doc_name": "report.pdf",
                "page_num": 3,
            },
        },
    )

    assert embedded is not None
    assert embedded["content"][0]["image_url"]["url"] == "data:image/png;base64,AAAA"
    assert "report.pdf/img-1.png" in embedded["content"][1]["text"]
    assert page is not None
    assert page["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,BBBB"
    assert "第3页" in page["content"][1]["text"]


class FakeDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-a")]


class FakePageIndexService:
    pass


class FakeToolExecutor:
    def __init__(self, pageindex_service, document_service, user_id=None, allowed_doc_ids=None):
        pass

    async def execute(self, tool_name: str, arguments: dict):
        assert tool_name == "get_document_image"
        return {
            "success": True,
            "type": "image",
            "mimeType": "image/jpeg",
            "data": "AAAA",
            "doc_name": "report.pdf",
            "image_path": arguments["image_path"],
            "page": 1,
        }


class FakeToolCallChunk:
    choices = [
        SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                reasoning_content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call-1",
                        function=SimpleNamespace(
                            name="get_document_image",
                            arguments='{"image_path":"report.pdf/img-1.jpeg"}',
                        ),
                    )
                ],
            )
        )
    ]


class FakeContentChunk:
    choices = [
        SimpleNamespace(
            delta=SimpleNamespace(
                content="answer",
                reasoning_content=None,
                tool_calls=None,
            )
        )
    ]


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)


def test_stream_sanitizes_image_tool_events_but_keeps_model_vision_payload(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_messages = []
        call_count = 0

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            nonlocal call_count
            call_count += 1
            seen_messages.append(kwargs["messages"])
            if call_count == 1:
                return FakeStream([FakeToolCallChunk()])
            return FakeStream([FakeContentChunk()])

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="look at the image",
                user_id="user-a",
                max_steps=2,
            )
        ]

        assert not any("AAAA" in event for event in events)
        tool_result_events = [event for event in events if event.startswith("event: tool_result")]
        assert tool_result_events
        data = json.loads(tool_result_events[0].split("data: ", 1)[1])
        assert data["result"]["data"] == "[omitted-base64-image]"
        assert any(
            "data:image/jpeg;base64,AAAA" in str(message)
            for message in seen_messages[-1]
        )

    asyncio.run(run())


def test_conversation_history_cache_omits_multimodal_base64(monkeypatch) -> None:
    async def run() -> None:
        agent_service_module._CONVERSATION_MESSAGES.clear()
        agent_service_module._CONVERSATION_CACHES.clear()
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_messages = []
        call_count = 0

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            nonlocal call_count
            call_count += 1
            seen_messages.append(kwargs["messages"])
            if call_count == 1:
                return FakeStream([FakeToolCallChunk()])
            return FakeStream([FakeContentChunk()])

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="look at the image",
                conversation_id="conv-image",
                user_id="user-a",
                max_steps=2,
            )
        ]

        assert events
        assert any(
            "data:image/jpeg;base64,AAAA" in str(message)
            for message in seen_messages[-1]
        )
        cached = list(agent_service_module._CONVERSATION_MESSAGES.values())[0]
        assert "AAAA" not in str(cached)
        assert "data:image" not in str(cached)

    try:
        asyncio.run(run())
    finally:
        agent_service_module._CONVERSATION_MESSAGES.clear()
        agent_service_module._CONVERSATION_CACHES.clear()


def test_request_attachments_are_injected_as_multimodal_user_message(
    monkeypatch,
) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_messages = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            seen_messages.append(kwargs["messages"])
            return FakeStream([FakeContentChunk()])

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr(
            "app.services.agent_service.chat_by_scenario", fake_chat_by_scenario
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="这张图里有什么？",
                user_id="user-a",
                max_steps=1,
                request_attachments=[
                    {
                        "attachment_id": "att-a",
                        "mime_type": "image/png",
                        "data_base64": "REQBASE64",
                        "original_name": "screen.png",
                    }
                ],
            )
        ]

        assert events
        user_message = [
            message for message in seen_messages[0] if message["role"] == "user"
        ][-1]
        assert user_message["role"] == "user"
        assert user_message["content"][0] == {
            "type": "text",
            "text": "这张图里有什么？",
        }
        assert user_message["content"][1]["image_url"]["url"] == (
            "data:image/png;base64,REQBASE64"
        )

    asyncio.run(run())


def test_conversation_history_cache_omits_request_attachment_base64(
    monkeypatch,
) -> None:
    async def run() -> None:
        agent_service_module._CONVERSATION_MESSAGES.clear()
        agent_service_module._CONVERSATION_CACHES.clear()
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_messages = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            seen_messages.append(kwargs["messages"])
            return FakeStream([FakeContentChunk()])

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr(
            "app.services.agent_service.chat_by_scenario", fake_chat_by_scenario
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="看截图",
                conversation_id="conv-request-image",
                user_id="user-a",
                max_steps=1,
                request_attachments=[
                    {
                        "attachment_id": "att-a",
                        "mime_type": "image/png",
                        "data_base64": "REQBASE64",
                        "original_name": "screen.png",
                    }
                ],
            )
        ]

        assert events
        assert "data:image/png;base64,REQBASE64" in str(seen_messages[0])
        cached = list(agent_service_module._CONVERSATION_MESSAGES.values())[0]
        assert "REQBASE64" not in str(cached)
        assert "data:image" not in str(cached)

    try:
        asyncio.run(run())
    finally:
        agent_service_module._CONVERSATION_MESSAGES.clear()
        agent_service_module._CONVERSATION_CACHES.clear()
