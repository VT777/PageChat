from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
import asyncio
from dataclasses import dataclass
from typing import Any

import aiosqlite
import requests

from app.core import config
from app.services.responses_adapter import response_provider_capabilities


ROUTE_SLOTS = {
    "general_chat",
    "document_qa",
    "query_expansion",
    "indexing",
    "vision",
}

ENV_ROUTE_MODELS = {
    "general_chat": lambda: config.LLM_FLASH_MODEL,
    "document_qa": lambda: config.LLM_PLUS_MODEL,
    "query_expansion": lambda: config.LLM_FLASH_MODEL,
    "indexing": lambda: config.LLM_FLASH_MODEL,
    "vision": lambda: config.LLM_PLUS_MODEL,
}


class ModelRouteNotConfiguredError(RuntimeError):
    def __init__(self, route_slot: str):
        super().__init__(
            f"Model route '{route_slot}' is not configured. Configure it in Settings."
        )
        self.route_slot = route_slot


class ModelProviderInvalidError(RuntimeError):
    def __init__(self, route_slot: str, provider_id: str):
        super().__init__(
            f"Model provider '{provider_id}' for route '{route_slot}' is invalid. "
            "Reconfigure or retest it in Settings."
        )
        self.route_slot = route_slot
        self.provider_id = provider_id


MODEL_ROUTE_NOT_CONFIGURED_ERROR_CODE = "MODEL_ROUTE_NOT_CONFIGURED"


def model_route_not_configured_payload(
    error: ModelRouteNotConfiguredError,
) -> dict[str, str]:
    message = {
        "general_chat": "请先在设置页配置聊天模型。",
        "document_qa": "请先在设置页配置问答模型。",
        "query_expansion": "请先在设置页配置问答模型。",
        "indexing": "请先在设置页配置解析模型。",
        "vision": "请先在设置页配置 OCR/VLM 模型。",
    }.get(error.route_slot, "请先在设置页配置所需模型。")
    return {
        "status": "failed",
        "error_code": MODEL_ROUTE_NOT_CONFIGURED_ERROR_CODE,
        "route_slot": error.route_slot,
        "message": message,
        "error": message,
    }


def _provider_preset(
    provider: str,
    label: str,
    base_url: str,
    *,
    supports_custom_base_url: bool = False,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "label": label,
        "base_url": base_url,
        "icon_url": f"/provider-logos/{provider}.svg",
        "supports_custom_base_url": supports_custom_base_url,
        **response_provider_capabilities(provider, base_url),
    }


PROVIDER_PRESETS = [
    _provider_preset(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1",
    ),
    _provider_preset(
        "dashscope",
        "Alibaba Cloud Bailian / Tongyi",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    _provider_preset(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "moonshot",
        "Moonshot AI / Kimi",
        "https://api.moonshot.cn/v1",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "zhipuai",
        "Zhipu AI",
        "https://open.bigmodel.cn/api/paas/v4",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "siliconflow",
        "SiliconFlow",
        "https://api.siliconflow.cn/v1",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "volcengine_ark",
        "Volcengine Ark",
        "https://ark.cn-beijing.volces.com/api/v3",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "google_gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "anthropic",
        "Anthropic",
        "https://api.anthropic.com/v1",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "azure_openai",
        "Azure OpenAI",
        "https://{resource}.openai.azure.com/openai/deployments/{deployment}",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "ollama",
        "Ollama",
        "http://localhost:11434/v1",
        supports_custom_base_url=True,
    ),
    _provider_preset(
        "openai_compatible",
        "OpenAI Compatible",
        config.LLM_BASE_URL,
        supports_custom_base_url=True,
    ),
]


@dataclass(frozen=True)
class ResolvedModelRoute:
    route_slot: str
    provider_id: str | None
    provider: str
    base_url: str
    api_key: str | None
    model: str
    source: str
    route_version: str
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_responses_api: bool = False
    supports_reasoning_effort: bool = False
    supports_reasoning_summary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "route_slot": self.route_slot,
            "provider_id": self.provider_id,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "source": self.source,
            "route_version": self.route_version,
            "supports_streaming": self.supports_streaming,
            "supports_tool_calling": self.supports_tool_calling,
            "supports_vision": self.supports_vision,
            "supports_structured_output": self.supports_structured_output,
            "supports_responses_api": self.supports_responses_api,
            "supports_reasoning_effort": self.supports_reasoning_effort,
            "supports_reasoning_summary": self.supports_reasoning_summary,
        }


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:3]}...{api_key[-4:]}"


def _settings_secret() -> str | None:
    value = os.getenv("MODEL_SETTINGS_SECRET") or os.getenv("SECRET_KEY")
    return value.strip() if value and value.strip() else None


def _fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _protect_api_key(api_key: str) -> str:
    secret = _settings_secret()
    if secret:
        try:
            from cryptography.fernet import Fernet

            token = Fernet(_fernet_key(secret)).encrypt(api_key.encode("utf-8"))
            return "fernet:" + token.decode("ascii")
        except ImportError as exc:
            raise RuntimeError("cryptography is required for model key encryption") from exc
    if config.IS_PRODUCTION:
        raise RuntimeError(
            "MODEL_SETTINGS_SECRET or SECRET_KEY is required before storing model "
            "API keys in production."
        )
    encoded = base64.urlsafe_b64encode(api_key.encode("utf-8")).decode("ascii")
    return "dev-plain:" + encoded


def _unprotect_api_key(ciphertext: str) -> str:
    if ciphertext.startswith("fernet:"):
        secret = _settings_secret()
        if not secret:
            raise RuntimeError("MODEL_SETTINGS_SECRET is required to decrypt model keys")
        from cryptography.fernet import Fernet

        return Fernet(_fernet_key(secret)).decrypt(ciphertext[7:].encode("ascii")).decode(
            "utf-8"
        )
    if ciphertext.startswith("dev-plain:"):
        return base64.urlsafe_b64decode(ciphertext[10:].encode("ascii")).decode("utf-8")
    raise RuntimeError("Unsupported model API key storage format")


def _models_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    return f"{base}/models"


def _sanitize_provider_error(exc: Exception, api_key: str | None) -> str:
    message = str(exc)
    if api_key:
        message = message.replace(str(api_key), "[redacted-api-key]")
    return message


MODEL_CAPABILITY_ORDER = (
    "llm",
    "vision",
    "tool_calling",
    "reasoning",
    "ocr",
    "embedding",
)


def _infer_model_capabilities(model_id: str, raw: dict[str, Any] | None = None) -> list[str]:
    raw_capabilities = []
    for key in ("capabilities", "supported_capabilities", "features"):
        value = (raw or {}).get(key)
        if isinstance(value, list):
            raw_capabilities.extend(_normalize_capability_alias(str(item)) for item in value)
    explicit = [item for item in raw_capabilities if item in MODEL_CAPABILITY_ORDER]

    normalized = model_id.lower()
    inferred: list[str] = []
    if "embedding" in normalized or "embed" in normalized or "bge-" in normalized:
        return ["embedding"]
    is_ocr_model = "ocr" in normalized
    if is_ocr_model:
        inferred.extend(["llm", "vision", "ocr"])
    if not is_ocr_model and any(
        marker in normalized
        for marker in ("vl", "vision", "gpt-4o", "gemini", "claude-3", "qvq")
    ):
        inferred.extend(["llm", "vision", "tool_calling"])
    if any(
        marker in normalized
        for marker in ("qwen3", "qwen-3", "qvq", "qwq", "r1", "reason", "thinking", "o1", "o3")
    ):
        inferred.extend(["llm", "tool_calling", "reasoning"])
    if not explicit and not inferred:
        inferred.extend(["llm", "tool_calling"])
    return _ordered_capabilities([*explicit, *inferred])


def _normalize_capability_alias(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "function_calling": "tool_calling",
        "tools": "tool_calling",
        "tool": "tool_calling",
        "image": "vision",
        "visual": "vision",
        "reason": "reasoning",
        "thinking": "reasoning",
        "text_embedding": "embedding",
    }
    return aliases.get(normalized, normalized)


def _first_int(raw: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = raw.get(key)
        if value is None and isinstance(raw.get("model_properties"), dict):
            value = raw["model_properties"].get(key)
        if value is None and isinstance(raw.get("metadata"), dict):
            value = raw["metadata"].get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            compact = value.strip().lower().replace(",", "")
            multiplier = 1
            if compact.endswith("k"):
                compact = compact[:-1]
                multiplier = 1000
            try:
                number = float(compact)
            except ValueError:
                continue
            return int(number * multiplier)
    return None


def _ordered_capabilities(capabilities: list[str]) -> list[str]:
    selected = set(capabilities)
    return [item for item in MODEL_CAPABILITY_ORDER if item in selected]



_UNSUITABLE_PROVIDER_TEST_MODEL_MARKERS = (
    "image",
    "img",
    "asr",
    "audio",
    "tts",
    "embedding",
    "embed",
    "bge",
    "rerank",
    "ocr",
    "sre",
    "test",
)

_PROVIDER_TEST_MODEL_PREFERENCE_MARKERS = (
    "qwen3.7-max",
    "qwen3-max",
    "qwen-plus",
    "qwen-max",
    "qwen-turbo",
    "gpt-4",
    "gpt-3.5",
    "claude",
    "deepseek-chat",
    "kimi",
)


def _is_suitable_provider_test_model(model: dict[str, Any]) -> bool:
    model_id = str(model.get("id") or "").strip().lower()
    if not model_id:
        return False
    if any(marker in model_id for marker in _UNSUITABLE_PROVIDER_TEST_MODEL_MARKERS):
        return False
    capabilities = set(model.get("capabilities") or [])
    if "embedding" in capabilities or "ocr" in capabilities:
        return False
    return "llm" in capabilities and "tool_calling" in capabilities


def select_provider_test_model(models: list[dict[str, Any]]) -> str:
    suitable = [model for model in models if _is_suitable_provider_test_model(model)]
    if suitable:
        for marker in _PROVIDER_TEST_MODEL_PREFERENCE_MARKERS:
            for model in suitable:
                model_id = str(model.get("id") or "").strip()
                if marker in model_id.lower():
                    return model_id
        return str(suitable[0].get("id") or "").strip()

    fallback = next(
        (
            str(model.get("id") or "").strip()
            for model in models
            if model.get("id")
            and "embedding" not in set(model.get("capabilities") or [])
            and "ocr" not in set(model.get("capabilities") or [])
        ),
        "",
    )
    return fallback

def _normalize_provider_models(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        raw = item if isinstance(item, dict) else {}
        model_id = (
            item.strip()
            if isinstance(item, str)
            else str(raw.get("id") or raw.get("name") or raw.get("model") or "").strip()
        )
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model: dict[str, Any] = {"id": model_id}
        for key in ("owned_by", "created", "object"):
            if raw.get(key) is not None:
                model[key] = raw[key]
        capabilities = _infer_model_capabilities(model_id, raw)
        context_window = _first_int(
            raw,
            (
                "context_window",
                "context_length",
                "max_context_length",
                "max_input_tokens",
                "input_token_limit",
            ),
        )
        max_output_tokens = _first_int(
            raw,
            (
                "max_output_tokens",
                "max_completion_tokens",
                "output_token_limit",
                "max_tokens",
            ),
        )
        model["capabilities"] = capabilities
        model["features"] = capabilities
        model["supports_vision"] = "vision" in capabilities
        model["supports_tool_calling"] = "tool_calling" in capabilities
        model["supports_reasoning"] = "reasoning" in capabilities
        model["supports_embedding"] = "embedding" in capabilities
        model["supports_ocr"] = "ocr" in capabilities
        model["context_window"] = context_window
        model["max_output_tokens"] = max_output_tokens
        models.append(model)
    return models


def _normalize_custom_model(
    *,
    model: str,
    display_name: str | None = None,
    model_type: str = "llm",
    endpoint_model_name: str | None = None,
    capabilities: list[str] | None = None,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    model_id = (endpoint_model_name or model or "").strip()
    if not model_id:
        raise ValueError("model is required")
    normalized_type = (model_type or "llm").strip().lower()
    explicit = [_normalize_capability_alias(str(item)) for item in capabilities or []]
    if normalized_type == "vision":
        explicit.extend(["llm", "vision", "tool_calling"])
    elif normalized_type == "embedding":
        explicit.append("embedding")
    elif normalized_type == "ocr":
        explicit.extend(["llm", "vision", "ocr"])
    else:
        explicit.extend(["llm", "tool_calling"])
    normalized_capabilities = _ordered_capabilities(
        [item for item in explicit if item in MODEL_CAPABILITY_ORDER]
        or _infer_model_capabilities(model_id)
    )
    return {
        "id": model_id,
        "display_name": display_name or None,
        "model_type": normalized_type,
        "capabilities": normalized_capabilities,
        "features": normalized_capabilities,
        "supports_vision": "vision" in normalized_capabilities,
        "supports_tool_calling": "tool_calling" in normalized_capabilities,
        "supports_reasoning": "reasoning" in normalized_capabilities,
        "supports_embedding": "embedding" in normalized_capabilities,
        "supports_ocr": "ocr" in normalized_capabilities,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "source": "custom",
    }


def _merge_provider_models(
    remote_models: list[dict[str, Any]],
    custom_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in [*remote_models, *custom_models]:
        model_id = str(model.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        merged.append(model)
    return merged


def _route_version(*parts: str) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ModelSettingsService:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    @staticmethod
    def provider_presets() -> list[dict[str, Any]]:
        return [dict(preset) for preset in PROVIDER_PRESETS]

    async def save_provider_config(
        self,
        *,
        user_id: str,
        provider: str,
        base_url: str,
        api_key: str,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")
        if not provider:
            raise ValueError("provider is required")
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")

        provider_id = provider_id or str(uuid.uuid4())
        cursor = await self.db.execute(
            "SELECT user_id FROM model_provider_configs WHERE provider_id = ?",
            (provider_id,),
        )
        existing = await cursor.fetchone()
        if existing and existing["user_id"] != user_id:
            raise ValueError("provider config not found")

        api_key_ciphertext = _protect_api_key(api_key)
        api_key_mask = mask_api_key(api_key)
        capabilities = response_provider_capabilities(provider, base_url)

        await self.db.execute(
            """
            INSERT INTO model_provider_configs (
                provider_id, user_id, provider, base_url, api_key_ciphertext,
                api_key_mask, validation_status, supports_responses_api,
                supports_reasoning_effort, supports_reasoning_summary, created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'untested', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(provider_id) DO UPDATE SET
                provider = excluded.provider,
                base_url = excluded.base_url,
                api_key_ciphertext = excluded.api_key_ciphertext,
                api_key_mask = excluded.api_key_mask,
                validation_status = 'untested',
                supports_responses_api = excluded.supports_responses_api,
                supports_reasoning_effort = excluded.supports_reasoning_effort,
                supports_reasoning_summary = excluded.supports_reasoning_summary,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                provider_id,
                user_id,
                provider,
                base_url,
                api_key_ciphertext,
                api_key_mask,
                int(capabilities["supports_responses_api"]),
                int(capabilities["supports_reasoning_effort"]),
                int(capabilities["supports_reasoning_summary"]),
            ),
        )
        await self.db.commit()
        return await self.get_provider_config(user_id, provider_id) or {}

    async def list_provider_configs(self, user_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_mask,
                   validation_status, supports_responses_api,
                   supports_reasoning_effort, supports_reasoning_summary,
                   created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user_id,),
        )
        return [self._provider_row_to_dict(row) for row in await cursor.fetchall()]

    async def get_provider_config(
        self, user_id: str, provider_id: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_mask,
                   validation_status, supports_responses_api,
                   supports_reasoning_effort, supports_reasoning_summary,
                   created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        )
        row = await cursor.fetchone()
        return self._provider_row_to_dict(row) if row else None

    async def save_custom_provider_model(
        self,
        *,
        user_id: str,
        provider_id: str,
        model: str,
        display_name: str | None = None,
        model_type: str = "llm",
        endpoint_model_name: str | None = None,
        capabilities: list[str] | None = None,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        provider = await self.get_provider_config(user_id, provider_id)
        if not provider:
            raise ValueError("provider config not found")
        normalized = _normalize_custom_model(
            model=model,
            display_name=display_name,
            model_type=model_type,
            endpoint_model_name=endpoint_model_name,
            capabilities=capabilities,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        model_config_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO model_provider_custom_models (
                model_config_id, user_id, provider_id, model, display_name,
                model_type, endpoint_model_name, capabilities_json,
                context_window, max_output_tokens, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, provider_id, model) DO UPDATE SET
                display_name = excluded.display_name,
                model_type = excluded.model_type,
                endpoint_model_name = excluded.endpoint_model_name,
                capabilities_json = excluded.capabilities_json,
                context_window = excluded.context_window,
                max_output_tokens = excluded.max_output_tokens,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                model_config_id,
                user_id,
                provider_id,
                model.strip(),
                display_name,
                (model_type or "llm").strip().lower(),
                endpoint_model_name,
                json.dumps(normalized["capabilities"], ensure_ascii=False),
                context_window,
                max_output_tokens,
            ),
        )
        await self.db.commit()
        return normalized

    async def list_custom_provider_models(
        self,
        *,
        user_id: str,
        provider_id: str,
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT model, display_name, model_type, endpoint_model_name,
                   capabilities_json, context_window, max_output_tokens
            FROM model_provider_custom_models
            WHERE user_id = ? AND provider_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user_id, provider_id),
        )
        models = []
        for row in await cursor.fetchall():
            try:
                capabilities = json.loads(row["capabilities_json"] or "[]")
            except json.JSONDecodeError:
                capabilities = []
            models.append(
                _normalize_custom_model(
                    model=row["model"],
                    display_name=row["display_name"],
                    model_type=row["model_type"],
                    endpoint_model_name=row["endpoint_model_name"],
                    capabilities=capabilities,
                    context_window=row["context_window"],
                    max_output_tokens=row["max_output_tokens"],
                )
            )
        return models

    async def list_provider_models(
        self,
        *,
        user_id: str,
        provider_id: str,
        timeout: float = 12,
    ) -> dict[str, Any]:
        provider = await self._get_provider_config_with_secret(user_id, provider_id)
        if not provider:
            raise ValueError("provider config not found")

        custom_models = await self.list_custom_provider_models(
            user_id=user_id,
            provider_id=provider_id,
        )
        api_key = _unprotect_api_key(provider["api_key_ciphertext"])
        url = _models_url(provider["base_url"])

        def fetch() -> Any:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        try:
            payload = await asyncio.to_thread(fetch)
            remote_models = _normalize_provider_models(payload)
        except Exception as exc:
            if not custom_models:
                raise RuntimeError(_sanitize_provider_error(exc, api_key)) from exc
            return {
                "provider_id": provider_id,
                "provider": provider["provider"],
                "base_url": provider["base_url"],
                "models": custom_models,
                "source": "custom",
            }

        models = _merge_provider_models(remote_models, custom_models)
        source = "remote+custom" if custom_models else "remote"

        return {
            "provider_id": provider_id,
            "provider": provider["provider"],
            "base_url": provider["base_url"],
            "models": models,
            "source": source,
        }

    async def update_provider_config_fields(
        self,
        *,
        user_id: str,
        provider_id: str,
        provider: str,
        base_url: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")
        if not provider_id:
            raise ValueError("provider_id is required")
        if not provider:
            raise ValueError("provider is required")
        if not base_url:
            raise ValueError("base_url is required")

        if api_key:
            api_key_ciphertext = _protect_api_key(api_key)
            api_key_mask = mask_api_key(api_key)
            capabilities = response_provider_capabilities(provider, base_url)
            cursor = await self.db.execute(
                """
                UPDATE model_provider_configs
                SET provider = ?, base_url = ?, api_key_ciphertext = ?,
                    api_key_mask = ?, validation_status = 'untested',
                    supports_responses_api = ?,
                    supports_reasoning_effort = ?,
                    supports_reasoning_summary = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND provider_id = ?
                """,
                (
                    provider,
                    base_url,
                    api_key_ciphertext,
                    api_key_mask,
                    int(capabilities["supports_responses_api"]),
                    int(capabilities["supports_reasoning_effort"]),
                    int(capabilities["supports_reasoning_summary"]),
                    user_id,
                    provider_id,
                ),
            )
        else:
            capabilities = response_provider_capabilities(provider, base_url)
            cursor = await self.db.execute(
                """
                UPDATE model_provider_configs
                SET provider = ?, base_url = ?, validation_status = 'untested',
                    supports_responses_api = ?,
                    supports_reasoning_effort = ?,
                    supports_reasoning_summary = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND provider_id = ?
                """,
                (
                    provider,
                    base_url,
                    int(capabilities["supports_responses_api"]),
                    int(capabilities["supports_reasoning_effort"]),
                    int(capabilities["supports_reasoning_summary"]),
                    user_id,
                    provider_id,
                ),
            )
        await self.db.commit()
        if cursor.rowcount == 0:
            raise ValueError("provider config not found")
        return await self.get_provider_config(user_id, provider_id) or {}

    async def update_provider_validation_status(
        self,
        *,
        user_id: str,
        provider_id: str,
        validation_status: str,
    ) -> dict[str, Any]:
        if validation_status not in {"untested", "valid", "invalid"}:
            raise ValueError("unsupported provider validation status")
        cursor = await self.db.execute(
            """
            UPDATE model_provider_configs
            SET validation_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND provider_id = ?
            """,
            (validation_status, user_id, provider_id),
        )
        await self.db.commit()
        if cursor.rowcount == 0:
            raise ValueError("provider config not found")
        return await self.get_provider_config(user_id, provider_id) or {}

    async def delete_provider_config(self, user_id: str, provider_id: str) -> bool:
        await self.db.execute(
            """
            DELETE FROM model_route_mappings
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        )
        cursor = await self.db.execute(
            "DELETE FROM model_provider_configs WHERE user_id = ? AND provider_id = ?",
            (user_id, provider_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def save_route_mapping(
        self,
        *,
        user_id: str,
        route_slot: str,
        provider_id: str,
        model: str,
        supports_streaming: bool = True,
        supports_tool_calling: bool = True,
        supports_vision: bool = False,
        supports_structured_output: bool = False,
        supports_responses_api: bool | None = None,
    ) -> dict[str, Any]:
        if route_slot not in ROUTE_SLOTS:
            raise ValueError(f"Unsupported route slot: {route_slot}")
        if not model:
            raise ValueError("model is required")
        provider = await self._get_provider_config_with_secret(user_id, provider_id)
        if not provider:
            raise ValueError("provider config not found")
        if str(provider.get("validation_status") or "").lower() == "invalid":
            raise ModelProviderInvalidError(route_slot, provider_id)
        known_models = await self.list_custom_provider_models(
            user_id=user_id,
            provider_id=provider_id,
        )
        if known_models and model not in {item["id"] for item in known_models}:
            raise ValueError("model is not available for this provider")
        route_supports_responses_api = (
            bool(provider.get("supports_responses_api"))
            if supports_responses_api is None
            else bool(supports_responses_api)
        )

        version = _route_version(
            user_id,
            route_slot,
            provider_id,
            model,
            str(bool(supports_streaming)),
            str(bool(supports_tool_calling)),
            str(bool(supports_vision)),
            str(bool(supports_structured_output)),
            str(route_supports_responses_api),
        )
        await self.db.execute(
            """
            INSERT INTO model_route_mappings (
                user_id, route_slot, provider_id, model, supports_streaming,
                supports_tool_calling, supports_vision, supports_structured_output,
                supports_responses_api,
                route_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, route_slot) DO UPDATE SET
                provider_id = excluded.provider_id,
                model = excluded.model,
                supports_streaming = excluded.supports_streaming,
                supports_tool_calling = excluded.supports_tool_calling,
                supports_vision = excluded.supports_vision,
                supports_structured_output = excluded.supports_structured_output,
                supports_responses_api = excluded.supports_responses_api,
                route_version = excluded.route_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                route_slot,
                provider_id,
                model,
                int(supports_streaming),
                int(supports_tool_calling),
                int(supports_vision),
                int(supports_structured_output),
                int(route_supports_responses_api),
                version,
            ),
        )
        await self.db.commit()
        return await self.get_route_mapping(user_id, route_slot) or {}

    async def get_route_mapping(
        self, user_id: str, route_slot: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT user_id, route_slot, provider_id, model, supports_streaming,
                   supports_tool_calling, supports_vision, supports_structured_output,
                   supports_responses_api,
                   route_version, created_at, updated_at
            FROM model_route_mappings
            WHERE user_id = ? AND route_slot = ?
            """,
            (user_id, route_slot),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        result["supports_streaming"] = bool(result["supports_streaming"])
        result["supports_tool_calling"] = bool(result["supports_tool_calling"])
        result["supports_vision"] = bool(result["supports_vision"])
        result["supports_structured_output"] = bool(result["supports_structured_output"])
        result["supports_responses_api"] = bool(result["supports_responses_api"])
        return result

    async def list_route_mappings(self, user_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT user_id, route_slot, provider_id, model, supports_streaming,
                   supports_tool_calling, supports_vision, supports_structured_output,
                   supports_responses_api,
                   route_version, created_at, updated_at
            FROM model_route_mappings
            WHERE user_id = ?
            ORDER BY route_slot
            """,
            (user_id,),
        )
        rows = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["supports_streaming"] = bool(item["supports_streaming"])
            item["supports_tool_calling"] = bool(item["supports_tool_calling"])
            item["supports_vision"] = bool(item["supports_vision"])
            item["supports_structured_output"] = bool(item["supports_structured_output"])
            item["supports_responses_api"] = bool(item["supports_responses_api"])
            rows.append(item)
        return rows

    async def resolve_route(self, user_id: str | None, route_slot: str) -> dict[str, Any]:
        if route_slot not in ROUTE_SLOTS:
            raise ValueError(f"Unsupported route slot: {route_slot}")
        if user_id:
            cursor = await self.db.execute(
                """
                SELECT m.route_slot, m.provider_id, m.model, m.supports_streaming,
                       m.supports_tool_calling, m.supports_vision,
                       m.supports_structured_output, m.supports_responses_api,
                       m.route_version,
                       p.provider, p.base_url, p.api_key_ciphertext,
                       p.validation_status,
                       p.supports_reasoning_effort,
                       p.supports_reasoning_summary
                FROM model_route_mappings m
                JOIN model_provider_configs p ON p.provider_id = m.provider_id
                WHERE m.user_id = ? AND m.route_slot = ? AND p.user_id = ?
                """,
                (user_id, route_slot, user_id),
            )
            row = await cursor.fetchone()
            if row:
                if str(row["validation_status"] or "").lower() == "invalid":
                    raise ModelProviderInvalidError(route_slot, row["provider_id"])
                return ResolvedModelRoute(
                    route_slot=route_slot,
                    provider_id=row["provider_id"],
                    provider=row["provider"],
                    base_url=row["base_url"],
                    api_key=_unprotect_api_key(row["api_key_ciphertext"]),
                    model=row["model"],
                    source="user",
                    route_version=row["route_version"],
                    supports_streaming=bool(row["supports_streaming"]),
                    supports_tool_calling=bool(row["supports_tool_calling"]),
                    supports_vision=bool(row["supports_vision"]),
                    supports_structured_output=bool(row["supports_structured_output"]),
                    supports_responses_api=bool(row["supports_responses_api"]),
                    supports_reasoning_effort=bool(row["supports_reasoning_effort"]),
                    supports_reasoning_summary=bool(row["supports_reasoning_summary"]),
                ).as_dict()

        if not config.ALLOW_ENV_MODEL_FALLBACK:
            raise ModelRouteNotConfiguredError(route_slot)

        model = ENV_ROUTE_MODELS[route_slot]()
        env_capabilities = response_provider_capabilities("environment", config.LLM_BASE_URL)
        return ResolvedModelRoute(
            route_slot=route_slot,
            provider_id=None,
            provider="environment",
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=model,
            source="environment",
            route_version=_route_version("environment", route_slot, model),
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=route_slot == "vision",
            supports_structured_output=False,
            **env_capabilities,
        ).as_dict()

    async def _get_provider_config_with_secret(
        self, user_id: str, provider_id: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_ciphertext,
                   api_key_mask, validation_status, supports_responses_api,
                   supports_reasoning_effort, supports_reasoning_summary,
                   created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        )
        row = await cursor.fetchone()
        return self._provider_secret_row_to_dict(row) if row else None

    @staticmethod
    def _provider_row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in (
            "supports_responses_api",
            "supports_reasoning_effort",
            "supports_reasoning_summary",
        ):
            item[key] = bool(item.get(key))
        return item

    @staticmethod
    def _provider_secret_row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
        return ModelSettingsService._provider_row_to_dict(row)
