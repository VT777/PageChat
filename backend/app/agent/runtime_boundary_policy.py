from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from app.agent.model_turn import ModelToolCall
from app.services.retrieval_policy import normalize_folder_id


_WEB_URL_RE = re.compile(r"https?://", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RuntimeBoundaryValidation:
    allowed: bool
    repaired_call: ModelToolCall
    tool_error: dict[str, Any]


class RuntimeBoundaryPolicy:
    """Boundary checks for a model-driven tool loop.

    This class deliberately avoids route planning and answer-evidence validation.
    """

    def __init__(self, *, tools: list[dict[str, Any]] | None = None) -> None:
        self.allowed_tools = {
            str(tool.get("function", {}).get("name"))
            for tool in tools or []
            if tool.get("function", {}).get("name")
        }

    def validate_tool_call(
        self,
        call: ModelToolCall,
        *,
        scope: dict[str, Any] | None = None,
    ) -> RuntimeBoundaryValidation:
        scope = scope or {}
        repaired = self._normalize_call(call, scope)
        if self.allowed_tools and repaired.name not in self.allowed_tools:
            return self._reject(
                repaired,
                f"Tool '{repaired.name}' is not available.",
            )
        if repaired.name == "web_search" and not self._web_search_allowed(scope):
            return self._reject(
                repaired,
                "Web Search is disabled for this question.",
                next_steps="Answer from available context or ask the user to enable Web Search.",
            )
        invalid_doc_id = self._invalid_doc_id(repaired, scope)
        if invalid_doc_id:
            next_steps = "Choose a document from the selected scope or browse the selected folder."
            if self._looks_like_url(invalid_doc_id) and scope.get("web_search_enabled"):
                next_steps = (
                    "Use web_search with intent=read_url or extract, and pass the URL "
                    "in urls instead of document doc_id."
                )
            return self._reject(
                repaired,
                f"Document '{invalid_doc_id}' is outside the selected scope.",
                next_steps=next_steps,
            )
        return RuntimeBoundaryValidation(True, repaired_call=repaired, tool_error={})

    def _normalize_call(
        self,
        call: ModelToolCall,
        scope: dict[str, Any],
    ) -> ModelToolCall:
        args = self._normalize_arguments(call.arguments)
        folder_id = normalize_folder_id(args.get("folder_id"))
        if folder_id != args.get("folder_id"):
            args["folder_id"] = folder_id

        if call.name in self._document_reference_tools():
            resolved = self._resolve_document_reference(args.get("doc_id"), scope)
            if resolved:
                args["doc_id"] = resolved
            elif not args.get("doc_id") and args.get("doc_name"):
                resolved = self._resolve_document_reference(args.get("doc_name"), scope)
                if resolved:
                    args["doc_id"] = resolved

        if call.name == "browse_documents" and scope.get("strict_scope") is not False:
            document_ids = [str(doc_id) for doc_id in scope.get("document_ids") or [] if doc_id]
            if document_ids and not args.get("document_ids"):
                args["document_ids"] = document_ids
            scoped_folder = normalize_folder_id(scope.get("folder_id"))
            if scoped_folder and not args.get("folder_id"):
                args["folder_id"] = scoped_folder
            if scope.get("include_subfolders") and "recursive" not in args:
                args["recursive"] = True

        if args == call.arguments:
            return call
        return ModelToolCall(id=call.id, name=call.name, arguments=args)

    def _normalize_arguments(self, arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return dict(arguments)
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError:
                return {"_raw_arguments": arguments}
            return dict(parsed) if isinstance(parsed, dict) else {"value": parsed}
        return {}

    def _web_search_allowed(self, scope: dict[str, Any]) -> bool:
        return bool(scope.get("web_search_enabled"))

    def _document_reference_tools(self) -> set[str]:
        return {
            "get_document_structure",
            "get_page_content",
            "get_page_image",
            "get_document_image",
            "search_within_document",
        }

    def _invalid_doc_id(self, call: ModelToolCall, scope: dict[str, Any]) -> str:
        if call.name not in self._document_reference_tools():
            return ""
        reference = call.arguments.get("doc_id")
        if reference in (None, ""):
            return ""
        resolved = self._resolve_document_reference(reference, scope)
        if resolved:
            allowed = self._known_document_ids(scope)
            strict_scope = scope.get("strict_scope") is not False
            selected = {str(doc_id) for doc_id in scope.get("document_ids") or [] if doc_id}
            if strict_scope and selected and resolved not in selected:
                return str(reference)
            if allowed and resolved not in allowed:
                return str(reference)
            return ""
        if self._has_document_reference_context(scope):
            return str(reference)
        return ""

    def _resolve_document_reference(self, reference: Any, scope: dict[str, Any]) -> str:
        if reference in (None, ""):
            return ""
        text = str(reference).strip()
        if not text:
            return ""
        known_ids = self._known_document_ids(scope)
        if text in known_ids:
            return text

        lowered = text.lower()
        matches: list[str] = []
        for item in self._document_registry(scope):
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
        unique = sorted(set(matches))
        return unique[0] if len(unique) == 1 else ""

    def _known_document_ids(self, scope: dict[str, Any]) -> set[str]:
        ids = {str(doc_id) for doc_id in scope.get("available_document_ids") or [] if doc_id}
        ids.update(str(doc_id) for doc_id in scope.get("document_ids") or [] if doc_id)
        ids.update(str(doc_id) for doc_id in scope.get("preferred_document_ids") or [] if doc_id)
        for item in self._document_registry(scope):
            doc_id = item.get("document_id") or item.get("doc_id") or item.get("id")
            if doc_id:
                ids.add(str(doc_id))
        return ids

    def _document_registry(self, scope: dict[str, Any]) -> list[dict[str, Any]]:
        registry = scope.get("document_registry")
        if not isinstance(registry, list):
            return []
        return [item for item in registry if isinstance(item, dict)]

    def _has_document_reference_context(self, scope: dict[str, Any]) -> bool:
        return bool(
            scope.get("available_document_ids")
            or scope.get("document_ids")
            or scope.get("preferred_document_ids")
            or self._document_registry(scope)
        )

    @staticmethod
    def _looks_like_url(value: Any) -> bool:
        return bool(_WEB_URL_RE.search(str(value or "")))

    def _reject(
        self,
        call: ModelToolCall,
        error: str,
        *,
        next_steps: str = "Revise the tool arguments and try again.",
    ) -> RuntimeBoundaryValidation:
        return RuntimeBoundaryValidation(
            False,
            repaired_call=call,
            tool_error={
                "success": False,
                "error": error,
                "next_steps": next_steps,
            },
        )
