"""VLM 工具模块：页面渲染 + Qwen3.5-flash 视觉 API 调用封装。"""

import base64
import asyncio
import weakref
import json
import os
import re
from typing import Any, Dict, List, Optional

import pymupdf
from openai import AsyncOpenAI

from app.core.config import LLM_API_KEY, LLM_BASE_URL, LLM_FLASH_MODEL
from app.core.logging_config import silence_noisy_http_loggers


silence_noisy_http_loggers()


# ---------------------------------------------------------------------------
# 页面渲染
# ---------------------------------------------------------------------------


def render_pages_to_images(
    file_path: str,
    page_indices: List[int],
    dpi: int = 150,
) -> List[Dict[str, Any]]:
    """把 PDF 指定页面渲染为 PNG 图片。

    Args:
        file_path: PDF 文件路径
        page_indices: 0-indexed 页码列表
        dpi: 渲染分辨率（150 DPI ≈ 1240x1750px/A4页）

    Returns:
        [{"page_index": 0, "image_base64": "...", "width": 1240, "height": 1750}, ...]
    """
    doc = pymupdf.open(file_path)
    results = []
    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)

    for idx in page_indices:
        if idx < 0 or idx >= len(doc):
            continue
        page = doc[idx]
        pix = page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")
        b64 = base64.b64encode(png_bytes).decode("ascii")
        results.append(
            {
                "page_index": idx,
                "image_base64": b64,
                "width": pix.width,
                "height": pix.height,
            }
        )

    doc.close()
    return results


def render_thumbnail_grids(
    file_path: str,
    pages_per_grid: int = 12,
    cols: int = 4,
    thumb_width: int = 250,
    thumb_height: int = 350,
    padding: int = 12,
    label_height: int = 22,
) -> List[Dict[str, Any]]:
    """把 PDF 所有页面渲染成缩略图网格（4x3 排列）。

    Args:
        file_path: PDF 文件路径
        pages_per_grid: 每张网格包含的最大页数（默认 12 = 4x3）
        cols: 每行列数

    Returns:
        [{"start_page": 0, "end_page": 11, "image_base64": "..."}, ...]
    """
    import io
    import math
    from PIL import Image, ImageDraw, ImageFont

    doc = pymupdf.open(file_path)
    page_count = len(doc)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    grids = []

    for start in range(0, page_count, pages_per_grid):
        end = min(start + pages_per_grid, page_count)
        n_pages = end - start
        rows = math.ceil(n_pages / cols)

        canvas_width = cols * (thumb_width + padding) + padding
        canvas_height = rows * (thumb_height + label_height + padding) + padding

        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(canvas)

        for i in range(n_pages):
            page_num = start + i
            row = i // cols
            col = i % cols

            x = padding + col * (thumb_width + padding)
            y = padding + row * (thumb_height + label_height + padding)

            page = doc[page_num]
            page_rect = page.rect
            scale = min(thumb_width / page_rect.width, thumb_height / page_rect.height)
            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)

            thumb_img = Image.open(io.BytesIO(pix.tobytes("png")))
            offset_x = (thumb_width - thumb_img.width) // 2
            offset_y = (thumb_height - thumb_img.height) // 2
            canvas.paste(thumb_img, (x + offset_x, y + label_height + offset_y))

            draw.rectangle(
                [x, y + label_height, x + thumb_width, y + label_height + thumb_height],
                outline="#999999",
                width=1,
            )
            draw.text((x + 4, y + 2), f"p.{page_num + 1}", fill="black", font=font)

        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        grids.append(
            {
                "start_page": start,
                "end_page": end - 1,
                "image_base64": b64,
            }
        )

    doc.close()
    return grids


# ---------------------------------------------------------------------------
# VLM API 调用
# ---------------------------------------------------------------------------

_vlm_clients_by_loop: "weakref.WeakKeyDictionary[Any, AsyncOpenAI]" = weakref.WeakKeyDictionary()
_sync_vlm_client: Optional[AsyncOpenAI] = None


def _get_vlm_client() -> AsyncOpenAI:
    global _sync_vlm_client
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if _sync_vlm_client is None:
            _sync_vlm_client = AsyncOpenAI(
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL,
            )
        return _sync_vlm_client

    client = _vlm_clients_by_loop.get(loop)
    if client is None:
        client = AsyncOpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
        )
        _vlm_clients_by_loop[loop] = client
    return client


async def vlm_call_with_images(
    images: List[Dict[str, Any]],
    prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 8000,
    timeout: Optional[float] = None,
) -> str:
    """调用 Qwen3.5-flash 视觉 API。

    Args:
        images: render_pages_to_images 返回的图片列表
        prompt: 文本提示词
        model: 模型名称（默认 qwen3.6-flash）
        max_tokens: 最大输出 token
        timeout: HTTP请求超时（秒），默认60秒

    Returns:
        模型文本输出
    """
    model = model or LLM_FLASH_MODEL or "qwen3.6-flash"
    client = _get_vlm_client()

    # 构建 content: 先放图片，再放文本 prompt
    content: List[Dict] = []
    for img in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img['image_base64']}",
                },
            }
        )
    content.append({"type": "text", "text": prompt})

    # 构建 extra_body（flash 模型禁用 thinking 以节省 token）
    extra_body = {}
    if "flash" in model.lower():
        extra_body["enable_thinking"] = False

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
        temperature=0,
        extra_body=extra_body if extra_body else None,
        timeout=timeout if timeout is not None else 60.0,  # 默认60秒超时
    )

    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# JSON 解析辅助
# ---------------------------------------------------------------------------


def parse_vlm_json(text: str) -> Any:
    """从 VLM 输出中解析 JSON（支持 markdown fence、前后噪音）。"""
    s = text.strip()

    # 去 markdown code fence
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = s.strip()

    # 尝试直接解析
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 找 { 或 [ 开头的 JSON
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = s.find(start_char)
        if start == -1:
            continue
        depth = 0
        end = -1
        for i in range(start, len(s)):
            if s[i] == start_char:
                depth += 1
            elif s[i] == end_char:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            candidate = s[start : end + 1]
            # 修复常见问题
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # 尾部逗号
            candidate = re.sub(r"}\s*{", "},{", candidate)  # 缺少逗号
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Cannot parse JSON from VLM output: {text[:200]}")
