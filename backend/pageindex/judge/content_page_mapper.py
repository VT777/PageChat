"""Map TOC logical pages to physical PDF pages using OCR text evidence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pageindex.catalog_classifier import CATALOG_MAIN, detect_catalog_type


def map_toc_items_to_physical_pages(
    toc_items: List[Dict[str, Any]],
    *,
    page_texts: Any,
    page_count: int,
    toc_pages: Optional[List[int]] = None,
    excluded_pages: Optional[List[int]] = None,
    min_title_match_rate: float = 0.55,
    prefer_printed_page_numbers: bool = False,
    allow_neighbor_inference: bool = True,
    require_all_mapped: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return TOC items with verified physical pages plus a compact report.

    The TOC ``page`` value is treated as a printed/logical page number. Only
    content evidence may create a high-confidence ``physical_index``.
    """
    items = [dict(item) for item in deepcopy(toc_items or []) if isinstance(item, dict)]
    page_count = max(0, int(page_count or 0))
    toc_page_set = {
        int(page)
        for page in (toc_pages or [])
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
    }
    if not toc_page_set:
        toc_page_set = _source_page_set(items)
    excluded_page_set = set(toc_page_set)
    excluded_page_set.update(
        int(page)
        for page in (excluded_pages or [])
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
    )
    page_text_map = page_texts_to_map(page_texts, page_count=page_count)
    shape = detect_logical_page_shape(items, page_count)
    _normalize_logical_fields(items, page_count, shape)
    _annotate_catalog_types(items)

    if not items or page_count <= 0:
        return items, _build_report(
            items,
            shape,
            status="failed",
            reasons=["empty_items" if not items else "invalid_page_count"],
            excluded_pages=excluded_page_set,
        )

    start_page = max(toc_page_set or {0}) + 1
    start_page = max(1, min(page_count, start_page))
    cursor_by_catalog: Dict[str, int] = {}
    strong_anchor_indices: List[int] = []

    if prefer_printed_page_numbers:
        printed_result = _map_printed_page_numbers(
            items,
            page_text_map=page_text_map,
            page_count=page_count,
            toc_page_set=toc_page_set,
            excluded_page_set=excluded_page_set,
            start_page=start_page,
        )
        if printed_result is not None:
            return printed_result

    for index, item in enumerate(items):
        item.pop("physical_index", None)
        title = str(item.get("title") or "").strip()
        if not title:
            item["mapping_source"] = "unmapped"
            continue

        catalog_type = str(item.get("catalog_type") or CATALOG_MAIN)
        cursor = cursor_by_catalog.get(catalog_type, start_page)

        match = find_title_page(
            title,
            page_text_map,
            start_page=cursor,
            end_page=page_count,
            excluded_pages=excluded_page_set,
        )
        if not match and catalog_type == CATALOG_MAIN:
            match = find_outline_marker_page(
                title,
                page_text_map,
                start_page=cursor,
                end_page=page_count,
                excluded_pages=excluded_page_set,
            )
        if not match:
            item["mapping_source"] = "unmapped"
            item["mapping_confidence"] = 0.0
            continue

        physical_page = int(match["page"])
        source = str(match.get("source") or "title_search")
        item["physical_index"] = physical_page
        item["mapping_source"] = source
        item["mapping_confidence"] = round(float(match["score"]), 4)
        item["mapping_evidence"] = {
            "matched_page": physical_page,
            "score": round(float(match["score"]), 4),
            "matched_fragments": match.get("matched_fragments", [])[:3],
            **_match_position_evidence(match),
        }
        strong_anchor_indices.append(index)
        cursor_by_catalog[catalog_type] = physical_page

    if allow_neighbor_inference:
        _infer_missing_between_anchors(items, page_count, start_page)
    report = _build_report(
        items,
        shape,
        min_title_match_rate=min_title_match_rate,
        excluded_pages=excluded_page_set,
        require_all_mapped=require_all_mapped,
    )
    return items, report


def page_texts_to_map(page_texts: Any, *, page_count: Optional[int] = None) -> Dict[int, str]:
    if isinstance(page_texts, dict):
        result = {}
        for key, value in page_texts.items():
            page = _positive_int(key)
            if page is not None:
                result[page] = _page_text(value)
        return result

    if not isinstance(page_texts, list):
        return {}

    result: Dict[int, str] = {}
    limit = page_count if page_count and page_count > 0 else len(page_texts)
    for index, value in enumerate(page_texts[:limit], start=1):
        result[index] = _page_text(value)
    return result


def detect_logical_page_shape(items: List[Dict[str, Any]], page_count: int) -> Dict[str, Any]:
    explicit_values = _logical_values(items, include_physical_fallback=False)
    uses_physical_fallback = not explicit_values
    values = explicit_values or _logical_values(items, include_physical_fallback=True)
    overflow = bool(values and page_count > 0 and max(values) > page_count)
    diffs = [
        values[index + 1] - values[index]
        for index in range(len(values) - 1)
        if values[index + 1] >= values[index]
    ]
    regular_step = None
    regular_step_ratio = 0.0
    if diffs:
        regular_step, count = Counter(diffs).most_common(1)[0]
        regular_step_ratio = count / len(diffs)
    suspected = bool(
        overflow
        or (
            regular_step is not None
            and regular_step > 1
            and regular_step_ratio >= 0.6
        )
    )
    return {
        "logical_overflow": overflow,
        "regular_step": regular_step,
        "regular_step_ratio": round(regular_step_ratio, 4),
        "multi_logical_per_physical_suspected": suspected,
        "uses_physical_as_logical_fallback": uses_physical_fallback,
    }


def normalize_title_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    return normalized


def _strip_outline_prefix(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"^(?:part|chapter|section)\s*0*\d{1,3}(?:[.:：\-、\s]+)?",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:第\s*)?[0-9一二三四五六七八九十百千]{1,4}[章节篇部]\s*[.:：\-、\s]*",
        "",
        value,
    )
    value = re.sub(
        r"^(?:[0-9一二三四五六七八九十百千]{1,4})(?:[.)、．。\-\s]+)",
        "",
        value,
    )
    return value


def title_fragments(title: str) -> List[str]:
    normalized = normalize_title_text(title)
    without_prefix = re.sub(
        r"^(?:第?[一二三四五六七八九十百千万零]+[章节篇部]?|[0-9]{1,3}(?:[.、．]\d+)*)",
        "",
        normalized,
    )
    outline_without_prefix = normalize_title_text(_strip_outline_prefix(title))
    if outline_without_prefix and outline_without_prefix != normalized:
        without_prefix = outline_without_prefix
    variants = [normalized]
    if without_prefix and without_prefix != normalized:
        variants.append(without_prefix)

    fragments: List[str] = []
    for value in variants:
        if not value:
            continue
        if len(value) <= 18:
            fragments.append(value)
            continue
        fragments.extend([value[:18], value[:24], value[-18:]])
        mid_start = max(0, len(value) // 2 - 9)
        fragments.append(value[mid_start : mid_start + 18])

    seen = set()
    result = []
    for fragment in fragments:
        if len(fragment) < 4 or fragment in seen:
            continue
        seen.add(fragment)
        result.append(fragment)
    return result


def score_title_on_page(title: str, page_text: str) -> Dict[str, Any]:
    normalized_page = normalize_title_text(page_text)
    full = normalize_title_text(title)
    if not full or not normalized_page:
        return {"score": 0.0, "matched_fragments": []}

    heading_match = _score_title_on_heading_lines(title, page_text)
    if float(heading_match.get("score") or 0.0) >= 0.95:
        return heading_match

    candidates: List[Dict[str, Any]] = []
    if float(heading_match.get("score") or 0.0) > 0.0:
        candidates.append(heading_match)

    segmented_match = _score_segmented_title_on_page(title, normalized_page)
    if float(segmented_match.get("score") or 0.0) > 0.0:
        candidates.append(segmented_match)

    if len(full) >= 4 and full in normalized_page:
        candidates.append({"score": 0.9, "matched_fragments": [full[:30]]})
    if 2 <= len(full) < 4:
        normalized_lines = [
            normalize_title_text(line)
            for line in str(page_text or "").splitlines()
            if str(line or "").strip()
        ]
        if full in normalized_lines:
            candidates.append({"score": 0.92, "matched_fragments": [full]})

    fragments = title_fragments(title)
    matched = [fragment for fragment in fragments if fragment in normalized_page]
    if not matched:
        fuzzy = _best_fuzzy_fragment_match(fragments, normalized_page)
        if fuzzy is not None:
            candidates.append(
                {
                    "score": fuzzy["score"],
                    "matched_fragments": [f"~{fuzzy['fragment'][:30]}"],
                }
            )
        return _best_scored_candidate(candidates)

    ratio = len(matched) / max(1, len(fragments))
    longest = max(len(fragment) for fragment in matched)
    score = 0.58 + min(0.32, ratio * 0.24) + min(0.1, longest / 200)
    candidates.append({"score": min(0.95, score), "matched_fragments": matched})
    return _best_scored_candidate(candidates)


def _score_title_on_heading_lines(title: str, page_text: str) -> Dict[str, Any]:
    variants = _title_match_variants(title)
    if not variants:
        return {"score": 0.0, "matched_fragments": []}

    marker_patterns = _outline_marker_patterns(title)
    lines = [str(line or "").strip() for line in str(page_text or "").splitlines()]
    lines = [line for line in lines if line]
    best: Optional[Dict[str, Any]] = None
    for line_index, line in enumerate(lines[:12]):
        line_variants = _title_match_variants(line)
        line_has_same_marker = any(pattern.search(line) for pattern in marker_patterns)
        for title_variant in variants:
            for line_variant in line_variants:
                score = _score_heading_line_variant(title_variant, line_variant)
                if score <= 0.0:
                    continue
                if marker_patterns and not line_has_same_marker:
                    score = min(score, 0.57)
                score = max(0.0, score - min(0.04, line_index * 0.003))
                candidate = {
                    "score": round(score, 4),
                    "matched_fragments": [f"line:{normalize_title_text(line)[:30]}"],
                }
                if best is None or float(candidate["score"]) > float(best["score"]):
                    best = candidate
    return best or {"score": 0.0, "matched_fragments": []}


def _title_match_variants(text: str) -> List[str]:
    variants = [normalize_title_text(text), normalize_title_text(_strip_outline_prefix(text))]
    result: List[str] = []
    seen: set[str] = set()
    for variant in variants:
        if not variant or variant in seen:
            continue
        seen.add(variant)
        result.append(variant)
    return result


def _score_heading_line_variant(title_variant: str, line_variant: str) -> float:
    if not title_variant or not line_variant:
        return 0.0
    if title_variant == line_variant:
        return 1.0
    if len(title_variant) >= 4 and (
        line_variant.startswith(title_variant) or title_variant in line_variant
    ):
        return 0.98
    if 2 <= len(title_variant) < 4 and line_variant.startswith(title_variant) and len(line_variant) <= len(title_variant) + 12:
        return 0.92
    if len(title_variant) < 8 or len(line_variant) < 8:
        return 0.0
    ratio = SequenceMatcher(None, title_variant, line_variant).ratio()
    if ratio >= 0.9:
        if _contains_cjk(title_variant + line_variant) and min(len(title_variant), len(line_variant)) < 14:
            required_prefix = max(2, min(4, min(len(title_variant), len(line_variant)) // 3))
            if _shared_prefix_length(title_variant, line_variant) < required_prefix:
                return 0.0
        return min(0.98, 0.96 + (ratio - 0.9) * 0.2)
    if ratio >= 0.84:
        return 0.84 + (ratio - 0.84) * 1.5
    return 0.0


def _best_scored_candidate(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return {"score": 0.0, "matched_fragments": []}
    return max(candidates, key=lambda candidate: float(candidate.get("score") or 0.0))


def _score_segmented_title_on_page(title: str, normalized_page: str) -> Dict[str, Any]:
    """Score headings whose visible title parts are split by layout text.

    VLM/OCR output often inserts coordinates, badges, or subtitles between the
    parts of a visible heading. Full-title substring matching then fails even
    though the page contains the same heading in reading order. This scorer only
    uses meaningful title segments and requires multiple pieces of evidence.
    """
    if not normalized_page:
        return {"score": 0.0, "matched_fragments": []}

    segments = _title_visible_segments(title)
    if len(segments) < 2:
        return {"score": 0.0, "matched_fragments": []}

    matched: List[Tuple[str, int]] = []
    cursor = 0
    for segment in segments:
        position = normalized_page.find(segment, cursor)
        if position < 0:
            position = normalized_page.find(segment)
        if position >= 0:
            matched.append((segment, position))
            cursor = position + len(segment)

    if len(matched) < 2:
        return {"score": 0.0, "matched_fragments": []}

    marker_segments = {segment for segment in segments if _is_outline_marker_segment(segment)}
    matched_segments = {segment for segment, _position in matched}
    content_segments = [segment for segment in segments if segment not in marker_segments]
    matched_content = [segment for segment in content_segments if segment in matched_segments]
    has_marker = bool(marker_segments)
    marker_matched = bool(marker_segments.intersection(matched_segments))

    if has_marker:
        min_content_matches = min(2, len(content_segments))
        if not marker_matched or len(matched_content) < max(1, min_content_matches):
            return {"score": 0.0, "matched_fragments": []}
        content_coverage = len(matched_content) / max(1, len(content_segments))
        score = 0.82 + min(0.1, content_coverage * 0.1)
    else:
        if len(matched_content) < 2:
            return {"score": 0.0, "matched_fragments": []}
        coverage = len(matched_content) / max(1, len(content_segments))
        if coverage < 0.5:
            return {"score": 0.0, "matched_fragments": []}
        score = 0.72 + min(0.18, coverage * 0.18)

    ordered_positions = [position for _segment, position in matched]
    if ordered_positions != sorted(ordered_positions):
        score = min(score, 0.78)

    return {
        "score": round(min(0.92, score), 4),
        "matched_fragments": [segment[:30] for segment, _position in matched[:5]],
    }


def _title_visible_segments(title: str) -> List[str]:
    value = unicodedata.normalize("NFKC", str(title or "")).lower()
    value = re.sub(r"<[^>]+>", " ", value)
    raw_parts = re.split(
        r"[\s:：;；,，、/\\|()\[\]{}<>《》“”\"'‘’\-–—]+",
        value,
    )
    segments: List[str] = []
    for part in raw_parts:
        normalized = normalize_title_text(part)
        if not normalized:
            continue
        if normalized in {"chapter", "part", "section"}:
            continue
        if len(normalized) < 4 and not _is_outline_marker_segment(normalized):
            continue
        segments.append(normalized)

    # Titles without punctuation may still contain a leading outline marker.
    compact = normalize_title_text(value)
    marker = re.match(r"^(part\d{1,3}|chapter\d{1,3}|section\d{1,3}|\d{1,3}(?:\.\d{1,3})*)", compact)
    if marker and marker.group(1) not in segments:
        segments.insert(0, marker.group(1))

    result: List[str] = []
    seen: set[str] = set()
    for segment in segments:
        if segment in seen:
            continue
        seen.add(segment)
        result.append(segment)
    return result


def _is_outline_marker_segment(segment: str) -> bool:
    return bool(
        re.fullmatch(r"(?:part|chapter|section)\d{1,3}", segment)
        or re.fullmatch(r"\d{1,3}(?:\.\d{1,3})*", segment)
    )


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in str(text or ""))


def _shared_prefix_length(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _best_fuzzy_fragment_match(fragments: List[str], normalized_page: str) -> Optional[Dict[str, Any]]:
    max_windows_per_fragment = 24
    best: Optional[Dict[str, Any]] = None
    for fragment in fragments:
        if len(fragment) < 10 or re.search(r"\d", fragment):
            continue
        window = len(fragment)
        max_start = max(0, len(normalized_page) - window)
        if max_start <= 0:
            starts = [0]
        else:
            step = max(1, max_start // max_windows_per_fragment)
            starts = list(range(0, max_start + 1, step))[:max_windows_per_fragment]
            if starts[-1] != max_start:
                starts.append(max_start)
        for start in starts:
            sample = normalized_page[start : start + window]
            if len(sample) < window:
                continue
            ratio = SequenceMatcher(None, fragment, sample).ratio()
            if ratio < 0.86:
                continue
            if best is None or ratio > best["ratio"]:
                best = {"fragment": fragment, "ratio": ratio}
    if best is None:
        return None
    return {
        "fragment": best["fragment"],
        "score": min(0.9, 0.58 + (best["ratio"] - 0.86) * 1.6),
    }


def find_title_page(
    title: str,
    page_text_map: Dict[int, str],
    *,
    start_page: int,
    end_page: int,
    excluded_pages: Iterable[int],
) -> Optional[Dict[str, Any]]:
    excluded = set(excluded_pages or [])
    best: Optional[Dict[str, Any]] = None
    for page in range(max(1, start_page), max(start_page, end_page) + 1):
        if page in excluded:
            continue
        scored = score_title_on_page(title, page_text_map.get(page, ""))
        score = float(scored.get("score") or 0.0)
        if score < 0.58:
            continue
        candidate = {
            "page": page,
            "score": score,
            "matched_fragments": scored.get("matched_fragments") or [],
            **_title_position_evidence(title, page_text_map.get(page, "")),
        }
        if best is None or score > float(best["score"]):
            best = candidate
        if score >= 0.95:
            return candidate
    return best


def _match_position_evidence(match: Dict[str, Any]) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {}
    for key in ("line_index", "char_offset", "meaningful_lines_before", "near_page_top"):
        if key in match:
            evidence[key] = match[key]
    return evidence


def _title_position_evidence(title: str, page_text: str) -> Dict[str, Any]:
    variants = _title_match_variants(title)
    if not variants:
        return {}

    text = str(page_text or "")
    char_offset = 0
    meaningful_before = 0
    for line_index, line in enumerate(text.splitlines()):
        stripped = str(line or "").strip()
        if not stripped:
            char_offset += len(line) + 1
            continue
        line_variants = _title_match_variants(stripped)
        matched = False
        for title_variant in variants:
            for line_variant in line_variants:
                if (
                    _score_heading_line_variant(title_variant, line_variant) >= 0.58
                    or (len(title_variant) >= 4 and title_variant in line_variant)
                ):
                    matched = True
                    break
            if matched:
                break
        if matched:
            return {
                "line_index": line_index,
                "char_offset": char_offset,
                "meaningful_lines_before": meaningful_before,
                "near_page_top": line_index <= 2 and meaningful_before <= 1 and char_offset <= 160,
            }
        meaningful_before += 1
        char_offset += len(line) + 1

    full = normalize_title_text(title)
    normalized = normalize_title_text(text)
    normalized_offset = normalized.find(full) if full else -1
    if normalized_offset < 0:
        return {}
    return {
        "char_offset": normalized_offset,
        "near_page_top": normalized_offset <= 80,
    }


def _regex_match_position_evidence(text: str, start: int) -> Dict[str, Any]:
    prefix = str(text or "")[: max(0, int(start or 0))]
    line_index = prefix.count("\n")
    meaningful_before = sum(1 for line in prefix.splitlines() if line.strip())
    return {
        "line_index": line_index,
        "char_offset": max(0, int(start or 0)),
        "meaningful_lines_before": meaningful_before,
        "near_page_top": line_index <= 2 and meaningful_before <= 1 and int(start or 0) <= 160,
    }


def find_outline_marker_page(
    title: str,
    page_text_map: Dict[int, str],
    *,
    start_page: int,
    end_page: int,
    excluded_pages: Iterable[int],
) -> Optional[Dict[str, Any]]:
    patterns = _outline_marker_patterns(title)
    if patterns:
        excluded = set(excluded_pages or [])
        for page in range(max(1, start_page), max(start_page, end_page) + 1):
            if page in excluded:
                continue
            text = str(page_text_map.get(page, "") or "")
            heading_text = "\n".join(line for line in text.splitlines()[:16] if line.strip())
            for pattern in patterns:
                marker_match = pattern.search(heading_text)
                if not marker_match:
                    continue
                return {
                    "page": page,
                    "score": 0.82,
                    "matched_fragments": [marker_match.group(0).strip()[:30]],
                    "source": "outline_marker",
                    **_regex_match_position_evidence(text, marker_match.start()),
                }

    match = re.match(r"^\s*(\d{1,3})(?:[.)\u3001\uff0e]\s*|\s+)", str(title or ""))
    if not match:
        return None
    marker = re.escape(match.group(1))
    pattern = re.compile(
        rf"(?:^|[\r\n]|\s{{2,}}){marker}\s*[.\uff0e\u3001]\s*(?:\d{{1,2}}[)）]|[A-Za-z\u4e00-\u9fff])",
        re.MULTILINE,
    )
    excluded = set(excluded_pages or [])
    for page in range(max(1, start_page), max(start_page, end_page) + 1):
        if page in excluded:
            continue
        text = str(page_text_map.get(page, "") or "")
        marker_match = pattern.search(text)
        if not marker_match:
            continue
        return {
            "page": page,
            "score": 0.78,
            "matched_fragments": [marker_match.group(0).strip()[:30]],
            "source": "outline_marker",
            **_regex_match_position_evidence(text, marker_match.start()),
        }
    return None


def _outline_marker_patterns(title: str) -> List[re.Pattern[str]]:
    text = str(title or "")
    patterns: List[re.Pattern[str]] = []

    numeric = re.match(r"^\s*(\d{1,3})(?:[.)\u3001\uff0e]\s*|\s+)", text)
    if numeric:
        marker = re.escape(numeric.group(1))
        patterns.append(
            re.compile(
                rf"(?:^|[\r\n]|\s{{2,}}){marker}\s*[.\uff0e\u3001]\s*(?:\d{{1,2}}[)）]|[A-Za-z\u4e00-\u9fff])",
                re.MULTILINE,
            )
        )

    english = re.match(r"^\s*(chapter|part|section)\s*0*(\d{1,3})\b", text, re.IGNORECASE)
    if english:
        label = re.escape(english.group(1))
        number = re.escape(english.group(2))
        patterns.append(
            re.compile(
                rf"(?:^|[\r\n])\s*{label}\s*0*{number}\b",
                re.IGNORECASE | re.MULTILINE,
            )
        )

    chinese = re.match(r"^\s*第\s*([一二三四五六七八九十百千万零〇\d]{1,6})\s*([章节篇部])", text)
    if chinese:
        marker = re.escape(chinese.group(1))
        unit = re.escape(chinese.group(2))
        patterns.append(
            re.compile(
                rf"(?:^|[\r\n])\s*第\s*{marker}\s*{unit}",
                re.MULTILINE,
            )
        )

    chinese_list = re.match(r"^\s*([一二三四五六七八九十百千万零〇]{1,6})\s*[、.．]\s*", text)
    if chinese_list:
        marker = re.escape(chinese_list.group(1))
        patterns.append(
            re.compile(
                rf"(?:^|[\r\n])\s*{marker}\s*[、.．]",
                re.MULTILINE,
            )
        )
    return patterns


def _normalize_logical_fields(
    items: List[Dict[str, Any]],
    page_count: int,
    shape: Dict[str, Any],
) -> None:
    allow_physical_logical_fallback = bool(shape.get("uses_physical_as_logical_fallback"))
    for item in items:
        page = _positive_int(item.get("page"))
        physical = _positive_int(item.get("physical_index"))
        if page is None and physical is not None and allow_physical_logical_fallback and (
            shape.get("logical_overflow")
            or (page_count > 0 and physical > page_count)
            or shape.get("regular_step", 0) and shape.get("regular_step", 0) > 1
        ):
            page = physical
        if page is not None:
            item["page"] = page
            item["logical_page"] = page
        elif _positive_int(item.get("logical_page")) is not None:
            item["logical_page"] = _positive_int(item.get("logical_page"))


def _infer_missing_between_anchors(
    items: List[Dict[str, Any]],
    page_count: int,
    start_page: int,
    *,
    include_auxiliary_catalogs: bool = False,
) -> None:
    anchor_sources = {"title_search", "outline_marker", "printed_page_offset"}
    anchor_indices = [
        index
        for index, item in enumerate(items)
        if item.get("mapping_source") in anchor_sources
        and _positive_int(item.get("physical_index")) is not None
    ]
    if not anchor_indices:
        return

    for index, item in enumerate(items):
        if _positive_int(item.get("physical_index")) is not None:
            continue
        catalog_type = str(item.get("catalog_type") or CATALOG_MAIN)
        if catalog_type != CATALOG_MAIN and not include_auxiliary_catalogs:
            continue
        same_catalog_anchors = [
            anchor
            for anchor in anchor_indices
            if str(items[anchor].get("catalog_type") or CATALOG_MAIN) == catalog_type
        ]
        previous_anchor = next((anchor for anchor in reversed(same_catalog_anchors) if anchor < index), None)
        next_anchor = next((anchor for anchor in same_catalog_anchors if anchor > index), None)
        inferred = None
        if previous_anchor is not None:
            inferred = _positive_int(items[previous_anchor].get("physical_index"))
        elif next_anchor is not None:
            inferred = _positive_int(items[next_anchor].get("physical_index")) or start_page
        if inferred is None:
            continue
        item["physical_index"] = max(1, min(page_count, inferred))
        item["mapping_source"] = "neighbor_inference"
        item["mapping_confidence"] = 0.45


def _build_report(
    items: List[Dict[str, Any]],
    shape: Dict[str, Any],
    *,
    status: Optional[str] = None,
    reasons: Optional[List[str]] = None,
    min_title_match_rate: float = 0.55,
    excluded_pages: Optional[Iterable[int]] = None,
    require_all_mapped: bool = False,
) -> Dict[str, Any]:
    reasons = list(reasons or [])
    report_items = _items_for_main_mapping_report(items)
    item_count = len(report_items)
    strong_anchor_indices = [
        index
        for index, item in enumerate(report_items)
        if item.get("mapping_source") == "title_search"
        and _positive_int(item.get("physical_index")) is not None
    ]
    mapped_pages = [
        _positive_int(item.get("physical_index"))
        for item in report_items
        if _positive_int(item.get("physical_index")) is not None
    ]
    unmapped_count = sum(
        1
        for item in report_items
        if str(item.get("title") or "").strip()
        and _positive_int(item.get("physical_index")) is None
    )
    inferred_count = sum(1 for item in report_items if item.get("mapping_source") == "neighbor_inference")
    title_match_rate = len(strong_anchor_indices) / item_count if item_count else 0.0
    estimated_ratio = inferred_count / item_count if item_count else 0.0
    mapping_monotonic = all(
        left <= right
        for left, right in zip(mapped_pages, mapped_pages[1:])
        if left is not None and right is not None
    )
    tail_collapse = _tail_collapse(mapped_pages, item_count)
    front_collapse = _front_collapse(mapped_pages, item_count, excluded_pages=excluded_pages)
    toc_page_match_count = sum(
        1
        for page in mapped_pages
        if page is not None and page in set(_positive_int(value) for value in (excluded_pages or []) if _positive_int(value) is not None)
    )
    anchor_coverage = _anchor_coverage(strong_anchor_indices, item_count)

    if item_count and not strong_anchor_indices and shape.get("logical_overflow"):
        reasons.append("logical_overflow_without_content_anchors")
    if item_count and not mapped_pages:
        reasons.append("no_content_anchors")
    if tail_collapse:
        reasons.append("tail_collapse")
    if front_collapse:
        reasons.append("front_collapse")
    if item_count and toc_page_match_count / item_count >= 0.3 and toc_page_match_count >= 2:
        reasons.append("toc_page_leakage")
    if item_count and title_match_rate < min_title_match_rate:
        reasons.append("title_match_rate_below_threshold")
    if require_all_mapped and unmapped_count:
        reasons.append("unmapped_required_anchor")
    if not mapping_monotonic:
        reasons.append("mapping_non_monotonic")

    if status is None:
        severe = (
            not item_count
            or "no_content_anchors" in reasons
            or "logical_overflow_without_content_anchors" in reasons
            or "tail_collapse" in reasons
            or "front_collapse" in reasons
            or "toc_page_leakage" in reasons
            or not mapping_monotonic
            or "title_match_rate_below_threshold" in reasons
            or "unmapped_required_anchor" in reasons
        )
        status = "failed" if severe else "ok"

    mapped_ratio = len(mapped_pages) / item_count if item_count else 0.0
    page_mapping_score = 0.0
    if item_count:
        page_mapping_score = (
            title_match_rate * 0.7
            + max(0.0, 1.0 - estimated_ratio) * 0.15
            + mapped_ratio * 0.15
        )
        if status == "failed":
            page_mapping_score = min(page_mapping_score, 0.49)

    return {
        "status": status,
        "strategy": "content_title_search",
        "excluded_pages": sorted(set(page for page in (_positive_int(value) for value in (excluded_pages or [])) if page is not None)),
        "logical_overflow": bool(shape.get("logical_overflow")),
        "regular_step": shape.get("regular_step"),
        "regular_step_ratio": shape.get("regular_step_ratio", 0.0),
        "multi_logical_per_physical_suspected": bool(
            shape.get("multi_logical_per_physical_suspected")
            or _has_duplicate_physical_pages(mapped_pages)
        ),
        "strong_anchor_count": len(strong_anchor_indices),
        "item_count": item_count,
        "unmapped_count": unmapped_count,
        "total_item_count": len(items),
        "auxiliary_item_count": len(items) - item_count,
        "title_match_rate": round(title_match_rate, 4),
        "sample_match_rate": round(title_match_rate, 4),
        "anchor_coverage": anchor_coverage,
        "mapping_monotonic": mapping_monotonic,
        "estimated_ratio": round(estimated_ratio, 4),
        "tail_collapse": tail_collapse,
        "front_collapse": front_collapse,
        "toc_page_leakage_count": toc_page_match_count,
        "page_mapping_score": round(page_mapping_score, 4),
        "reasons": sorted(set(reasons)),
    }


def _annotate_catalog_types(items: List[Dict[str, Any]]) -> None:
    for item in items:
        catalog_type = detect_catalog_type(item)
        item["catalog_type"] = catalog_type
        if catalog_type != CATALOG_MAIN:
            item["is_auxiliary"] = True


def _items_for_main_mapping_report(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    main_items = [item for item in items if str(item.get("catalog_type") or CATALOG_MAIN) == CATALOG_MAIN]
    return main_items or items


def _anchor_coverage(anchor_indices: List[int], item_count: int) -> Dict[str, bool]:
    if item_count <= 0:
        return {"front": False, "middle": False, "back": False}
    thirds = {
        "front": range(0, max(1, item_count // 3)),
        "middle": range(max(1, item_count // 3), max(2, (item_count * 2) // 3)),
        "back": range(max(2, (item_count * 2) // 3), item_count),
    }
    anchors = set(anchor_indices)
    return {name: bool(anchors.intersection(indices)) for name, indices in thirds.items()}

def _map_printed_page_numbers(
    items: List[Dict[str, Any]],
    *,
    page_text_map: Dict[int, str],
    page_count: int,
    toc_page_set: set[int],
    excluded_page_set: set[int],
    start_page: int,
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    indexed_pages = [
        (index, _positive_int(item.get("page") or item.get("logical_page")))
        for index, item in enumerate(items)
    ]
    indexed_pages = [(index, page) for index, page in indexed_pages if page is not None]
    if not indexed_pages:
        return None
    indexed_item_indices = {index for index, _ in indexed_pages}
    trusted_sources = {"title_search", "outline_marker"}
    for index, item in enumerate(items):
        if index in indexed_item_indices:
            continue
        if item.get("mapping_source") in trusted_sources:
            continue
        item.pop("physical_index", None)
        item.pop("mapping_source", None)
        item.pop("mapping_confidence", None)

    logical_pages = [page for _, page in indexed_pages]
    if not _logical_pages_monotonic_by_catalog(items, indexed_pages):
        report = _build_printed_page_report(
            items,
            page_text_map=page_text_map,
            page_count=page_count,
            toc_page_set=excluded_page_set,
            status="failed",
            reasons=["printed_pages_non_monotonic"],
        )
        return items, report

    if _should_use_ordinal_printed_mapping(items, indexed_pages, page_count, start_page):
        ordinal_start = _ordinal_printed_start_from_title_matches(
            items,
            indexed_pages,
            page_text_map=page_text_map,
            page_count=page_count,
            excluded_page_set=excluded_page_set,
            start_page=start_page,
        )
        if ordinal_start is None:
            ordinal_start = start_page
        for ordinal, (index, logical_page) in enumerate(indexed_pages):
            physical_page = max(1, min(page_count, ordinal_start + ordinal))
            _set_printed_page_mapping(items[index], logical_page, physical_page)
        _apply_title_overrides_after_printed_mapping(
            items,
            page_text_map=page_text_map,
            page_count=page_count,
            toc_page_set=toc_page_set,
            excluded_page_set=excluded_page_set,
            start_page=start_page,
        )
        _infer_missing_between_anchors(
            items,
            page_count,
            start_page,
            include_auxiliary_catalogs=True,
        )
        report = _build_printed_page_report(
            items,
            page_text_map=page_text_map,
            page_count=page_count,
            toc_page_set=excluded_page_set,
            status=None,
            reasons=[],
        )
        return items, report

    offset = _printed_page_offset_from_title_matches(
        items,
        indexed_pages,
        page_text_map=page_text_map,
        page_count=page_count,
        toc_page_set=toc_page_set,
        excluded_page_set=excluded_page_set,
        start_page=start_page,
    )
    offset_from_title_anchors = offset is not None
    if offset is None:
        offset = start_page - _base_logical_page_for_offset(items, indexed_pages)

    estimated_last = max(logical_pages) + offset
    if estimated_last <= page_count or offset_from_title_anchors:
        for index, logical_page in indexed_pages:
            physical_page = max(1, min(page_count, logical_page + offset))
            _set_printed_page_mapping(items[index], logical_page, physical_page)
    else:
        logical_range = max(1, max(logical_pages) - min(logical_pages))
        physical_range = max(1, page_count - start_page + 1)
        scale = physical_range / logical_range
        first_logical = logical_pages[0]
        for index, logical_page in indexed_pages:
            physical_page = start_page + (logical_page - first_logical) * scale
            _set_printed_page_mapping(
                items[index],
                logical_page,
                max(1, min(page_count, round(physical_page))),
            )

    _apply_title_overrides_after_printed_mapping(
        items,
        page_text_map=page_text_map,
        page_count=page_count,
        toc_page_set=toc_page_set,
        excluded_page_set=excluded_page_set,
        start_page=start_page,
    )
    _infer_missing_between_anchors(
        items,
        page_count,
        start_page,
        include_auxiliary_catalogs=True,
    )
    report = _build_printed_page_report(
        items,
        page_text_map=page_text_map,
        page_count=page_count,
        toc_page_set=excluded_page_set,
        status=None,
        reasons=[],
    )
    return items, report


def _should_use_ordinal_printed_mapping(
    items: List[Dict[str, Any]],
    indexed_pages: List[Tuple[int, int]],
    page_count: int,
    start_page: int,
) -> bool:
    if len(indexed_pages) < 4 or page_count <= 0:
        return False
    catalogs = {
        str(items[index].get("catalog_type") or CATALOG_MAIN)
        for index, _ in indexed_pages
        if isinstance(items[index], dict)
    }
    if len(catalogs) != 1:
        return False
    logical_pages = [page for _, page in indexed_pages]
    diffs = [
        logical_pages[index + 1] - logical_pages[index]
        for index in range(len(logical_pages) - 1)
    ]
    if not diffs:
        return False
    step, count = Counter(diffs).most_common(1)[0]
    if step <= 1 or count / len(diffs) < 0.8:
        return False
    logical_last_with_simple_offset = max(logical_pages) + start_page - logical_pages[0]
    if logical_last_with_simple_offset <= page_count:
        return False
    physical_slots = max(1, page_count - start_page + 1)
    return len(indexed_pages) <= physical_slots + 1


def _ordinal_printed_start_from_title_matches(
    items: List[Dict[str, Any]],
    indexed_pages: List[Tuple[int, int]],
    *,
    page_text_map: Dict[int, str],
    page_count: int,
    excluded_page_set: set[int],
    start_page: int,
) -> Optional[int]:
    offsets: List[int] = []
    cursor = start_page
    for ordinal, (index, _logical_page) in enumerate(indexed_pages[:12]):
        title = str(items[index].get("title") or "").strip()
        if not title:
            continue
        match = find_title_page(
            title,
            page_text_map,
            start_page=cursor,
            end_page=page_count,
            excluded_pages=excluded_page_set,
        )
        if not match:
            continue
        physical_page = int(match["page"])
        offsets.append(physical_page - ordinal)
        cursor = physical_page
    if not offsets:
        return None
    return max(1, min(page_count, Counter(offsets).most_common(1)[0][0]))


def _printed_page_offset_from_title_matches(
    items: List[Dict[str, Any]],
    indexed_pages: List[Tuple[int, int]],
    *,
    page_text_map: Dict[int, str],
    page_count: int,
    toc_page_set: set[int],
    excluded_page_set: set[int],
    start_page: int,
) -> Optional[int]:
    offsets: List[int] = []
    cursor_by_catalog: Dict[str, int] = {}
    sample_count_by_catalog: Dict[str, int] = {}
    for index, logical_page in indexed_pages:
        catalog_type = str(items[index].get("catalog_type") or CATALOG_MAIN)
        if sample_count_by_catalog.get(catalog_type, 0) >= 12:
            continue
        sample_count_by_catalog[catalog_type] = sample_count_by_catalog.get(catalog_type, 0) + 1
        title = str(items[index].get("title") or "").strip()
        if not title:
            continue
        cursor = cursor_by_catalog.get(catalog_type, start_page)
        match = find_title_page(
            title,
            page_text_map,
            start_page=cursor,
            end_page=page_count,
            excluded_pages=excluded_page_set,
        )
        if not match:
            continue
        physical_page = int(match["page"])
        offsets.append(physical_page - logical_page)
        cursor_by_catalog[catalog_type] = physical_page
    if not offsets:
        return None
    return Counter(offsets).most_common(1)[0][0]


def _logical_pages_monotonic_by_catalog(
    items: List[Dict[str, Any]],
    indexed_pages: List[Tuple[int, int]],
) -> bool:
    pages_by_catalog: Dict[str, List[int]] = {}
    for index, logical_page in indexed_pages:
        catalog_type = str(items[index].get("catalog_type") or CATALOG_MAIN)
        pages_by_catalog.setdefault(catalog_type, []).append(logical_page)
    return all(
        all(left <= right for left, right in zip(pages, pages[1:]))
        for pages in pages_by_catalog.values()
    )


def _base_logical_page_for_offset(
    items: List[Dict[str, Any]],
    indexed_pages: List[Tuple[int, int]],
) -> int:
    for index, logical_page in indexed_pages:
        if str(items[index].get("catalog_type") or CATALOG_MAIN) == CATALOG_MAIN:
            return logical_page
    return 1


def _set_printed_page_mapping(item: Dict[str, Any], logical_page: int, physical_page: int) -> None:
    item["page"] = logical_page
    item["logical_page"] = logical_page
    item["physical_index"] = physical_page
    item["mapping_source"] = "printed_page_offset"
    item["mapping_confidence"] = 0.72


def _apply_title_overrides_after_printed_mapping(
    items: List[Dict[str, Any]],
    *,
    page_text_map: Dict[int, str],
    page_count: int,
    toc_page_set: set[int],
    excluded_page_set: set[int],
    start_page: int,
) -> None:
    cursor_by_catalog: Dict[str, int] = {}
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        catalog_type = str(item.get("catalog_type") or CATALOG_MAIN)
        current_page = _positive_int(item.get("physical_index"))
        if item.get("mapping_source") != "printed_page_offset" and current_page is not None:
            cursor_by_catalog[catalog_type] = max(cursor_by_catalog.get(catalog_type, start_page), current_page)
            continue
        cursor = cursor_by_catalog.get(catalog_type, start_page)
        is_printed_mapping = item.get("mapping_source") == "printed_page_offset"
        match = find_title_page(
            title,
            page_text_map,
            start_page=cursor,
            end_page=page_count,
            excluded_pages=excluded_page_set,
        )
        score = float(match.get("score") or 0.0) if match else 0.0
        if is_printed_mapping:
            if score < 0.75:
                if current_page is not None:
                    cursor_by_catalog[catalog_type] = max(
                        cursor_by_catalog.get(catalog_type, start_page),
                        current_page,
                    )
                continue
        elif not match:
            match = (
                find_outline_marker_page(
                    title,
                    page_text_map,
                    start_page=cursor,
                    end_page=page_count,
                    excluded_pages=excluded_page_set,
                )
                if catalog_type == CATALOG_MAIN
                else None
            )
        if not match:
            continue
        score = float(match.get("score") or 0.0)
        physical_page = int(match["page"])
        if is_printed_mapping and current_page is not None and physical_page < current_page:
            current_score = score_title_on_page(title, page_text_map.get(current_page, ""))
            if float(current_score.get("score") or 0.0) >= 0.58:
                cursor_by_catalog[catalog_type] = max(
                    cursor_by_catalog.get(catalog_type, start_page),
                    current_page,
                )
                continue
        source = str(match.get("source") or "title_search")
        item["physical_index"] = physical_page
        item["mapping_source"] = source
        item["mapping_confidence"] = round(score, 4)
        item["mapping_evidence"] = {
            "matched_page": physical_page,
            "score": round(score, 4),
            "matched_fragments": match.get("matched_fragments", [])[:3],
            "overrode": "printed_page_offset" if current_page is not None else "unmapped",
            **_match_position_evidence(match),
        }
        cursor_by_catalog[catalog_type] = physical_page


def _build_printed_page_report(
    items: List[Dict[str, Any]],
    *,
    page_text_map: Dict[int, str],
    page_count: int,
    toc_page_set: set[int],
    status: Optional[str],
    reasons: List[str],
) -> Dict[str, Any]:
    item_count = len(items)
    mapped_pages = [
        _positive_int(item.get("physical_index"))
        for item in items
        if _positive_int(item.get("physical_index")) is not None
    ]
    logical_pages = [
        _positive_int(item.get("logical_page") or item.get("page"))
        for item in items
        if _positive_int(item.get("logical_page") or item.get("page")) is not None
    ]
    strong_anchor_indices = _printed_page_title_anchors(items, page_text_map)
    sample_checked_count = sum(
        1
        for item in items
        if item.get("mapping_source") in {"printed_page_offset", "title_search", "outline_marker"}
        and _positive_int(item.get("physical_index")) is not None
        and str(item.get("title") or "").strip()
    )
    main_sample_checked_count = sum(
        1
        for item in items
        if str(item.get("catalog_type") or CATALOG_MAIN) == CATALOG_MAIN
        and item.get("mapping_source") in {"printed_page_offset", "title_search", "outline_marker"}
        and _positive_int(item.get("physical_index")) is not None
        and str(item.get("title") or "").strip()
    )
    main_strong_anchor_indices = [
        index
        for index in strong_anchor_indices
        if str(items[index].get("catalog_type") or CATALOG_MAIN) == CATALOG_MAIN
    ]
    title_match_rate = len(strong_anchor_indices) / sample_checked_count if sample_checked_count else 0.0
    main_title_match_rate = (
        len(main_strong_anchor_indices) / main_sample_checked_count
        if main_sample_checked_count
        else 0.0
    )
    mapped_ratio = len(mapped_pages) / item_count if item_count else 0.0
    mapping_monotonic = _physical_pages_monotonic_by_catalog(items)
    pages_in_range = all(1 <= page <= page_count for page in mapped_pages) if page_count else True
    tail_collapse = _tail_collapse(mapped_pages, item_count)
    front_collapse = _front_collapse(mapped_pages, item_count, excluded_pages=toc_page_set)
    toc_page_match_count = sum(1 for page in mapped_pages if page in toc_page_set)

    if not mapping_monotonic:
        reasons.append("mapping_non_monotonic")
    if not pages_in_range:
        reasons.append("printed_pages_out_of_range")
    if tail_collapse:
        reasons.append("tail_collapse")
    if front_collapse:
        reasons.append("front_collapse")
    if toc_page_match_count:
        reasons.append("toc_page_leakage")

    if status is None:
        status = "failed" if reasons or not item_count else "ok"

    page_mapping_score = 0.0
    if item_count:
        page_mapping_score = 0.78 * mapped_ratio
        if sample_checked_count:
            page_mapping_score += min(0.18, title_match_rate * 0.18)
        if _has_duplicate_physical_pages(mapped_pages):
            page_mapping_score -= 0.08
        if status == "failed":
            page_mapping_score = min(page_mapping_score, 0.49)

    return {
        "status": status,
        "strategy": "printed_page_offset",
        "excluded_pages": sorted(toc_page_set),
        "logical_overflow": bool(logical_pages and max(logical_pages) > page_count),
        "regular_step": None,
        "regular_step_ratio": 0.0,
        "multi_logical_per_physical_suspected": _has_duplicate_physical_pages(mapped_pages),
        "strong_anchor_count": len(strong_anchor_indices),
        "item_count": item_count,
        "title_match_rate": round(title_match_rate, 4),
        "sample_match_rate": round(title_match_rate, 4),
        "sample_checked_count": sample_checked_count,
        "main_strong_anchor_count": len(main_strong_anchor_indices),
        "main_title_match_rate": round(main_title_match_rate, 4),
        "main_sample_checked_count": main_sample_checked_count,
        "anchor_coverage": _anchor_coverage(strong_anchor_indices, item_count),
        "mapping_monotonic": mapping_monotonic,
        "estimated_ratio": round(1.0 - mapped_ratio, 4) if item_count else 0.0,
        "tail_collapse": tail_collapse,
        "front_collapse": front_collapse,
        "toc_page_leakage_count": toc_page_match_count,
        "page_mapping_score": round(max(0.0, min(1.0, page_mapping_score)), 4),
        "reasons": sorted(set(reasons)),
    }


def _printed_page_title_anchors(items: List[Dict[str, Any]], page_text_map: Dict[int, str]) -> List[int]:
    anchors: List[int] = []
    for index, item in enumerate(items):
        if item.get("mapping_source") not in {"printed_page_offset", "title_search", "outline_marker"}:
            continue
        page = _positive_int(item.get("physical_index"))
        title = str(item.get("title") or "").strip()
        if page is None or not title:
            continue
        scored = score_title_on_page(title, page_text_map.get(page, ""))
        if float(scored.get("score") or 0.0) >= 0.58:
            anchors.append(index)
    return anchors


def _physical_pages_monotonic_by_catalog(items: List[Dict[str, Any]]) -> bool:
    pages_by_catalog: Dict[str, List[int]] = {}
    for item in items:
        page = _positive_int(item.get("physical_index"))
        if page is None:
            continue
        catalog_type = str(item.get("catalog_type") or CATALOG_MAIN)
        pages_by_catalog.setdefault(catalog_type, []).append(page)
    return all(
        all(left <= right for left, right in zip(pages, pages[1:]))
        for pages in pages_by_catalog.values()
    )


def _tail_collapse(mapped_pages: List[int], item_count: int) -> bool:
    if item_count < 5 or not mapped_pages:
        return False
    last_page = max(mapped_pages)
    if last_page <= 0:
        return False
    count = sum(1 for page in mapped_pages if page == last_page)
    return count / item_count > 0.3 and count >= 3


def _front_collapse(
    mapped_pages: List[int],
    item_count: int,
    *,
    excluded_pages: Optional[Iterable[int]] = None,
) -> bool:
    if item_count < 5 or not mapped_pages:
        return False
    first_page = mapped_pages[0]
    if first_page <= 0:
        return False
    count = 0
    for page in mapped_pages:
        if page != first_page:
            break
        count += 1
    if count / item_count > 0.3 and count >= 3:
        return True
    excluded = {page for page in (_positive_int(value) for value in (excluded_pages or [])) if page is not None}
    return bool(first_page in excluded and count >= 2)


def _has_duplicate_physical_pages(mapped_pages: List[int]) -> bool:
    return any(count > 1 for count in Counter(mapped_pages).values())


def _source_page_set(items: List[Dict[str, Any]]) -> set[int]:
    pages = {
        page
        for page in (_positive_int(item.get("source_page")) for item in items)
        if page is not None
    }
    return pages if len(pages) <= max(3, max(1, len(items) // 4)) else set()

def _logical_values(items: List[Dict[str, Any]], *, include_physical_fallback: bool) -> List[int]:
    values: List[int] = []
    for item in items:
        page = _positive_int(item.get("page"))
        if page is None:
            page = _positive_int(item.get("logical_page"))
        if page is None and include_physical_fallback:
            page = _positive_int(item.get("physical_index"))
        if page is not None:
            values.append(page)
    return values


def _page_text(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        return str(value[0] or "")
    if isinstance(value, dict):
        return str(value.get("text") or value.get("plain_text") or value.get("markdown") or "")
    return str(value or "")


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
