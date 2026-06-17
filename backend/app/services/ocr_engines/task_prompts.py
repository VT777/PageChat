"""Shared default OCR task prompts."""

from __future__ import annotations

from .contracts import OCRTask

TOC_PAGE_PROMPT = "Fully extract TOC data following the natural reading sequence."
TOC_PAGE_PROMPT_NAME = "toc_page_markdown_v1"
PAGE_TEXT_PROMPT = (
    "Extract all readable text from this page completely in natural reading order. "
    "Preserve meaningful line breaks. Output text only. "
    "Do not output coordinates, bounding boxes, JSON, Markdown, metadata, commentary, or explanations."
)
PAGE_TEXT_PROMPT_NAME = "page_text_reading_order_v1"


def default_task_prompt(task: OCRTask) -> tuple[str, str]:
    if task == "toc_page":
        return TOC_PAGE_PROMPT, TOC_PAGE_PROMPT_NAME
    return PAGE_TEXT_PROMPT, PAGE_TEXT_PROMPT_NAME
