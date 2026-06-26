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


def test_selected_document_locating_query_uses_search_within_document_first() -> None:
    plan = RetrievalPlanner().plan(
        question="在哪一页提到了华东收入增长？",
        document_ids=["doc-a"],
        strict_scope=True,
    )

    assert plan.route == RetrievalRoute.SELECTED_DOCUMENT
    assert plan.steps[0].tool_name == "search_within_document"
    assert plan.steps[0].arguments == {
        "doc_id": "doc-a",
        "query": "在哪一页提到了华东收入增长？",
    }
    assert plan.fallback_to_agent is True


def test_selected_document_summary_still_inspects_structure_first() -> None:
    plan = RetrievalPlanner().plan(
        question="总结这份文档的主要内容",
        document_ids=["doc-a"],
        strict_scope=True,
    )

    assert plan.steps[0].tool_name == "get_document_structure"


def test_selected_folder_question_uses_folder_scoped_search() -> None:
    plan = RetrievalPlanner().plan(
        question="what changed in this folder",
        folder_id="folder-a",
        include_subfolders=True,
    )

    assert plan.route == RetrievalRoute.SELECTED_FOLDER
    assert plan.steps[0].tool_name == "browse_documents"
    assert plan.steps[0].arguments["query"] == "what changed in this folder"
    assert plan.steps[0].arguments["folder_id"] == "folder-a"
    assert plan.steps[0].arguments["recursive"] is True
    assert plan.steps[0].arguments["sort"] == "relevance"


def test_empty_semantic_folder_ids_do_not_trigger_document_search() -> None:
    for folder_id in ["", "root", "null", "undefined", " ROOT "]:
        plan = RetrievalPlanner().plan(
            question="\u4f60\u597d",
            folder_id=folder_id,
            include_subfolders=True,
        )

        assert plan.route == RetrievalRoute.AGENT_FALLBACK
        assert plan.steps == []
        assert plan.scope.folder_id is None


def test_global_document_question_searches_current_user_library() -> None:
    plan = RetrievalPlanner().plan(question="find alpha in uploaded documents")

    assert plan.route == RetrievalRoute.USER_LIBRARY
    assert plan.steps[0].tool_name == "browse_documents"
    assert plan.steps[0].arguments["query"] == "find alpha in uploaded documents"
    assert "strict_scope" not in plan.steps[0].arguments


def test_general_non_document_tasks_do_not_search_current_user_library() -> None:
    for question in [
        "find restaurants in Beijing",
        "analyze this idea",
        "write content for my website",
        "how do I file taxes",
        "write a file upload feature",
        "recommend a documentary film",
        "what is a PDF",
    ]:
        plan = RetrievalPlanner().plan(question=question)

        assert plan.route == RetrievalRoute.AGENT_FALLBACK
        assert plan.steps == []


def test_explicit_document_context_searches_current_user_library() -> None:
    for question in [
        "summarize this document",
        "what does the uploaded file mention",
        "according to the document, what changed",
    ]:
        plan = RetrievalPlanner().plan(question=question)

        assert plan.route == RetrievalRoute.USER_LIBRARY
        assert plan.steps[0].tool_name == "browse_documents"


def test_general_greeting_does_not_search_current_user_library() -> None:
    plan = RetrievalPlanner().plan(question="\u4f60\u597d")

    assert plan.route == RetrievalRoute.AGENT_FALLBACK
    assert plan.steps == []


def test_explicit_empty_document_scope_does_not_search_current_user_library() -> None:
    plan = RetrievalPlanner().plan(
        question="summarize selected document",
        document_ids=[],
        strict_scope=True,
    )

    assert plan.route == RetrievalRoute.AGENT_FALLBACK
    assert plan.steps == []


def test_table_query_without_document_context_does_not_search_current_user_library() -> None:
    for kwargs in [
        {"question": "count rows by department"},
        {"question": "count rows by department", "document_ids": []},
    ]:
        plan = RetrievalPlanner().plan(**kwargs)

        assert plan.route == RetrievalRoute.AGENT_FALLBACK
        assert plan.steps == []


def test_table_query_uses_table_aggregation_route() -> None:
    plan = RetrievalPlanner().plan(
        question="count rows by department",
        document_ids=["doc-a", "doc-b"],
    )

    assert plan.route == RetrievalRoute.TABLE_AGGREGATION
    assert plan.steps[0].tool_name == "browse_documents"
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
    assert plan.steps[0].tool_name == "browse_documents"
    assert "document_ids" not in plan.steps[0].arguments


def test_strict_scope_false_folder_expands_without_folder_filter() -> None:
    plan = RetrievalPlanner().plan(
        question="find related risk",
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=False,
    )

    assert plan.route == RetrievalRoute.USER_LIBRARY
    assert plan.scope.expanded_to_user_library is True
    assert plan.steps[0].tool_name == "browse_documents"
    assert "folder_id" not in plan.steps[0].arguments
    assert "recursive" not in plan.steps[0].arguments
