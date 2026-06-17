"""OpenAI-compatible vision OCR adapter."""

from __future__ import annotations

import hashlib
import inspect
import os
import time
from typing import Any, Dict, Optional

from .contracts import OCRDocumentResult, OCRPageResult, OCRTask
from .task_prompts import default_task_prompt


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-vl-ocr-2025-11-20"
PROMPT_VERSION = "2026-06-15"


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

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None) or getattr(self.client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def recognize(
        self,
        image_url: str,
        *,
        task: OCRTask,
        options: Optional[Dict[str, Any]] = None,
    ) -> OCRDocumentResult:
        options = options or {}
        prompt, prompt_name = _prompt(task, options)
        started = time.perf_counter()
        base_diagnostics = self._diagnostics(
            task=task,
            prompt=prompt,
            prompt_name=prompt_name,
            input_type=_input_type(image_url),
        )
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[_message(image_url, prompt)],
                max_tokens=int(options.get("max_tokens") or self.max_tokens),
            )
            content = (completion.choices[0].message.content or "").strip()
            page = _normalize_response(content, task=task)
            diagnostics = {
                **base_diagnostics,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "result_pages": 1,
                "evidence_level": page.evidence_level,
                "content_chars": len(content),
            }
            return OCRDocumentResult(
                task=task,
                engine_type="openai_compatible_ocr",
                model=self.model,
                pages=[page],
                profile_id=self.profile_id,
                profile_version=self.profile_version,
                diagnostics=diagnostics,
                raw={"base_url": self.base_url, "diagnostics": diagnostics, "content": content},
            )
        except Exception as exc:
            raise RuntimeError(self._redact(str(exc))) from exc

    def _redact(self, message: str) -> str:
        if self.api_key:
            return message.replace(self.api_key, "[redacted-api-key]")
        return message

    def _diagnostics(
        self,
        *,
        task: OCRTask,
        prompt: str,
        prompt_name: str,
        input_type: str,
    ) -> Dict[str, Any]:
        return {
            "task": task,
            "engine_type": "openai_compatible_ocr",
            "model": self.model,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "prompt_name": prompt_name,
            "prompt_version": PROMPT_VERSION,
            "prompt_text": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_chars": len(prompt),
            "input_type": input_type,
        }


def _message(image_url: str, prompt: str) -> Dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ],
    }


def _prompt(task: OCRTask, options: Dict[str, Any]) -> tuple[str, str]:
    configured = str(options.get("prompt") or "").strip()
    if configured:
        return configured, str(options.get("prompt_name") or "custom_prompt")
    return default_task_prompt(task)

def _input_type(image_url: str) -> str:
    if str(image_url).startswith("data:"):
        return "data_url"
    if str(image_url).startswith(("http://", "https://")):
        return "remote_url"
    return "local_or_raw"


def _normalize_response(content: str, *, task: OCRTask) -> OCRPageResult:
    return OCRPageResult(page_num=1, evidence_level="text_only", markdown=content)
