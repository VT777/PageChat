"""Model gateway for Qwen3.5 text/vision routing.

Policy table:
| Route | Use when | Timeout | Timeout retry | Downgrade |
| ----- | -------- | ------- | ------------- | --------- |
| flash | light text intent/plan/answer, input_tokens < 4k, no vision | 8s | 1 | n/a |
| plus  | complex reasoning, long text, all vision tasks | 20s | 1 | plus(timeout)->flash only for text tasks |

Constraints:
- Vision tasks never downgrade to a non-vision route.
- Downgrade is allowed only after plus timeout for a text task.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Sequence

from app.core import config
from app.core.llm import async_chat_completion
from app.agent.provider_adapter import ProviderCapabilityError, apply_provider_protocol


CompletionFn = Callable[..., Any]
TIMEOUT_EXCEPTIONS = (asyncio.TimeoutError, TimeoutError)


class ModelGateway:
    def __init__(
        self,
        completion_fn: CompletionFn | None = None,
        model_settings_service: Any | None = None,
        user_id: str | None = None,
    ):
        self._completion_fn = completion_fn or async_chat_completion
        self._model_settings_service = model_settings_service
        self._user_id = user_id

    def timeout_for(self, route: str) -> int:
        if route == "flash":
            return config.MODEL_FLASH_TIMEOUT_SECONDS
        return config.MODEL_PLUS_TIMEOUT_SECONDS

    def route_for(
        self,
        task: str,
        input_tokens: int,
        needs_vision: bool,
        reasoning_complexity: str,
    ) -> str:
        if needs_vision:
            return "plus"
        if task == "vision":
            return "plus"
        if reasoning_complexity == "complex":
            return "plus"
        if input_tokens >= config.MODEL_ROUTE_FLASH_MAX_INPUT_TOKENS:
            return "plus"
        return "flash"

    async def classify_intent(self, question: str) -> Any:
        messages = [{"role": "user", "content": question}]
        return await self._invoke(
            task="intent",
            messages=messages,
            input_tokens=self._estimate_tokens_from_messages(messages),
            needs_vision=False,
            reasoning_complexity="light",
            stream=False,
            tools=None,
            temperature=0,
        )

    async def plan_with_tools(
        self,
        messages: Sequence[dict],
        tools: Sequence[dict] | None,
        *,
        input_tokens: int | None = None,
        needs_vision: bool = False,
        reasoning_complexity: str = "light",
    ) -> Any:
        return await self._invoke(
            task="plan",
            messages=list(messages),
            input_tokens=input_tokens
            if input_tokens is not None
            else self._estimate_tokens_from_messages(messages),
            needs_vision=needs_vision,
            reasoning_complexity=reasoning_complexity,
            stream=False,
            tools=list(tools) if tools else None,
            temperature=0,
        )

    async def stream_answer(
        self,
        messages: Sequence[dict],
        *,
        input_tokens: int | None = None,
        needs_vision: bool = False,
        reasoning_complexity: str = "complex",
        temperature: float = 0.7,
    ) -> Any:
        return await self._invoke(
            task="answer",
            messages=list(messages),
            input_tokens=input_tokens
            if input_tokens is not None
            else self._estimate_tokens_from_messages(messages),
            needs_vision=needs_vision,
            reasoning_complexity=reasoning_complexity,
            stream=True,
            tools=None,
            temperature=temperature,
        )

    async def vision_enrich_pdf_page(self, prompt: str, image_url: str) -> Any:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        return await self._invoke(
            task="vision",
            messages=messages,
            input_tokens=self._estimate_tokens_from_messages(messages),
            needs_vision=True,
            reasoning_complexity="complex",
            stream=False,
            tools=None,
            temperature=0,
        )

    async def _invoke(
        self,
        *,
        task: str,
        messages: list[dict],
        input_tokens: int,
        needs_vision: bool,
        reasoning_complexity: str,
        stream: bool,
        tools: list[dict] | None,
        temperature: float,
    ) -> Any:
        route = self.route_for(task, input_tokens, needs_vision, reasoning_complexity)

        try:
            return await self._call_with_timeout_retry(
                route=route,
                task=task,
                messages=messages,
                stream=stream,
                tools=tools,
                temperature=temperature,
                needs_vision=needs_vision,
            )
        except TIMEOUT_EXCEPTIONS:
            if route != "plus":
                raise
            if needs_vision or task == "vision":
                raise
            return await self._call_with_timeout_retry(
                route="flash",
                task=task,
                messages=messages,
                stream=stream,
                tools=tools,
                temperature=temperature,
                needs_vision=needs_vision,
            )

    async def _call_with_timeout_retry(
        self,
        *,
        route: str,
        task: str = "",
        messages: list[dict],
        stream: bool,
        tools: list[dict] | None,
        temperature: float,
        needs_vision: bool = False,
    ) -> Any:
        retries_left = config.MODEL_TIMEOUT_RETRIES
        timeout = self.timeout_for(route)
        provider_config = await self._resolve_provider_config(
            task=task,
            route=route,
            requires_streaming=stream,
            requires_tool_calling=bool(tools),
            requires_vision=needs_vision or task == "vision",
        )
        model_name = (
            provider_config["model"] if provider_config else self._model_for(route)
        )
        if (
            tools
            and provider_config
            and provider_config.get("tool_strategy") == "pagechat_deterministic_tools"
        ):
            raise ProviderCapabilityError(
                "Model "
                f"'{model_name}' requires PageChat deterministic tool execution before "
                "ModelGateway.plan_with_tools; provider tool calling is disabled."
            )

        while True:
            try:
                params = {
                    "model": model_name,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": stream,
                    "timeout": timeout,
                }
                if tools:
                    params["tools"] = tools
                    params["tool_choice"] = "auto"
                if provider_config:
                    params["provider_config"] = provider_config
                return await self._completion_fn(**params)
            except TIMEOUT_EXCEPTIONS:
                if retries_left <= 0:
                    raise
                retries_left -= 1

    @staticmethod
    def _estimate_tokens_from_messages(messages: Sequence[dict]) -> int:
        total_chars = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    text = item.get("text") if isinstance(item, dict) else ""
                    if isinstance(text, str):
                        total_chars += len(text)
        return max(1, total_chars // 4)

    @staticmethod
    def _model_for(route: str) -> str:
        if route == "flash":
            return config.LLM_FLASH_MODEL
        return config.LLM_PLUS_MODEL

    @staticmethod
    def _route_slot_for_task(task: str, route: str) -> str:
        if task == "vision" or route == "vision":
            return "vision"
        if task == "answer":
            return "document_qa"
        return "general_chat"

    async def _resolve_provider_config(
        self,
        *,
        task: str,
        route: str,
        requires_streaming: bool = False,
        requires_tool_calling: bool = False,
        requires_vision: bool = False,
        requires_structured_output: bool = False,
    ) -> dict[str, Any] | None:
        if not self._model_settings_service or not self._user_id:
            return None
        route_slot = self._route_slot_for_task(task, route)
        provider_config = await self._model_settings_service.resolve_route(
            self._user_id, route_slot
        )
        return apply_provider_protocol(
            provider_config,
            requires_streaming=requires_streaming,
            requires_tool_calling=requires_tool_calling,
            requires_vision=requires_vision or route_slot == "vision",
            requires_structured_output=requires_structured_output,
        )
