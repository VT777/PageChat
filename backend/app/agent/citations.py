from __future__ import annotations

import json
import re
from urllib.parse import urlparse
import uuid
from typing import Any


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _strip_extension(name: str) -> str:
    return re.sub(r"\.(pdf|txt|md|markdown|csv|tsv|xlsx|xls|docx|pptx)$", "", name, flags=re.I)


def _kind_from_name(name: str, fallback: str = "document") -> str:
    suffix = ""
    if "." in name:
        suffix = name.rsplit(".", 1)[-1].lower()
    return {
        "pdf": "pdf",
        "txt": "text",
        "md": "markdown",
        "markdown": "markdown",
        "csv": "table",
        "tsv": "table",
        "xlsx": "xlsx",
        "xls": "xlsx",
        "docx": "docx",
        "pptx": "pptx",
    }.get(suffix, fallback)


def _safe_web_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _format_anchor_label(document_name: str, source_anchor: dict[str, Any]) -> str:
    if not source_anchor:
        return document_name

    base = _strip_extension(document_name)
    start_page = _first_present(source_anchor.get("start_page"), source_anchor.get("page"))
    end_page = _first_present(source_anchor.get("end_page"), start_page)
    if start_page:
        return f"{base} p.{start_page}" if str(start_page) == str(end_page) else f"{base} p.{start_page}-{end_page}"

    start_line = source_anchor.get("start_line")
    end_line = _first_present(source_anchor.get("end_line"), start_line)
    if start_line:
        return f"{base} line {start_line}" if str(start_line) == str(end_line) else f"{base} lines {start_line}-{end_line}"

    start_row = source_anchor.get("start_row")
    end_row = _first_present(source_anchor.get("end_row"), start_row)
    if start_row:
        return f"{base} row {start_row}" if str(start_row) == str(end_row) else f"{base} rows {start_row}-{end_row}"

    start_slide = source_anchor.get("start_slide")
    end_slide = _first_present(source_anchor.get("end_slide"), start_slide)
    if start_slide:
        return f"{base} slide {start_slide}" if str(start_slide) == str(end_slide) else f"{base} slides {start_slide}-{end_slide}"

    start_para = source_anchor.get("start_paragraph")
    end_para = _first_present(source_anchor.get("end_paragraph"), start_para)
    if start_para:
        return f"{base} paragraph {start_para}" if str(start_para) == str(end_para) else f"{base} paragraphs {start_para}-{end_para}"

    return document_name


def _anchor_from_page(value: dict[str, Any], document_name: str) -> dict[str, Any]:
    page = _first_present(
        value.get("start_page"),
        value.get("page_num"),
        value.get("page"),
    )
    if not page:
        page_range = str(value.get("page_range") or "").strip()
        match = re.match(r"^(\d+)(?:\s*[-~]\s*(\d+))?$", page_range)
        if match:
            page = int(match.group(1))
            end_page = int(match.group(2) or match.group(1))
            return {
                "format": "pdf" if _kind_from_name(document_name) == "pdf" else _kind_from_name(document_name),
                "unit_type": "page",
                "start_page": page,
                "end_page": end_page,
            }
    if not page:
        return {}
    end_page = _first_present(value.get("end_page"), page)
    return {
        "format": "pdf" if _kind_from_name(document_name) == "pdf" else _kind_from_name(document_name),
        "unit_type": "page",
        "start_page": int(page),
        "end_page": int(end_page),
    }


def normalize_citation(citation: dict[str, Any]) -> dict[str, Any]:
    source_anchor = citation.get("source_anchor") or {}
    if not isinstance(source_anchor, dict):
        source_anchor = {}

    document_id = _first_present(citation.get("document_id"), citation.get("doc_id"))
    document_name = str(
        _first_present(
            citation.get("document_name"),
            citation.get("doc_name"),
            citation.get("name"),
            citation.get("title"),
            citation.get("url"),
            "Source",
        )
    )
    preview_kind = str(
        _first_present(
            citation.get("preview_kind"),
            "web" if citation.get("url") else None,
            source_anchor.get("format"),
            _kind_from_name(document_name),
        )
    ).lower()
    source_format = str(source_anchor.get("format") or "").lower()
    if preview_kind == "web" or source_format == "web":
        safe_url = _safe_web_url(
            _first_present(source_anchor.get("url"), citation.get("url"), document_id)
        )
        source_anchor = dict(source_anchor)
        source_anchor["format"] = "web"
        if safe_url:
            source_anchor["url"] = safe_url
            document_id = safe_url
        else:
            source_anchor.pop("url", None)
            document_id = None
        preview_kind = "web"
    display_label = str(
        _first_present(
            citation.get("display_label"),
            citation.get("source_label"),
            _format_anchor_label(document_name, source_anchor),
        )
    )

    return {
        "id": str(citation.get("id") or uuid.uuid4().hex[:16]),
        "citation_key": str(
            citation.get("citation_key")
            or f"{document_id or document_name}:{json.dumps(source_anchor, sort_keys=True, ensure_ascii=False)}"
        ),
        "document_id": document_id,
        "document_name": document_name,
        "source_anchor": source_anchor,
        "display_label": display_label,
        "preview_kind": preview_kind,
    }


def citation_events_from_tool_result(result: Any) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []

    def append_citation(citation: dict[str, Any]) -> None:
        normalized = normalize_citation(citation)
        source_anchor = normalized.get("source_anchor") or {}
        source_format = str(source_anchor.get("format") or "").lower()
        preview_kind = str(normalized.get("preview_kind") or "").lower()
        if (
            preview_kind == "web"
            or source_format == "web"
        ) and not _safe_web_url(source_anchor.get("url")):
            return
        citations.append(normalized)

    def candidate_from_tool_item(
        value: dict[str, Any],
        context: dict[str, Any],
        parent_key: str,
    ) -> dict[str, Any] | None:
        if value.get("url"):
            url = _safe_web_url(value.get("url"))
            if not url:
                return None
            return normalize_citation(
                {
                    "citation_key": url,
                    "document_id": url,
                    "document_name": value.get("title") or url,
                    "display_label": value.get("title") or url,
                    "source_anchor": {"format": "web", "url": url},
                    "preview_kind": "web",
                }
            )

        document_id = _first_present(
            value.get("document_id"),
            value.get("doc_id"),
            context.get("document_id"),
            context.get("doc_id"),
        )
        document_name = str(
            _first_present(
                value.get("document_name"),
                value.get("doc_name"),
                value.get("name"),
                context.get("document_name"),
                context.get("doc_name"),
                context.get("name"),
                "",
            )
        )
        if not document_id and not document_name:
            return None

        source_anchor = value.get("source_anchor")
        if not isinstance(source_anchor, dict):
            source_anchor = _anchor_from_page(value, document_name)
        if not source_anchor:
            return None

        file_type = str(
            _first_present(
                value.get("file_type"),
                context.get("file_type"),
                "",
            )
        ).lstrip(".")
        preview_kind = _first_present(
            value.get("preview_kind"),
            source_anchor.get("format"),
            file_type,
            _kind_from_name(document_name),
        )
        if preview_kind == "txt":
            preview_kind = "text"

        return normalize_citation(
            {
                "citation_key": value.get("citation_key"),
                "document_id": document_id,
                "document_name": document_name or str(document_id),
                "source_anchor": source_anchor,
                "display_label": value.get("display_label"),
                "preview_kind": preview_kind,
            }
        )

    def context_from(value: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        merged = dict(context)
        for key in (
            "document_id",
            "doc_id",
            "document_name",
            "doc_name",
            "name",
            "file_type",
        ):
            if value.get(key) is not None:
                merged[key] = value.get(key)
        return merged

    def visit(
        value: Any,
        depth: int = 0,
        context: dict[str, Any] | None = None,
        parent_key: str = "",
    ) -> None:
        context = context or {}
        if value is None or depth > 5:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1, context, parent_key)
            return
        if not isinstance(value, dict):
            return

        current_context = context_from(value, context)
        nested = value.get("citations")
        if isinstance(nested, list):
            for citation in nested:
                if isinstance(citation, dict):
                    append_citation(citation)
        if value.get("citation_key") and value.get("source_anchor"):
            append_citation(value)

        candidate = candidate_from_tool_item(value, current_context, parent_key)
        if candidate:
            append_citation(candidate)

        for key, item in value.items():
            if key == "citations":
                continue
            if isinstance(item, (dict, list)):
                visit(item, depth + 1, current_context, key)

    visit(result)

    return dedupe_citations(citations)


def dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        key = citation_dedupe_key(citation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def citation_dedupe_key(citation: dict[str, Any]) -> str:
    anchor_json = _citation_anchor_identity(citation.get("source_anchor") or {})
    return "|".join(
        [
            str(citation.get("document_id") or ""),
            str(citation.get("document_name") or ""),
            anchor_json,
        ]
    )


def _citation_anchor_identity(source_anchor: Any) -> str:
    if not isinstance(source_anchor, dict):
        return "{}"

    anchor = dict(source_anchor)
    source_format = str(anchor.get("format") or "").lower()
    start_page = _first_present(anchor.get("start_page"), anchor.get("page"))
    if start_page is not None:
        end_page = _first_present(anchor.get("end_page"), start_page)
        return json.dumps(
            {
                "format": source_format or "pdf",
                "unit_type": "page",
                "start_page": str(start_page),
                "end_page": str(end_page),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    for unit, start_key, end_key in (
        ("line", "start_line", "end_line"),
        ("row", "start_row", "end_row"),
        ("slide", "start_slide", "end_slide"),
        ("paragraph", "start_paragraph", "end_paragraph"),
    ):
        start = anchor.get(start_key)
        if start is not None:
            end = _first_present(anchor.get(end_key), start)
            identity = {
                "format": source_format,
                "unit_type": unit,
                start_key: str(start),
                end_key: str(end),
            }
            if unit == "row" and anchor.get("sheet") not in (None, ""):
                identity["sheet"] = str(anchor.get("sheet"))
            return json.dumps(identity, sort_keys=True, ensure_ascii=False)

    if source_format == "web" or anchor.get("url"):
        return json.dumps(
            {
                "format": "web",
                "url": _safe_web_url(anchor.get("url")),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    return json.dumps(anchor, sort_keys=True, ensure_ascii=False)
