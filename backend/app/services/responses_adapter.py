from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI


def response_provider_capabilities(provider: str, base_url: str) -> dict[str, bool]:
    provider_key = (provider or "").strip().lower()
    url = (base_url or "").strip().lower()
    is_openai = "api.openai.com" in url or provider_key == "openai"
    is_dashscope = "dashscope.aliyuncs.com" in url or provider_key == "dashscope"
    supported = is_openai or is_dashscope
    return {
        "supports_responses_api": supported,
        "supports_reasoning_effort": supported,
        "supports_reasoning_summary": is_openai,
    }


class OpenAIResponsesAdapter:
    def _client(self, provider_config: dict[str, Any]) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=provider_config.get("api_key"),
            base_url=provider_config.get("base_url"),
        )

    async def create(
        self,
        *,
        provider_config: dict[str, Any],
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float | None = None,
        timeout: float | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        if not provider_config.get("supports_responses_api"):
            raise ValueError("Provider does not advertise Responses API support")

        params: dict[str, Any] = {
            "model": provider_config["model"],
            "input": input_items,
            "stream": stream,
        }
        if instructions:
            params["instructions"] = instructions
        if temperature is not None:
            params["temperature"] = temperature
        if previous_response_id:
            params["previous_response_id"] = previous_response_id
        if max_output_tokens:
            params["max_output_tokens"] = max_output_tokens
        if tools:
            params["tools"] = [self._tool_for_responses(tool) for tool in tools]

        reasoning: dict[str, str] = {}
        if provider_config.get("supports_reasoning_effort"):
            reasoning["effort"] = "low"
        if provider_config.get("supports_reasoning_summary"):
            reasoning["summary"] = "auto"
        if reasoning:
            params["reasoning"] = reasoning

        return await self._client(provider_config).responses.create(
            **params,
            timeout=timeout,
        )

    @staticmethod
    def _tool_for_responses(tool: dict[str, Any]) -> dict[str, Any]:
        if tool.get("type") != "function":
            return dict(tool)
        function = tool.get("function") or {}
        mapped = {
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description") or "",
            "parameters": function.get("parameters") or {"type": "object"},
        }
        if "strict" in function:
            mapped["strict"] = function["strict"]
        return mapped
