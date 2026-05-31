from __future__ import annotations

import re
from typing import Any

from app.core import config


_SENTENCE_ENDINGS = {"。", "！", "？", "；", ".", "!", "?", ";"}
_COMMA_SPLITTERS = {",", "，"}


def segment_answer_sentences(text: str, max_sentence_chars: int = 220) -> list[str]:
    if not text:
        return []

    chunks: list[str] = []
    buffer: list[str] = []

    for char in text:
        buffer.append(char)
        if char in _SENTENCE_ENDINGS:
            sentence = "".join(buffer).strip()
            if sentence:
                chunks.extend(_split_long_sentence(sentence, max_sentence_chars))
            buffer = []

    tail = "".join(buffer).strip()
    if tail:
        chunks.extend(_split_long_sentence(tail, max_sentence_chars))

    return [item for item in chunks if item]


def bind_sentence_citations(
    sentence_id: str,
    sentence: str,
    evidence: list[dict[str, Any]],
    min_confidence: float = config.CITATION_MIN_CONFIDENCE,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    bindings: list[dict[str, Any]] = []
    warns: list[dict[str, str]] = []

    ranked = sorted(
        evidence or [],
        key=lambda item: (
            _sentence_relevance_score(sentence, item),
            _extract_confidence(item),
        ),
        reverse=True,
    )
    for item in ranked:
        confidence = _extract_confidence(item)
        if confidence < min_confidence:
            warns.append(
                {
                    "code": "LOW_CITATION_CONFIDENCE",
                    "message": "citation confidence is below threshold",
                    "impact": "none",
                }
            )
            continue

        bindings.append(
            {
                "sentence_id": sentence_id,
                "source_id": str(item.get("source_id", "")),
                "source_type": item.get("source_type", "pdf"),
                "anchor": item.get("anchor"),
                "snippet": item.get("snippet", ""),
                "citation_confidence": confidence,
            }
        )
        if len(bindings) >= 2:
            break

    return bindings, warns


def _sentence_relevance_score(sentence: str, item: dict[str, Any]) -> float:
    confidence = _extract_confidence(item)
    sentence_tokens = _tokenize(sentence)
    evidence_tokens = _tokenize(_evidence_text(item))
    lexical_overlap = _token_overlap(sentence_tokens, evidence_tokens)
    return lexical_overlap * 0.75 + confidence * 0.25


def _split_long_sentence(sentence: str, max_sentence_chars: int) -> list[str]:
    if len(sentence) <= max_sentence_chars:
        return [sentence]

    comma_parts: list[str] = []
    current = ""
    for char in sentence:
        current += char
        if char in _COMMA_SPLITTERS:
            piece = current.strip()
            if piece:
                comma_parts.append(piece)
            current = ""
    if current.strip():
        comma_parts.append(current.strip())

    if len(comma_parts) > 1:
        normalized: list[str] = []
        for piece in comma_parts:
            if len(piece) <= max_sentence_chars:
                normalized.append(piece)
            else:
                normalized.extend(_hard_wrap(piece, max_sentence_chars))
        return normalized

    return _hard_wrap(sentence, max_sentence_chars)


def _hard_wrap(text: str, max_sentence_chars: int) -> list[str]:
    return [
        text[idx : idx + max_sentence_chars]
        for idx in range(0, len(text), max_sentence_chars)
    ]


def _extract_confidence(item: dict[str, Any]) -> float:
    raw = item.get("citation_confidence")
    if raw is None:
        raw = item.get("confidence")
    if raw is None:
        raw = item.get("relevance")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _evidence_text(item: dict[str, Any]) -> str:
    keys = ["snippet", "summary", "reasoning", "node_title", "content"]
    parts = [str(item.get(key, "")) for key in keys if item.get(key)]
    if parts:
        return " ".join(parts)
    return str(item)


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", lowered)
    return {token for token in tokens if token}


def _token_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return overlap / max(1, len(left))
