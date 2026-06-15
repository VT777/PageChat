"""Persistence and resolution for user-configured OCR engine profiles."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Optional

import aiosqlite

from app.core import config
from app.services.model_settings_service import (
    _protect_api_key,
    _unprotect_api_key,
    mask_api_key,
)


OCR_TASKS = {"toc_page", "page_text"}


class OCRSettingsService:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def save_profile(
        self,
        *,
        user_id: str,
        name: str,
        engine_type: str,
        provider: str,
        endpoint: str,
        model: str,
        api_key: str,
        capabilities: list[str],
        options: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
        profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not api_key:
            raise ValueError("api_key is required")
        return await self._upsert_profile(
            user_id=user_id,
            profile_id=profile_id,
            name=name,
            engine_type=engine_type,
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key_ciphertext=_protect_api_key(api_key),
            api_key_mask=mask_api_key(api_key),
            capabilities=capabilities,
            options=options or {},
            is_default=is_default,
        )

    async def update_profile(
        self,
        *,
        user_id: str,
        profile_id: str,
        name: str,
        engine_type: str,
        provider: str,
        endpoint: str,
        model: str,
        capabilities: list[str],
        options: Optional[Dict[str, Any]] = None,
        is_default: bool = False,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = await self._get_profile_with_secret(user_id, profile_id)
        if not existing:
            raise ValueError("OCR profile not found")
        api_key_ciphertext = existing["api_key_ciphertext"]
        api_key_mask = existing["api_key_mask"]
        if api_key:
            api_key_ciphertext = _protect_api_key(api_key)
            api_key_mask = mask_api_key(api_key)
        return await self._upsert_profile(
            user_id=user_id,
            profile_id=profile_id,
            name=name,
            engine_type=engine_type,
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key_ciphertext=api_key_ciphertext,
            api_key_mask=api_key_mask,
            capabilities=capabilities,
            options=options or {},
            is_default=is_default,
        )

    async def _upsert_profile(
        self,
        *,
        user_id: str,
        profile_id: Optional[str],
        name: str,
        engine_type: str,
        provider: str,
        endpoint: str,
        model: str,
        api_key_ciphertext: str,
        api_key_mask: str,
        capabilities: list[str],
        options: Dict[str, Any],
        is_default: bool,
    ) -> Dict[str, Any]:
        _validate_profile(user_id, name, engine_type, provider, endpoint, model, capabilities)
        profile_id = profile_id or str(uuid.uuid4())
        cursor = await self.db.execute(
            "SELECT user_id FROM ocr_engine_profiles WHERE profile_id = ?",
            (profile_id,),
        )
        existing = await cursor.fetchone()
        if existing and existing["user_id"] != user_id:
            raise ValueError("OCR profile not found")

        normalized_capabilities = _normalize_capabilities(capabilities)
        options_json = _json_dumps(options)
        capabilities_json = _json_dumps(normalized_capabilities)
        profile_version = _profile_version(
            engine_type, provider, endpoint, model, capabilities_json, options_json
        )

        if is_default:
            await self.db.execute(
                "UPDATE ocr_engine_profiles SET is_default = 0 WHERE user_id = ?",
                (user_id,),
            )
        await self.db.execute(
            """
            INSERT INTO ocr_engine_profiles (
                profile_id, user_id, name, engine_type, provider, endpoint, model,
                api_key_ciphertext, api_key_mask, capabilities_json, options_json,
                profile_version, is_default, validation_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'untested', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(profile_id) DO UPDATE SET
                name = excluded.name,
                engine_type = excluded.engine_type,
                provider = excluded.provider,
                endpoint = excluded.endpoint,
                model = excluded.model,
                api_key_ciphertext = excluded.api_key_ciphertext,
                api_key_mask = excluded.api_key_mask,
                capabilities_json = excluded.capabilities_json,
                options_json = excluded.options_json,
                profile_version = excluded.profile_version,
                is_default = excluded.is_default,
                validation_status = 'untested',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                profile_id,
                user_id,
                name,
                engine_type,
                provider,
                endpoint,
                model,
                api_key_ciphertext,
                api_key_mask,
                capabilities_json,
                options_json,
                profile_version,
                int(is_default),
            ),
        )
        await self.db.commit()
        return await self.get_profile(user_id, profile_id) or {}

    async def list_profiles(self, user_id: str) -> list[Dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT profile_id, user_id, name, engine_type, provider, endpoint, model,
                   api_key_mask, capabilities_json, options_json, profile_version,
                   is_default, validation_status, created_at, updated_at
            FROM ocr_engine_profiles
            WHERE user_id = ?
            ORDER BY is_default DESC, updated_at DESC, created_at DESC
            """,
            (user_id,),
        )
        return [_public_profile(dict(row)) for row in await cursor.fetchall()]

    async def get_profile(self, user_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
        row = await self._get_profile_row(user_id, profile_id)
        return _public_profile(dict(row)) if row else None

    async def delete_profile(self, user_id: str, profile_id: str) -> bool:
        await self.db.execute(
            "DELETE FROM ocr_task_overrides WHERE user_id = ? AND profile_id = ?",
            (user_id, profile_id),
        )
        cursor = await self.db.execute(
            "DELETE FROM ocr_engine_profiles WHERE user_id = ? AND profile_id = ?",
            (user_id, profile_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def save_task_overrides(self, user_id: str, overrides: Dict[str, Optional[str]]) -> list[Dict[str, Any]]:
        for task, profile_id in overrides.items():
            if task not in OCR_TASKS:
                raise ValueError(f"Unsupported OCR task: {task}")
            if not profile_id:
                await self.db.execute(
                    "DELETE FROM ocr_task_overrides WHERE user_id = ? AND task = ?",
                    (user_id, task),
                )
                continue
            if not await self._get_profile_row(user_id, profile_id):
                raise ValueError("OCR profile not found")
            await self.db.execute(
                """
                INSERT INTO ocr_task_overrides (user_id, task, profile_id, created_at, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, task) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, task, profile_id),
            )
        await self.db.commit()
        return await self.list_task_overrides(user_id)

    async def list_task_overrides(self, user_id: str) -> list[Dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT user_id, task, profile_id, created_at, updated_at
            FROM ocr_task_overrides
            WHERE user_id = ?
            ORDER BY task
            """,
            (user_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def resolve_task(self, user_id: Optional[str], task: str) -> Dict[str, Any]:
        if task not in OCR_TASKS:
            raise ValueError(f"Unsupported OCR task: {task}")
        if user_id:
            override = await self._profile_for_task_override(user_id, task)
            if override:
                return _resolved_profile(override, source="task_override")
            default = await self._default_profile(user_id)
            if default:
                return _resolved_profile(default, source="default_profile")
        return _environment_fallback(task)

    async def _profile_for_task_override(self, user_id: str, task: str) -> Optional[Dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT p.*
            FROM ocr_task_overrides o
            JOIN ocr_engine_profiles p ON p.profile_id = o.profile_id
            WHERE o.user_id = ? AND o.task = ? AND p.user_id = ?
            """,
            (user_id, task, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def _default_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT * FROM ocr_engine_profiles
            WHERE user_id = ? AND is_default = 1
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def _get_profile_row(self, user_id: str, profile_id: str):
        cursor = await self.db.execute(
            "SELECT * FROM ocr_engine_profiles WHERE user_id = ? AND profile_id = ?",
            (user_id, profile_id),
        )
        return await cursor.fetchone()

    async def _get_profile_with_secret(self, user_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
        row = await self._get_profile_row(user_id, profile_id)
        return dict(row) if row else None


def _validate_profile(
    user_id: str,
    name: str,
    engine_type: str,
    provider: str,
    endpoint: str,
    model: str,
    capabilities: list[str],
) -> None:
    for field_name, value in {
        "user_id": user_id,
        "name": name,
        "engine_type": engine_type,
        "provider": provider,
        "endpoint": endpoint,
        "model": model,
    }.items():
        if not str(value or "").strip():
            raise ValueError(f"{field_name} is required")
    if not _normalize_capabilities(capabilities):
        raise ValueError("capabilities are required")


def _normalize_capabilities(capabilities: list[str]) -> list[str]:
    normalized = sorted({capability for capability in capabilities if capability in OCR_TASKS})
    return normalized


def _public_profile(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    result["capabilities"] = json.loads(result.pop("capabilities_json") or "[]")
    result["options"] = json.loads(result.pop("options_json") or "{}")
    result["is_default"] = bool(result["is_default"])
    result.pop("api_key_ciphertext", None)
    return result


def _resolved_profile(row: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    public = _public_profile(row)
    public["api_key"] = _unprotect_api_key(row["api_key_ciphertext"])
    public["source"] = source
    return public


def _environment_fallback(task: str) -> Dict[str, Any]:
    engine_type = getattr(config, "OCR_DEFAULT_ENGINE_TYPE", "openai_compatible_ocr")
    endpoint = getattr(config, "OCR_BASE_URL", "")
    model = getattr(config, "OCR_MODEL", "")
    provider = "environment"
    return {
        "profile_id": None,
        "user_id": None,
        "name": "Environment OCR",
        "engine_type": engine_type,
        "provider": provider,
        "endpoint": endpoint,
        "model": model,
        "api_key": getattr(config, "OCR_API_KEY", ""),
        "api_key_mask": mask_api_key(getattr(config, "OCR_API_KEY", "")),
        "capabilities": [task],
        "options": {},
        "profile_version": _profile_version(engine_type, provider, endpoint, model, task, "{}"),
        "is_default": False,
        "validation_status": "environment",
        "source": "environment",
    }


def _profile_version(*parts: str) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

