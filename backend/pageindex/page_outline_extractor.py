"""Expand flat TOC skeletons with deterministic page-title evidence."""

from __future__ import annotations

import re
from typing import Dict, List


_NOISE_PATTERNS = [
    re.compile(r"^\d{1,3}$"),
    re.compile(r"www\.", re.IGNORECASE),
    re.compile(r"iyiou\.com", re.IGNORECASE),
    re.compile(r"\u83b7\u53d6\u66f4\u591a.*\u62a5\u544a\u6570\u636e"),
    re.compile(r"\u6570\u636e\u6765\u6e90"),
    re.compile(r"鑾峰彇鏇村.*鎶ュ憡鏁版嵁"),
    re.compile(r"鏁版嵁鏉ユ簮"),
    re.compile(r"^Chapter\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^(?:\u7b2c\s*)?[\d\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+[\u7ae0\u8282\u7bc7\u90e8]\s*$"),
]

_APPENDIX_MARKER_RE = re.compile(r"^(?:[nN]\s+|[\u2022\u00b7]\s*)(?P<title>.+)$")

_BACK_MATTER_KEYWORDS = (
    "\u8c22\u8c22\u9605\u8bfb",
    "\u7f16\u5236\u5355\u4f4d",
    "\u7f16\u5236\u6307\u5bfc",
    "\u7b56\u5212\u6307\u5bfc",
    "\u9879\u76ee\u8d1f\u8d23\u4eba",
    "\u4e3b      \u7f16",
)

_CHART_LABEL_TITLES = {
    "\u6280\u672f\u73af\u5883",
    "\u667a\u80fd\u7d20\u517b",
    "\u95ee\u5377\u7c7b\u578b",
    "\u603b\u4f53\u5747\u503c",
    "\u6307\u6807\u6570\u91cf",
    "\u4e2d\u804c\u5360\u6bd4",
    "\u9ad8\u804c\u5360\u6bd4",
    "\u521d\u7ea7\u804c\u79f0",
}

_SECTION_WITH_TITLE_RE = re.compile(
    r"^(?P<label>(?:part|chapter|section)\s*0?\d{1,3}|"
    r"(?:\u7b2c\s*)?[\d\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]{1,4}\s*[\u7ae0\u8282\u7bc7\u90e8])"
    r"\s*[::\uff1a.\-]\s*(?P<title>\S.*)$",
    re.IGNORECASE,
)

_SECTION_MARKER_RE = re.compile(
    r"^(?:part|chapter|section)\s*0?\d{1,3}$|"
    r"^(?:\u7b2c\s*)?[\d\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]{1,4}\s*[\u7ae0\u8282\u7bc7\u90e8]$",
    re.IGNORECASE,
)


def _clean_line(line: str) -> str:
    text = _strip_inline_markdown_fence(str(line or ""))
    text = re.sub(r"(^|\s)#{1,6}\s+", " ", text).strip()
    text = re.sub(r"^[-*+]\s+", "", text)
    return re.sub(r"\s+", " ", text.strip())


def _clean_section_label(label: str) -> str:
    text = _clean_line(label)
    match = re.match(r"^(part|chapter|section)\s*0?(\d{1,3})$", text, re.IGNORECASE)
    if match:
        return f"{match.group(1).capitalize()}{int(match.group(2)):02d}"
    return text


def _strip_inline_markdown_fence(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:[A-Za-z0-9_-]+)?\s*", "", value)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _extract_leading_markdown_heading(line: str) -> str:
    value = _strip_inline_markdown_fence(line)
    match = re.match(r"^#{1,6}\s+(?P<title>\S.*)$", value)
    if not match:
        return ""
    title = re.split(r"\s+#{1,6}\s+", match.group("title"), maxsplit=1)[0]
    return _clean_line(title)


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    if len(line) <= 1:
        return True
    if len(line) > 80:
        return True
    if re.fullmatch(r"\d{4}(?:[-\u2013\u2014]\d{4})?", line):
        return True
    digit_count = sum(ch.isdigit() for ch in line)
    if digit_count / max(1, len(line)) > 0.45:
        return True
    return any(pattern.search(line) for pattern in _NOISE_PATTERNS)


def _looks_like_title(line: str) -> bool:
    if _is_noise_line(line):
        return False
    if len(line) < 4:
        return False
    weak_tokens = {
        "AI", "SCE", "SaaS", "Agent", "IDCA", "Meta", "Qwen3",
        "Claude", "Llama", "Gemini", "DDoS", "WhatGEO",
    }
    if line in weak_tokens:
        return False
    cjk_count = sum("\u4e00" <= ch <= "\u9fff" for ch in line)
    if cjk_count >= 4:
        return True
    if cjk_count == 0 and len(line) < 12:
        return False
    if re.search(r"[:\uff1a\-\u2013\u2014]", line) and len(line) >= 8:
        return True
    return True


def _normalize_title_key(title: str) -> str:
    return re.sub(r"[\s:\uff1a,\uff0c\u3001\u3002\-\u2013\u2014]+", "", title).lower()


def _is_duplicate_of_parent(title: str, parent_title: str) -> bool:
    key = _normalize_title_key(title)
    parent_key = _normalize_title_key(parent_title)
    if not key or not parent_key:
        return False
    return key in parent_key or parent_key in key


def _contains_back_matter_marker(text: str) -> bool:
    return any(marker in text for marker in _BACK_MATTER_KEYWORDS)


def _is_appendix(node: Dict) -> bool:
    title = str(node.get("title") or "").lower()
    structure = str(node.get("structure") or "").upper()
    return structure.startswith("A") or "\u9644\u5f55" in title or "appendix" in title


def _strip_appendix_marker(line: str) -> str:
    match = _APPENDIX_MARKER_RE.match(_clean_line(line))
    if not match:
        return ""
    return _clean_line(match.group("title"))


def _is_chart_label_title(title: str) -> bool:
    return _clean_line(title) in _CHART_LABEL_TITLES


def _is_body_sentence_title(title: str) -> bool:
    text = _clean_line(title)
    if len(text) > 42 and not re.search(r"[\u2014:-]", text):
        return True
    if text.endswith(("\u3002", "\uff0c", ".", ",")):
        return True
    return False


def _is_valid_appendix_heading(title: str, parent_title: str) -> bool:
    if not title or _is_noise_line(title):
        return False
    if _is_duplicate_of_parent(title, parent_title):
        return False
    if _is_chart_label_title(title) or _contains_back_matter_marker(title):
        return False
    if _is_body_sentence_title(title):
        return False
    cjk_count = sum("\u4e00" <= ch <= "\u9fff" for ch in title)
    return cjk_count >= 3 or len(title) >= 8


def _extract_explicit_page_heading(lines: List[str]) -> Dict:
    raw_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    cleaned = [_clean_line(line) for line in raw_lines if _clean_line(line)]
    for index, line in enumerate(cleaned[:20]):
        if _is_noise_line(line) or has_toc_page_heading(line):
            continue
        combined = _SECTION_WITH_TITLE_RE.match(line)
        if combined:
            title = _clean_line(combined.group("title"))
            if _looks_like_title(title):
                label = _clean_section_label(combined.group("label"))
                return {
                    "title": f"{label}: {title}",
                    "reason": "explicit_section_marker_with_title",
                }
        if not _SECTION_MARKER_RE.match(line):
            continue
        for next_line in cleaned[index + 1 : index + 5]:
            if _is_noise_line(next_line) or has_toc_page_heading(next_line):
                continue
            if _SECTION_MARKER_RE.match(next_line):
                break
            if _looks_like_title(next_line):
                return {
                    "title": f"{_clean_section_label(line)}: {next_line}",
                    "reason": "explicit_section_marker_next_title",
                }
    for line in raw_lines[:20]:
        title = _extract_leading_markdown_heading(line)
        if title and _looks_like_title(title):
            return {
                "title": title,
                "reason": "markdown_heading",
            }
    return {}

def has_toc_page_heading(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    return any(marker in normalized for marker in ("\u76ee\u5f55", "contents", "tableofcontents"))


def extract_page_title_candidates(
    page_texts: List[str],
    start_page: int,
    end_page: int,
) -> List[Dict]:
    """Extract one page-title candidate per page from analyzer/OCR text."""
    candidates: List[Dict] = []
    if not page_texts:
        return candidates

    for page in range(max(1, start_page), min(end_page, len(page_texts)) + 1):
        text = page_texts[page - 1] or ""
        if _contains_back_matter_marker(text):
            continue
        raw_lines = list(text.splitlines())
        explicit = _extract_explicit_page_heading(raw_lines)
        if explicit:
            candidates.append(
                {
                    "title": explicit["title"],
                    "page": page,
                    "physical_index": page,
                    "source": "flat_text_fallback",
                    "confidence": 0.74,
                    "page_type": "content_slide",
                    "reason": explicit["reason"],
                }
            )
            continue
        lines = [_clean_line(line) for line in raw_lines]
        ranked = sorted(
            lines[:60],
            key=lambda line: (
                0 if sum("\u4e00" <= ch <= "\u9fff" for ch in line) >= 4 else 1,
                0 if re.search(r"[锛?鈥斺€斺€?]", line) else 1,
                len(line),
            ),
        )
        for line in ranked:
            if _looks_like_title(line):
                candidates.append(
                    {
                        "title": line,
                        "page": page,
                        "physical_index": page,
                        "source": "flat_text_fallback",
                        "confidence": 0.45,
                        "page_type": "content_slide",
                        "reason": "fallback_text_line",
                    }
                )
                break

    return candidates


def extract_appendix_title_candidates(
    page_texts: List[str],
    start_page: int,
    end_page: int,
    parent_title: str,
) -> List[Dict]:
    """Extract appendix section titles from explicit appendix page markers."""
    candidates: List[Dict] = []
    if not page_texts:
        return candidates

    for page in range(max(1, start_page), min(end_page, len(page_texts)) + 1):
        text = page_texts[page - 1] or ""
        if _contains_back_matter_marker(text):
            continue
        lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
        for line in lines[:16]:
            title = _strip_appendix_marker(line)
            if not _is_valid_appendix_heading(title, parent_title):
                continue
            candidates.append(
                {
                    "title": title,
                    "page": page,
                    "physical_index": page,
                    "source": "appendix_heading",
                    "confidence": 0.82,
                    "page_type": "appendix_section",
                    "reason": "appendix_marker",
                }
            )
            break

    return candidates


def build_page_title_candidates(
    page_evidence: List[Dict],
    parent: Dict,
    page_count: int,
) -> List[Dict]:
    """Build structured PageTitleCandidate objects inside a parent range."""
    start = int(parent.get("start_index") or parent.get("physical_index") or 1)
    end = int(parent.get("end_index") or page_count)
    candidates: List[Dict] = []
    for evidence in page_evidence or []:
        page = evidence.get("page")
        if not isinstance(page, int) or page < start or page > end:
            continue
        page_type = evidence.get("primary_role") or evidence.get("page_type") or "content_slide"
        if page_type in {"toc_page", "appendix", "noise"}:
            continue
        for span in evidence.get("evidence_spans") or []:
            if span.get("role") != "page_title":
                continue
            title = _clean_line(span.get("text", ""))
            if not _looks_like_title(title):
                continue
            candidates.append(
                {
                    "title": title,
                    "page": page,
                    "physical_index": page,
                    "source": evidence.get("source") or "structured_evidence",
                    "confidence": float(span.get("confidence") or evidence.get("confidence") or 0.75),
                    "page_type": page_type,
                    "reason": "structured_page_title",
                }
            )
    return candidates


def _make_child_node(parent: Dict, child_no: int, candidate: Dict, end_page: int) -> Dict:
    parent_structure = str(parent.get("structure") or "")
    structure = f"{parent_structure}.{child_no}" if parent_structure else str(child_no)
    page = int(candidate.get("physical_index") or candidate.get("page"))
    return {
        "structure": structure,
        "title": candidate["title"],
        "level": 2,
        "physical_index": page,
        "start_index": page,
        "end_index": end_page,
        "nodes": [],
        "source": candidate.get("source") or "page_title",
        "mapping_confidence": float(candidate.get("confidence") or 0.0),
        "title_confidence": float(candidate.get("confidence") or 0.0),
        "page_type": candidate.get("page_type"),
    }


def _assign_child_ranges(children: List[Dict], parent_end: int) -> None:
    for idx, child in enumerate(children):
        if idx + 1 < len(children):
            child["end_index"] = max(child["start_index"], children[idx + 1]["start_index"] - 1)
        else:
            child["end_index"] = parent_end


def expand_flat_toc_with_page_titles(
    tree: List[Dict],
    page_texts: List[str],
    page_count: int,
) -> Dict:
    """Attach page-title children under flat top-level chapters.

    Returns a quality result for the expansion.
    """
    if not tree or not page_texts:
        return _expansion_result(0, tree, page_count)

    added = 0
    for parent in tree:
        if parent.get("nodes"):
            continue
        if _is_preface(parent):
            continue
        start = parent.get("start_index") or parent.get("physical_index")
        end = parent.get("end_index") or page_count
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            continue

        if _is_appendix(parent):
            candidates = extract_appendix_title_candidates(
                page_texts,
                start,
                end,
                str(parent.get("title") or ""),
            )
        else:
            candidates = extract_page_title_candidates(page_texts, start, end)
        children: List[Dict] = []
        seen = set()
        for candidate in candidates:
            title = candidate.get("title", "")
            if _is_duplicate_of_parent(title, parent.get("title", "")):
                continue
            key = _normalize_title_key(title)
            if key in seen:
                continue
            seen.add(key)
            children.append(_make_child_node(parent, len(children) + 1, candidate, end))

        if not children:
            continue

        _assign_child_ranges(children, end)
        parent["nodes"] = children
        added += len(children)

    return _expansion_result(added, tree, page_count)


def expand_toc_with_page_evidence(
    tree: List[Dict],
    page_evidence: List[Dict],
    page_count: int,
) -> Dict:
    """Attach child nodes using structured PageEvidence."""
    if not tree or not page_evidence:
        return _expansion_result(0, tree, page_count)

    added = 0
    for parent in tree:
        if parent.get("nodes"):
            continue
        if _is_preface(parent):
            continue
        start = parent.get("start_index") or parent.get("physical_index")
        end = parent.get("end_index") or page_count
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            continue
        candidates = build_page_title_candidates(page_evidence, parent, page_count)
        children: List[Dict] = []
        seen = set()
        for candidate in candidates:
            title = candidate.get("title", "")
            if _is_duplicate_of_parent(title, parent.get("title", "")):
                continue
            key = _normalize_title_key(title)
            if key in seen:
                continue
            seen.add(key)
            children.append(_make_child_node(parent, len(children) + 1, candidate, end))
        if not children:
            continue
        _assign_child_ranges(children, end)
        parent["nodes"] = children
        added += len(children)
    return _expansion_result(added, tree, page_count)


def _expansion_result(added: int, tree: List[Dict], page_count: int) -> Dict:
    expected = 0
    actual = 0
    source_distribution: Dict[str, int] = {}
    confidences: List[float] = []
    for parent in tree or []:
        start = parent.get("start_index") or parent.get("physical_index")
        end = parent.get("end_index") or page_count
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        for child in parent.get("nodes") or []:
            source = str(child.get("source") or "unknown")
            source_distribution[source] = source_distribution.get(source, 0) + 1
            try:
                confidences.append(float(child.get("title_confidence") or 0.0))
            except Exception:
                confidences.append(0.0)
        span = end - start + 1
        if span >= 10 and not _is_preface(parent):
            expected += max(1, span // 4)
            actual += len(parent.get("nodes") or [])
    needs_repair = expected > 0 and actual < max(1, expected // 2)
    if needs_repair:
        quality = "bad"
    elif added > 0:
        quality = "good"
    else:
        quality = "warning"
    avg_confidence = None
    low_confidence_ratio = None
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)
        low_confidence_ratio = sum(1 for value in confidences if value < 0.6) / len(confidences)
    return {
        "added_children": added,
        "quality": quality,
        "expected_children": expected,
        "actual_children": actual,
        "needs_repair": needs_repair,
        "source_distribution": source_distribution or None,
        "avg_title_confidence": avg_confidence,
        "low_confidence_ratio": low_confidence_ratio,
    }


def _is_preface(node: Dict) -> bool:
    title = str(node.get("title") or "").lower()
    structure = str(node.get("structure") or "").upper()
    if (
        structure in {"0", "P"}
        or "preface" in title
        or "\u5e8f\u8a00" in title
        or "\u524d\u8a00" in title
    ):
        return True
    return structure == "0" or "preface" in title or "鍓嶈█" in title

