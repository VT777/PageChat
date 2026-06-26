import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.planner import StructuredLLMPlanner  # noqa: E402
from app.agent.state import AgentRunState  # noqa: E402


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "view_folder_structure",
                "description": "View folders",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browse_documents",
                "description": "Browse documents",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


class _ChunkStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=self.chunks.pop(0))
                )
            ]
        )


def test_structured_planner_parses_model_generated_call_tool_action() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return _response(
                """
                {
                  "thought": "我先查看资料库目录，判断资料可能在哪个文件夹。",
                  "action": {
                    "type": "call_tool",
                    "tool_name": "view_folder_structure",
                    "arguments": {"folder_id": "root"}
                  }
                }
                """
            )

        planner = StructuredLLMPlanner(
            completion_fn=fake_completion,
            tools=_tools(),
            user_id="user-a",
        )
        state = AgentRunState(
            question="重庆师范大学有什么 AI 应用创新？",
            conversation_id="conv-a",
            run_id="run-a",
            message_id="msg-a",
            scope={"user_id": "user-a"},
        )

        action = await planner.next_action(state)

        assert action.action_type == "call_tool"
        assert action.tool_name == "view_folder_structure"
        assert action.arguments == {"folder_id": "root"}
        assert action.thought == "我先查看资料库目录，判断资料可能在哪个文件夹。"
        assert calls[0]["scenario"] == "qa"
        assert calls[0]["stream"] is False
        assert calls[0]["user_id"] == "user-a"
        assert calls[0]["disable_thinking"] is True

    asyncio.run(run())


def test_structured_planner_prompt_keeps_visible_notes_natural() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return _response(
                """
                {
                  "thought": "我先看一下资料库，确认有哪些可用文档。",
                  "action": {"type": "call_tool", "tool_name": "browse_documents", "arguments": {"recursive": true}}
                }
                """
            )

        planner = StructuredLLMPlanner(completion_fn=fake_completion, tools=_tools())
        state = AgentRunState(
            question="现在有哪些文档？",
            conversation_id="conv-a",
            run_id="run-a",
            message_id="msg-a",
        )

        await planner.next_action(state)

        system_prompt = calls[0]["messages"][0]["content"]
        assert "sound natural, calm, and helpful" in system_prompt
        assert "Do not narrate implementation details" in system_prompt
        assert "avoid robotic phrases" in system_prompt

    asyncio.run(run())


def test_structured_planner_streams_thought_before_final_action() -> None:
    async def run() -> None:
        async def fake_completion(**kwargs):
            assert kwargs["stream"] is True
            assert kwargs["disable_thinking"] is True
            return _ChunkStream(
                [
                    '{"thought":"我先',
                    '查看资料库目录',
                    '。","action":{"type":"call_tool","tool_name":"view_folder_structure","arguments":{}}}',
                ]
            )

        planner = StructuredLLMPlanner(
            completion_fn=fake_completion,
            tools=_tools(),
        )
        state = AgentRunState(
            question="有哪些文档？",
            conversation_id="conv-a",
            run_id="run-a",
            message_id="msg-a",
        )

        events = [event async for event in planner.stream_next_action(state)]

        assert events[0] == {"type": "thought", "message": "我先"}
        assert events[1] == {"type": "thought", "message": "我先查看资料库目录"}
        assert events[2] == {"type": "thought", "message": "我先查看资料库目录。"}
        assert events[-1].action_type == "call_tool"
        assert events[-1].tool_name == "view_folder_structure"

    asyncio.run(run())


def test_structured_planner_retries_invalid_json_once() -> None:
    async def run() -> None:
        responses = [
            _response("I will browse the library first."),
            _response(
                """```json
                {
                  "thought": "上一次格式不对，我重新按结构选择查看目录。",
                  "action": {"type": "call_tool", "tool_name": "view_folder_structure", "arguments": {}}
                }
                ```"""
            ),
        ]
        prompts = []

        async def fake_completion(**kwargs):
            prompts.append(kwargs["messages"][-1]["content"])
            return responses.pop(0)

        planner = StructuredLLMPlanner(
            completion_fn=fake_completion,
            tools=_tools(),
            max_retries=1,
        )
        state = AgentRunState(
            question="找一下资料库里的重庆案例",
            conversation_id="conv-a",
            run_id="run-a",
            message_id="msg-a",
        )

        action = await planner.next_action(state)

        assert action.action_type == "call_tool"
        assert action.thought == "上一次格式不对，我重新按结构选择查看目录。"
        assert len(prompts) == 2
        assert "previous planner output was invalid JSON" in prompts[1]

    asyncio.run(run())


def test_structured_planner_parses_answer_action_without_template_text() -> None:
    async def run() -> None:
        async def fake_completion(**_kwargs):
            return _response(
                """
                {
                  "thought": "我已经有页面证据，可以直接回答。",
                  "action": {
                    "type": "answer",
                    "content": "重庆师范大学案例强调 AI 辅助教学和治理。"
                  }
                }
                """
            )

        planner = StructuredLLMPlanner(completion_fn=fake_completion, tools=_tools())
        state = AgentRunState(
            question="重庆师范大学有什么 AI 应用创新？",
            conversation_id="conv-a",
            run_id="run-a",
            message_id="msg-a",
        )

        action = await planner.next_action(state)

        assert action.action_type == "answer"
        assert action.content == "重庆师范大学案例强调 AI 辅助教学和治理。"
        assert action.thought == "我已经有页面证据，可以直接回答。"

    asyncio.run(run())
