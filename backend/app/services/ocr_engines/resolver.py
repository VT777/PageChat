"""Resolve configured OCR engines for PageIndex OCR tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core import config
from app.services.ocr_settings_service import OCRSettingsService, OCR_TASKS, ocr_task_default_route

from .contracts import OCRTask
from .openai_compatible_adapter import OpenAICompatibleOCRAdapter
from .paddleocr_job_adapter import PaddleOCRJobAdapter


@dataclass(frozen=True)
class ResolvedOCREngine:
    task: OCRTask
    route: Dict[str, Any]
    adapter: Any


class OCREngineResolver:
    def __init__(self, *, settings_service: OCRSettingsService):
        self.settings_service = settings_service

    async def resolve(
        self,
        user_id: Optional[str],
        task: OCRTask,
        *,
        profile_id: Optional[str] = None,
    ) -> ResolvedOCREngine:
        if task not in OCR_TASKS:
            raise ValueError(f"Unsupported OCR task: {task}")
        if profile_id:
            route = await self._resolve_explicit_profile(user_id, profile_id)
        elif user_id:
            route = await self.settings_service.resolve_task(user_id, task)
        else:
            route = _env_route(task)
        _ensure_capability(route, task)
        return ResolvedOCREngine(task=task, route=route, adapter=_build_adapter(route))

    async def _resolve_explicit_profile(self, user_id: Optional[str], profile_id: str) -> Dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required for explicit OCR profile resolution")
        profile = await self.settings_service._get_profile_with_secret(user_id, profile_id)
        if not profile:
            raise ValueError("OCR profile not found")
        route = dict(profile)
        if "api_key" not in route and "api_key_ciphertext" in route:
            route["api_key"] = _decrypt_profile_key(profile)
        route["capabilities"] = _json_loads(
            route.get("capabilities_json", route.get("capabilities")), default=[]
        )
        route["options"] = _json_loads(route.get("options_json", route.get("options")), default={})
        route["source"] = "explicit_profile"
        route.pop("api_key_ciphertext", None)
        route.pop("capabilities_json", None)
        route.pop("options_json", None)
        return route


def _decrypt_profile_key(profile: Dict[str, Any]) -> str:
    from app.services.model_settings_service import _unprotect_api_key

    return _unprotect_api_key(profile["api_key_ciphertext"])


def _ensure_capability(route: Dict[str, Any], task: OCRTask) -> None:
    capabilities = set(route.get("capabilities") or [])
    if task not in capabilities:
        raise ValueError(f"OCR engine lacks capability for task: {task}")


def _build_adapter(route: Dict[str, Any]) -> Any:
    engine_type = route.get("engine_type")
    options = dict(route.get("options") or {})
    if engine_type == "paddleocr_job":
        return PaddleOCRJobAdapter(
            token=route.get("api_key") or "",
            job_url=route.get("endpoint") or config.OCR_PADDLEOCR_JOB_URL,
            model=route.get("model") or config.OCR_PADDLEOCR_MODEL,
            optional_payload=options or None,
            profile_id=route.get("profile_id"),
            profile_version=route.get("profile_version"),
        )
    if engine_type == "openai_compatible_ocr":
        return OpenAICompatibleOCRAdapter(
            api_key=route.get("api_key") or "",
            base_url=route.get("endpoint") or config.OCR_OPENAI_BASE_URL,
            model=route.get("model") or config.OCR_OPENAI_MODEL,
            profile_id=route.get("profile_id"),
            profile_version=route.get("profile_version"),
        )
    raise ValueError(f"Unsupported OCR engine type: {engine_type}")


def _env_route(task: OCRTask) -> Dict[str, Any]:
    return ocr_task_default_route(task)


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    import json

    try:
        return json.loads(value)
    except Exception:
        return default
