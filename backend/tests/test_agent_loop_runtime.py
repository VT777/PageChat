import asyncio
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop_runtime import (  # noqa: E402
    AgentLoopRuntime,
    PlannerAction,
    PolicyGuidedPlanner,
)
from app.agent.policy import AgentPolicy  # noqa: E402
from app.agent.state import AgentRunState  # noqa: E402


class RecordingPlanner:
    def __init__(self):
        self.calls = []

    async def next_action(self, state: AgentRunState) -> PlannerAction:
        self.calls.append(
            {
                "tool_results": [item["tool_name"] for item in state.tool_results],
                "observations": [
                    observation["tool_name"] for observation in state.scope.get("observations", [])
                ],
            }
        )
        if len(self.calls) == 1:
            return PlannerAction.call_tool(
                "view_folder_structure",
                {},
                thought="Inspect the folder tree first.",
            )
        if len(self.calls) == 2:
            return PlannerAction.call_tool(
                "browse_documents",
                {"folder_id": "root", "query": state.question},
                thought="Browse candidate documents from the observed tree.",
            )
        return PlannerAction.answer(
            "Answer grounded in observed evidence.",
            thought="Enough evidence is available to answer.",
        )


class RecordingToolRunner:
    def __init__(self):
        self.calls = []

    async def execute(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        if tool_name == "view_folder_structure":
            return {
                "success": True,
                "tree": {"id": "root", "children": [{"id": "folder-a", "name": "Cases"}]},
                "total_folders": 1,
            }
        if tool_name == "browse_documents":
            return {
                "success": True,
                "documents": [{"doc_id": "doc-alpha", "name": "alpha.pdf"}],
            }
        return {"success": True}


def test_loop_runtime_interleaves_plan_tool_observation_until_answer() -> None:
    async def run() -> None:
        planner = RecordingPlanner()
        tool_runner = RecordingToolRunner()
        runtime = AgentLoopRuntime(planner=planner, tool_runner=tool_runner, max_steps=4)
        state = AgentRunState(
            question="Summarize alpha",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        events = [event async for event in runtime.stream(state)]

        assert [event.event_type for event in events] == [
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "progress",
            "answer_delta",
        ]
        assert [call[0] for call in tool_runner.calls] == [
            "view_folder_structure",
            "browse_documents",
        ]
        assert len(planner.calls) == 3
        assert planner.calls[1]["observations"] == ["view_folder_structure"]
        assert planner.calls[2]["observations"] == [
            "view_folder_structure",
            "browse_documents",
        ]
        assert events[0].payload == {
            "kind": "plan",
            "message": "Inspect the folder tree first.",
            "step": 1,
        }
        assert events[3].payload["kind"] == "observation"
        assert events[-1].payload == {"content": "Answer grounded in observed evidence."}
        assert state.answer == "Answer grounded in observed evidence."

    asyncio.run(run())


def test_loop_runtime_streams_planner_thought_updates_before_tool_call() -> None:
    class StreamingPlanner:
        async def stream_next_action(self, state: AgentRunState):
            yield {"type": "thought", "message": "我先"}
            yield {"type": "thought", "message": "我先查看资料库目录"}
            yield PlannerAction.call_tool(
                "view_folder_structure",
                {},
                thought="我先查看资料库目录",
            )

    async def run() -> None:
        async def answer_generator(_state: AgentRunState) -> str:
            return "done"

        runtime = AgentLoopRuntime(
            planner=StreamingPlanner(),
            tool_runner=RecordingToolRunner(),
            answer_generator=answer_generator,
            max_steps=1,
        )
        state = AgentRunState(
            question="现在有哪些文档",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        events = [event async for event in runtime.stream(state)]

        assert events[0].event_type == "progress"
        assert events[0].payload == {
            "kind": "plan",
            "message": "我先",
            "step": 1,
            "status": "streaming",
        }
        assert events[1].payload["message"] == "我先查看资料库目录"
        assert events[1].payload["status"] == "streaming"
        assert events[2].event_type == "tool_started"

    asyncio.run(run())


def test_loop_runtime_streams_answer_generator_chunks() -> None:
    class AnswerPlanner:
        async def next_action(self, state: AgentRunState) -> PlannerAction:
            return PlannerAction.answer(thought="Ready to answer.")

    async def run() -> None:
        async def answer_generator(_state: AgentRunState):
            yield "Alpha"
            yield " Beta"

        runtime = AgentLoopRuntime(
            planner=AnswerPlanner(),
            tool_runner=RecordingToolRunner(),
            answer_generator=answer_generator,
            max_steps=1,
        )
        state = AgentRunState(
            question="q",
            conversation_id="conv-answer",
            run_id="run-answer",
            message_id="msg-answer",
        )

        events = [event async for event in runtime.stream(state)]

        assert [event.event_type for event in events] == [
            "progress",
            "answer_delta",
            "answer_delta",
        ]
        assert [event.payload.get("content") for event in events[1:]] == ["Alpha", " Beta"]
        assert state.answer == "Alpha Beta"

    asyncio.run(run())


def test_policy_guided_planner_starts_library_questions_with_folder_tree() -> None:
    async def run() -> None:
        planner = PolicyGuidedPlanner()
        state = AgentRunState(
            question="What AI innovation cases are mentioned?",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        action = await planner.next_action(state)

        assert action.action_type == "call_tool"
        assert action.tool_name == "view_folder_structure"
        assert "folder tree" in action.thought

    asyncio.run(run())


def test_policy_guided_planner_starts_selected_document_with_structure() -> None:
    async def run() -> None:
        planner = PolicyGuidedPlanner()
        state = AgentRunState(
            question="Summarize alpha.pdf",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"]},
        )

        action = await planner.next_action(state)

        assert action.action_type == "call_tool"
        assert action.tool_name == "get_document_structure"
        assert action.arguments == {"doc_id": "doc-alpha", "compact": True}

    asyncio.run(run())


def test_loop_runtime_emits_guardrail_and_replans_invalid_action() -> None:
    class GuardrailPlanner:
        def __init__(self):
            self.calls = 0

        async def next_action(self, state: AgentRunState) -> PlannerAction:
            self.calls += 1
            if self.calls == 1:
                return PlannerAction.call_tool(
                    "delete_everything",
                    {},
                    thought="我想先尝试一个不可用工具。",
                )
            assert state.scope["observations"][-1]["kind"] == "guardrail"
            return PlannerAction.answer(
                "我无法使用该工具，因此先说明无法执行。",
                thought="不可用工具已被拦截，我改为直接说明限制。",
            )

    async def run() -> None:
        planner = GuardrailPlanner()
        runtime = AgentLoopRuntime(
            planner=planner,
            tool_runner=RecordingToolRunner(),
            policy=AgentPolicy(
                tools=[{"type": "function", "function": {"name": "view_folder_structure"}}]
            ),
            max_steps=3,
        )
        state = AgentRunState(
            question="删除所有文档",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        events = [event async for event in runtime.stream(state)]

        assert [event.event_type for event in events] == [
            "progress",
            "progress",
            "progress",
            "answer_delta",
        ]
        assert events[0].payload["message"] == "我想先尝试一个不可用工具。"
        assert events[1].payload["kind"] == "guardrail"
        assert events[2].payload["message"] == "不可用工具已被拦截，我改为直接说明限制。"
        assert planner.calls == 2

    asyncio.run(run())


def test_loop_runtime_blocks_document_answer_until_page_evidence() -> None:
    class EvidencePlanner:
        def __init__(self):
            self.calls = 0

        async def next_action(self, state: AgentRunState) -> PlannerAction:
            self.calls += 1
            if self.calls == 1:
                return PlannerAction.answer(
                    "没有读页面就给出的文档答案。",
                    thought="我先尝试回答。",
                )
            if self.calls == 2:
                assert state.scope["observations"][-1]["kind"] == "guardrail"
                return PlannerAction.call_tool(
                    "get_page_content",
                    {"pages": "1"},
                    thought="证据不足，我先读取页面。",
                )
            return PlannerAction.answer(
                "这是基于页面证据的答案。",
                thought="页面证据已具备，可以回答。",
            )

    class PageToolRunner:
        async def execute(self, tool_name: str, arguments: dict):
            assert tool_name == "get_page_content"
            assert arguments == {"pages": "1", "doc_id": "doc-alpha"}
            return {
                "success": True,
                "doc_id": "doc-alpha",
                "page_num": 1,
                "text_content": "重庆师范大学 AI 创新内容。",
            }

    async def run() -> None:
        runtime = AgentLoopRuntime(
            planner=EvidencePlanner(),
            tool_runner=PageToolRunner(),
            policy=AgentPolicy(
                tools=[{"type": "function", "function": {"name": "get_page_content"}}]
            ),
            max_steps=4,
        )
        state = AgentRunState(
            question="重庆师范大学有什么 AI 应用创新？",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"], "strict_scope": True},
        )

        events = [event async for event in runtime.stream(state)]
        answer_events = [event for event in events if event.event_type == "answer_delta"]
        guardrail_events = [
            event
            for event in events
            if event.event_type == "progress" and event.payload.get("kind") == "guardrail"
        ]

        assert len(answer_events) == 1
        assert answer_events[0].payload["content"] == "这是基于页面证据的答案。"
        assert guardrail_events

    asyncio.run(run())


def test_loop_runtime_raises_when_guardrails_exhaust_steps() -> None:
    class InvalidPlanner:
        async def next_action(self, state: AgentRunState) -> PlannerAction:
            return PlannerAction.call_tool(
                "missing_tool",
                {},
                thought="我还是选择不存在的工具。",
            )

    async def run() -> None:
        runtime = AgentLoopRuntime(
            planner=InvalidPlanner(),
            tool_runner=RecordingToolRunner(),
            policy=AgentPolicy(
                tools=[{"type": "function", "function": {"name": "view_folder_structure"}}]
            ),
            max_steps=2,
        )
        state = AgentRunState(
            question="做一件不可用的事",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        with pytest.raises(RuntimeError, match="No final answer"):
            [event async for event in runtime.stream(state)]

    asyncio.run(run())
