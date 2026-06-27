from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
import aiosqlite
import asyncio
import uuid

from app.core.config import CHAT_ATTACHMENTS_DIR
from app.models.database import get_db, DB_PATH
from app.models.schemas import ChatRequest
from app.services.chat_attachment_service import ChatAttachmentService
from app.services.chat_run_repository import ChatRunRepository
from app.services.chat_service import ChatService
from app.api.auth import require_auth
from app.agent.events import PageChatEventEmitter, sse_frame, utc_now_iso

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
                    web_search_requested=request.web_search_requested,
                    web_search_enabled=request.web_search_enabled,
                    conversation_id=request.conversation_id,
                    web_search=request.web_search,
                    attachment_ids=request.attachment_ids,
                    user_id=current_user["id"],
                ):
                    if stream_state["active"]:
                        await queue.put(event)
        except Exception as e:
            if stream_state["active"]:
                error_message = str(e)
                try:
                    async with aiosqlite.connect(str(DB_PATH)) as db:
                        db.row_factory = aiosqlite.Row
                        chat_service = ChatService(db)
                        repository = ChatRunRepository(db)
                        conversation_id = await chat_service.ensure_conversation(
                            request.conversation_id,
                            user_id=current_user["id"],
                        )
                        transport_run_id = f"run_{run_id}"
                        user_message_id = await repository.create_user_message(
                            conversation_id,
                            request.question,
                        )
                        assistant_message_id = await repository.create_assistant_placeholder(
                            conversation_id,
                            transport_run_id,
                        )
                        await repository.create_run(
                            run_id=transport_run_id,
                            conversation_id=conversation_id,
                            user_message_id=user_message_id,
                            assistant_message_id=assistant_message_id,
                            protocol="transport",
                        )
                        emitter = PageChatEventEmitter(
                            run_id=transport_run_id,
                            conversation_id=conversation_id,
                            message_id=assistant_message_id,
                        )
                        event_type, payload = emitter.build(
                            "run_failed",
                            {"status": "failed", "error": error_message},
                        )
                        await repository.append_run_event(
                            transport_run_id,
                            event_type,
                            payload,
                        )
                        await repository.fail_run(transport_run_id, error_message)
                        await queue.put(sse_frame(event_type, payload))
                except Exception:
                    await queue.put(
                        sse_frame(
                            "run_failed",
                            {
                                "run_id": f"transport_{run_id}",
                                "conversation_id": request.conversation_id or "transport_error",
                                "message_id": "transport_error",
                                "seq": 1,
                                "ts": utc_now_iso(),
                                "status": "failed",
                                "error": error_message,
                            },
                        )
                    )
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
            if not task.done():
                task.cancel()
            raise
        finally:
            stream_state["active"] = False
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    after_seq: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Replay persisted PageChat run events owned by the current user."""
    cursor = await db.execute(
        """
        SELECT r.id
        FROM agent_runs r
        JOIN conversations c ON c.id = r.conversation_id
        WHERE r.id = ? AND c.user_id = ?
        """,
        (run_id, current_user["id"]),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="run not found")

    return await ChatRunRepository(db).list_run_events(run_id, after_seq=after_seq)


@router.get("/conversations")
async def list_conversations(
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取会话列表（仅当前用户）"""
    cursor = await db.execute(
        """
        SELECT id, title, created_at, updated_at
        FROM conversations
        WHERE user_id = ?
        ORDER BY updated_at DESC, created_at DESC
        """,
        (current_user["id"],),
    )
    rows = await cursor.fetchall()
    return [
        {"id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3]}
        for row in rows
    ]


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

    return await ChatRunRepository(db).list_messages(conversation_id)


@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Export one owned conversation with ordered messages."""
    cursor = await db.execute(
        """
        SELECT id, title, created_at, updated_at
        FROM conversations
        WHERE id = ? AND user_id = ?
        """,
        (conversation_id, current_user["id"]),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="浼氳瘽涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")

    return {
        "conversation": {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
        },
        "messages": await ChatRunRepository(db).list_messages(conversation_id),
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """Delete one owned conversation and its durable run data."""
    cursor = await db.execute(
        "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, current_user["id"]),
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="浼氳瘽涓嶅瓨鍦ㄦ垨鏃犳潈璁块棶")

    await db.execute(
        """
        DELETE FROM message_citations
        WHERE message_id IN (
            SELECT id FROM messages WHERE conversation_id = ?
        )
        """,
        (conversation_id,),
    )
    await db.execute(
        """
        DELETE FROM agent_run_events
        WHERE run_id IN (
            SELECT id FROM agent_runs WHERE conversation_id = ?
        )
        """,
        (conversation_id,),
    )
    await db.execute(
        "DELETE FROM conversation_evidence WHERE conversation_id = ?",
        (conversation_id,),
    )
    await db.execute(
        "DELETE FROM agent_runs WHERE conversation_id = ?",
        (conversation_id,),
    )
    await db.execute(
        "DELETE FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    )
    await db.execute(
        "DELETE FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    await db.commit()
    return {"success": True}
