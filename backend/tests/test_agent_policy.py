from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.loop_runtime import PlannerAction  # noqa: E402
from app.agent.policy import AgentPolicy  # noqa: E402
from app.agent.state import AgentRunState  # noqa: E402


def _tools():
    return [
        {"type": "function", "function": {"name": "view_folder_structure"}},
        {"type": "function", "function": {"name": "browse_documents"}},
        {"type": "function", "function": {"name": "get_document_structure"}},
        {"type": "function", "function": {"name": "get_page_content"}},
        {"type": "function", "function": {"name": "search_within_document"}},
        {"type": "function", "function": {"name": "web_search"}},
    ]


def _state(**scope):
    return AgentRunState(
        question="重庆师范大学有什么 AI 应用创新？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope=scope,
    )


def test_policy_rejects_unknown_tool() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(PlannerAction.call_tool("delete_everything", {}), _state())

    assert result.allowed is False
    assert result.observation is not None
    assert result.observation["kind"] == "guardrail"
    assert "delete_everything" in result.observation["message"]


def test_policy_injects_single_selected_doc_id() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(
        PlannerAction.call_tool("get_document_structure", {"compact": True}),
        _state(document_ids=["doc-alpha"], strict_scope=True),
    )

    assert result.allowed is True
    assert result.action is not None
    assert result.action.arguments == {"compact": True, "doc_id": "doc-alpha"}


def test_policy_blocks_web_search_when_disabled() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(
        PlannerAction.call_tool("web_search", {"query": "北京天气"}),
        _state(web_search_requested=False, web_search_enabled=False),
    )

    assert result.allowed is False
    assert result.observation is not None
    assert "Web Search" in result.observation["message"]


def test_policy_blocks_repeated_same_tool_signature() -> None:
    policy = AgentPolicy(tools=_tools())
    state = _state()
    action = PlannerAction.call_tool("view_folder_structure", {})

    first = policy.validate(action, state)
    assert first.allowed is True
    policy.mark_tool_executed(first.action)

    second = policy.validate(action, state)
    assert second.allowed is False
    assert second.observation is not None
    assert "repeated" in second.observation["message"].lower()


def test_policy_blocks_document_answer_without_evidence() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(
        PlannerAction.answer("重庆师范大学做了很多 AI 创新。"),
        _state(document_ids=["doc-alpha"], strict_scope=True),
    )

    assert result.allowed is False
    assert result.observation is not None
    assert "evidence" in result.observation["message"].lower()


def test_policy_allows_document_answer_with_sufficient_evidence() -> None:
    policy = AgentPolicy(tools=_tools())
    state = _state(document_ids=["doc-alpha"], strict_scope=True)
    state.scope["observations"] = [
        {
            "kind": "observation",
            "tool_name": "get_page_content",
            "message": "Fetched page evidence.",
            "evidence_sufficient": True,
        }
    ]

    result = policy.validate(
        PlannerAction.answer("重庆师范大学做了很多 AI 创新。"),
        state,
    )

    assert result.allowed is True


def test_policy_allows_library_inventory_answer_from_browse_metadata() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="现在有哪些文档",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "browse_documents",
                    "message": "Found 2 candidate document(s) and 0 folder(s).",
                    "candidate_document_ids": ["doc-a", "doc-b"],
                    "evidence_sufficient": False,
                }
            ],
            "evidence_pack": [
                {
                    "tool_name": "browse_documents",
                    "documents": [
                        {"doc_id": "doc-a", "name": "alpha.pdf"},
                        {"doc_id": "doc-b", "name": "beta.pdf"},
                    ],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("当前有 alpha.pdf 和 beta.pdf。"),
        state,
    )

    assert result.allowed is True


def test_policy_still_blocks_content_answer_after_browse_metadata_only() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="alpha.pdf 主要讲什么？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "browse_documents",
                    "message": "Found 1 candidate document(s) and 0 folder(s).",
                    "candidate_document_ids": ["doc-a"],
                    "evidence_sufficient": False,
                }
            ],
            "evidence_pack": [
                {
                    "tool_name": "browse_documents",
                    "documents": [{"doc_id": "doc-a", "name": "alpha.pdf"}],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("alpha.pdf 主要讲 AI 趋势。"),
        state,
    )

    assert result.allowed is False
