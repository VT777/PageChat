from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.agent.loop_runtime import PlannerAction
from app.agent.state import AgentRunState


@dataclass(frozen=True, slots=True)
class PolicyValidation:
    allowed: bool
    action: PlannerAction | None = None
    observation: dict[str, Any] | None = None


class AgentPolicy:
    """Validate planner decisions without turning validation into a route planner."""

    def __init__(self, *, tools: list[dict[str, Any]] | None = None) -> None:
        self.allowed_tools = {
            str(tool.get("function", {}).get("name"))
            for tool in tools or []
            if tool.get("function", {}).get("name")
        }
        self._executed_signatures: set[str] = set()

    def validate(self, action: PlannerAction, state: AgentRunState) -> PolicyValidation:
        if action.action_type == "call_tool":
            return self._validate_tool_call(action, state)
        if action.action_type == "answer":
            return self._validate_answer(action, state)
        if action.action_type in {"ask_clarification", "fail"}:
            return PolicyValidation(True, action=action)
        return self._reject(f"Unsupported action type: {action.action_type}")

    def mark_tool_executed(self, action: PlannerAction | None) -> None:
        if action is None or action.action_type != "call_tool":
            return
        self._executed_signatures.add(self._signature(action.tool_name, action.arguments))

    def _validate_tool_call(
        self,
        action: PlannerAction,
        state: AgentRunState,
    ) -> PolicyValidation:
        if self.allowed_tools and action.tool_name not in self.allowed_tools:
            return self._reject(
                f"Tool '{action.tool_name}' is not available. Choose one of: "
                f"{', '.join(sorted(self.allowed_tools))}."
            )
        if action.tool_name == "web_search" and not (
            state.scope.get("web_search_requested") and state.scope.get("web_search_enabled")
        ):
            return self._reject(
                "Web Search is not available for this question. Answer from available context "
                "or ask the user to enable Web Search."
            )

        patched = self._patch_scope_arguments(action, state)
        invalid_reference = self._invalid_document_reference(patched, state)
        if invalid_reference:
            return self._reject(
                (
                    f"Document reference '{invalid_reference}' is not available in the "
                    "current selected document scope."
                ),
                next_steps=[
                    "Use browse_documents or choose a valid doc_id from the selected document list."
                ],
            )
        signature = self._signature(patched.tool_name, patched.arguments)
        if signature in self._executed_signatures:
            return self._reject(
                f"Repeated tool call rejected: {patched.tool_name} with the same arguments. "
                "Use the observation to choose a different tool, refine arguments, or answer if evidence is sufficient."
            )
        return PolicyValidation(True, action=patched)

    def _validate_answer(
        self,
        action: PlannerAction,
        state: AgentRunState,
    ) -> PolicyValidation:
        if not self._requires_document_evidence(state):
            return PolicyValidation(True, action=action)
        if self._has_sufficient_evidence(state):
            return PolicyValidation(True, action=action)
        if self._has_sufficient_metadata_evidence(state):
            return PolicyValidation(True, action=action)
        if self._has_visual_evidence_gap(state):
            return self._reject(
                "The available page evidence is marked visual_evidence_required. "
                "Use an image-capable tool before making visual or layout-dependent claims."
            )
        return self._reject(
            "The final answer needs source evidence. Decide what information is missing "
            "and choose an available tool or ask a clarification."
        )

    def _patch_scope_arguments(
        self,
        action: PlannerAction,
        state: AgentRunState,
    ) -> PlannerAction:
        args = dict(action.arguments or {})
        doc_ids = list(state.scope.get("document_ids") or [])
        preferred_doc_ids = list(state.scope.get("preferred_document_ids") or [])
        single_doc_id = None
        if len(preferred_doc_ids) == 1:
            single_doc_id = str(preferred_doc_ids[0])
        elif len(doc_ids) == 1:
            single_doc_id = str(doc_ids[0])

        if action.tool_name in {
            "get_document_structure",
            "get_page_content",
            "get_page_image",
            "search_within_document",
        } and single_doc_id and not args.get("doc_id"):
            args["doc_id"] = single_doc_id

        if action.tool_name == "get_document_image" and single_doc_id and not args.get("doc_id") and not args.get("image_path"):
            args["doc_id"] = single_doc_id

        if action.tool_name in self._document_reference_tools():
            canonical_doc_id = self._resolve_document_reference(args.get("doc_id"), state)
            if canonical_doc_id:
                args["doc_id"] = canonical_doc_id
            elif not args.get("doc_id") and args.get("doc_name"):
                canonical_doc_id = self._resolve_document_reference(args.get("doc_name"), state)
                if canonical_doc_id:
                    args["doc_id"] = canonical_doc_id

        strict_scope = state.scope.get("strict_scope") is not False
        folder_id = state.scope.get("folder_id")
        if action.tool_name == "browse_documents" and strict_scope:
            if doc_ids and not args.get("document_ids"):
                args["document_ids"] = doc_ids
            if folder_id and not args.get("folder_id"):
                args["folder_id"] = folder_id
            if state.scope.get("include_subfolders") and "recursive" not in args:
                args["recursive"] = True

        if args == action.arguments:
            return action
        return PlannerAction.call_tool(
            action.tool_name,
            args,
            thought=action.thought,
        )

    def _document_reference_tools(self) -> set[str]:
        return {
            "get_document_structure",
            "get_page_content",
            "get_page_image",
            "get_document_image",
            "search_within_document",
        }

    def _invalid_document_reference(
        self,
        action: PlannerAction,
        state: AgentRunState,
    ) -> str:
        if action.tool_name not in self._document_reference_tools():
            return ""
        reference = action.arguments.get("doc_id")
        if reference in (None, ""):
            return ""
        if self._resolve_document_reference(reference, state):
            return ""
        if self._has_document_reference_context(state):
            return str(reference)
        return ""

    def _resolve_document_reference(
        self,
        reference: Any,
        state: AgentRunState,
    ) -> str:
        if reference in (None, ""):
            return ""
        text = str(reference).strip()
        if not text:
            return ""

        allowed_ids = self._known_document_ids(state)
        if text in allowed_ids:
            return text

        matches: list[str] = []
        lowered = text.lower()
        for item in self._document_registry(state):
            doc_id = str(item.get("document_id") or item.get("doc_id") or item.get("id") or "")
            if not doc_id:
                continue
            names = {
                str(item.get("document_name") or ""),
                str(item.get("doc_name") or ""),
                str(item.get("name") or ""),
                str(item.get("original_name") or ""),
            }
            if lowered in {name.lower() for name in names if name}:
                matches.append(doc_id)
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
        return ""

    def _known_document_ids(self, state: AgentRunState) -> set[str]:
        ids = {str(doc_id) for doc_id in state.scope.get("available_document_ids") or [] if doc_id}
        for doc_id in state.scope.get("document_ids") or []:
            if doc_id:
                ids.add(str(doc_id))
        for doc_id in state.scope.get("preferred_document_ids") or []:
            if doc_id:
                ids.add(str(doc_id))
        for item in self._document_registry(state):
            doc_id = item.get("document_id") or item.get("doc_id") or item.get("id")
            if doc_id:
                ids.add(str(doc_id))
        return ids

    def _document_registry(self, state: AgentRunState) -> list[dict[str, Any]]:
        registry = state.scope.get("document_registry")
        if not isinstance(registry, list):
            return []
        return [item for item in registry if isinstance(item, dict)]

    def _has_document_reference_context(self, state: AgentRunState) -> bool:
        return bool(
            state.scope.get("available_document_ids")
            or state.scope.get("document_ids")
            or state.scope.get("preferred_document_ids")
            or self._document_registry(state)
        )

    def _requires_document_evidence(self, state: AgentRunState) -> bool:
        if state.scope.get("document_ids") or state.scope.get("folder_id"):
            return True
        if state.tool_results:
            return True
        observations = state.scope.get("observations") or []
        return any(
            observation.get("tool_name")
            in {
                "browse_documents",
                "get_document_structure",
                "get_page_content",
                "get_page_image",
                "get_document_image",
                "search_within_document",
                "aggregate_tables",
            }
            for observation in observations
            if isinstance(observation, dict)
        )

    def _has_sufficient_evidence(self, state: AgentRunState) -> bool:
        for observation in state.scope.get("observations") or []:
            if (
                isinstance(observation, dict)
                and observation.get("evidence_sufficient")
                and self._evidence_entry_is_sufficient(observation)
            ):
                return True
        for evidence in list(state.scope.get("evidence_pack") or []) + list(
            state.scope.get("prior_evidence") or []
        ):
            if not isinstance(evidence, dict):
                continue
            if self._evidence_entry_is_sufficient(evidence):
                return True
        return False

    def _has_sufficient_metadata_evidence(self, state: AgentRunState) -> bool:
        overview_question = self._is_overview_question(state.question)
        inventory_question = self._is_library_inventory_question(state.question)
        if not (overview_question or inventory_question):
            return False
        selected_scope_summary = state.scope.get("selected_scope_summary")
        if (
            isinstance(selected_scope_summary, dict)
            and self._is_library_count_question(state.question)
            and isinstance(selected_scope_summary.get("document_count"), int)
        ):
            return True
        tool_names = {
            item.get("tool_name")
            for item in (state.scope.get("observations") or [])
            if isinstance(item, dict)
        }
        tool_names.update(
            item.get("tool_name")
            for item in (state.scope.get("evidence_pack") or [])
            if isinstance(item, dict)
        )
        if inventory_question and tool_names & {"browse_documents", "view_folder_structure"}:
            return True
        if overview_question and tool_names & {"browse_documents", "get_document_structure"}:
            return True
        return False

    def _has_visual_evidence_gap(self, state: AgentRunState) -> bool:
        entries: list[Any] = []
        entries.extend(state.scope.get("observations") or [])
        entries.extend(state.scope.get("evidence_pack") or [])
        entries.extend(state.scope.get("prior_evidence") or [])
        return any(
            isinstance(entry, dict) and self._entry_mentions_visual_required(entry)
            for entry in entries
        )

    def _entry_mentions_visual_required(self, entry: dict[str, Any]) -> bool:
        if entry.get("visual_evidence_required") is True:
            return True
        if entry.get("text_omitted_reason") == "visual_evidence_required":
            return True
        for key in ("items", "pages", "content", "matches", "results"):
            value = entry.get(key)
            if isinstance(value, list) and any(
                isinstance(item, dict) and self._entry_mentions_visual_required(item)
                for item in value
            ):
                return True
        data = entry.get("data")
        if isinstance(data, dict):
            return self._entry_mentions_visual_required(data)
        return False

    def _evidence_entry_is_sufficient(self, entry: dict[str, Any]) -> bool:
        tool_name = entry.get("tool_name")
        if tool_name == "get_page_content":
            return self._page_content_entry_has_readable_evidence(entry)
        if tool_name in {
            "get_page_image",
            "get_document_image",
            "web_search",
            "search_within_document",
            "aggregate_tables",
        }:
            return True
        return False

    def _page_content_entry_has_readable_evidence(self, entry: dict[str, Any]) -> bool:
        if self._has_readable_content(entry):
            return True
        items = self._page_content_items(entry)
        if items:
            return any(self._page_content_item_has_readable_evidence(item) for item in items)
        if entry.get("visual_evidence_required") is True:
            return False
        return bool(entry.get("evidence_sufficient"))

    def _page_content_item_has_readable_evidence(self, item: Any) -> bool:
        if not isinstance(item, dict):
            return bool(str(item or "").strip())
        if self._has_readable_content(item):
            return True
        if item.get("visual_evidence_required") is True:
            return False
        if item.get("text_omitted_reason") == "visual_evidence_required":
            return False
        return bool(item.get("text") or item.get("snippet"))

    def _has_readable_content(self, entry: dict[str, Any]) -> bool:
        for key in (
            "text",
            "snippet",
            "content_preview",
            "markdown",
            "structured_content",
        ):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, (list, dict)) and value:
                return True
        for key in ("tables", "table", "rows"):
            value = entry.get(key)
            if isinstance(value, (list, dict)) and value:
                return True
        return False

    def _page_content_items(self, entry: dict[str, Any]) -> list[Any]:
        for key in ("items", "pages", "content"):
            value = entry.get(key)
            if isinstance(value, list):
                return value
        data = entry.get("data")
        if isinstance(data, dict):
            for key in ("items", "pages", "content"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _is_overview_question(self, question: str) -> bool:
        text = (question or "").strip().lower()
        if not text or self._is_specific_fact_question(text):
            return False
        zh_overview_hints = (
            "主要讲",
            "主要内容",
            "讲什么",
            "概括",
            "总结",
            "整体介绍",
            "总体介绍",
            "文档介绍",
            "有哪些章节",
            "章节",
            "目录",
        )
        en_overview_hints = (
            "overview",
            "summary",
            "summarize",
            "mainly about",
            "what is this document about",
            "what is the document about",
            "chapters",
            "sections",
            "outline",
        )
        return any(hint in text for hint in zh_overview_hints) or any(
            hint in text for hint in en_overview_hints
        )

    def _is_specific_fact_question(self, text: str) -> bool:
        zh_specific_hints = (
            "具体",
            "详细",
            "第几页",
            "哪一页",
            "第 43 页",
            "第43页",
            "创新点",
            "金额",
            "日期",
            "参数",
        )
        en_specific_hints = (
            "specific",
            "detail",
            "details",
            "which page",
            "what page",
            "page ",
            "exact",
        )
        return any(hint in text for hint in zh_specific_hints) or any(
            hint in text for hint in en_specific_hints
        )

    def _is_library_inventory_question(self, question: str) -> bool:
        text = (question or "").strip().lower()
        if not text:
            return False
        zh_inventory_hints = (
            "有哪些文档",
            "有哪些文件",
            "有哪些资料",
            "有什么文档",
            "有什么文件",
            "当前文档",
            "当前文件",
            "现在有哪些",
            "列出文档",
            "列一下文档",
            "文档列表",
            "文件列表",
            "有哪些文件夹",
            "有什么文件夹",
            "文件夹列表",
            "多少文件",
            "几个文件",
            "多少文档",
            "几个文档",
            "有多少文件",
            "有多少文档",
        )
        en_inventory_hints = (
            "what documents",
            "which documents",
            "available documents",
            "list documents",
            "show documents",
            "what files",
            "which files",
            "available files",
            "list files",
            "show files",
            "what folders",
            "which folders",
            "available folders",
            "list folders",
            "how many files",
            "how many documents",
        )
        return any(hint in text for hint in zh_inventory_hints) or any(
            hint in text for hint in en_inventory_hints
        )

    def _is_library_count_question(self, question: str) -> bool:
        text = (question or "").strip().lower()
        if not text:
            return False
        zh_count_hints = (
            "多少文件",
            "几个文件",
            "多少文档",
            "几个文档",
            "有多少文件",
            "有多少文档",
        )
        en_count_hints = (
            "how many files",
            "how many documents",
            "number of files",
            "number of documents",
        )
        return any(hint in text for hint in zh_count_hints) or any(
            hint in text for hint in en_count_hints
        )

    def _reject(
        self,
        message: str,
        *,
        next_steps: list[str] | None = None,
    ) -> PolicyValidation:
        observation: dict[str, Any] = {
            "kind": "guardrail",
            "message": message,
            "evidence_sufficient": False,
        }
        if next_steps:
            observation["next_steps"] = next_steps
        return PolicyValidation(False, observation=observation)

    def _signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"
