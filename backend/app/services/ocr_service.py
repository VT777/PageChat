"""OCR 服务：使用 DashScope qwen-vl-ocr-latest 通过 OpenAI 兼容 API 调用。"""

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.core.config import (
    OCR_API_KEY,
    OCR_BASE_URL,
    OCR_MAX_CONCURRENCY,
    OCR_MAX_RETRIES,
    OCR_MODEL,
    OCR_RATE_LIMIT_RPS,
)
from app.core.logging_config import silence_noisy_http_loggers
from app.services.ocr_engines.task_prompts import PAGE_TEXT_PROMPT


silence_noisy_http_loggers()


@dataclass
class OCRPageResult:
    page_num: int
    text: str
    ok: bool
    error: str = ""


class RateLimiter:
    """基于时间窗口的速率限制器。"""

    def __init__(self, max_concurrent: int, max_rps: int):
        self.concurrent_sem = asyncio.Semaphore(max_concurrent)
        self.max_rps = max_rps
        self.request_times: List[float] = []
        self.lock = asyncio.Lock()

    async def acquire(self):
        """获取执行许可（同时控制并发和速率）。"""
        async with self.lock:
            now = time.time()
            # 清理 1 秒前的记录
            self.request_times = [t for t in self.request_times if now - t < 1.0]
            # 如果超过 RPS 限制，等待
            while len(self.request_times) >= self.max_rps:
                await asyncio.sleep(0.05)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 1.0]
            self.request_times.append(now)

        return self.concurrent_sem


class OCRService:
    def __init__(self, *, log_model_identity: bool = True) -> None:
        self.client = AsyncOpenAI(
            api_key=OCR_API_KEY,
            base_url=OCR_BASE_URL,
        )
        self.model = OCR_MODEL
        self.log_model_identity = bool(log_model_identity)
        self.rate_limiter = RateLimiter(
            max_concurrent=OCR_MAX_CONCURRENCY,
            max_rps=OCR_RATE_LIMIT_RPS,
        )
        self._model_identity_logged = False
        self._model_identity_log_lock = asyncio.Lock()

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None) or getattr(self.client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _log_model_identity_once(self) -> None:
        if not self.log_model_identity:
            return
        if self._model_identity_logged:
            return
        async with self._model_identity_log_lock:
            if self._model_identity_logged:
                return
            print(f"[TOC-OCR] task=page_text engine=legacy_openai_ocr model={self.model}")
            self._model_identity_logged = True

    @staticmethod
    def _extract_text_from_response(payload: Dict[str, Any]) -> str:
        md = str(payload.get("md_results") or "").strip()
        if md:
            return md

        layout_details = payload.get("layout_details") or []
        lines: List[str] = []
        for page in layout_details:
            if not isinstance(page, list):
                continue
            for item in page:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip().lower()
                if label not in {"text", "table", "formula"}:
                    continue
                content = str(item.get("content") or "").strip()
                if content:
                    lines.append(content)
        return "\n".join(lines).strip()

    @staticmethod
    def _page_text_prompt() -> str:
        return PAGE_TEXT_PROMPT

    async def ocr_image_base64(self, image_base64: str, page_num: int) -> OCRPageResult:
        """对单张图片执行 OCR。"""
        if not image_base64:
            return OCRPageResult(
                page_num=page_num,
                text="",
                ok=False,
                error="empty_image_base64",
            )

        last_error = ""
        max_attempts = max(1, int(OCR_MAX_RETRIES) + 1)
        prompt = self._page_text_prompt()

        for attempt in range(1, max_attempts + 1):
            try:
                if attempt == 1:
                    await self._log_model_identity_once()
                async with await self.rate_limiter.acquire():
                    completion = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{image_base64}"
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": prompt,
                                    },
                                ],
                            }
                        ],
                        max_tokens=4096,
                    )

                text = completion.choices[0].message.content or ""
                return OCRPageResult(
                    page_num=page_num,
                    text=text.strip(),
                    ok=True,
                )

            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts:
                    await asyncio.sleep(0.5 * attempt)
                continue

        return OCRPageResult(
            page_num=page_num,
            text="",
            ok=False,
            error=f"ocr_failed_after_{max_attempts}_attempts: {last_error}",
        )

    async def ocr_images_batch(
        self,
        image_items: List[Dict[str, Any]],
    ) -> List[OCRPageResult]:
        """批量 OCR，自动限流和并发控制。"""

        async def _ocr_single(item: Dict[str, Any]) -> OCRPageResult:
            page_num = item.get("page_num", 0)
            image_b64 = item.get("image_b64", "")
            return await self.ocr_image_base64(image_b64, page_num)

        results = await asyncio.gather(*[_ocr_single(item) for item in image_items])
        return list(results)
