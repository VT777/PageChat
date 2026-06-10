import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_auth
from app.models.database import get_db
from app.services.litellm_adapter import LiteLLMAdapter
from app.services.model_settings_service import ModelSettingsService, _unprotect_api_key
from app.services.runtime_settings_service import runtime_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class PageIndexModeUpdate(BaseModel):
    pageindex_mode: str


class ModelProviderConfigIn(BaseModel):
    provider: str
    base_url: str
    api_key: str


class ModelProviderTestIn(BaseModel):
    model: str


class ModelRouteIn(BaseModel):
    route_slot: str
    provider_id: str
    model: str
    supports_vision: bool = False


class ModelRoutesUpdate(BaseModel):
    routes: list[ModelRouteIn]


def _model_settings_service(db: aiosqlite.Connection) -> ModelSettingsService:
    return ModelSettingsService(db)


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

    try:
        provider_config = {
            "provider": provider["provider"],
            "base_url": provider["base_url"],
            "api_key": _unprotect_api_key(provider["api_key_ciphertext"]),
            "model": payload.model,
        }
        await LiteLLMAdapter().acompletion(
            provider_config=provider_config,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
            timeout=5,
        )
        return {"success": True}
    except Exception as exc:
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
                    supports_vision=route.supports_vision,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return saved
