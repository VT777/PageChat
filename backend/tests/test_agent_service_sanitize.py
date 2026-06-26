import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

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

class FakeReasoningChunk:
    choices = [
        SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                reasoning_content="raw private reasoning",
                tool_calls=None,
            )
        )
    ]


class FakeReasoningContentChunk:
    choices = [
        SimpleNamespace(
            delta=SimpleNamespace(
                content="answer",
                reasoning_content="raw private reasoning",
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

class FakeResponsesEvent:
    def __init__(self, event_type: str, **payload):
        self.type = event_type
        for key, value in payload.items():
            setattr(self, key, value)


class FakeResponsesStream:
    def __init__(self, events):
        self.events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.events:
            raise StopAsyncIteration
        return self.events.pop(0)


class FakeEmptyChunk:
    choices = [
        SimpleNamespace(
            delta=SimpleNamespace(
                content=None,
                reasoning_content=None,
                tool_calls=None,
            )
        )
    ]


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
                document_ids=["doc-a"],
                preferred_document_ids=["doc-a"],
                strict_scope=True,
                user_id="user-a",
                max_steps=2,
            )
        ]

        assert not any("AAAA" in event for event in events)
        tool_completed_events = [
            event for event in events if event.startswith("event: tool_completed")
        ]
        assert tool_completed_events
        data = json.loads(tool_completed_events[0].split("data: ", 1)[1])
        assert data["result"]["data"] == "[omitted-base64-image]"
        assert any(
            "data:image/jpeg;base64,AAAA" in str(message)
            for message in seen_messages[-1]
        )

    asyncio.run(run())


def test_agent_stream_does_not_emit_raw_reasoning_content(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream([FakeReasoningContentChunk()])

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="hello",
                document_ids=["doc-a"],
                preferred_document_ids=["doc-a"],
                strict_scope=True,
                user_id="user-a",
                max_steps=1,
            )
        ]

        assert not any(event.startswith("event: thinking") for event in events)
        assert not any(event.startswith("event: content") for event in events)
        assert not any("raw private reasoning" in event for event in events)
        assert any(event.startswith("event: answer_delta") for event in events)

    asyncio.run(run())


def test_agent_stream_raises_structured_failure_when_no_final_answer(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream([FakeEmptyChunk()])

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        with pytest.raises(RuntimeError, match="No final answer"):
            _events = [
                event
                async for event in agent.run_agent_stream(
                    question="summarize this document",
                    document_ids=["doc-a"],
                    preferred_document_ids=["doc-a"],
                    strict_scope=True,
                    user_id="user-a",
                    max_steps=1,
                )
            ]

    asyncio.run(run())


def test_simple_chat_raises_when_stream_has_no_final_answer(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream([FakeEmptyChunk()])

        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        with pytest.raises(RuntimeError, match="No final answer"):
            _events = [
                event
                async for event in agent._simple_chat_stream(
                    question="hello",
                )
            ]

    asyncio.run(run())


def test_simple_chat_reraises_provider_errors(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)

        async def fake_chat_by_scenario(**kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        with pytest.raises(RuntimeError, match="provider down"):
            _events = [
                event
                async for event in agent._simple_chat_stream(
                    question="hello",
                )
            ]

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
                document_ids=["doc-a"],
                preferred_document_ids=["doc-a"],
                strict_scope=True,
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


def test_chat_fallback_does_not_stream_raw_reasoning_content(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream([FakeReasoningChunk(), FakeContentChunk()])

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
                question="summarize",
                user_id="user-a",
                max_steps=1,
            )
        ]

        joined = "".join(events)
        assert "raw private reasoning" not in joined
        assert "answer" in joined

    asyncio.run(run())


def test_image_only_request_skips_initial_document_retrieval(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        initial_retrieval_calls = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            initial_retrieval_calls.append(kwargs)
            return [{"tool_name": "browse_documents", "result": {"documents": []}}]

        async def fake_chat_by_scenario(**kwargs):
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
                question="图片说了什么内容？",
                user_id="user-a",
                folder_id="folder-a",
                include_subfolders=True,
                strict_scope=True,
                max_steps=1,
                request_attachments=[
                    {
                        "attachment_id": "att-a",
                        "mime_type": "image/png",
                        "data_base64": "REQBASE64",
                    }
                ],
            )
        ]

        assert events
        assert initial_retrieval_calls == []
        assert "browse_documents" not in "".join(events)

    asyncio.run(run())


def test_responses_capability_does_not_activate_mixed_runtime(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_calls = []

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            seen_calls.append(kwargs)
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
        assert not hasattr(agent_service_module, "OpenAIResponsesAdapter")
        assert not hasattr(agent, "_run_responses_agent_stream")

        events = [
            event
            async for event in agent.run_agent_stream(
                question="Find the answer in the document",
                user_id="user-a",
                document_ids=["doc-a"],
                max_steps=1,
            )
        ]

        joined = "".join(events)
        assert "answer" in joined
        assert seen_calls

    asyncio.run(run())


@pytest.mark.skip(reason="Responses API is retained as an adapter only, not an active runtime path")
def test_responses_summary_flow_streams_reasoning_and_tool_calls(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()
        seen_calls = []

        class FakeToolExecutorWithSearch(FakeToolExecutor):
            async def execute(self, tool_name: str, arguments: dict):
                seen_calls.append((tool_name, arguments))
                return {
                    "success": True,
                    "documents": [],
                    "result": {"ok": True},
                }

        class FakeResponsesAdapter:
            def __init__(self):
                self.calls = 0

            async def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponsesStream([
                        FakeResponsesEvent(
                            "response.reasoning_summary_text.delta",
                            delta="先找一下对应文档。",
                        ),
                        FakeResponsesEvent(
                            "response.output_item.done",
                            item=SimpleNamespace(
                                type="function_call",
                                id="item-1",
                                call_id="call-1",
                                name="search_within_document",
                                arguments='{"doc_id":"doc-a","query":"图片说了什么"}',
                            ),
                        ),
                        FakeResponsesEvent(
                            "response.completed",
                            response=SimpleNamespace(id="resp-1"),
                        ),
                    ])
                return FakeResponsesStream([
                    FakeResponsesEvent(
                        "response.output_text.delta",
                        delta="这是图片中的内容。",
                    ),
                    FakeResponsesEvent(
                        "response.completed",
                        response=SimpleNamespace(id="resp-2"),
                    ),
                ])

        async def fake_resolve_scenario_route(*args, **kwargs):
            return {
                "provider_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-secret",
                    "model": "gpt-5-mini",
                    "supports_responses_api": True,
                    "supports_reasoning_effort": True,
                    "supports_reasoning_summary": True,
                },
                "model": "gpt-5-mini",
                "temperature": 0.3,
                "max_tokens": 1000,
            }

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutorWithSearch)
        monkeypatch.setattr(
            "app.services.agent_service.OpenAIResponsesAdapter",
            lambda: FakeResponsesAdapter(),
        )
        monkeypatch.setattr(
            "app.services.agent_service.resolve_scenario_route",
            fake_resolve_scenario_route,
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="图片说了什么内容？",
                user_id="user-a",
                max_steps=2,
                request_attachments=[
                    {
                        "attachment_id": "att-a",
                        "mime_type": "image/png",
                        "data_base64": "REQBASE64",
                    }
                ],
            )
        ]

        assert any("先找一下对应文档" in event for event in events)
        assert any(event.startswith("event: tool_call") for event in events)
        assert any("这是图片中的内容" in event for event in events)
        assert seen_calls[0][0] == "search_within_document"

    asyncio.run(run())


@pytest.mark.skip(reason="Responses API is retained as an adapter only, not an active runtime path")
def test_responses_flow_does_not_stream_raw_reasoning_text(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        class FakeResponsesAdapter:
            async def create(self, **kwargs):
                return FakeResponsesStream([
                    FakeResponsesEvent(
                        "response.reasoning_summary_text.delta",
                        delta="Short plan.",
                    ),
                    FakeResponsesEvent(
                        "response.reasoning_text.delta",
                        delta="private chain of thought that should never be shown",
                    ),
                    FakeResponsesEvent(
                        "response.output_text.delta",
                        delta="Final answer.",
                    ),
                    FakeResponsesEvent(
                        "response.completed",
                        response=SimpleNamespace(id="resp-1"),
                    ),
                ])

        async def fake_resolve_scenario_route(*args, **kwargs):
            return {
                "provider_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-secret",
                    "model": "gpt-5-mini",
                    "supports_responses_api": True,
                    "supports_reasoning_effort": True,
                    "supports_reasoning_summary": True,
                },
                "model": "gpt-5-mini",
                "temperature": 0.3,
                "max_tokens": 1000,
            }

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr(
            "app.services.agent_service.OpenAIResponsesAdapter",
            lambda: FakeResponsesAdapter(),
        )
        monkeypatch.setattr(
            "app.services.agent_service.resolve_scenario_route",
            fake_resolve_scenario_route,
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="Find the answer",
                user_id="user-a",
                max_steps=1,
            )
        ]

        joined = "".join(events)
        assert "Short plan." in joined
        assert "Final answer." in joined
        assert "private chain of thought" not in joined

    asyncio.run(run())


@pytest.mark.skip(reason="Responses API is retained as an adapter only, not an active runtime path")
def test_responses_flow_streams_final_message_done_item(monkeypatch) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        class FakeToolExecutorWithSearch(FakeToolExecutor):
            async def execute(self, tool_name: str, arguments: dict):
                return {
                    "success": True,
                    "matches": [{"page": 1, "snippet": "evidence"}],
                }

        class FakeResponsesAdapter:
            def __init__(self):
                self.calls = 0

            async def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponsesStream([
                        FakeResponsesEvent(
                            "response.output_item.done",
                            item=SimpleNamespace(
                                type="function_call",
                                id="item-1",
                                call_id="call-1",
                                name="search_within_document",
                                arguments='{"doc_id":"doc-a","query":"evidence"}',
                            ),
                        ),
                        FakeResponsesEvent(
                            "response.completed",
                            response=SimpleNamespace(id="resp-1"),
                        ),
                    ])
                return FakeResponsesStream([
                    FakeResponsesEvent(
                        "response.output_item.done",
                        item=SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(
                                    type="output_text",
                                    text="Final answer from message item.",
                                )
                            ],
                        ),
                    ),
                    FakeResponsesEvent(
                        "response.completed",
                        response=SimpleNamespace(id="resp-2"),
                    ),
                ])

        async def fake_resolve_scenario_route(*args, **kwargs):
            return {
                "provider_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-secret",
                    "model": "gpt-5-mini",
                    "supports_responses_api": True,
                    "supports_reasoning_effort": True,
                    "supports_reasoning_summary": True,
                },
                "model": "gpt-5-mini",
                "temperature": 0.3,
                "max_tokens": 1000,
            }

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        monkeypatch.setattr(
            "app.services.agent_service.ToolExecutor",
            FakeToolExecutorWithSearch,
        )
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr(
            "app.services.agent_service.OpenAIResponsesAdapter",
            lambda: FakeResponsesAdapter(),
        )
        monkeypatch.setattr(
            "app.services.agent_service.resolve_scenario_route",
            fake_resolve_scenario_route,
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="Find evidence",
                user_id="user-a",
                max_steps=2,
            )
        ]

        joined = "".join(events)
        assert "Final answer from message item." in joined
        assert "暂时无法整理出最终回答" not in joined

    asyncio.run(run())


@pytest.mark.skip(reason="Responses API is retained as an adapter only, not an active runtime path")
def test_responses_flow_uses_chat_fallback_when_tools_return_no_final_text(
    monkeypatch,
) -> None:
    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = FakePageIndexService()
        agent.document_service = FakeDocumentService()

        class FakeToolExecutorWithSearch(FakeToolExecutor):
            async def execute(self, tool_name: str, arguments: dict):
                return {
                    "success": True,
                    "matches": [{"page": 43, "snippet": "重庆师范大学案例"}],
                }

        class FakeResponsesAdapter:
            def __init__(self):
                self.calls = 0

            async def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponsesStream([
                        FakeResponsesEvent(
                            "response.output_item.done",
                            item=SimpleNamespace(
                                type="function_call",
                                id="item-1",
                                call_id="call-1",
                                name="search_within_document",
                                arguments='{"doc_id":"doc-a","query":"重庆师范大学"}',
                            ),
                        ),
                        FakeResponsesEvent(
                            "response.completed",
                            response=SimpleNamespace(id="resp-1"),
                        ),
                    ])
                return FakeResponsesStream([
                    FakeResponsesEvent(
                        "response.completed",
                        response=SimpleNamespace(id="resp-2"),
                    ),
                ])

        async def fake_resolve_scenario_route(*args, **kwargs):
            return {
                "provider_config": {
                    "provider": "dashscope",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-secret",
                    "model": "qwen3.6-plus",
                    "supports_responses_api": True,
                    "supports_reasoning_effort": True,
                    "supports_reasoning_summary": False,
                },
                "model": "qwen3.6-plus",
                "temperature": 0.3,
                "max_tokens": 1000,
            }

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return []

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="最终回答：重庆师范大学案例。",
                                reasoning_content=None,
                                tool_calls=None,
                            )
                        )
                    ]
                )
            ])

        monkeypatch.setattr(
            "app.services.agent_service.ToolExecutor",
            FakeToolExecutorWithSearch,
        )
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr(
            "app.services.agent_service.OpenAIResponsesAdapter",
            lambda: FakeResponsesAdapter(),
        )
        monkeypatch.setattr(
            "app.services.agent_service.resolve_scenario_route",
            fake_resolve_scenario_route,
        )
        monkeypatch.setattr(
            "app.services.agent_service.chat_by_scenario",
            fake_chat_by_scenario,
        )

        events = [
            event
            async for event in agent.run_agent_stream(
                question="重庆师范大学有什么ai应用的创新",
                user_id="user-a",
                max_steps=2,
            )
        ]

        joined = "".join(events)
        assert "最终回答：重庆师范大学案例。" in joined
        assert "暂时无法整理出最终回答" not in joined

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
