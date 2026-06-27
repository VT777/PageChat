import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_tool_loop import ModelToolLoopRuntime
from app.agent.model_turn import ModelTextDelta, ModelToolCall, ModelToolCallDelta, ModelTurn
from app.agent.state import AgentRunState


def _state(question: str = "What documents are available?") -> AgentRunState:
    return AgentRunState(
        question=question,
        conversation_id="conv-1",
        run_id="run-1",
        message_id="msg-1",
        scope={"user_id": "user-1"},
    )


class ToolThenAnswerModel:
    def __init__(self):
        self.calls = 0
        self.messages_by_turn = []

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        self.messages_by_turn.append(list(messages))
        if self.calls == 1:
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root", "recursive": True},
                    )
                ]
            )
        else:
            yield ModelTurn(content="There are three documents.")


class FinalOnlyModel:
    async def stream_turn(self, *, messages, tools, user_id=None):
        yield ModelTurn(content="Hello, how can I help?")


class StreamingFinalAnswerModel:
    async def stream_turn(self, *, messages, tools, user_id=None):
        yield ModelTextDelta("Hello, ")
        yield ModelTextDelta("how can I help?")
        yield ModelTurn(content="Hello, how can I help?")


class StreamingToolCallThenAnswerModel:
    def __init__(self):
        self.calls = 0

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelToolCallDelta(index=0, id="call_1", name="browse_documents")
            yield ModelToolCallDelta(index=0, arguments_delta='{"folder_id":"root"')
            yield ModelToolCallDelta(index=0, arguments_delta=',"recursive":true}')
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root", "recursive": True},
                    )
                ]
            )
        else:
            yield ModelTurn(content="There are three documents.")


class MultiToolThenAnswerModel:
    def __init__(self):
        self.calls = 0
        self.messages_by_turn = []

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        self.messages_by_turn.append(list(messages))
        if self.calls == 1:
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_structure",
                        name="get_document_structure",
                        arguments={"doc_id": "doc-a"},
                    ),
                    ModelToolCall(
                        id="call_search",
                        name="search_within_document",
                        arguments={"doc_id": "doc-a", "query": "AI"},
                    ),
                ]
            )
        else:
            yield ModelTurn(content="The document mentions AI.")


class RecordingToolRunner:
    def __init__(self):
        self.calls = []

    async def execute(self, tool_name, arguments):
        self.calls.append((tool_name, dict(arguments)))
        if tool_name == "browse_documents":
            return {
                "success": True,
                "documents": [
                    {"doc_id": "doc-a", "name": "A.pdf"},
                    {"doc_id": "doc-b", "name": "B.pdf"},
                    {"doc_id": "doc-c", "name": "C.pdf"},
                ],
            }
        if tool_name == "get_document_structure":
            return {
                "success": True,
                "doc_id": arguments["doc_id"],
                "total_pages": 2,
                "structure": [{"title": "AI"}],
            }
        if tool_name == "search_within_document":
            return {
                "success": True,
                "matches": [{"doc_id": arguments["doc_id"], "page": 1, "snippet": "AI"}],
            }
        return {"success": True}


def test_flat_loop_executes_tool_and_returns_final_answer():
    async def run() -> None:
        model = ToolThenAnswerModel()
        runner = RecordingToolRunner()
        runtime = ModelToolLoopRuntime(
            model=model,
            tool_runner=runner,
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state())]

        assert [call[0] for call in runner.calls] == ["browse_documents"]
        assert any(event.type == "tool_started" for event in events)
        assert any(event.type == "tool_completed" for event in events)
        assert "".join(
            event.payload.get("content", "") or event.payload.get("delta", "")
            for event in events
            if event.type == "answer_delta"
        ) == "There are three documents."
        assert model.calls == 2
        second_turn_messages = model.messages_by_turn[1]
        assert any(
            message.get("role") == "assistant" and message.get("tool_calls")
            for message in second_turn_messages
        )
        assert any(
            message.get("role") == "tool" and message.get("tool_call_id") == "call_1"
            for message in second_turn_messages
        )

    asyncio.run(run())


def test_flat_loop_greeting_returns_answer_without_tool_call():
    async def run() -> None:
        runner = RecordingToolRunner()
        runtime = ModelToolLoopRuntime(
            model=FinalOnlyModel(),
            tool_runner=runner,
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state("Hello"))]

        assert runner.calls == []
        assert not any(event.type == "tool_started" for event in events)
        assert [event.payload["content"] for event in events if event.type == "answer_delta"] == [
            "Hello, how can I help?"
        ]

    asyncio.run(run())


def test_flat_loop_streams_final_answer_text_deltas():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=StreamingFinalAnswerModel(),
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state("Hello"))]

        assert [event.payload["content"] for event in events if event.type == "answer_delta"] == [
            "Hello, ",
            "how can I help?",
        ]

    asyncio.run(run())


def test_flat_loop_forwards_native_tool_call_deltas_before_tool_start():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=StreamingToolCallThenAnswerModel(),
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state())]

        event_types = [event.type for event in events]
        assert event_types.index("tool_call_delta") < event_types.index("tool_started")
        deltas = [event for event in events if event.type == "tool_call_delta"]
        assert deltas[0].payload == {
            "tool_call_id": "call_1",
            "tool_name": "browse_documents",
            "arguments_delta": "",
            "status": "streaming",
        }
        assert deltas[1].payload["arguments_delta"] == '{"folder_id":"root"'
        assert deltas[2].payload["arguments_delta"] == ',"recursive":true}'

    asyncio.run(run())


def test_flat_loop_executes_multiple_tool_calls_in_model_order():
    async def run() -> None:
        model = MultiToolThenAnswerModel()
        runner = RecordingToolRunner()
        runtime = ModelToolLoopRuntime(
            model=model,
            tool_runner=runner,
            tools=[
                {"function": {"name": "get_document_structure"}},
                {"function": {"name": "search_within_document"}},
            ],
        )

        events = [event async for event in runtime.stream(_state("Summarize AI mentions."))]

        assert [call[0] for call in runner.calls] == [
            "get_document_structure",
            "search_within_document",
        ]
        completed = [event for event in events if event.type == "tool_completed"]
        assert [event.payload["tool_name"] for event in completed] == [
            "get_document_structure",
            "search_within_document",
        ]
        second_turn_messages = model.messages_by_turn[1]
        tool_messages = [
            message for message in second_turn_messages if message.get("role") == "tool"
        ]
        assert [message["tool_call_id"] for message in tool_messages] == [
            "call_structure",
            "call_search",
        ]

    asyncio.run(run())
