from __future__ import annotations

import re


EMPTY_FOLDER_IDS = {"", "root", "null", "undefined"}


def normalize_folder_id(folder_id: object) -> str | None:
    if folder_id is None:
        return None
    normalized = str(folder_id).strip()
    if not normalized or normalized.lower() in EMPTY_FOLDER_IDS:
        return None
    return normalized


ENGLISH_DOCUMENT_CONTEXT_PATTERNS = (
    r"\b(uploaded|attached|current|selected|available|all)\s+(document|documents|file|files|pdf|pdfs|attachment|attachments)\b",
    r"\b(my|our|the|this|these)\s+(document|documents|file|files|pdf|pdfs|attachment|attachments)\b",
    r"\b(document|documents|file|files|pdf|pdfs|attachment|attachments)\s+(i|we)\s+(uploaded|attached|selected)\b",
    r"\b(document|documents|file|files|pdf|pdfs|attachment|attachments)\s+(content|contents|summary|summaries|analysis|evidence)\b",
    r"\b(in|from|within|inside)\s+(the|this|these|my|our|uploaded|attached|current|selected)\s+(document|documents|file|files|pdf|pdfs|library|folder)\b",
    r"\b(document|file|pdf)\s+library\b",
    r"\bcurrent\s+(scope|folder|library)\b",
)

CHINESE_DOCUMENT_CONTEXT_HINTS = (
    "\u4e0a\u4f20\u7684\u6587\u6863",
    "\u4e0a\u4f20\u7684\u6587\u4ef6",
    "\u6211\u7684\u6587\u6863",
    "\u6211\u7684\u6587\u4ef6",
    "\u5f53\u524d\u6587\u6863",
    "\u5f53\u524d\u6587\u4ef6",
    "\u9009\u4e2d\u6587\u6863",
    "\u9009\u4e2d\u7684\u6587\u6863",
    "\u6587\u6863\u5e93",
    "\u6587\u4ef6\u5939",
    "\u5f53\u524d\u8303\u56f4",
    "\u8fd9\u7bc7",
    "\u8fd9\u4efd",
    "\u8fd9\u4e2a\u6587\u4ef6",
    "\u8fd9\u4e9b\u6587\u6863",
    "\u8fd9\u4e9b\u6587\u4ef6",
    "\u9644\u4ef6",
    "\u8d44\u6599",
)

CHINESE_DOCUMENT_ACTION_PATTERN = re.compile(
    r"(\u6587\u6863|\u6587\u4ef6).*(\u5185\u5bb9|\u603b\u7ed3|\u6982\u62ec|\u63d0\u70bc|\u5206\u6790|\u5bf9\u6bd4|\u67e5\u627e|\u641c\u7d22|\u68c0\u7d22)"
    r"|(\u5185\u5bb9|\u603b\u7ed3|\u6982\u62ec|\u63d0\u70bc|\u5206\u6790|\u5bf9\u6bd4|\u67e5\u627e|\u641c\u7d22|\u68c0\u7d22).*(\u6587\u6863|\u6587\u4ef6)"
)


def question_needs_document_retrieval(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False
    if any(re.search(pattern, q) for pattern in ENGLISH_DOCUMENT_CONTEXT_PATTERNS):
        return True
    if any(hint in q for hint in CHINESE_DOCUMENT_CONTEXT_HINTS):
        return True
    if CHINESE_DOCUMENT_ACTION_PATTERN.search(q):
        return True

    english_query_patterns = (
        r"\bwhat (does|do|is|are).*\b(document|file|pdf|attachment|upload|library)\b.*\b(say|contain|mention)\b",
        r"\baccording to\b.*\b(document|file|pdf|attachment|upload|library)\b",
        r"\bbased on\b.*\b(document|file|pdf|attachment|upload|library)\b",
    )
    return any(re.search(pattern, q) for pattern in english_query_patterns)
