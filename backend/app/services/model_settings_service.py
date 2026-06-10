from __future__ import annotations

import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from typing import Any

import aiosqlite

from app.core import config


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

PROVIDER_PRESETS = [
    {
        "provider": "openai_compatible",
        "label": "OpenAI compatible",
        "base_url": config.LLM_BASE_URL,
        "supports_custom_base_url": True,
    },
    {
        "provider": "dashscope",
        "label": "DashScope compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "supports_custom_base_url": False,
    },
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
    supports_vision: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "route_slot": self.route_slot,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "source": self.source,
            "route_version": self.route_version,
            "supports_vision": self.supports_vision,
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

        await self.db.execute(
            """
            INSERT INTO model_provider_configs (
                provider_id, user_id, provider, base_url, api_key_ciphertext,
                api_key_mask, validation_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'untested', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(provider_id) DO UPDATE SET
                provider = excluded.provider,
                base_url = excluded.base_url,
                api_key_ciphertext = excluded.api_key_ciphertext,
                api_key_mask = excluded.api_key_mask,
                validation_status = 'untested',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                provider_id,
                user_id,
                provider,
                base_url,
                api_key_ciphertext,
                api_key_mask,
            ),
        )
        await self.db.commit()
        return await self.get_provider_config(user_id, provider_id) or {}

    async def list_provider_configs(self, user_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_mask,
                   validation_status, created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_provider_config(
        self, user_id: str, provider_id: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_mask,
                   validation_status, created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_provider_config(self, user_id: str, provider_id: str) -> bool:
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
        supports_vision: bool = False,
    ) -> dict[str, Any]:
        if route_slot not in ROUTE_SLOTS:
            raise ValueError(f"Unsupported route slot: {route_slot}")
        if not model:
            raise ValueError("model is required")
        provider = await self._get_provider_config_with_secret(user_id, provider_id)
        if not provider:
            raise ValueError("provider config not found")

        version = _route_version(user_id, route_slot, provider_id, model)
        await self.db.execute(
            """
            INSERT INTO model_route_mappings (
                user_id, route_slot, provider_id, model, supports_vision,
                route_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, route_slot) DO UPDATE SET
                provider_id = excluded.provider_id,
                model = excluded.model,
                supports_vision = excluded.supports_vision,
                route_version = excluded.route_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, route_slot, provider_id, model, int(supports_vision), version),
        )
        await self.db.commit()
        return await self.get_route_mapping(user_id, route_slot) or {}

    async def get_route_mapping(
        self, user_id: str, route_slot: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT user_id, route_slot, provider_id, model, supports_vision,
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
        result["supports_vision"] = bool(result["supports_vision"])
        return result

    async def list_route_mappings(self, user_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT user_id, route_slot, provider_id, model, supports_vision,
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
            item["supports_vision"] = bool(item["supports_vision"])
            rows.append(item)
        return rows

    async def resolve_route(self, user_id: str | None, route_slot: str) -> dict[str, Any]:
        if route_slot not in ROUTE_SLOTS:
            raise ValueError(f"Unsupported route slot: {route_slot}")
        if user_id:
            cursor = await self.db.execute(
                """
                SELECT m.route_slot, m.model, m.supports_vision, m.route_version,
                       p.provider, p.base_url, p.api_key_ciphertext
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
                    supports_vision=bool(row["supports_vision"]),
                ).as_dict()

        model = ENV_ROUTE_MODELS[route_slot]()
        return ResolvedModelRoute(
            route_slot=route_slot,
            provider="environment",
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=model,
            source="environment",
            route_version=_route_version("environment", route_slot, model),
            supports_vision=route_slot == "vision",
        ).as_dict()

    async def _get_provider_config_with_secret(
        self, user_id: str, provider_id: str
    ) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT provider_id, user_id, provider, base_url, api_key_ciphertext,
                   api_key_mask, validation_status, created_at, updated_at
            FROM model_provider_configs
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
