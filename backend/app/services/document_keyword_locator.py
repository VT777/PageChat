"""Deterministic in-document keyword locator for agent tools.

This module intentionally avoids BM25, rerankers, embeddings, query expansion,
or broad document search. It only scans the supplied index data for one document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


_INTENT_PATTERNS = [
    r"在哪(?:一|个)?页",
    r"哪(?:一|个)?页",
    r"哪个章节",
    r"哪一章节",
    r"提到(?:了|过)?",
    r"出现(?:了|过)?",
    r"查找",
    r"搜索",
    r"定位",
    r"包含",
    r"请",
    r"帮我",
    r"where",
    r"which\s+page",
    r"find",
    r"locate",
    r"mentioned",
    r"contains",
]

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "in",
    "on",
    "of",
    "to",
    "for",
    "about",
    "page",
    "pages",
    "which",
    "where",
    "find",
    "locate",
    "mentioned",
    "contains",
}


def locate_keywords_in_index(
    *,
    index_data: dict,
    query: str,
    doc_id: str,
    doc_name: str,
    limit: int = 10,
) -> dict:
    phrase_candidates, terms = _extract_query_terms(query)
    entries = _collect_page_entries(index_data)
    matches: List[Dict[str, Any]] = []

    for entry in entries:
        text = entry.get("text", "")
        if not text:
            continue
        text_for_match = _normalize_for_match(text)
        phrase_hit = next(
            (
                phrase
                for phrase in phrase_candidates
                if _normalize_for_match(phrase) and _normalize_for_match(phrase) in text_for_match
            ),
            "",
        )
        matched_terms = [
            term for term in terms if _normalize_for_match(term) in text_for_match
        ]
        if not phrase_hit and not _has_sufficient_keyword_match(phrase_candidates, matched_terms):
            continue

        page = int(entry["page"])
        is_toc_like = _is_toc_like_entry(entry)
        is_visual = _is_visual_or_ocr_entry(index_data, entry)
        match_type = _match_type(phrase_hit, matched_terms, is_visual)
        title_exact_hit = bool(
            phrase_hit
            and _normalize_for_match(phrase_hit)
            in _normalize_for_match(str(entry.get("title") or ""))
        )
        match = {
            "page": page,
            "page_num": page,
            "match_type": match_type,
            "matched_terms": matched_terms or ([phrase_hit] if phrase_hit else []),
            "display_label": f"{doc_name} p.{page}",
            "source_anchor": _source_anchor(doc_name, page),
            "next_tool": "get_page_image" if is_visual else "get_page_content",
        }
        if entry.get("node_id"):
            match["node_id"] = entry["node_id"]
        if entry.get("title"):
            match["title"] = entry["title"]
        if is_toc_like:
            match["toc_like"] = True
        if title_exact_hit:
            match["title_exact_hit"] = True

        if is_visual:
            match["visual_evidence_required"] = True
            match["text_omitted_reason"] = "visual_evidence_required"
            match["image_refs"] = _image_refs(entry, doc_id, page)
        else:
            focus = phrase_hit or (matched_terms[0] if matched_terms else "")
            match["snippet"] = _snippet(text, focus)

        matches.append(
            {
                **match,
                "_rank": _rank_tuple(
                    page=page,
                    phrase_hit=phrase_hit,
                    matched_terms=matched_terms,
                    text=text,
                    title=str(entry.get("title") or ""),
                ),
            }
        )

    if any(not match.get("toc_like") for match in matches):
        matches = [match for match in matches if not match.get("toc_like")]
    if any(match.get("title_exact_hit") for match in matches):
        matches = [match for match in matches if match.get("title_exact_hit")]
    if any(match.get("match_type") == "exact_phrase" for match in matches):
        matches = [match for match in matches if match.get("match_type") == "exact_phrase"]

    matches.sort(key=lambda item: item["_rank"])
    compact_matches = []
    for match in matches[: max(1, limit)]:
        compact = dict(match)
        compact.pop("_rank", None)
        compact.pop("toc_like", None)
        compact.pop("title_exact_hit", None)
        compact_matches.append(compact)

    return {
        "success": True,
        "doc_id": doc_id,
        "doc_name": doc_name,
        "query": query,
        "search_method": "keyword_exact",
        "matches": compact_matches,
        "next_steps": {
            "summary": f"Found {len(compact_matches)} keyword match(es) in {doc_name}",
            "options": _next_step_options(compact_matches),
        },
    }


def _extract_query_terms(query: str) -> tuple[List[str], List[str]]:
    raw = str(query or "").strip()
    stripped = raw
    for pattern in _INTENT_PATTERNS:
        stripped = re.sub(pattern, " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"[\s，。！？；：、,.!?;:()\[\]【】\"'“”‘’]+", " ", stripped).strip()

    phrase_candidates = []
    for candidate in [stripped, raw]:
        cleaned = re.sub(r"[\s，。！？；：、,.!?;:()\[\]【】\"'“”‘’]+", "", candidate)
        if len(cleaned) >= 2 and cleaned not in phrase_candidates:
            phrase_candidates.append(cleaned)

    tokens = re.findall(r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*|[\u4e00-\u9fff]+", stripped)
    terms: List[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if re.fullmatch(r"[A-Za-z]+", token) and token.lower() in _STOPWORDS:
            continue
        if _contains_cjk(token) and len(token) > 6:
            terms.extend(_cjk_chunks(token))
        terms.append(token)

    deduped_terms: List[str] = []
    for term in terms:
        if term and term not in deduped_terms:
            deduped_terms.append(term)
    return phrase_candidates, deduped_terms


def _collect_page_entries(index_data: dict) -> List[Dict[str, Any]]:
    by_page: Dict[int, Dict[str, Any]] = {}

    if isinstance(index_data, dict):
        page_count = _page_count(index_data)
        for page in index_data.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_num = _page_number(page, page_count=page_count)
            if page_num <= 0:
                continue
            by_page[page_num] = {
                **page,
                "page": page_num,
                "text": str(page.get("text") or page.get("text_content") or ""),
            }

        nodes = index_data.get("structure", [])
        if isinstance(nodes, dict):
            nodes = [nodes]
        for node in _walk_nodes(nodes):
            page_num = _page_number(node, page_count=page_count, prefer_physical=True)
            if page_num <= 0:
                continue
            entry = by_page.setdefault(page_num, {"page": page_num, "text": ""})
            node_text = _node_text_for_entry(node)
            entry["text"] = " ".join([str(entry.get("text") or ""), node_text]).strip()
            entry.setdefault("title", node.get("title", ""))
            entry.setdefault("node_id", node.get("node_id", ""))
            for key in ("logical_page", "raw_page_label", "physical_index", "start_index"):
                if node.get(key) is not None:
                    entry.setdefault(key, node.get(key))
            if node.get("images"):
                entry.setdefault("images", [])
                entry["images"].extend(node.get("images") or [])
            if node.get("has_visual_content"):
                entry["has_visual_content"] = True

    return [by_page[key] for key in sorted(by_page)]


def _walk_nodes(nodes: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk_nodes(node.get("nodes") or node.get("children") or [])


def _node_text_for_entry(node: Dict[str, Any]) -> str:
    keys = ["title", "summary", "content"]
    if not _has_child_nodes(node):
        keys.append("text")
    return " ".join(str(node.get(key) or "") for key in keys)


def _has_child_nodes(node: Dict[str, Any]) -> bool:
    for key in ("nodes", "children"):
        children = node.get(key)
        if isinstance(children, list) and children:
            return True
    return False


def _page_count(index_data: Dict[str, Any]) -> int:
    try:
        value = int(index_data.get("page_count") or index_data.get("total_pages") or 0)
        return value if value > 0 else 0
    except (TypeError, ValueError):
        return 0


def _page_number(
    item: Dict[str, Any],
    *,
    page_count: int = 0,
    prefer_physical: bool = False,
) -> int:
    source_anchor = item.get("source_anchor")
    mapping_evidence = item.get("mapping_evidence")
    candidates: List[Any] = []
    if prefer_physical:
        candidates.extend(
            [
                item.get("physical_index"),
                item.get("start_index"),
                mapping_evidence.get("matched_page") if isinstance(mapping_evidence, dict) else None,
            ]
        )
    if isinstance(source_anchor, dict):
        candidates.extend([source_anchor.get("start_page"), source_anchor.get("page")])
    if not prefer_physical:
        candidates.extend([item.get("page"), item.get("page_num"), item.get("start_page"), item.get("start_index")])
    for candidate in candidates:
        try:
            value = int(candidate)
            if value > 0 and (page_count <= 0 or value <= page_count):
                return value
        except (TypeError, ValueError):
            continue
    return 0


def _is_visual_or_ocr_entry(index_data: dict, entry: Dict[str, Any]) -> bool:
    page = int(entry.get("page") or 0)
    ocr_pages = set()
    if isinstance(index_data, dict):
        for key in ("page_text_map_ocr_pages", "ocr_pages", "visual_pages"):
            values = index_data.get(key) or []
            if isinstance(values, list):
                for value in values:
                    try:
                        ocr_pages.add(int(value))
                    except (TypeError, ValueError):
                        continue
    return bool(
        entry.get("ocr_used")
        or entry.get("has_visual_content")
        or entry.get("images")
        or page in ocr_pages
    )


def _image_refs(entry: Dict[str, Any], doc_id: str, page: int) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for image in entry.get("images") or []:
        if not isinstance(image, dict):
            continue
        image_path = str(image.get("image_path") or image.get("path") or "").strip()
        if not image_path:
            continue
        refs.append(
            {
                "image_path": image_path,
                "page": int(image.get("page") or page),
                "mimeType": image.get("mimeType") or image.get("mime_type") or "image/jpeg",
            }
        )
    if refs:
        return refs
    return [{"image_path": f"page://{doc_id}/{page}", "page": page, "mimeType": "image/jpeg"}]


def _source_anchor(doc_name: str, page: int) -> Dict[str, Any]:
    suffix = Path(doc_name or "").suffix.lower().lstrip(".") or "pdf"
    return {
        "format": suffix,
        "unit_type": "page",
        "start_page": page,
        "end_page": page,
    }


def _match_type(phrase_hit: str, matched_terms: List[str], is_visual: bool) -> str:
    if is_visual:
        return "ocr_keyword"
    if phrase_hit:
        return "exact_phrase"
    if len(matched_terms) > 1:
        return "keyword"
    return "keyword"


def _is_toc_like_entry(entry: Dict[str, Any]) -> bool:
    title = _normalize_for_match(str(entry.get("title") or ""))
    if title in {"目录", "preface", "tableofcontents", "contents"}:
        return True
    text = str(entry.get("text") or "")
    if _normalize_for_match(text).startswith("目录"):
        return True
    toc_line_count = 0
    for line in text.splitlines():
        compact = line.strip()
        if not compact:
            continue
        if re.search(r"(?:^|\s|\|)\d{1,3}\s*(?:\||$)", compact) and (
            "|" in compact or "…" in compact or "..." in compact
        ):
            toc_line_count += 1
    return toc_line_count >= 3


def _has_sufficient_keyword_match(phrase_candidates: List[str], matched_terms: List[str]) -> bool:
    if not matched_terms:
        return False
    longest_phrase_len = max((len(_normalize_for_match(phrase)) for phrase in phrase_candidates), default=0)
    if longest_phrase_len < 6:
        return True
    meaningful_terms = [
        term for term in matched_terms
        if len(_normalize_for_match(term)) >= 3 or re.search(r"[A-Za-z0-9]{4,}", term)
    ]
    return len(meaningful_terms) >= 2


def _rank_tuple(
    *,
    page: int,
    phrase_hit: str,
    matched_terms: List[str],
    text: str,
    title: str,
) -> tuple:
    normalized_text = _normalize_for_match(text)
    occurrence_count = sum(
        normalized_text.count(_normalize_for_match(term))
        for term in matched_terms
        if _normalize_for_match(term)
    )
    title_hit = any(_normalize_for_match(term) in _normalize_for_match(title) for term in matched_terms)
    return (
        0 if phrase_hit else 1,
        0 if matched_terms and len(matched_terms) >= 2 else 1,
        -len(matched_terms),
        0 if title_hit else 1,
        -occurrence_count,
        page,
    )


def _snippet(text: str, focus: str, radius: int = 48) -> str:
    clean_text = re.sub(r"\s+", " ", text).strip()
    if not clean_text:
        return ""
    haystack = _normalize_for_match(clean_text)
    needle = _normalize_for_match(focus)
    index = haystack.find(needle) if needle else -1
    if index < 0:
        return clean_text[: radius * 2]
    start = max(0, index - radius)
    end = min(len(clean_text), index + len(focus) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean_text) else ""
    return f"{prefix}{clean_text[start:end]}{suffix}"


def _next_step_options(matches: List[Dict[str, Any]]) -> List[str]:
    if not matches:
        return ["No exact keyword match found; ask the user for a more specific term or inspect the document structure."]
    if any(match.get("visual_evidence_required") for match in matches):
        return ["Use get_page_image() or get_document_image() to inspect visual evidence before answering."]
    return ["Use get_page_content() on matched pages before answering with citations."]


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").lower())


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _cjk_chunks(value: str) -> List[str]:
    chunks: List[str] = []
    for size in (4, 3, 2):
        for index in range(0, len(value) - size + 1):
            chunks.append(value[index : index + size])
    return chunks
