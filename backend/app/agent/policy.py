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
        return self._reject(
            "Document evidence is not sufficient yet. Read document structure, search within a selected document, "
            "or fetch page/image evidence before answering."
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
            if isinstance(observation, dict) and observation.get("evidence_sufficient"):
                return True
        for evidence in state.scope.get("evidence_pack") or []:
            if not isinstance(evidence, dict):
                continue
            if evidence.get("tool_name") in {
                "get_page_content",
                "get_page_image",
                "get_document_image",
                "web_search",
                "aggregate_tables",
            }:
                return True
        return False

    def _has_sufficient_metadata_evidence(self, state: AgentRunState) -> bool:
        if not self._is_library_inventory_question(state.question):
            return False
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
        return bool(tool_names & {"browse_documents", "view_folder_structure"})

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
        )
        return any(hint in text for hint in zh_inventory_hints) or any(
            hint in text for hint in en_inventory_hints
        )

    def _reject(self, message: str) -> PolicyValidation:
        return PolicyValidation(
            False,
            observation={
                "kind": "guardrail",
                "message": message,
                "evidence_sufficient": False,
            },
        )

    def _signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"
