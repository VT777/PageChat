"""OCR 服务：使用 DashScope qwen-vl-ocr-latest 通过 OpenAI 兼容 API 调用。"""

import asyncio
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
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=OCR_API_KEY,
            base_url=OCR_BASE_URL,
        )
        self.model = OCR_MODEL
        self.rate_limiter = RateLimiter(
            max_concurrent=OCR_MAX_CONCURRENCY,
            max_rps=OCR_RATE_LIMIT_RPS,
        )

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

        for attempt in range(1, max_attempts + 1):
            try:
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
                                        "text": (
                                            "请提取图像中的所有文本内容，保持原有排版结构。\n"
                                            "要求：\n"
                                            "1. 保留所有文字，不要遗漏\n"
                                            "2. 保持段落和换行格式\n"
                                            "3. 表格内容用表格格式输出\n"
                                            "4. 不要添加任何额外描述或解释\n"
                                            "5. 如果文字模糊无法识别，用[?]标记\n"
                                        ),
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
