"""Shared default OCR task prompts."""

from __future__ import annotations

from .contracts import OCRTask

PAGE_TEXT_PROMPT = "Recognize all readable text in natural reading order."
PAGE_TEXT_PROMPT_NAME = "page_text_reading_order_v1"
TOC_PAGE_PROMPT = PAGE_TEXT_PROMPT
TOC_PAGE_PROMPT_NAME = "toc_page_text_reading_order_v1"


def default_task_prompt(task: OCRTask) -> tuple[str, str]:
    if task == "toc_page":
        return TOC_PAGE_PROMPT, TOC_PAGE_PROMPT_NAME
    return PAGE_TEXT_PROMPT, PAGE_TEXT_PROMPT_NAME
