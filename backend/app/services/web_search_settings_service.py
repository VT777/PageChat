from __future__ import annotations

import json
from typing import Any

import aiosqlite

from app.services.model_settings_service import (
    _protect_api_key,
    _unprotect_api_key,
    mask_api_key,
)


VALID_WEB_SEARCH_MODES = {"on-demand", "auto"}
VALID_WEB_SEARCH_PROVIDERS = {"anysearch"}
VALID_WEB_SEARCH_ZONES = {"cn", "intl"}
VALID_WEB_SEARCH_CONTENT_TYPES = {"web", "news"}
DEFAULT_WEB_SEARCH_CONTENT_TYPES = ["web", "news"]

DEFAULT_WEB_SEARCH_SETTINGS: dict[str, Any] = {
    "provider": "anysearch",
    "mode": "on-demand",
    "zone": "cn",
    "language": "zh-CN",
    "max_results": 5,
    "content_types": DEFAULT_WEB_SEARCH_CONTENT_TYPES,
    "api_key_mask": "",
}


class WebSearchSettingsService:
    """Per-user Web Search provider settings."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_settings(self, user_id: str) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")

        cursor = await self.db.execute(
            """
            SELECT provider, mode, api_key_mask, zone, language, max_results,
                   content_types_json, updated_at
            FROM web_search_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return dict(DEFAULT_WEB_SEARCH_SETTINGS)

        return {
            "provider": row["provider"],
            "mode": row["mode"],
            "zone": row["zone"],
            "language": row["language"],
            "max_results": int(row["max_results"]),
            "content_types": self._parse_content_types(row["content_types_json"]),
            "api_key_mask": row["api_key_mask"] or "",
            "updated_at": row["updated_at"],
        }

    async def save_settings(
        self,
        *,
        user_id: str,
        provider: str = "anysearch",
        mode: str = "on-demand",
        api_key: str | None = None,
        zone: str = "cn",
        language: str = "zh-CN",
        max_results: int = 5,
        content_types: list[str] | None = None,
    ) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")

        normalized = self._validate_settings(
            provider=provider,
            mode=mode,
            zone=zone,
            language=language,
            max_results=max_results,
            content_types=content_types,
        )

        existing_secret = await self._get_secret_row(user_id)
        api_key_ciphertext = existing_secret.get("api_key_ciphertext") if existing_secret else None
        api_key_mask = existing_secret.get("api_key_mask") if existing_secret else ""
        if api_key is not None and api_key.strip():
            stripped_key = api_key.strip()
            api_key_ciphertext = _protect_api_key(stripped_key)
            api_key_mask = mask_api_key(stripped_key)

        await self.db.execute(
            """
            INSERT INTO web_search_settings (
                user_id, provider, mode, api_key_ciphertext, api_key_mask,
                zone, language, max_results, content_types_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                provider = excluded.provider,
                mode = excluded.mode,
                api_key_ciphertext = excluded.api_key_ciphertext,
                api_key_mask = excluded.api_key_mask,
                zone = excluded.zone,
                language = excluded.language,
                max_results = excluded.max_results,
                content_types_json = excluded.content_types_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                normalized["provider"],
                normalized["mode"],
                api_key_ciphertext,
                api_key_mask or "",
                normalized["zone"],
                normalized["language"],
                normalized["max_results"],
                json.dumps(normalized["content_types"], ensure_ascii=False),
            ),
        )
        await self.db.commit()
        return await self.get_settings(user_id)

    async def get_secret(self, user_id: str) -> str | None:
        row = await self._get_secret_row(user_id)
        if not row or not row.get("api_key_ciphertext"):
            return None
        return _unprotect_api_key(row["api_key_ciphertext"])

    async def resolve_for_request(self, user_id: str, requested: bool) -> dict[str, Any]:
        settings = await self.get_settings(user_id)
        settings["api_key"] = await self.get_secret(user_id)
        settings["enabled"] = settings["mode"] == "auto" or bool(requested)
        settings["requested"] = bool(requested)
        return settings

    async def _get_secret_row(self, user_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            """
            SELECT api_key_ciphertext, api_key_mask
            FROM web_search_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _parse_content_types(raw: str | None) -> list[str]:
        if not raw:
            return list(DEFAULT_WEB_SEARCH_CONTENT_TYPES)
        try:
            parsed = json.loads(raw)
        except Exception:
            return list(DEFAULT_WEB_SEARCH_CONTENT_TYPES)
        if not isinstance(parsed, list):
            return list(DEFAULT_WEB_SEARCH_CONTENT_TYPES)
        content_types = [
            item for item in parsed if item in VALID_WEB_SEARCH_CONTENT_TYPES
        ]
        return content_types or list(DEFAULT_WEB_SEARCH_CONTENT_TYPES)

    @classmethod
    def _validate_settings(
        cls,
        *,
        provider: str,
        mode: str,
        zone: str,
        language: str,
        max_results: int,
        content_types: list[str] | None,
    ) -> dict[str, Any]:
        provider = (provider or "").strip().lower()
        mode = (mode or "").strip()
        zone = (zone or "").strip()
        language = (language or "").strip() or "zh-CN"
        safe_content_types = (
            list(DEFAULT_WEB_SEARCH_CONTENT_TYPES)
            if content_types is None
            else content_types
        )

        if provider not in VALID_WEB_SEARCH_PROVIDERS:
            raise ValueError(f"Unsupported web search provider: {provider}")
        if mode not in VALID_WEB_SEARCH_MODES:
            raise ValueError(f"Unsupported web search mode: {mode}")
        if zone not in VALID_WEB_SEARCH_ZONES:
            raise ValueError(f"Unsupported web search zone: {zone}")
        if not isinstance(max_results, int) or max_results < 1 or max_results > 10:
            raise ValueError("max_results must be between 1 and 10")
        if (
            not isinstance(safe_content_types, list)
            or not safe_content_types
            or any(item not in VALID_WEB_SEARCH_CONTENT_TYPES for item in safe_content_types)
        ):
            raise ValueError("content_types must be a non-empty subset of web/news")

        return {
            "provider": provider,
            "mode": mode,
            "zone": zone,
            "language": language,
            "max_results": max_results,
            "content_types": safe_content_types,
        }
