from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_auth
from app.services.runtime_settings_service import runtime_settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class PageIndexModeUpdate(BaseModel):
    pageindex_mode: str


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
