from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


_CITATION_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
_POSITION_RE = re.compile(
    r"^(.*?)\s+(p|page|pages|页|line|lines|row|rows|para|paragraph|paragraphs|slide|slides)\.?\s*(\d+(?:\s*-\s*\d+)?)$",
    re.IGNORECASE,
)


def has_document_citation(answer: str) -> bool:
    return any(_parse_citation_label(match.group(1)) for match in _CITATION_RE.finditer(answer or ""))


def bind_answer_citations(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = collect_citation_evidence(tool_results)
    bindings: list[dict[str, Any]] = []
    for match in _CITATION_RE.finditer(answer or ""):
        citation = _parse_citation_label(match.group(1))
        if not citation:
            continue
        item = _best_evidence(citation, evidence)
        bindings.append(
            {
                "marker": match.group(0),
                "label": citation["label"],
                "doc_id": item.get("doc_id") if item else None,
                "document_name": item.get("document_name") if item else citation["document_name"],
                "display_label": item.get("display_label") if item else citation["label"],
                "source_anchor": item.get("source_anchor") if item else _anchor_from_citation(citation),
                "resolved": bool(item and item.get("doc_id")),
            }
        )
    return bindings


def build_missing_citation_suffix(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> str:
    if has_document_citation(answer):
        return ""
    for item in collect_citation_evidence(tool_results):
        label = item.get("display_label")
        if label:
            return f" [[{label}]]"
    return ""


def collect_citation_evidence(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any, depth: int = 0) -> None:
        if value is None or depth > 5:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return

        evidence = _evidence_from_record(value)
        if evidence:
            key = (
                evidence.get("doc_id") or "",
                evidence.get("display_label") or "",
                str(evidence.get("source_anchor") or ""),
            )
            key_text = "|".join(key)
            if key_text not in seen:
                seen.add(key_text)
                collected.append(evidence)

        for nested in value.values():
            if isinstance(nested, (dict, list)):
                visit(nested, depth + 1)

    visit(tool_results)
    return collected[:24]


def collect_web_sources(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def visit(value: Any, depth: int = 0) -> None:
        if value is None or depth > 5 or len(collected) >= 24:
            return
        if isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
            return
        if not isinstance(value, dict):
            return

        source = _web_source_from_record(value, len(collected) + 1)
        if source:
            url = source["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                collected.append(source)

        for nested in value.values():
            if isinstance(nested, (dict, list)):
                visit(nested, depth + 1)

    visit(tool_results)
    return collected


def _parse_citation_label(label: str) -> dict[str, Any] | None:
    normalized = re.sub(r"\s+", " ", (label or "").strip())
    if not normalized:
        return None
    match = _POSITION_RE.match(normalized)
    if not match:
        return None
    return {
        "label": normalized,
        "document_name": match.group(1).strip(),
        "position_type": _normalize_position_type(match.group(2)),
        "position": _first_number(match.group(3)),
    }


def _web_source_from_record(record: dict[str, Any], number: int) -> dict[str, Any] | None:
    url = _first_string(record, "url", "link")
    if not url:
        return None
    if record.get("source") != "anysearch" and not (
        "content_preview" in record or "snippet" in record
    ):
        return None

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "", 1)
    title = _first_string(record, "title", "name") or domain or url
    return {
        "type": "web",
        "source_id": f"web-{number}",
        "title": title,
        "display_label": title,
        "url": url,
        "domain": domain,
        "snippet": _first_string(record, "snippet", "summary") or "",
        "content_preview": _first_string(record, "content_preview", "content") or "",
        "provider": str(record.get("source") or "web"),
    }


def _normalize_position_type(value: str) -> str:
    item = value.lower()
    if item in {"page", "pages", "页"}:
        return "p"
    if item == "lines":
        return "line"
    if item == "rows":
        return "row"
    if item in {"paragraph", "paragraphs"}:
        return "para"
    if item == "slides":
        return "slide"
    return item


def _evidence_from_record(record: dict[str, Any]) -> dict[str, Any] | None:
    source_anchor = record.get("source_anchor")
    if source_anchor is not None and not isinstance(source_anchor, dict):
        source_anchor = None

    doc_id = _first_string(record, "doc_id", "docId", "document_id", "documentId")
    document_name = _first_string(
        record,
        "document_name",
        "documentName",
        "doc_name",
        "docName",
        "name",
    )
    page_num = _first_int(record, "page_num", "page", "start_page")
    display_label = _first_string(record, "display_label", "displayLabel")

    if not source_anchor and page_num:
        source_anchor = {
            "format": "pdf",
            "unit_type": "page",
            "start_page": page_num,
            "end_page": page_num,
        }

    if not display_label and document_name and page_num:
        display_label = f"{document_name} p.{page_num}"

    if not (doc_id or source_anchor or display_label):
        return None

    return {
        "doc_id": doc_id,
        "document_name": document_name,
        "display_label": display_label,
        "source_anchor": source_anchor,
        "snippet": _compact_snippet(record),
    }


def _compact_snippet(record: dict[str, Any], limit: int = 240) -> str:
    for key in ("snippet", "text_content", "content_preview", "summary", "node_title"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            text = re.sub(r"\s+", " ", value.strip())
            return text[:limit]
    return ""


def _best_evidence(
    citation: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for item in evidence:
        score = 0
        if _same_text(item.get("display_label"), citation["label"]):
            score += 100
        if _same_document(item.get("document_name") or item.get("display_label"), citation["document_name"]):
            score += 50
        if _anchor_position(item.get("source_anchor")) == citation["position"]:
            score += 30
        if item.get("doc_id"):
            score += 10
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def _anchor_from_citation(citation: dict[str, Any]) -> dict[str, Any]:
    position = citation["position"]
    position_type = citation["position_type"]
    document_name = citation["document_name"]
    fmt = _format_from_name(document_name)
    if position_type == "p" and fmt == "pdf":
        return {"format": "pdf", "unit_type": "page", "start_page": position, "end_page": position}
    if position_type == "row":
        return {"format": fmt, "unit_type": "row_range", "start_row": position, "end_row": position}
    if position_type == "line":
        return {"format": fmt, "unit_type": "line", "start_line": position, "end_line": position}
    if position_type == "para":
        return {"format": fmt, "unit_type": "paragraph", "start_paragraph": position, "end_paragraph": position}
    if position_type == "slide":
        return {"format": fmt, "unit_type": "slide", "slide": position, "start_slide": position, "end_slide": position}
    return {"format": fmt, "unit_type": "page", "start_page": position, "end_page": position}


def _format_from_name(name: str) -> str:
    match = re.search(r"\.(pdf|docx|xlsx|csv|tsv|pptx|md|markdown|txt)\b", name or "", re.IGNORECASE)
    if not match:
        return "pdf"
    value = match.group(1).lower()
    return "md" if value == "markdown" else value


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = record.get(key)
        parsed = _first_number(value)
        if parsed:
            return parsed
    return None


def _first_number(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return max(1, int(match.group(0))) if match else 0


def _anchor_position(anchor: Any) -> int:
    if not isinstance(anchor, dict):
        return 0
    for key in (
        "start_page",
        "page",
        "start_line",
        "start_row",
        "start_paragraph",
        "start_slide",
        "slide",
    ):
        value = _first_number(anchor.get(key))
        if value:
            return value
    return 0


def _same_text(left: Any, right: Any) -> bool:
    return _normalize(left) == _normalize(right) and bool(_normalize(left))


def _same_document(left: Any, right: Any) -> bool:
    left_norm = _strip_extension(_normalize(left))
    right_norm = _strip_extension(_normalize(right))
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm in right_norm or right_norm in left_norm))


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _strip_extension(value: str) -> str:
    return re.sub(r"\.(pdf|docx|xlsx|csv|tsv|pptx|md|markdown|txt)\b", "", value)
