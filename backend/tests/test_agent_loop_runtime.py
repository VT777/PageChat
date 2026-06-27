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


def test_loop_runtime_retracts_plan_and_replans_invalid_action() -> None:
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
        assert events[1].payload == {
            "kind": "plan_retract",
            "message": "",
            "step": 1,
            "target_kind": "plan",
        }
        assert events[2].payload["message"] == "不可用工具已被拦截，我改为直接说明限制。"
        assert state.scope["observations"][0]["kind"] == "guardrail"
        assert planner.calls == 2

    asyncio.run(run())


def test_loop_runtime_retracts_streamed_thought_when_policy_rejects_action() -> None:
    class RejectedStreamingPlanner:
        def __init__(self):
            self.calls = 0

        async def stream_next_action(self, state: AgentRunState):
            self.calls += 1
            if self.calls == 1:
                yield {"type": "thought", "message": "I will use a risky tool."}
                yield PlannerAction.call_tool(
                    "delete_everything",
                    {},
                    thought="I will use a risky tool.",
                )
                return
            assert state.scope["observations"][-1]["kind"] == "guardrail"
            yield {"type": "thought", "message": "I will answer without that tool."}
            yield PlannerAction.answer(
                "I cannot use that tool.",
                thought="I will answer without that tool.",
            )

    async def run() -> None:
        planner = RejectedStreamingPlanner()
        runtime = AgentLoopRuntime(
            planner=planner,
            tool_runner=RecordingToolRunner(),
            policy=AgentPolicy(
                tools=[{"type": "function", "function": {"name": "view_folder_structure"}}]
            ),
            max_steps=3,
        )
        state = AgentRunState(
            question="Delete everything",
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
        assert events[0].payload == {
            "kind": "plan",
            "message": "I will use a risky tool.",
            "step": 1,
            "status": "streaming",
        }
        assert events[1].payload == {
            "kind": "plan_retract",
            "message": "",
            "step": 1,
            "target_kind": "plan",
        }
        assert events[2].payload == {
            "kind": "plan",
            "message": "I will answer without that tool.",
            "step": 2,
            "status": "streaming",
        }
        assert not any(
            event.payload.get("kind") == "guardrail"
            for event in events
            if event.event_type == "progress"
        )
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
        visible_guardrail_events = [
            event
            for event in events
            if event.event_type == "progress" and event.payload.get("kind") == "guardrail"
        ]
        retract_events = [
            event
            for event in events
            if event.event_type == "progress" and event.payload.get("kind") == "plan_retract"
        ]

        assert len(answer_events) == 1
        assert answer_events[0].payload["content"] == "这是基于页面证据的答案。"
        assert visible_guardrail_events == []
        assert retract_events
        assert state.scope["observations"][0]["kind"] == "guardrail"

    asyncio.run(run())


def test_loop_runtime_requires_image_after_visual_only_page_content() -> None:
    class VisualEvidencePlanner:
        def __init__(self):
            self.calls = 0

        async def next_action(self, state: AgentRunState) -> PlannerAction:
            self.calls += 1
            if self.calls == 1:
                return PlannerAction.call_tool(
                    "get_page_content",
                    {"doc_id": "doc-alpha", "pages": "1"},
                    thought="I will read page content first.",
                )
            if self.calls == 2:
                return PlannerAction.answer(
                    "This answer should not pass before image evidence.",
                    thought="I can answer from the page metadata.",
                )
            if self.calls == 3:
                assert state.scope["observations"][-1]["kind"] == "guardrail"
                return PlannerAction.call_tool(
                    "get_page_image",
                    {"doc_id": "doc-alpha", "page": 1},
                    thought="The page requires visual evidence, so I will inspect the image.",
                )
            return PlannerAction.answer(
                "The image shows the cover page.",
                thought="The page image is enough to answer.",
            )

    class VisualToolRunner:
        def __init__(self):
            self.calls = []

        async def execute(self, tool_name: str, arguments: dict):
            self.calls.append((tool_name, arguments))
            if tool_name == "get_page_content":
                return {
                    "success": True,
                    "data": {
                        "doc_id": "doc-alpha",
                        "doc_name": "alpha.pdf",
                        "content": [
                            {
                                "page": 1,
                                "visual_evidence_required": True,
                                "text_omitted_reason": "visual_evidence_required",
                            }
                        ],
                    },
                }
            if tool_name == "get_page_image":
                return {
                    "success": True,
                    "doc_id": "doc-alpha",
                    "page": 1,
                    "image_ref": "page-1.png",
                }
            raise AssertionError(f"unexpected tool {tool_name}")

    async def run() -> None:
        planner = VisualEvidencePlanner()
        tool_runner = VisualToolRunner()
        runtime = AgentLoopRuntime(
            planner=planner,
            tool_runner=tool_runner,
            policy=AgentPolicy(
                tools=[
                    {"type": "function", "function": {"name": "get_page_content"}},
                    {"type": "function", "function": {"name": "get_page_image"}},
                ]
            ),
            max_steps=5,
        )
        state = AgentRunState(
            question="What is on the first page?",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"], "strict_scope": True},
        )

        events = [event async for event in runtime.stream(state)]
        tool_names = [
            event.payload["tool_name"]
            for event in events
            if event.event_type == "tool_started"
        ]
        retract_events = [
            event
            for event in events
            if event.event_type == "progress" and event.payload.get("kind") == "plan_retract"
        ]

        assert tool_names == ["get_page_content", "get_page_image"]
        assert retract_events
        assert events[-1].payload["content"] == "The image shows the cover page."

    asyncio.run(run())


def test_loop_runtime_reuses_prior_evidence_for_same_tool_arguments() -> None:
    class RepeatToolPlanner:
        def __init__(self):
            self.calls = 0

        async def next_action(self, state: AgentRunState) -> PlannerAction:
            self.calls += 1
            if self.calls == 1:
                return PlannerAction.call_tool(
                    "get_page_content",
                    {"doc_id": "doc-alpha", "pages": "2"},
                    thought="I will read the same page again.",
                )
            assert state.scope["observations"][-1]["kind"] == "reuse"
            return PlannerAction.answer("复用上一轮证据回答。")

    class ExplodingToolRunner:
        def __init__(self):
            self.calls = []

        async def execute(self, tool_name: str, arguments: dict):
            self.calls.append((tool_name, arguments))
            raise AssertionError("cached prior evidence should avoid executing the tool")

    async def run() -> None:
        planner = RepeatToolPlanner()
        tool_runner = ExplodingToolRunner()
        runtime = AgentLoopRuntime(
            planner=planner,
            tool_runner=tool_runner,
            max_steps=3,
        )
        state = AgentRunState(
            question="继续说第二页的创新。",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={
                "prior_evidence": [
                    {
                        "tool_name": "get_page_content",
                        "arguments": {"doc_id": "doc-alpha", "pages": "2"},
                        "doc_id": "doc-alpha",
                        "doc_name": "alpha.pdf",
                        "page": 2,
                        "snippet": "上一轮已经读取过的页面证据。",
                        "result": {
                            "doc_id": "doc-alpha",
                            "doc_name": "alpha.pdf",
                            "items": [{"page": 2, "text": "上一轮已经读取过的页面证据。"}],
                            "citations": [],
                        },
                    }
                ]
            },
        )

        events = [event async for event in runtime.stream(state)]
        reuse_events = [
            event for event in events if event.event_type == "progress" and event.payload.get("kind") == "reuse"
        ]

        assert tool_runner.calls == []
        assert len(reuse_events) == 1
        assert reuse_events[0].payload["message"] == "Using previous evidence."
        assert state.scope["observations"][-1]["evidence_sufficient"] is True
        assert events[-1].event_type == "answer_delta"

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
