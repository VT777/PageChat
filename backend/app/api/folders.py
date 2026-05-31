from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import aiosqlite

from app.models.database import get_db
from app.models.schemas import (
    FolderResponse,
    FolderCreate,
    FolderListResponse,
    FolderTreeResponse,
)
from app.services.folder_service import FolderService
from app.api.auth import require_auth

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.post("", response_model=FolderResponse)
async def create_folder(
    folder_data: FolderCreate,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """创建文件夹（仅当前用户）"""
    service = FolderService(db)
    try:
        return await service.create_folder(
            folder_data.name, folder_data.parent_id, user_id=current_user["id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tree", response_model=List[FolderTreeResponse])
async def get_folder_tree(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文件夹树形结构（仅当前用户）"""
    service = FolderService(db)
    return await service.get_folder_tree(user_id=current_user["id"])


@router.get("", response_model=FolderListResponse)
async def list_folders(
    parent_id: Optional[str] = Query(None, description="父文件夹ID，null表示根目录"),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """列出文件夹（平级，仅当前用户）"""
    service = FolderService(db)
    items = await service.list_folders(parent_id, user_id=current_user["id"])
    return FolderListResponse(items=items, total=len(items))


@router.get("/{folder_id}", response_model=FolderResponse)
async def get_folder(
    folder_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取单个文件夹信息（仅当前用户）"""
    service = FolderService(db)
    folder = await service.get_folder(folder_id, user_id=current_user["id"])
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return folder


@router.put("/{folder_id}", response_model=FolderResponse)
async def rename_folder(
    folder_id: str,
    folder_data: FolderCreate,  # 只使用 name 字段
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """重命名文件夹（仅当前用户）"""
    service = FolderService(db)
    try:
        return await service.rename_folder(
            folder_id, folder_data.name, user_id=current_user["id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{folder_id}/move", response_model=FolderResponse)
async def move_folder(
    folder_id: str,
    parent_id: Optional[str] = Query(
        None, description="新父文件夹ID，省略或null表示移动到根目录"
    ),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """移动文件夹（仅当前用户）"""
    service = FolderService(db)
    try:
        # Convert string "null" to Python None
        actual_parent_id = None if parent_id in (None, "null", "") else parent_id
        return await service.move_folder(
            folder_id, actual_parent_id, user_id=current_user["id"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """删除文件夹（递归删除，仅当前用户）"""
    service = FolderService(db)
    success = await service.delete_folder(folder_id, user_id=current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"message": "删除成功"}


@router.get("/{folder_id}/contents")
async def get_folder_contents(
    folder_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文件夹内容（子文件夹 + 文档，仅当前用户）"""
    service = FolderService(db)
    items, total = await service.get_folder_contents(
        folder_id if folder_id != "root" else None,
        page,
        page_size,
        user_id=current_user["id"],
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
