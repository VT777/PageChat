import os
import base64
import io
import inspect
from openai import OpenAI, AsyncOpenAI
from app.core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MODEL_CONFIG,
    MODEL_FLASH_TIMEOUT_SECONDS,
    MODEL_PLUS_TIMEOUT_SECONDS,
)
from app.core.logging_config import silence_noisy_http_loggers
from app.services.litellm_adapter import LiteLLMAdapter
from app.agent.provider_adapter import ProviderCapabilityError, apply_provider_protocol
from app.services.responses_adapter import response_provider_capabilities


silence_noisy_http_loggers()


def _should_disable_thinking(model_name: str) -> bool:
    return "flash" in (model_name or "").lower()


def _default_timeout_for_model(model_name: str) -> float:
    return (
        float(MODEL_FLASH_TIMEOUT_SECONDS)
        if "flash" in (model_name or "").lower()
        else float(MODEL_PLUS_TIMEOUT_SECONDS)
    )


def _apply_thinking_control(
    params: dict,
    model_name: str | None,
    *,
    disable_thinking: bool = False,
) -> None:
    if not disable_thinking and not _should_disable_thinking(model_name or ""):
        return
    extra_body = params.get("extra_body")
    if isinstance(extra_body, dict):
        merged_extra_body = dict(extra_body)
    else:
        merged_extra_body = {}
    merged_extra_body["enable_thinking"] = False
    params["extra_body"] = merged_extra_body


SCENARIO_ROUTE_SLOTS = {
    "chat": "general_chat",
    "qa": "document_qa",
    "query_expansion": "query_expansion",
    "index": "indexing",
    "node_summary": "indexing",
    "relevance": "document_qa",
}


async def _resolve_user_route(user_id: str, route_slot: str) -> dict | None:
    if not user_id:
        return None

    try:
        import aiosqlite

        from app.models.database import DB_PATH
        from app.services.model_settings_service import ModelSettingsService

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            resolved = await ModelSettingsService(db).resolve_route(user_id, route_slot)
            if resolved.get("source") != "user":
                return None
            return {
                "route_version": resolved["route_version"],
                "provider_config": resolved,
                "model": resolved["model"],
            }
    except Exception:
        return None


async def resolve_scenario_route(
    scenario: str,
    user_id: str | None = None,
) -> dict:
    config = MODEL_CONFIG.get(scenario, MODEL_CONFIG["qa"])
    route_slot = SCENARIO_ROUTE_SLOTS.get(scenario)
    if user_id and route_slot:
        route = await _resolve_user_route(user_id, route_slot)
        if route:
            return {
                "model": route["model"],
                "temperature": config.get("temperature", 0),
                "max_tokens": config.get("max_tokens"),
                "provider_config": route["provider_config"],
            }

    model = config["model"]
    return {
        "model": model,
        "temperature": config.get("temperature", 0),
        "max_tokens": config.get("max_tokens"),
        "provider_config": {
            "provider": "environment",
            "base_url": LLM_BASE_URL,
            "api_key": LLM_API_KEY,
            "model": model,
            **response_provider_capabilities("environment", LLM_BASE_URL),
        },
    }


def get_llm_client() -> OpenAI:
    """获取同步 LLM 客户端"""
    return OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
    )


def get_async_llm_client() -> AsyncOpenAI:
    """获取异步 LLM 客户端"""
    return AsyncOpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
    )


async def _close_async_client(client) -> None:
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def pdf_page_to_base64(pdf_path: str, page_num: int) -> str | None:
    """将PDF页面转换为base64图片（JPEG压缩）"""
    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        if page_num < 1 or page_num > len(doc):
            doc.close()
            return None

        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=150)  # 150 DPI足够清晰，且更快
        img_bytes = pix.tobytes(output="jpeg", jpg_quality=75)  # JPEG压缩，更小
        doc.close()
        return base64.b64encode(img_bytes).decode("utf-8")
    except Exception as e:
        print(f"PDF page to base64 error: {e}")
        return None


def build_vision_message(text: str, images_base64: list[str] = None) -> list:
    """
    构建支持多模态的消息格式

    Args:
        text: 文本内容
        images_base64: base64 编码的图片列表
    """
    if not images_base64:
        return [{"role": "user", "content": text}]

    content = []
    for img_b64 in images_base64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
            }
        )
    content.append({"type": "text", "text": text})

    return [{"role": "user", "content": content}]


def _messages_need_vision(messages: list) -> bool:
    for message in messages or []:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "image_url":
                return True
    return False


def chat_completion(
    messages: list,
    model: str = None,
    temperature: float = 0,
    stream: bool = False,
    timeout: float | None = None,
    provider_config: dict | None = None,
    disable_thinking: bool = False,
    **kwargs,
):
    """同步调用 LLM"""
    if provider_config:
        resolved_config = dict(provider_config)
        if model:
            resolved_config["model"] = model
        extra = dict(kwargs)
        allow_deterministic_tools = bool(extra.pop("allow_deterministic_tools", False))
        resolved_config = apply_provider_protocol(
            resolved_config,
            requires_streaming=stream,
            requires_tool_calling=bool(extra.get("tools")),
            requires_vision=_messages_need_vision(messages),
            requires_structured_output=bool(extra.get("response_format")),
        )
        if resolved_config.get("tool_strategy") == "pagechat_deterministic_tools":
            if extra.get("tools") and not allow_deterministic_tools:
                raise ProviderCapabilityError(
                    "Model "
                    f"'{resolved_config.get('model') or model or LLM_MODEL}' requires "
                    "PageChat deterministic tool execution before LLM generation; "
                    "provider tool calling is disabled."
                )
            extra.pop("tools", None)
            extra.pop("tool_choice", None)
        _apply_thinking_control(
            extra,
            resolved_config.get("model") or model or LLM_MODEL,
            disable_thinking=disable_thinking,
        )
        return LiteLLMAdapter().completion(
            provider_config=resolved_config,
            messages=messages,
            temperature=temperature,
            stream=stream,
            timeout=timeout,
            **extra,
        )
    client = get_llm_client()
    resolved_model = model or LLM_MODEL
    params = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    _apply_thinking_control(params, resolved_model, disable_thinking=disable_thinking)
    params["timeout"] = timeout if timeout is not None else _default_timeout_for_model(resolved_model)
    params.update(kwargs)
    return client.chat.completions.create(**params)


async def async_chat_completion(
    messages: list,
    model: str = None,
    temperature: float = 0,
    stream: bool = False,
    timeout: float | None = None,
    provider_config: dict | None = None,
    disable_thinking: bool = False,
    **kwargs,
):
    """异步调用 LLM"""
    if provider_config:
        resolved_config = dict(provider_config)
        if model:
            resolved_config["model"] = model
        extra = dict(kwargs)
        allow_deterministic_tools = bool(extra.pop("allow_deterministic_tools", False))
        resolved_config = apply_provider_protocol(
            resolved_config,
            requires_streaming=stream,
            requires_tool_calling=bool(extra.get("tools")),
            requires_vision=_messages_need_vision(messages),
            requires_structured_output=bool(extra.get("response_format")),
        )
        if resolved_config.get("tool_strategy") == "pagechat_deterministic_tools":
            if extra.get("tools") and not allow_deterministic_tools:
                raise ProviderCapabilityError(
                    "Model "
                    f"'{resolved_config.get('model') or model or LLM_MODEL}' requires "
                    "PageChat deterministic tool execution before LLM generation; "
                    "provider tool calling is disabled."
                )
            extra.pop("tools", None)
            extra.pop("tool_choice", None)
        _apply_thinking_control(
            extra,
            resolved_config.get("model") or model or LLM_MODEL,
            disable_thinking=disable_thinking,
        )
        return await LiteLLMAdapter().acompletion(
            provider_config=resolved_config,
            messages=messages,
            temperature=temperature,
            stream=stream,
            timeout=timeout,
            **extra,
        )
    client = get_async_llm_client()
    resolved_model = model or LLM_MODEL
    params = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    _apply_thinking_control(params, resolved_model, disable_thinking=disable_thinking)
    params["timeout"] = timeout if timeout is not None else _default_timeout_for_model(resolved_model)
    params.update(kwargs)
    try:
        response = await client.chat.completions.create(**params)
    except Exception:
        await _close_async_client(client)
        raise
    if not stream:
        await _close_async_client(client)
    return response


async def chat_by_scenario(
    scenario: str,
    messages: list,
    stream: bool = False,
    tools: list = None,
    timeout: float | None = None,
    user_id: str | None = None,
    allow_deterministic_tools: bool = False,
    disable_thinking: bool = False,
    **kwargs,
):
    """
    按场景调用对应模型

    Args:
        scenario: 场景类型 (intent/chat/qa/index)
        messages: 消息列表
        stream: 是否流式
        tools: 工具定义 (Function Calling)
    """
    config = MODEL_CONFIG.get(scenario, MODEL_CONFIG["qa"])
    route_slot = SCENARIO_ROUTE_SLOTS.get(scenario)
    if user_id and route_slot:
        route = await _resolve_user_route(user_id, route_slot)
        if route:
            extra = dict(kwargs)
            if tools:
                extra["tools"] = tools
                extra["tool_choice"] = "auto"
            if config.get("max_tokens"):
                extra["max_tokens"] = config["max_tokens"]
            return await async_chat_completion(
                messages=messages,
                model=route["model"],
                temperature=config.get("temperature", 0),
                stream=stream,
                timeout=timeout,
                provider_config=route["provider_config"],
                allow_deterministic_tools=allow_deterministic_tools,
                disable_thinking=disable_thinking,
                **extra,
            )
    client = get_async_llm_client()

    resolved_model = config["model"]
    params = {
        "model": resolved_model,
        "messages": messages,
        "temperature": config.get("temperature", 0),
        "stream": stream,
    }
    _apply_thinking_control(params, resolved_model, disable_thinking=disable_thinking)

    params["timeout"] = timeout if timeout is not None else _default_timeout_for_model(resolved_model)

    # 添加 max_tokens (如果配置了)
    if config.get("max_tokens"):
        params["max_tokens"] = config["max_tokens"]

    # 添加 tools (如果提供了)
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"

    # 合并其他参数
    params.update(kwargs)

    try:
        response = await client.chat.completions.create(**params)
    except Exception:
        await _close_async_client(client)
        raise
    if not stream:
        await _close_async_client(client)
    return response
