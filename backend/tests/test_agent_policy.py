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
        {"type": "function", "function": {"name": "get_page_image"}},
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


def test_policy_repairs_filename_doc_id_from_document_registry() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(
        PlannerAction.call_tool(
            "search_within_document",
            {"doc_id": "alpha.pdf", "query": "revenue"},
        ),
        _state(
            document_registry=[
                {"document_id": "doc-alpha", "document_name": "alpha.pdf"},
                {"document_id": "doc-beta", "document_name": "beta.pdf"},
            ],
            available_document_ids=["doc-alpha", "doc-beta"],
        ),
    )

    assert result.allowed is True
    assert result.action is not None
    assert result.action.arguments == {"doc_id": "doc-alpha", "query": "revenue"}


def test_policy_rejects_unknown_doc_id_with_recoverable_next_steps() -> None:
    policy = AgentPolicy(tools=_tools())
    result = policy.validate(
        PlannerAction.call_tool(
            "get_page_content",
            {"doc_id": "missing.pdf", "pages": "1"},
        ),
        _state(
            document_registry=[
                {"document_id": "doc-alpha", "document_name": "alpha.pdf"},
                {"document_id": "doc-beta", "document_name": "beta.pdf"},
            ],
            available_document_ids=["doc-alpha", "doc-beta"],
        ),
    )

    assert result.allowed is False
    assert result.observation is not None
    assert result.observation["kind"] == "guardrail"
    assert "missing.pdf" in result.observation["message"]
    assert result.observation["next_steps"] == [
        "Use browse_documents or choose a valid doc_id from the selected document list."
    ]


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
    assert "Decide what information is missing" in result.observation["message"]
    assert "Read document structure" not in result.observation["message"]
    assert "search within a selected document" not in result.observation["message"]
    assert "fetch page/image evidence" not in result.observation["message"]


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


def test_policy_allows_folder_count_answer_from_selected_scope_summary() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="这里有多少文件？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "folder_id": "folder-a",
            "include_subfolders": True,
            "strict_scope": True,
            "selected_scope_summary": {
                "type": "folder",
                "folder_id": "folder-a",
                "folder_name": "AI_Knowledge",
                "include_subfolders": True,
                "document_count": 3,
            },
        },
    )

    result = policy.validate(
        PlannerAction.answer("当前文件夹下共有 3 个文件。"),
        state,
    )

    assert result.allowed is True


def test_policy_allows_answer_from_prior_page_evidence() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="继续说明第二页的创新。",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "document_ids": ["doc-alpha"],
            "strict_scope": True,
            "prior_evidence": [
                {
                    "tool_name": "get_page_content",
                    "arguments": {"doc_id": "doc-alpha", "pages": "2"},
                    "doc_id": "doc-alpha",
                    "doc_name": "alpha.pdf",
                    "page": 2,
                    "snippet": "第二页已经读取过的证据。",
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("基于上一轮第二页证据回答。"),
        state,
    )

    assert result.allowed is True


def test_policy_allows_overview_answer_after_browse_metadata() -> None:
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

    assert result.allowed is True


def test_policy_allows_overview_answer_after_document_structure() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="第一个文档主要讲什么？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "document_ids": ["doc-a"],
            "strict_scope": True,
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "get_document_structure",
                    "message": "Read structure for alpha.pdf.",
                    "candidate_document_ids": ["doc-a"],
                    "candidate_pages": [1, 2, 3],
                    "evidence_sufficient": False,
                }
            ],
            "evidence_pack": [
                {
                    "tool_name": "get_document_structure",
                    "doc_id": "doc-a",
                    "doc_name": "alpha.pdf",
                    "total_pages": 12,
                    "structure": [
                        {"title": "背景", "start_page": 1},
                        {"title": "方案", "start_page": 5},
                    ],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("它主要介绍项目背景和方案。"),
        state,
    )

    assert result.allowed is True


def test_policy_blocks_specific_fact_answer_after_structure_only() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="重庆师范大学具体创新点是什么？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "document_ids": ["doc-a"],
            "strict_scope": True,
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "get_document_structure",
                    "message": "Read structure for alpha.pdf.",
                    "candidate_document_ids": ["doc-a"],
                    "candidate_pages": [3],
                    "evidence_sufficient": False,
                }
            ],
            "evidence_pack": [
                {
                    "tool_name": "get_document_structure",
                    "doc_id": "doc-a",
                    "doc_name": "alpha.pdf",
                    "total_pages": 12,
                    "structure": [{"title": "重庆师范大学", "start_page": 3}],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("具体创新点包括智能问答和数据治理。"),
        state,
    )

    assert result.allowed is False


def test_policy_blocks_answer_after_visual_only_page_content() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="前两页主要讲什么？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "document_ids": ["doc-a"],
            "strict_scope": True,
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "get_page_content",
                    "message": "Fetched page evidence.",
                    "evidence_sufficient": True,
                    "visual_evidence_required": True,
                    "items": [
                        {
                            "page": 1,
                            "visual_evidence_required": True,
                            "text_omitted_reason": "visual_evidence_required",
                        }
                    ],
                }
            ],
            "evidence_pack": [
                {
                    "tool_name": "get_page_content",
                    "items": [
                        {
                            "page": 1,
                            "visual_evidence_required": True,
                            "text_omitted_reason": "visual_evidence_required",
                        }
                    ],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("前两页主要是封面和目录。"),
        state,
    )

    assert result.allowed is False
    assert result.observation is not None
    assert "visual_evidence_required" in result.observation["message"]
    assert "image-capable tool" in result.observation["message"]
    assert "Read document structure" not in result.observation["message"]


def test_policy_allows_answer_after_page_image_evidence() -> None:
    policy = AgentPolicy(tools=_tools())
    state = AgentRunState(
        question="前两页主要讲什么？",
        conversation_id="conv-a",
        run_id="run-a",
        message_id="msg-a",
        scope={
            "document_ids": ["doc-a"],
            "strict_scope": True,
            "observations": [
                {
                    "kind": "observation",
                    "tool_name": "get_page_image",
                    "message": "Fetched page image.",
                    "evidence_sufficient": True,
                    "candidate_pages": [1],
                }
            ],
        },
    )

    result = policy.validate(
        PlannerAction.answer("前两页主要是封面和目录。"),
        state,
    )

    assert result.allowed is True
