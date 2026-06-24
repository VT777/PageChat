"""Build PageTextMap before TOC routing."""

from __future__ import annotations

import inspect
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.services.ocr_engines.task_prompts import PAGE_TEXT_PROMPT
from pageindex.page_text_map import PageTextEntry, PageTextMap


PAGE_TEXT_OCR_PROMPT = PAGE_TEXT_PROMPT


def infer_content_type(analysis: Mapping[str, Any]) -> str:
    page_count = max(1, int(analysis.get("page_count") or 0))
    text_coverage = float(analysis.get("text_coverage") or 0.0)
    image_coverage = float(analysis.get("image_coverage") or 0.0)
    image_only_pages = list(analysis.get("image_only_pages") or [])
    garbled_pages = list(analysis.get("garbled_pages") or [])
    image_only_ratio = len(image_only_pages) / page_count
    garbled_ratio = len(garbled_pages) / page_count
    text_quality = str(analysis.get("text_layer_quality") or "").lower()
    sparse_edge_images = (
        text_quality == "reliable"
        and text_coverage >= 0.95
        and not garbled_pages
        and len(image_only_pages) / page_count <= 0.05
        and all(page in {0, page_count - 1} for page in image_only_pages)
    )

    if (
        analysis.get("is_image_only_pdf")
        or analysis.get("is_garbled_pdf")
        or image_only_ratio >= 0.9
        or garbled_ratio >= 0.5
        or (text_coverage <= 0.05 and image_coverage >= 0.5)
        or text_quality == "garbled"
    ):
        return "ocr"
    if sparse_edge_images:
        return "text"
    if image_only_pages or garbled_pages or text_quality in {"partial", "noisy"}:
        return "hybrid"
    return "text"


async def preprocess_page_text_map(
    file_path: str | Path,
    analysis: Dict[str, Any],
    *,
    ocr_pages_fn=None,
    content_type: Optional[str] = None,
    prompt: str = PAGE_TEXT_OCR_PROMPT,
) -> PageTextMap:
    """Convert PDF analysis output into canonical per-page text.

    ``ocr_pages_fn`` is injected by the service layer. It receives 0-indexed page
    indices and must return OCR text keyed by 1-indexed physical page numbers.
    """

    page_count = int(analysis.get("page_count") or 0)
    page_list = list(analysis.get("page_list") or [])
    if page_count <= 0:
        page_count = len(page_list)
    content_type = content_type or infer_content_type(analysis)
    if content_type not in {"text", "ocr", "hybrid"}:
        raise ValueError(f"Unsupported content_type: {content_type}")

    if content_type == "text":
        page_map = _build_from_pdf_text(page_list, page_count=page_count)
        _attach_to_analysis(analysis, page_map, content_type=content_type)
        return page_map

    pages_to_ocr = _pages_to_ocr(analysis, content_type=content_type, page_count=page_count)
    if pages_to_ocr and ocr_pages_fn is None:
        raise ValueError("ocr_pages_fn is required for OCR-backed PageTextMap preprocessing")

    ocr_by_page = await _call_ocr_pages(
        ocr_pages_fn,
        file_path,
        pages_to_ocr,
        prompt=prompt,
        analysis=analysis,
    )
    entries = _merge_entries(
        page_list=page_list,
        page_count=page_count,
        content_type=content_type,
        pages_to_ocr=pages_to_ocr,
        ocr_by_page=ocr_by_page,
    )
    page_map = PageTextMap(entries)
    _attach_to_analysis(analysis, page_map, content_type=content_type)
    return page_map


def _build_from_pdf_text(page_list: List[Any], *, page_count: int) -> PageTextMap:
    entries = []
    for index in range(1, page_count + 1):
        original = _page_list_text(page_list, index)
        entries.append(
            PageTextEntry(
                physical_page=index,
                text=original,
                source="pdf_text",
                quality="reliable" if original.strip() else "low",
                ocr_used=False,
            )
        )
    return PageTextMap(entries)


def _pages_to_ocr(analysis: Mapping[str, Any], *, content_type: str, page_count: int) -> List[int]:
    if content_type == "ocr":
        return list(range(page_count))
    bad_pages = set()
    if content_type == "hybrid":
        for index in range(page_count):
            page_info = _page_info(analysis, index)
            if int(page_info.get("image_count") or 0) > 0:
                bad_pages.add(index)
    for key in ("image_only_pages", "garbled_pages"):
        for page in analysis.get(key) or []:
            try:
                page_idx = int(page)
            except Exception:
                continue
            if 0 <= page_idx < page_count:
                bad_pages.add(page_idx)
    page_list = list(analysis.get("page_list") or [])
    for index in range(page_count):
        if not _page_list_text(page_list, index + 1).strip():
            page_info = _page_info(analysis, index)
            if page_info.get("image_count", 0) or page_info.get("type") in {"image_only", "garbled", "empty"}:
                bad_pages.add(index)
    return sorted(bad_pages)


async def _call_ocr_pages(
    ocr_pages_fn,
    file_path: str | Path,
    page_indices: Iterable[int],
    *,
    prompt: str,
    analysis: Dict[str, Any],
) -> Dict[int, str]:
    page_indices = list(page_indices)
    if not page_indices:
        return {}
    result = ocr_pages_fn(file_path, page_indices, prompt=prompt, analysis=analysis)
    if inspect.isawaitable(result):
        result = await result
    return _normalize_ocr_result(result)


def _normalize_ocr_result(result: Any) -> Dict[int, str]:
    if isinstance(result, dict):
        if "ocr_pages" in result:
            return _normalize_ocr_result(result.get("ocr_pages") or [])
        normalized = {}
        for key, value in result.items():
            try:
                page_num = int(key)
            except Exception:
                continue
            if isinstance(value, dict):
                text = str(value.get("text") or value.get("plain_text") or "")
            else:
                text = str(value or "")
            normalized[page_num] = text
        return normalized

    normalized = {}
    for item in result or []:
        if not isinstance(item, dict):
            continue
        page_num = int(item.get("page_num") or 0)
        if page_num <= 0:
            continue
        normalized[page_num] = str(item.get("text") or item.get("plain_text") or "")
    return normalized


def _merge_entries(
    *,
    page_list: List[Any],
    page_count: int,
    content_type: str,
    pages_to_ocr: List[int],
    ocr_by_page: Mapping[int, str],
) -> List[PageTextEntry]:
    ocr_indices = set(pages_to_ocr)
    entries: List[PageTextEntry] = []
    for index in range(1, page_count + 1):
        original = _page_list_text(page_list, index)
        ocr_text = str(ocr_by_page.get(index) or "")
        if index - 1 in ocr_indices:
            if ocr_text.strip():
                text, heading_supplemented = _supplement_ocr_text_with_text_layer_heading(
                    original,
                    ocr_text,
                )
                source = "ocr"
                quality = "reliable"
                ocr_used = True
                diagnostics = {
                    "ocr_requested": True,
                    "original_text_chars": len(original),
                    "ocr_text_chars": len(ocr_text),
                }
                if heading_supplemented:
                    diagnostics["text_layer_heading_supplemented"] = True
            elif content_type == "hybrid" and original.strip():
                text = original
                source = "pdf_text_fallback"
                quality = "partial"
                ocr_used = False
                diagnostics = {
                    "ocr_requested": True,
                    "ocr_fallback": "pdf_text",
                    "original_text_chars": len(original),
                    "ocr_text_chars": 0,
                }
            else:
                text = ""
                source = "ocr"
                quality = "low"
                ocr_used = True
                diagnostics = {
                    "ocr_requested": True,
                    "original_text_chars": len(original),
                    "ocr_text_chars": 0,
                }
            entries.append(
                PageTextEntry(
                    physical_page=index,
                    text=text,
                    source=source,
                    quality=quality,
                    ocr_used=ocr_used,
                    diagnostics=diagnostics,
                )
            )
            continue

        entries.append(
            PageTextEntry(
                physical_page=index,
                text=original,
                source="pdf_text",
                quality="reliable" if original.strip() else "low",
                ocr_used=False,
            )
        )
    return entries


def _attach_to_analysis(analysis: Dict[str, Any], page_map: PageTextMap, *, content_type: str) -> None:
    diagnostics = page_map.to_diagnostics()
    analysis["content_type"] = content_type
    analysis["page_text_map"] = page_map
    analysis["page_text_map_diagnostics"] = diagnostics
    analysis["page_text_map_ocr_pages"] = diagnostics["ocr_pages"]
    analysis["page_text_map_ocr_completed"] = bool(diagnostics["ocr_pages"])
    analysis["page_list"] = page_map.to_page_list()
    analysis["page_texts"] = page_map.page_texts()


def _page_list_text(page_list: List[Any], physical_page: int) -> str:
    index = physical_page - 1
    if index < 0 or index >= len(page_list):
        return ""
    page = page_list[index]
    if isinstance(page, (list, tuple)) and page:
        return str(page[0] or "")
    return str(page or "")


def _supplement_ocr_text_with_text_layer_heading(original: str, ocr_text: str) -> tuple[str, bool]:
    heading = _recover_text_layer_leading_heading(original)
    if not heading:
        return ocr_text, False
    if _compact_text_key(heading) in _compact_text_key(ocr_text):
        return ocr_text, False
    return f"{heading}\n{ocr_text}", True


def _recover_text_layer_leading_heading(text: str) -> Optional[str]:
    return (
        _recover_text_layer_leading_numbered_heading(text)
        or _recover_text_layer_leading_appendix_heading(text)
    )


def _recover_text_layer_leading_numbered_heading(text: str) -> Optional[str]:
    lines = [_normalize_text_layer_line(line) for line in str(text or "").splitlines()[:40]]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines[:16]):
        if not re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{1,2})*", line):
            continue
        if "." not in line and int(line) > 12:
            continue
        title_words = _collect_heading_words_after_number(lines, index + 1)
        if not title_words:
            continue
        title = " ".join(title_words[:12]).strip()
        if _looks_like_recovered_heading_title(title, number=line):
            return f"{line} {title}"
    return None


def _recover_text_layer_leading_appendix_heading(text: str) -> Optional[str]:
    lines = [_normalize_text_layer_line(line) for line in str(text or "").splitlines()[:40]]
    lines = [line for line in lines if line]
    tokens = _merge_fragmented_text_layer_tokens(lines[:24])
    if not tokens:
        return None
    for index, token in enumerate(tokens[:8]):
        if token.lower() != "appendix":
            continue
        if index + 2 >= len(tokens):
            continue
        label = tokens[index + 1].strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,4}:?", label):
            continue
        words: List[str] = []
        for word_index, word in enumerate(tokens[index + 2 : index + 10], start=index + 2):
            if words and _looks_like_body_sentence_start(tokens, word_index, len(words) + 2):
                break
            if _token_is_heading_word(word):
                words.append(word)
                continue
            if words:
                break
        if not words:
            continue
        title = " ".join(words[:8]).strip()
        if not _looks_like_recovered_appendix_title(title):
            continue
        label_text = label if label.endswith(":") else f"{label}:"
        return f"Appendix {label_text} {title}"
    return None


def _collect_heading_words_after_number(lines: List[str], start: int) -> List[str]:
    tokens = _merge_fragmented_text_layer_tokens(lines[start : start + 18])
    words: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        consumed = 1
        if index + 1 < len(tokens) and _should_join_heading_fragment(token, tokens[index + 1], words):
            token = f"{token}{tokens[index + 1]}"
            consumed = 2
        remaining = [token] + tokens[index + consumed :]
        if words and str(token or "").strip().startswith("("):
            break
        if (
            words
            and _looks_like_body_sentence_start(remaining, 0, len(words))
            and not _is_version_heading_continuation(words, token)
        ):
            break
        if _token_allowed_in_recovered_heading(remaining, 0, words):
            words.append(token)
            index += consumed
            continue
        if words:
            break
        index += consumed
    return words


_FRAGMENT_START_STOPWORDS = {
    "as",
    "if",
    "in",
    "it",
    "the",
    "these",
    "this",
    "we",
    "when",
    "while",
}

_FRAGMENT_PIECE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "we",
}


def _merge_fragmented_text_layer_tokens(lines: List[str]) -> List[str]:
    tokens: List[str] = []
    index = 0
    while index < len(lines):
        token = lines[index].strip()
        if _can_start_fragmented_word(token):
            pieces = [token]
            next_index = index + 1
            while next_index < len(lines):
                next_token = lines[next_index].strip()
                if not _is_fragment_piece(next_token):
                    break
                pieces.append(next_token)
                next_index += 1
            if len(pieces) > 1:
                merged = "".join(pieces)
                if len(merged) <= 32:
                    tokens.append(merged)
                    index = next_index
                    continue
        tokens.append(token)
        index += 1
    return tokens


def _can_start_fragmented_word(token: str) -> bool:
    return bool(
        re.fullmatch(r"[A-Z][a-z]{0,7}", token or "")
        and token.lower() not in _FRAGMENT_START_STOPWORDS
    )


def _is_fragment_piece(token: str) -> bool:
    normalized = str(token or "").strip()
    if not re.fullmatch(r"[a-z]{1,5}", normalized):
        return False
    if normalized.lower() in _FRAGMENT_PIECE_STOPWORDS:
        return False
    return True


_RECOVERED_HEADING_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "between",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def _token_allowed_in_recovered_heading(tokens: List[str], index: int, words: List[str]) -> bool:
    token = str(tokens[index] or "").strip()
    if not token:
        return False
    if re.fullmatch(r"\d{1,3}:?", token):
        return bool(words and words[-1].casefold() == "version")
    bare = token.strip("()[]{}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*:?", bare):
        return token in {"&", "/", "-"}
    lowered = bare.rstrip(":").casefold()
    if lowered in _RECOVERED_HEADING_STOPWORDS:
        return True
    if bare[:1].isupper() or bare.isupper():
        return True
    previous = words[-1].strip("()[]{}").casefold() if words else ""
    next_token = str(tokens[index + 1] or "").strip("()[]{}") if index + 1 < len(tokens) else ""
    if previous in {"a", "an", "the"} and next_token[:1].isupper():
        return True
    return False


def _should_join_heading_fragment(token: str, next_token: str, words: List[str]) -> bool:
    token = str(token or "").strip()
    next_token = str(next_token or "").strip()
    if not re.fullmatch(r"[a-z]{4,12}", next_token):
        return False
    if re.fullmatch(r"[A-Z]", token):
        return True
    if token == "In" and words and words[-1].casefold() in {"a", "an", "the"}:
        return True
    return False


def _is_version_heading_continuation(words: List[str], token: str) -> bool:
    if str(token or "").strip().casefold() not in {"the", "a", "an"}:
        return False
    for index, word in enumerate(words[:-1]):
        if word.casefold() == "version" and re.fullmatch(r"\d{1,3}:?", words[index + 1]):
            return True
    return False


def _looks_like_single_word_numbered_heading(title: str, number: str) -> bool:
    if "." not in str(number or ""):
        return False
    word = str(title or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z'-]{2,24}:?", word):
        return False
    return word[:1].isupper() and word.casefold().rstrip(":") not in _FRAGMENT_START_STOPWORDS


def _looks_like_recovered_heading_title(title: str, *, number: str = "") -> bool:
    words = [word for word in title.split() if word]
    if len(words) == 1:
        return _looks_like_single_word_numbered_heading(words[0], number)
    if not 2 <= len(words) <= 12:
        return False
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    if len(alpha_words) < 2:
        return False
    titleish = sum(
        1
        for word in alpha_words
        if word.strip("()[]{}")[:1].isupper()
        or word.strip("()[]{}").lower().rstrip(":") in _RECOVERED_HEADING_STOPWORDS
    )
    return titleish / len(alpha_words) >= 0.75


def _looks_like_recovered_appendix_title(title: str) -> bool:
    words = [word for word in title.split() if word]
    if not 1 <= len(words) <= 8:
        return False
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    if not alpha_words:
        return False
    titleish = sum(
        1
        for word in alpha_words
        if word[:1].isupper() or word.lower() in {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to"}
    )
    return titleish / len(alpha_words) >= 0.75


def _normalize_text_layer_line(line: str) -> str:
    mapped = []
    for char in str(line or ""):
        code = ord(char)
        if 1 <= code <= 9:
            mapped.append(str(code))
        elif char.isprintable():
            mapped.append(char)
    return re.sub(r"\s+", " ", "".join(mapped)).strip()


def _compact_text_key(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())


def _page_info(analysis: Mapping[str, Any], index: int) -> Dict[str, Any]:
    pages = analysis.get("pages") or []
    if 0 <= index < len(pages) and isinstance(pages[index], dict):
        return pages[index]
    return {}


def _looks_like_body_sentence_start(tokens: List[str], index: int, collected_count: int) -> bool:
    if collected_count < 2 or index + 1 >= len(tokens):
        return False
    token = tokens[index]
    next_token = tokens[index + 1]
    if token.lower() in {"it", "the", "this", "these", "suppose", "consider", "notice"}:
        return next_token[:1].islower()
    return bool(
        token[:1].isupper()
        and next_token[:1].islower()
        and next_token.lower() not in _RECOVERED_HEADING_STOPWORDS
    )


def _token_is_heading_word(token: str) -> bool:
    if not token or len(token) > 32:
        return False
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]*", token):
        return True
    return token in {"&", "/", "-"}
