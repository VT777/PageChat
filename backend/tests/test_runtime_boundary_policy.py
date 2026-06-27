import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_turn import ModelToolCall
from app.agent.runtime_boundary_policy import RuntimeBoundaryPolicy


def test_policy_allows_browse_documents_without_planning_route():
    policy = RuntimeBoundaryPolicy(tools=[{"function": {"name": "browse_documents"}}])
    call = ModelToolCall(id="call_1", name="browse_documents", arguments={})

    result = policy.validate_tool_call(call, scope={})

    assert result.allowed is True
    assert result.repaired_call.name == "browse_documents"
    assert result.repaired_call.arguments == {}


def test_policy_does_not_reject_final_answer_for_evidence_sufficiency():
    policy = RuntimeBoundaryPolicy(tools=[])

    assert not hasattr(policy, "validate_answer_evidence")


def test_policy_returns_tool_error_for_disabled_web_search():
    policy = RuntimeBoundaryPolicy(tools=[{"function": {"name": "web_search"}}])
    call = ModelToolCall(id="call_1", name="web_search", arguments={"query": "weather"})

    result = policy.validate_tool_call(
        call,
        scope={"web_search_enabled": False, "web_search_requested": True},
    )

    assert result.allowed is False
    assert result.tool_error["success"] is False
    assert "Web Search is disabled" in result.tool_error["error"]


def test_policy_repairs_unique_document_name_to_doc_id():
    policy = RuntimeBoundaryPolicy(tools=[{"function": {"name": "get_page_content"}}])
    call = ModelToolCall(
        id="call_1",
        name="get_page_content",
        arguments={"doc_name": "report.pdf", "pages": "2"},
    )

    result = policy.validate_tool_call(
        call,
        scope={
            "document_registry": [
                {"document_id": "doc-a", "document_name": "report.pdf"}
            ],
            "strict_scope": True,
        },
    )

    assert result.allowed is True
    assert result.repaired_call.arguments["doc_id"] == "doc-a"
    assert result.repaired_call.arguments["pages"] == "2"


def test_policy_rejects_doc_id_outside_selected_scope():
    policy = RuntimeBoundaryPolicy(tools=[{"function": {"name": "get_page_content"}}])
    call = ModelToolCall(
        id="call_1",
        name="get_page_content",
        arguments={"doc_id": "doc-b", "pages": "1"},
    )

    result = policy.validate_tool_call(
        call,
        scope={"document_ids": ["doc-a"], "strict_scope": True},
    )

    assert result.allowed is False
    assert "outside the selected scope" in result.tool_error["error"]
