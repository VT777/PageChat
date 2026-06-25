from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
import aiosqlite
import asyncio
import uuid

from app.core.config import CHAT_ATTACHMENTS_DIR
from app.models.database import get_db, DB_PATH
from app.models.schemas import ChatRequest
from app.services.chat_attachment_service import ChatAttachmentService
from app.services.chat_service import ChatService
from app.api.auth import require_auth

router = APIRouter(prefix="/api/chat", tags=["chat"])

_RUN_TASKS = set()


@router.post("/attachments")
async def upload_chat_attachment(
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Upload an image attachment for a draft chat message."""
    try:
        data = await file.read()
        service = ChatAttachmentService(db, storage_dir=CHAT_ATTACHMENTS_DIR)
        return await service.save_upload(
            user_id=current_user["id"],
            filename=file.filename or "image",
            content_type=file.content_type or "",
            data=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/attachments/{attachment_id}/content")
async def get_chat_attachment_content(
    attachment_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Return image bytes for authenticated UI previews."""
    service = ChatAttachmentService(db, storage_dir=CHAT_ATTACHMENTS_DIR)
    try:
        metadata = await service.get_attachment(current_user["id"], attachment_id)
        path = await service.content_path_for_user(current_user["id"], attachment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="附件不存在或无权访问") from exc
    return FileResponse(path, media_type=metadata["mime_type"])


@router.delete("/attachments/{attachment_id}")
async def delete_chat_attachment(
    attachment_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Delete an uploaded attachment before it is bound to a message."""
    service = ChatAttachmentService(db, storage_dir=CHAT_ATTACHMENTS_DIR)
    try:
        deleted = await service.delete_unbound_attachment(
            current_user["id"], attachment_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="附件不存在或无权访问") from exc
    if not deleted:
        raise HTTPException(status_code=409, detail="附件已绑定到消息，不能删除")
    return {"success": True}


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: dict = Depends(require_auth),
):
    """流式问答接口（仅当前用户）"""

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    stream_state = {"active": True}
    run_id = uuid.uuid4().hex[:16]

    async def producer():
        try:
            async with aiosqlite.connect(str(DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                chat_service = ChatService(db)
                async for event in chat_service.stream_chat(
                    question=request.question,
                    document_ids=request.document_ids,
                    folder_id=request.folder_id,
                    include_subfolders=request.include_subfolders,
                    strict_scope=request.strict_scope,
                    conversation_id=request.conversation_id,
                    web_search=request.web_search,
                    attachment_ids=request.attachment_ids,
                    user_id=current_user["id"],
                ):
                    if stream_state["active"]:
                        await queue.put(event)
        except Exception as e:
            if stream_state["active"]:
                error_event = f'event: content\ndata: {{"content": "抱歉，处理请求时发生错误：{str(e).replace('"', '\\"')}"}}\n\n'
                await queue.put(error_event)
        finally:
            if stream_state["active"]:
                await queue.put(None)

    task = asyncio.create_task(producer(), name=f"chat-run-{run_id}")
    _RUN_TASKS.add(task)
    task.add_done_callback(_RUN_TASKS.discard)

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        except asyncio.CancelledError:
            stream_state["active"] = False
            raise
        finally:
            stream_state["active"] = False

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def list_conversations(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取会话列表（仅当前用户）"""
    cursor = await db.execute(
        "SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC",
        (current_user["id"],),
    )
    rows = await cursor.fetchall()
    return [{"id": row[0], "title": row[1], "created_at": row[2]} for row in rows]


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取会话消息（仅当前用户）"""
    cursor = await db.execute(
        "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, current_user["id"]),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    cursor = await db.execute(
        "SELECT id, role, content, thinking_content, sources, agent_steps, status, attachments_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at, id",
        (conversation_id,),
    )
    rows = await cursor.fetchall()

    import json

    messages = []
    for row in rows:
        messages.append(
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "thinking": row[3] or "",
                "sources": json.loads(row[4]) if row[4] else [],
                "agent_steps": json.loads(row[5]) if row[5] else [],
                "status": row[6] or "completed",
                "attachments": json.loads(row[7]) if row[7] else [],
                "created_at": row[8],
            }
        )

    return messages
