from __future__ import annotations

from types import SimpleNamespace
from typing import Any

try:
    import litellm
except ImportError:
    litellm = SimpleNamespace(completion=None, acompletion=None)


class ModelProviderError(RuntimeError):
    pass


class LiteLLMAdapter:
    def completion(
        self,
        *,
        provider_config: dict[str, Any],
        messages: list[dict[str, Any]],
        temperature: float = 0,
        stream: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        params = self._build_params(
            provider_config=provider_config,
            messages=messages,
            temperature=temperature,
            stream=stream,
            timeout=timeout,
            extra=kwargs,
        )
        try:
            if litellm.completion is None:
                raise RuntimeError("litellm is not installed")
            return litellm.completion(**params)
        except Exception as exc:
            raise ModelProviderError(self._sanitize_error(exc, provider_config)) from exc

    async def acompletion(
        self,
        *,
        provider_config: dict[str, Any],
        messages: list[dict[str, Any]],
        temperature: float = 0,
        stream: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        params = self._build_params(
            provider_config=provider_config,
            messages=messages,
            temperature=temperature,
            stream=stream,
            timeout=timeout,
            extra=kwargs,
        )
        try:
            if litellm.acompletion is None:
                raise RuntimeError("litellm is not installed")
            return await litellm.acompletion(**params)
        except Exception as exc:
            raise ModelProviderError(self._sanitize_error(exc, provider_config)) from exc

    @staticmethod
    def _build_params(
        *,
        provider_config: dict[str, Any],
        messages: list[dict[str, Any]],
        temperature: float,
        stream: bool,
        timeout: float | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        params = {
            "model": provider_config["model"],
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
            "api_key": provider_config.get("api_key"),
            "api_base": provider_config.get("base_url"),
        }
        if timeout is not None:
            params["timeout"] = timeout
        params.update(extra)
        return params

    @staticmethod
    def _sanitize_error(exc: Exception, provider_config: dict[str, Any]) -> str:
        message = str(exc)
        api_key = provider_config.get("api_key")
        if api_key:
            message = message.replace(str(api_key), "[redacted-api-key]")
        return message
