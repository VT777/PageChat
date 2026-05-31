from __future__ import annotations

from typing import Any


class SourcePreviewService:
    def normalize_binding(
        self,
        binding: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        normalized = dict(binding or {})
        snippet = str(normalized.get("snippet", "")).strip()
        anchor = normalized.get("anchor")
        warns: list[dict[str, str]] = []

        if self._is_valid_pdf_anchor(anchor):
            normalized["anchor"] = {
                "type": "pdf_anchor",
                "page": anchor["page"],
                "bbox": anchor["bbox"],
            }
            return normalized, warns

        if self._is_valid_md_anchor(anchor):
            normalized["anchor"] = {
                "type": "md_anchor",
                "node_path": anchor["node_path"],
            }
            return normalized, warns

        if self._is_valid_snippet_fallback_anchor(anchor):
            normalized["anchor"] = {
                "type": "snippet_fallback",
                "snippet": str(anchor["snippet"]).strip(),
            }
            return normalized, warns

        normalized["anchor"] = {"type": "snippet_fallback", "snippet": snippet}
        warns.append(
            {
                "code": "ANCHOR_FALLBACK",
                "message": "anchor is invalid, fallback to snippet matching",
                "impact": "none",
            }
        )
        return normalized, warns

    @staticmethod
    def _is_valid_pdf_anchor(anchor: Any) -> bool:
        if not isinstance(anchor, dict):
            return False
        if anchor.get("type") != "pdf_anchor":
            return False
        if "node_path" in anchor:
            return False
        page = anchor.get("page")
        bbox = anchor.get("bbox")
        if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
            return False
        if not (isinstance(bbox, list) and len(bbox) == 4):
            return False
        for item in bbox:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                return False
        return True

    @staticmethod
    def _is_valid_md_anchor(anchor: Any) -> bool:
        if not isinstance(anchor, dict):
            return False
        if anchor.get("type") != "md_anchor":
            return False
        if "page" in anchor or "bbox" in anchor:
            return False
        node_path = anchor.get("node_path")
        return isinstance(node_path, str) and bool(node_path.strip())

    @staticmethod
    def _is_valid_snippet_fallback_anchor(anchor: Any) -> bool:
        if not isinstance(anchor, dict):
            return False
        if anchor.get("type") != "snippet_fallback":
            return False
        snippet = anchor.get("snippet")
        return isinstance(snippet, str) and bool(snippet.strip())
