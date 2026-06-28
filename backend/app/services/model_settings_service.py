from __future__ import annotations

import base64
import hashlib
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


MODEL_CAPABILITY_ORDER = ("llm", "vision", "tool_calling", "ocr", "embedding")


def _infer_model_capabilities(model_id: str, raw: dict[str, Any] | None = None) -> list[str]:
    raw_capabilities = []
    for key in ("capabilities", "supported_capabilities", "features"):
        value = (raw or {}).get(key)
        if isinstance(value, list):
            raw_capabilities.extend(str(item).lower() for item in value)
    explicit = [item for item in raw_capabilities if item in MODEL_CAPABILITY_ORDER]
    if explicit:
        return _ordered_capabilities(explicit)

    normalized = model_id.lower()
    if "embedding" in normalized or "embed" in normalized or "bge-" in normalized:
        return ["embedding"]
    if "ocr" in normalized:
        return ["llm", "vision", "ocr"]
    if any(
        marker in normalized
        for marker in ("vl", "vision", "gpt-4o", "gemini", "claude-3", "qvq")
    ):
        return ["llm", "vision", "tool_calling"]
    return ["llm", "tool_calling"]


def _ordered_capabilities(capabilities: list[str]) -> list[str]:
    selected = set(capabilities)
    return [item for item in MODEL_CAPABILITY_ORDER if item in selected]


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
        model["capabilities"] = _infer_model_capabilities(model_id, raw)
        models.append(model)
    return models


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
        except Exception as exc:
            raise RuntimeError(_sanitize_provider_error(exc, api_key)) from exc

        return {
            "provider_id": provider_id,
            "provider": provider["provider"],
            "base_url": provider["base_url"],
            "models": _normalize_provider_models(payload),
            "source": "remote",
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
                SELECT m.route_slot, m.model, m.supports_streaming,
                       m.supports_tool_calling, m.supports_vision,
                       m.supports_structured_output, m.supports_responses_api,
                       m.route_version,
                       p.provider, p.base_url, p.api_key_ciphertext,
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
                return ResolvedModelRoute(
                    route_slot=route_slot,
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
