from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CHAT_COMPLETIONS_PROTOCOL = "chat_completions"
RESPONSES_PROTOCOL = "responses_api"


class ProviderCapabilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_streaming: bool = True
    supports_tool_calling: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_responses_api: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderProtocolSelection:
    provider: str
    model: str
    protocol: str
    capabilities: ProviderCapabilities
    tool_strategy: str = "none"
    fallback_protocol: str | None = None
    reason: str = ""


def select_provider_protocol(
    provider_config: dict[str, Any] | None,
    *,
    requires_streaming: bool = False,
    requires_tool_calling: bool = False,
    requires_vision: bool = False,
    requires_structured_output: bool = False,
    prefer_responses: bool = False,
) -> ProviderProtocolSelection:
    config = dict(provider_config or {})
    provider = str(config.get("provider") or "openai_compatible").lower()
    model = str(config.get("model") or "")
    capabilities = infer_provider_capabilities(config)

    if requires_streaming and not capabilities.supports_streaming:
        raise ProviderCapabilityError(
            f"Model '{model or provider}' is not configured for streaming responses."
        )
    if requires_vision and not capabilities.supports_vision:
        raise ProviderCapabilityError(
            f"Model '{model or provider}' is not configured for vision tasks."
        )
    if requires_structured_output and not capabilities.supports_structured_output:
        raise ProviderCapabilityError(
            f"Model '{model or provider}' is not configured for structured output."
        )

    tool_strategy = "none"
    if requires_tool_calling:
        if capabilities.supports_tool_calling:
            tool_strategy = "function_calling"
        elif provider in {"openai_compatible", "dashscope"}:
            tool_strategy = "pagechat_deterministic_tools"
        else:
            raise ProviderCapabilityError(
                f"Model '{model or provider}' cannot run required tool calls."
            )

    protocol = CHAT_COMPLETIONS_PROTOCOL
    reason = "OpenAI-compatible providers use Chat Completions for PageChat runs."
    if prefer_responses:
        reason = (
            "Responses API was requested but the PageChat Responses transport is "
            "not enabled; using a single Chat Completions protocol."
        )

    return ProviderProtocolSelection(
        provider=provider,
        model=model,
        protocol=protocol,
        capabilities=capabilities,
        tool_strategy=tool_strategy,
        fallback_protocol=None,
        reason=reason,
    )


def apply_provider_protocol(
    provider_config: dict[str, Any],
    *,
    requires_streaming: bool = False,
    requires_tool_calling: bool = False,
    requires_vision: bool = False,
    requires_structured_output: bool = False,
    prefer_responses: bool = False,
) -> dict[str, Any]:
    selection = select_provider_protocol(
        provider_config,
        requires_streaming=requires_streaming,
        requires_tool_calling=requires_tool_calling,
        requires_vision=requires_vision,
        requires_structured_output=requires_structured_output,
        prefer_responses=prefer_responses,
    )
    resolved = dict(provider_config)
    resolved["protocol"] = selection.protocol
    resolved["tool_strategy"] = selection.tool_strategy
    resolved["provider_capabilities"] = selection.capabilities.as_dict()
    resolved["protocol_reason"] = selection.reason
    if selection.fallback_protocol is not None:
        resolved["fallback_protocol"] = selection.fallback_protocol
    else:
        resolved.pop("fallback_protocol", None)
    return resolved


def infer_provider_capabilities(
    provider_config: dict[str, Any] | None,
) -> ProviderCapabilities:
    config = dict(provider_config or {})
    provider = str(config.get("provider") or "openai_compatible").lower()

    default_tool_calling = provider in {
        "environment",
        "openai",
        "openai_compatible",
        "dashscope",
    }
    default_responses = False

    return ProviderCapabilities(
        supports_streaming=_bool_config(config, "supports_streaming", True),
        supports_tool_calling=_bool_config(
            config,
            "supports_tool_calling",
            default_tool_calling,
        ),
        supports_vision=_bool_config(config, "supports_vision", False),
        supports_structured_output=_bool_config(
            config,
            "supports_structured_output",
            False,
        ),
        supports_responses_api=_bool_config(
            config, "supports_responses_api", default_responses
        ),
    )


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
