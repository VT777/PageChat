import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_tool_loop import ModelToolLoopRuntime
from app.agent.model_turn import (
    ModelReasoningDelta,
    ModelTextDelta,
    ModelToolCall,
    ModelToolCallDelta,
    ModelTurn,
)
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


class StreamingToolThenGatedStreamingAnswerModel:
    def __init__(self):
        self.calls = 0
        self.final_turn_gate = asyncio.Event()

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root"},
                    )
                ]
            )
        else:
            yield ModelTextDelta("There are ")
            yield ModelTextDelta("three documents.")
            await self.final_turn_gate.wait()
            yield ModelTurn(content="There are three documents.")


class ToolThenNarratedToolThenAnswerModel:
    def __init__(self):
        self.calls = 0

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root"},
                    )
                ]
            )
        elif self.calls == 2:
            yield ModelTextDelta("I need to inspect the folder structure.")
            yield ModelToolCallDelta(index=0, id="call_2", name="view_folder_structure")
            yield ModelToolCallDelta(index=0, arguments_delta='{"folder_id":"root"}')
            yield ModelTurn(
                content="I need to inspect the folder structure.",
                tool_calls=[
                    ModelToolCall(
                        id="call_2",
                        name="view_folder_structure",
                        arguments={"folder_id": "root"},
                    )
                ],
            )
        else:
            yield ModelTextDelta("The folder contains ")
            yield ModelTextDelta("three documents.")
            yield ModelTurn(content="The folder contains three documents.")


class StreamingNarratedToolCallThenAnswerModel:
    def __init__(self):
        self.calls = 0

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelTextDelta("我先查一下相关文档。")
            yield ModelTextDelta("找到了候选文件，继续读取。")
            yield ModelToolCallDelta(index=0, id="call_1", name="browse_documents")
            yield ModelToolCallDelta(index=0, arguments_delta='{"folder_id":"root"}')
            yield ModelTurn(
                content="我先查一下相关文档。找到了候选文件，继续读取。",
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root"},
                    )
                ],
            )
        else:
            yield ModelTurn(content="找到 3 个文档。")


class ReasoningThenToolCallModel:
    def __init__(self):
        self.calls = 0

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelReasoningDelta("I need to inspect the document library.")
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "root"},
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


def test_flat_loop_does_not_emit_hardcoded_processing_note_before_tool_start():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=ToolThenAnswerModel(),
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state("现在有哪些文件夹？"))]

        event_types = [event.type for event in events]
        assert "processing_delta" not in event_types
        assert "tool_started" in event_types
        return
        assert event_types.index("processing_delta") < event_types.index("tool_started")
        processing = [event for event in events if event.type == "processing_delta"]
        assert [event.payload for event in processing] == [
            {
                "content": "正在查看文档库。",
                "tool_call_id": "call_1",
                "tool_name": "browse_documents",
                "status": "streaming",
            }
        ]
        assert "There are three documents." not in processing[0].payload["content"]

    asyncio.run(run())


def test_flat_loop_forwards_native_reasoning_delta_before_tool_start():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=ReasoningThenToolCallModel(),
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state())]

        event_types = [event.type for event in events]
        assert event_types.index("reasoning_delta") < event_types.index("tool_started")
        reasoning = [event for event in events if event.type == "reasoning_delta"]
        assert [event.payload for event in reasoning] == [
            {"content": "I need to inspect the document library.", "status": "streaming"}
        ]
        assert "processing_delta" not in event_types

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

        assert [event.payload["content"] for event in events if event.type == "answer_candidate_delta"] == [
            "Hello, ",
            "how can I help?",
        ]
        assert [event.payload["content"] for event in events if event.type == "answer_candidate_commit"] == [
            "Hello, how can I help?"
        ]

    asyncio.run(run())


def test_flat_loop_streams_answer_deltas_after_tool_before_final_turn_finishes():
    async def run() -> None:
        model = StreamingToolThenGatedStreamingAnswerModel()
        runtime = ModelToolLoopRuntime(
            model=model,
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        stream = runtime.stream(_state())
        try:
            while True:
                event = await asyncio.wait_for(stream.__anext__(), timeout=1)
                if event.type == "tool_completed":
                    break

            first_answer = await asyncio.wait_for(stream.__anext__(), timeout=0.1)
            second_answer = await asyncio.wait_for(stream.__anext__(), timeout=0.1)
            assert first_answer.type == "answer_candidate_delta"
            assert first_answer.payload["content"] == "There are "
            assert second_answer.type == "answer_candidate_delta"
            assert second_answer.payload["content"] == "three documents."
        finally:
            model.final_turn_gate.set()
            with contextlib.suppress(StopAsyncIteration):
                while True:
                    await asyncio.wait_for(stream.__anext__(), timeout=1)

    asyncio.run(run())


def test_flat_loop_retracts_candidate_text_when_same_turn_calls_another_tool():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=ToolThenNarratedToolThenAnswerModel(),
            tool_runner=RecordingToolRunner(),
            tools=[
                {"function": {"name": "browse_documents"}},
                {"function": {"name": "view_folder_structure"}},
            ],
        )

        events = [event async for event in runtime.stream(_state("What is in the selected folder?"))]

        candidate_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type == "answer_candidate_delta"
        )
        retracted_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type == "answer_candidate_retract"
        )
        processing_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type == "processing_delta"
        )
        committed_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type in {"answer_candidate_commit", "answer_delta"}
        )

        assert "I need to inspect the folder structure." in candidate_text
        assert "I need to inspect the folder structure." in retracted_text
        assert "I need to inspect the folder structure." not in processing_text
        assert "I need to inspect the folder structure." not in committed_text
        assert committed_text == "The folder contains three documents."

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


def test_flat_loop_moves_narration_before_tool_calls_to_processing_details():
    async def run() -> None:
        runtime = ModelToolLoopRuntime(
            model=StreamingNarratedToolCallThenAnswerModel(),
            tool_runner=RecordingToolRunner(),
            tools=[{"function": {"name": "browse_documents"}}],
        )

        events = [event async for event in runtime.stream(_state("三一重工的母公司资产负债表"))]

        processing_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type in {"answer_candidate_retract", "processing_delta"}
        )
        answer_text = "".join(
            event.payload.get("content", "")
            for event in events
            if event.type == "answer_delta"
        )

        assert "我先查一下相关文档。" in processing_text
        assert "找到了候选文件，继续读取。" in processing_text
        assert "我先查一下相关文档。" not in answer_text
        assert "找到了候选文件，继续读取。" not in answer_text
        assert answer_text == "找到 3 个文档。"

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
