from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval_planner import RetrievalPlanner, RetrievalRoute


def test_selected_document_question_inspects_structure_first() -> None:
    plan = RetrievalPlanner().plan(
        question="summarize renewal risk",
        document_ids=["doc-a"],
    )

    assert plan.route == RetrievalRoute.SELECTED_DOCUMENT
    assert plan.steps[0].tool_name == "get_document_structure"
    assert plan.steps[0].arguments == {"doc_id": "doc-a", "compact": True}
    assert plan.scope.strict_scope is True


def test_selected_folder_question_uses_folder_scoped_search() -> None:
    plan = RetrievalPlanner().plan(
        question="what changed in this folder",
        folder_id="folder-a",
        include_subfolders=True,
    )

    assert plan.route == RetrievalRoute.SELECTED_FOLDER
    assert plan.steps[0].tool_name == "find_related_documents"
    assert plan.steps[0].arguments["folder_id"] == "folder-a"
    assert plan.steps[0].arguments["include_subfolders"] is True
    assert plan.steps[0].arguments["strict_scope"] is True


def test_global_question_searches_current_user_library() -> None:
    plan = RetrievalPlanner().plan(question="find alpha")

    assert plan.route == RetrievalRoute.USER_LIBRARY
    assert plan.steps[0].tool_name == "find_related_documents"
    assert plan.steps[0].arguments["strict_scope"] is False


def test_table_query_uses_table_aggregation_route() -> None:
    plan = RetrievalPlanner().plan(
        question="count rows by department",
        document_ids=["doc-a", "doc-b"],
    )

    assert plan.route == RetrievalRoute.TABLE_AGGREGATION
    assert plan.steps[0].tool_name == "find_related_documents"
    assert plan.steps[0].arguments["document_ids"] == ["doc-a", "doc-b"]


def test_low_confidence_route_keeps_agent_fallback() -> None:
    plan = RetrievalPlanner().plan(question="")

    assert plan.route == RetrievalRoute.AGENT_FALLBACK
    assert plan.steps == []


def test_strict_scope_false_records_current_user_expansion() -> None:
    plan = RetrievalPlanner().plan(
        question="find related risk",
        document_ids=["doc-a"],
        strict_scope=False,
    )

    assert plan.route == RetrievalRoute.USER_LIBRARY
    assert plan.scope.expanded_to_user_library is True
    assert plan.steps[0].arguments["strict_scope"] is False
