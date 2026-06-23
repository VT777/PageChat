"""Shared default OCR task prompts."""

from __future__ import annotations

from .contracts import OCRTask

PAGE_TEXT_PROMPT = "完整、准确地抽取内容，用markdown输出"
PAGE_TEXT_PROMPT_NAME = "page_text_reading_order_v1"


def default_task_prompt(task: OCRTask) -> tuple[str, str]:
    if task != "page_text":
        raise ValueError(f"Unsupported OCR task: {task}")
    return PAGE_TEXT_PROMPT, PAGE_TEXT_PROMPT_NAME
