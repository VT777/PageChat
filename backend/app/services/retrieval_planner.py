from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional


class RetrievalRoute(str, Enum):
    SELECTED_DOCUMENT = "selected_document"
    SELECTED_FOLDER = "selected_folder"
    USER_LIBRARY = "user_library"
    TABLE_AGGREGATION = "table_aggregation"
    AGENT_FALLBACK = "agent_fallback"


@dataclass
class RetrievalPlanScope:
    document_ids: List[str] = field(default_factory=list)
    folder_id: Optional[str] = None
    include_subfolders: bool = False
    strict_scope: bool = False
    expanded_to_user_library: bool = False


@dataclass
class RetrievalStep:
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class RetrievalPlan:
    route: RetrievalRoute
    steps: List[RetrievalStep] = field(default_factory=list)
    scope: RetrievalPlanScope = field(default_factory=RetrievalPlanScope)
    fallback_to_agent: bool = True


class RetrievalPlanner:
    def plan(
        self,
        question: str,
        document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
    ) -> RetrievalPlan:
        question = (question or "").strip()
        selected_docs = list(document_ids or [])

        if not question:
            return RetrievalPlan(route=RetrievalRoute.AGENT_FALLBACK)

        effective_strict = strict_scope
        if effective_strict is None:
            effective_strict = bool(selected_docs or folder_id)

        scope = RetrievalPlanScope(
            document_ids=selected_docs,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=bool(effective_strict),
            expanded_to_user_library=bool((selected_docs or folder_id) and not effective_strict),
        )

        if self._is_table_query(question):
            return RetrievalPlan(
                route=RetrievalRoute.TABLE_AGGREGATION,
                scope=scope,
                steps=[
                    RetrievalStep(
                        tool_name="find_related_documents",
                        arguments={
                            "query": question,
                            "document_ids": selected_docs or None,
                            "folder_id": folder_id,
                            "include_subfolders": include_subfolders,
                            "strict_scope": bool(effective_strict),
                        },
                        reason="Identify scoped table documents before aggregation.",
                    )
                ],
            )

        if selected_docs and effective_strict:
            if len(selected_docs) == 1 and not folder_id:
                return RetrievalPlan(
                    route=RetrievalRoute.SELECTED_DOCUMENT,
                    scope=scope,
                    steps=[
                        RetrievalStep(
                            tool_name="get_document_structure",
                            arguments={"doc_id": selected_docs[0], "compact": True},
                            reason="Inspect selected document structure first.",
                        )
                    ],
                )
            return self._search_plan(question, RetrievalRoute.SELECTED_DOCUMENT, scope)

        if folder_id and effective_strict:
            return self._search_plan(question, RetrievalRoute.SELECTED_FOLDER, scope)

        return self._search_plan(question, RetrievalRoute.USER_LIBRARY, scope)

    def _search_plan(
        self, question: str, route: RetrievalRoute, scope: RetrievalPlanScope
    ) -> RetrievalPlan:
        return RetrievalPlan(
            route=route,
            scope=scope,
            steps=[
                RetrievalStep(
                    tool_name="find_related_documents",
                    arguments={
                        "query": question,
                        "document_ids": scope.document_ids or None,
                        "folder_id": scope.folder_id,
                        "include_subfolders": scope.include_subfolders,
                        "strict_scope": scope.strict_scope,
                    },
                    reason="Find candidate documents within the resolved scope.",
                )
            ],
        )

    @staticmethod
    def _is_table_query(question: str) -> bool:
        q = question.lower()
        english_keywords = [
            "count",
            "sum",
            "avg",
            "average",
            "group by",
            "total",
        ]
        chinese_keywords = [
            "统计",
            "汇总",
            "总数",
            "平均",
            "分组",
            "多少",
        ]
        return any(re.search(rf"\b{re.escape(k)}\b", q) for k in english_keywords) or any(
            k in q for k in chinese_keywords
        )
