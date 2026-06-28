import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_auth
from app.models.database import get_db
from app.services.litellm_adapter import LiteLLMAdapter
from app.services.model_settings_service import (
    ModelSettingsService,
    _sanitize_provider_error,
    _unprotect_api_key,
)
from app.services.ocr_engines.openai_compatible_adapter import OpenAICompatibleOCRAdapter
from app.services.ocr_engines.paddleocr_job_adapter import PaddleOCRJobAdapter
from app.services.ocr_settings_service import OCRSettingsService
from app.services.runtime_settings_service import runtime_settings_service
from app.services.user_runtime_settings_service import UserRuntimeSettingsService
from app.services.web_search_settings_service import WebSearchSettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class PageIndexModeUpdate(BaseModel):
    pageindex_mode: str


class QASettingsUpdate(BaseModel):
    qa_thinking_mode: str


class ModelProviderConfigIn(BaseModel):
    provider: str
    base_url: str
    api_key: str


class ModelProviderUpdateIn(BaseModel):
    provider: str
    base_url: str
    api_key: str | None = None


class ModelProviderTestIn(BaseModel):
    model: str | None = None


class ModelRouteIn(BaseModel):
    route_slot: str
    provider_id: str
    model: str
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_responses_api: bool = False


class ModelRoutesUpdate(BaseModel):
    routes: list[ModelRouteIn]


class OCREngineProfileIn(BaseModel):
    name: str
    engine_type: str
    provider: str
    endpoint: str
    model: str
    api_key: str
    capabilities: list[str]
    options: dict = {}
    is_default: bool = False


class OCREngineProfileUpdateIn(BaseModel):
    name: str
    engine_type: str
    provider: str
    endpoint: str
    model: str
    api_key: str | None = None
    capabilities: list[str]
    options: dict = {}
    is_default: bool = False


class OCREngineTestIn(BaseModel):
    task: str = "page_text"
    image_url: str = "data:image/png;base64,"
    options: dict = {}


class OCRRoutesUpdate(BaseModel):
    routes: dict[str, str | None]


class WebSearchSettingsUpdate(BaseModel):
    provider: str = "anysearch"
    mode: str = "on-demand"
    api_key: str | None = None
    zone: str = "cn"
    language: str = "zh-CN"
    max_results: int = 5
    content_types: list[str] = Field(default_factory=lambda: ["web", "news"])


def _model_settings_service(db: aiosqlite.Connection) -> ModelSettingsService:
    return ModelSettingsService(db)


def _ocr_settings_service(db: aiosqlite.Connection) -> OCRSettingsService:
    return OCRSettingsService(db)


def _web_search_settings_service(db: aiosqlite.Connection) -> WebSearchSettingsService:
    return WebSearchSettingsService(db)


def _user_runtime_settings_service(
    db: aiosqlite.Connection,
) -> UserRuntimeSettingsService:
    return UserRuntimeSettingsService(db)


@router.get("/pageindex")
async def get_pageindex_settings(_current_user: dict = Depends(require_auth)):
    return runtime_settings_service.get_settings()


@router.put("/pageindex")
async def update_pageindex_settings(
    payload: PageIndexModeUpdate,
    _current_user: dict = Depends(require_auth),
):
    try:
        return runtime_settings_service.update_pageindex_mode(payload.pageindex_mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/qa")
async def get_qa_settings(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    settings = await _user_runtime_settings_service(db).get_settings(current_user["id"])
    return {"qa_thinking_mode": settings["qa_thinking_mode"]}


@router.put("/qa")
async def update_qa_settings(
    payload: QASettingsUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    try:
        settings = await _user_runtime_settings_service(db).update_qa_thinking_mode(
            current_user["id"],
            payload.qa_thinking_mode,
        )
        return {"qa_thinking_mode": settings["qa_thinking_mode"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/web-search")
async def get_web_search_settings(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _web_search_settings_service(db)
    return await service.get_settings(current_user["id"])


@router.put("/web-search")
async def update_web_search_settings(
    payload: WebSearchSettingsUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _web_search_settings_service(db)
    try:
        return await service.save_settings(
            user_id=current_user["id"],
            provider=payload.provider,
            mode=payload.mode,
            api_key=payload.api_key,
            zone=payload.zone,
            language=payload.language,
            max_results=payload.max_results,
            content_types=payload.content_types,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/model-providers/presets")
async def list_model_provider_presets(_current_user: dict = Depends(require_auth)):
    return ModelSettingsService.provider_presets()


@router.get("/model-providers")
async def list_model_providers(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    return await service.list_provider_configs(current_user["id"])


@router.post("/model-providers")
async def save_model_provider(
    payload: ModelProviderConfigIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    try:
        return await service.save_provider_config(
            user_id=current_user["id"],
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/model-providers/{provider_id}")
async def delete_model_provider(
    provider_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    deleted = await service.delete_provider_config(current_user["id"], provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return {"success": True}


@router.patch("/model-providers/{provider_id}")
async def update_model_provider(
    provider_id: str,
    payload: ModelProviderUpdateIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    try:
        return await service.update_provider_config_fields(
            user_id=current_user["id"],
            provider_id=provider_id,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/model-providers/{provider_id}/test")
async def test_model_provider(
    provider_id: str,
    payload: ModelProviderTestIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    provider = await service._get_provider_config_with_secret(
        current_user["id"], provider_id
    )
    if not provider:
        raise HTTPException(status_code=404, detail="Provider config not found")

    api_key = _unprotect_api_key(provider["api_key_ciphertext"])
    try:
        model = (payload.model or "").strip()
        if not model:
            models_payload = await service.list_provider_models(
                user_id=current_user["id"],
                provider_id=provider_id,
                timeout=5,
            )
            model = str(
                next(
                    (
                        item.get("id")
                        for item in models_payload.get("models", [])
                        if item.get("id")
                    ),
                    "",
                )
            ).strip()
        if not model:
            raise ValueError("No available model returned by provider")
        provider_config = {
            "provider": provider["provider"],
            "base_url": provider["base_url"],
            "api_key": api_key,
            "model": model,
        }
        await LiteLLMAdapter().acompletion(
            provider_config=provider_config,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
            timeout=5,
        )
        await service.update_provider_validation_status(
            user_id=current_user["id"],
            provider_id=provider_id,
            validation_status="valid",
        )
        return {"success": True, "tested_model": model}
    except Exception as exc:
        await service.update_provider_validation_status(
            user_id=current_user["id"],
            provider_id=provider_id,
            validation_status="invalid",
        )
        raise HTTPException(status_code=400, detail=_sanitize_provider_error(exc, api_key))


@router.get("/model-providers/{provider_id}/models")
async def list_model_provider_models(
    provider_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    try:
        return await service.list_provider_models(
            user_id=current_user["id"],
            provider_id=provider_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/model-routes")
async def list_model_routes(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    return await service.list_route_mappings(current_user["id"])


@router.put("/model-routes")
async def save_model_routes(
    payload: ModelRoutesUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _model_settings_service(db)
    saved = []
    try:
        for route in payload.routes:
            saved.append(
                await service.save_route_mapping(
                    user_id=current_user["id"],
                    route_slot=route.route_slot,
                    provider_id=route.provider_id,
                    model=route.model,
                    supports_streaming=route.supports_streaming,
                    supports_tool_calling=route.supports_tool_calling,
                    supports_vision=route.supports_vision,
                    supports_structured_output=route.supports_structured_output,
                    supports_responses_api=route.supports_responses_api,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return saved


@router.get("/ocr-engines")
async def list_ocr_engines(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    return await service.list_profiles(current_user["id"])


@router.post("/ocr-engines")
async def save_ocr_engine(
    payload: OCREngineProfileIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    try:
        return await service.save_profile(
            user_id=current_user["id"],
            name=payload.name,
            engine_type=payload.engine_type,
            provider=payload.provider,
            endpoint=payload.endpoint,
            model=payload.model,
            api_key=payload.api_key,
            capabilities=payload.capabilities,
            options=payload.options,
            is_default=payload.is_default,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/ocr-engines/{profile_id}")
async def update_ocr_engine(
    profile_id: str,
    payload: OCREngineProfileUpdateIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    try:
        return await service.update_profile(
            user_id=current_user["id"],
            profile_id=profile_id,
            name=payload.name,
            engine_type=payload.engine_type,
            provider=payload.provider,
            endpoint=payload.endpoint,
            model=payload.model,
            api_key=payload.api_key or None,
            capabilities=payload.capabilities,
            options=payload.options,
            is_default=payload.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/ocr-engines/{profile_id}")
async def delete_ocr_engine(
    profile_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    deleted = await service.delete_profile(current_user["id"], profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OCR profile not found")
    return {"success": True}


@router.post("/ocr-engines/{profile_id}/test")
async def test_ocr_engine(
    profile_id: str,
    payload: OCREngineTestIn,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    profile = await service._get_profile_with_secret(current_user["id"], profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="OCR profile not found")
    try:
        api_key = _unprotect_api_key(profile["api_key_ciphertext"])
        if profile["engine_type"] == "paddleocr_job":
            adapter = PaddleOCRJobAdapter(
                token=api_key,
                job_url=profile["endpoint"],
                model=profile["model"],
                optional_payload=payload.options or None,
            )
        elif profile["engine_type"] == "openai_compatible_ocr":
            adapter = OpenAICompatibleOCRAdapter(
                api_key=api_key,
                base_url=profile["endpoint"],
                model=profile["model"],
            )
        else:
            raise ValueError(f"Unsupported OCR engine type: {profile['engine_type']}")
        result = adapter.recognize(payload.image_url, task=payload.task, options=payload.options)
        if hasattr(result, "__await__"):
            await result
        return {"success": True}
    except Exception as exc:
        message = str(exc).replace(_unprotect_api_key(profile["api_key_ciphertext"]), "[redacted-api-key]")
        raise HTTPException(status_code=400, detail=message)


@router.get("/ocr-routes")
async def list_ocr_routes(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    return await service.list_task_overrides(current_user["id"])


@router.put("/ocr-routes")
async def save_ocr_routes(
    payload: OCRRoutesUpdate,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    service = _ocr_settings_service(db)
    try:
        return await service.save_task_overrides(current_user["id"], payload.routes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
