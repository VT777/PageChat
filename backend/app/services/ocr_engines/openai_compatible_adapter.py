"""OpenAI-compatible vision OCR adapter."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .contracts import OCRDocumentResult, OCRPageResult, OCRTask


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-vl-ocr-2025-11-20"


class OpenAICompatibleOCRAdapter:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        client: Any = None,
        profile_id: Optional[str] = None,
        profile_version: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("OCR_API_KEY") or ""
        self.base_url = base_url
        self.model = model
        self.profile_id = profile_id
        self.profile_version = profile_version
        self.max_tokens = max_tokens
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        self.client = client

    async def recognize(
        self,
        image_url: str,
        *,
        task: OCRTask,
        options: Optional[Dict[str, Any]] = None,
    ) -> OCRDocumentResult:
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[_message(image_url, _prompt(task, options or {}))],
                max_tokens=int((options or {}).get("max_tokens") or self.max_tokens),
            )
            content = (completion.choices[0].message.content or "").strip()
            page = _normalize_response(content, task=task)
            return OCRDocumentResult(
                task=task,
                engine_type="openai_compatible_ocr",
                model=self.model,
                pages=[page],
                profile_id=self.profile_id,
                profile_version=self.profile_version,
                raw={"base_url": self.base_url},
            )
        except Exception as exc:
            raise RuntimeError(self._redact(str(exc))) from exc

    def _redact(self, message: str) -> str:
        if self.api_key:
            return message.replace(self.api_key, "[redacted-api-key]")
        return message


def _message(image_url: str, prompt: str) -> Dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ],
    }


def _prompt(task: OCRTask, options: Dict[str, Any]) -> str:
    if task == "toc_page":
        return (
            "Extract the table-of-contents entries from this page. Return strict JSON only, "
            "with no Markdown fences or commentary. The JSON shape must be "
            '{"items":[{"title":"...","page":1,"level":1}],"confidence":0.0}. '
            "Use the page numbers printed on the image. If no reliable TOC exists, return "
            '{"items":[],"confidence":0.0}. '
        )
    return (
        "Extract all readable page text as Markdown. Preserve headings, lists, tables, and "
        "line breaks where they carry meaning. Do not add commentary about the image."
    )


def _normalize_response(content: str, *, task: OCRTask) -> OCRPageResult:
    if task == "toc_page":
        try:
            payload = _parse_json_object(content)
            items = payload.get("items") or []
            if isinstance(items, list):
                return OCRPageResult(
                    page_num=1,
                    evidence_level="model_inferred",
                    structured_items=[dict(item) for item in items if isinstance(item, dict)],
                    raw={key: value for key, value in payload.items() if key != "items"},
                )
        except Exception as exc:
            return OCRPageResult(
                page_num=1,
                evidence_level="text_only",
                markdown=content,
                raw={"parse_error": str(exc)},
            )
    return OCRPageResult(page_num=1, evidence_level="text_only", markdown=content)


def _parse_json_object(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("OCR JSON response must be an object")
    return payload

