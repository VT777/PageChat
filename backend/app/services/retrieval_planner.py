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
            arguments = self._browse_arguments(question, scope)
            return RetrievalPlan(
                route=RetrievalRoute.TABLE_AGGREGATION,
                scope=scope,
                steps=[
                    RetrievalStep(
                        tool_name="browse_documents",
                        arguments=arguments,
                        reason="Identify scoped table documents before aggregation without exposing retrieval internals.",
                    )
                ],
            )

        if selected_docs and effective_strict:
            if len(selected_docs) == 1 and not folder_id:
                if self._is_locating_query(question):
                    return RetrievalPlan(
                        route=RetrievalRoute.SELECTED_DOCUMENT,
                        scope=scope,
                        steps=[
                            RetrievalStep(
                                tool_name="search_within_document",
                                arguments={"doc_id": selected_docs[0], "query": question},
                                reason="Locate the most relevant pages or sections within the selected document before reading source pages.",
                            )
                        ],
                    )
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
                    tool_name="browse_documents",
                    arguments=self._browse_arguments(question, scope),
                    reason="Find candidate documents within the resolved scope without exposing retrieval internals.",
                )
            ],
        )

    @staticmethod
    def _browse_arguments(question: str, scope: RetrievalPlanScope) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {
            "query": question,
            "sort": "relevance",
        }
        if scope.folder_id:
            arguments["folder_id"] = scope.folder_id
        if scope.include_subfolders:
            arguments["recursive"] = True
        if scope.document_ids and scope.strict_scope:
            arguments["document_ids"] = scope.document_ids
        return arguments

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

    @staticmethod
    def _is_locating_query(question: str) -> bool:
        q = question.lower()
        english_patterns = [
            "where",
            "which page",
            "find",
            "locate",
            "mentioned",
            "contains",
        ]
        chinese_patterns = [
            "在哪",
            "哪一页",
            "哪页",
            "哪个章节",
            "提到",
            "出现",
            "查找",
            "搜索",
            "定位",
            "包含",
        ]
        return any(pattern in q for pattern in english_patterns) or any(
            pattern in question for pattern in chinese_patterns
        )
