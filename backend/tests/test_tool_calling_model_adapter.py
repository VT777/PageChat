import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_turn import (
    ModelReasoningDelta,
    ModelTextDelta,
    ModelToolCallDelta,
    ModelTurn,
)
from app.agent.tool_calling_model_adapter import ToolCallingModelAdapter


def _tools():
    return [{"function": {"name": "browse_documents"}}]


async def _collect(adapter):
    return [
        event
        async for event in adapter.stream_turn(
            messages=[{"role": "user", "content": "List documents"}],
            tools=_tools(),
            user_id="user-a",
        )
    ]


def test_adapter_parses_non_streaming_message_tool_calls():
    calls = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "browse_documents",
                                    "arguments": '{"folder_id":"root"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

    adapter = ToolCallingModelAdapter(completion_fn=fake_completion)

    import asyncio

    events = asyncio.run(_collect(adapter))

    assert calls[0]["stream"] is True
    assert calls[0]["tools"] == _tools()
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["disable_thinking"] is True
    assert events == [
        ModelTurn(
            tool_calls=[
                events[0].tool_calls[0],
            ]
        )
    ]
    assert events[0].tool_calls[0].id == "call_1"
    assert events[0].tool_calls[0].name == "browse_documents"
    assert events[0].tool_calls[0].arguments == {"folder_id": "root"}


def test_adapter_allows_native_thinking_when_configured():
    calls = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    adapter = ToolCallingModelAdapter(
        completion_fn=fake_completion,
        disable_thinking=False,
    )

    import asyncio

    events = asyncio.run(_collect(adapter))

    assert calls[0]["disable_thinking"] is False
    assert events == [ModelTurn(content="ok")]


def test_adapter_streams_tool_call_deltas_and_final_turn():
    async def stream_response():
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "search_within_document",
                                    "arguments": '{"doc_id":"doc-a"',
                                },
                            }
                        ]
                    }
                }
            ]
        }
        yield {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ',"query":"AI"}'},
                            }
                        ]
                    }
                }
            ]
        }

    async def fake_completion(**kwargs):
        return stream_response()

    adapter = ToolCallingModelAdapter(completion_fn=fake_completion)

    import asyncio

    events = asyncio.run(_collect(adapter))

    assert [type(event) for event in events] == [
        ModelToolCallDelta,
        ModelToolCallDelta,
        ModelTurn,
    ]
    assert events[0].id == "call_1"
    assert events[0].name == "search_within_document"
    assert events[-1].tool_calls[0].arguments == {"doc_id": "doc-a", "query": "AI"}


def test_adapter_streams_text_deltas_and_final_text_turn():
    async def stream_response():
        yield {"choices": [{"delta": {"content": "Hello"}}]}
        yield {"choices": [{"delta": {"content": " world"}}]}

    async def fake_completion(**kwargs):
        return stream_response()

    adapter = ToolCallingModelAdapter(completion_fn=fake_completion)

    import asyncio

    events = asyncio.run(_collect(adapter))

    assert [type(event) for event in events] == [
        ModelTextDelta,
        ModelTextDelta,
        ModelTurn,
    ]
    assert [event.delta for event in events[:-1]] == ["Hello", " world"]
    assert events[-1].content == "Hello world"


def test_adapter_streams_native_reasoning_deltas_without_answer_pollution():
    async def stream_response():
        yield {"choices": [{"delta": {"reasoning_content": "I should inspect docs."}}]}
        yield {"choices": [{"delta": {"content": "Final"}}]}

    async def fake_completion(**kwargs):
        return stream_response()

    adapter = ToolCallingModelAdapter(completion_fn=fake_completion, disable_thinking=False)

    import asyncio

    events = asyncio.run(_collect(adapter))

    assert [type(event) for event in events] == [
        ModelReasoningDelta,
        ModelTextDelta,
        ModelTurn,
    ]
    assert events[0].delta == "I should inspect docs."
    assert events[1].delta == "Final"
    assert events[-1].content == "Final"
