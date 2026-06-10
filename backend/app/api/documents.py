import json
import os
import re
import sqlite3
import threading
import traceback
import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional, Literal
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import zipfile
import io
from pydantic import BaseModel
import aiosqlite

from app.models.database import get_db
from app.models.schemas import DocumentResponse, DocumentListResponse, ProcessingStepsResponse, ProcessingStep
from app.services.document_service import DocumentService
from app.services.pageindex_service import PageIndexService
from app.core.config import (
    DATA_DIR,
    INDEXES_DIR,
    PAGEINDEX_MAX_INDEX_SECONDS,
    PAGEINDEX_MAX_CONCURRENT_JOBS,
    PAGEINDEX_QUEUE_ENABLED,
    INDEXING_STUCK_THRESHOLD_MINUTES,
)
from app.api.auth import require_auth

router = APIRouter(prefix="/api/documents", tags=["documents"])

INDEX_TIMEOUT_SECONDS = 60 * 30

_search_rebuild_lock = threading.Lock()
_search_rebuild_running = False
_search_rebuild_pending = False

_index_queue_lock = threading.Lock()
_index_queue_condition = threading.Condition(_index_queue_lock)
_index_queue: list[tuple[str, str, Optional[str]]] = []
_index_worker_started = False
_index_running_jobs = 0
_index_queue_generation = 0


class ReindexRequest(BaseModel):
    mode: Literal["smart", "fast", "balanced"] = "smart"


def _build_toc_from_index(index_data: Optional[dict]) -> List[dict]:
    if not index_data:
        return []

    structure = index_data.get("structure", index_data)

    def extract_toc(nodes: List[dict], level: int = 0) -> List[dict]:
        result: List[dict] = []
        for node in nodes:
            source_anchor: dict[str, Any] = (
                node.get("source_anchor")
                if isinstance(node.get("source_anchor"), dict)
                else {}
            )
            toc_item = {
                "node_id": node.get("node_id", ""),
                "title": node.get("title", ""),
                "level": level,
                "structure": node.get("structure", ""),
                "summary": (node.get("summary", "") or "")[:200],
                "start_page": source_anchor.get("start_page")
                or node.get("start_index"),
                "end_page": source_anchor.get("end_page") or node.get("end_index"),
                "source_anchor": source_anchor,
                "children": [],
            }
            if node.get("nodes"):
                toc_item["children"] = extract_toc(node["nodes"], level + 1)
            result.append(toc_item)
        return result

    if isinstance(structure, list):
        return extract_toc(structure)
    return extract_toc([structure])


def _load_index_meta_brief(index_path: Optional[str]) -> dict:
    if not index_path:
        return {}
    try:
        if not os.path.exists(index_path):
            return {}
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        route = data.get("route_decision")
        if not isinstance(route, dict):
            route = {}
        return {
            "requested_mode": route.get("requested_mode"),
            "execution_mode": route.get("execution_mode"),
            "reasons": route.get("reasons")
            if isinstance(route.get("reasons"), list)
            else [],
        }
    except Exception:
        return {}


def _parse_completion_from_status(status: str) -> str:
    base = str(status or "").split(":")[0]
    if base == "completed":
        return "completed"
    if base == "failed":
        return "failed"
    return "processing"


def _parse_error_code(status: str) -> Optional[str]:
    parts = str(status or "").split(":", 1)
    if len(parts) == 2 and parts[0] == "failed":
        return parts[1]
    return None


def _extract_failure_status_code(error_message: str) -> str:
    message = str(error_message or "")
    if ":" in message:
        prefix = message.split(":", 1)[0].strip()
        if re.fullmatch(r"[A-Z_]+", prefix):
            return prefix.lower()
    return "indexing"


def _calculate_processing_duration(doc: DocumentResponse) -> Optional[float]:
    """计算文档处理用时（秒）
    
    初次上传：updated_at - created_at
    重新解析：updated_at - last_reindex_at
    """
    if doc.status == 'completed' and doc.updated_at:
        try:
            if isinstance(doc.updated_at, str):
                updated = datetime.fromisoformat(doc.updated_at.replace('Z', '+00:00'))
            else:
                updated = doc.updated_at
            
            # 优先使用 last_reindex_at（重新解析开始时间）
            if hasattr(doc, 'last_reindex_at') and doc.last_reindex_at:
                if isinstance(doc.last_reindex_at, str):
                    start = datetime.fromisoformat(doc.last_reindex_at.replace('Z', '+00:00'))
                else:
                    start = doc.last_reindex_at
            elif doc.created_at:
                if isinstance(doc.created_at, str):
                    start = datetime.fromisoformat(doc.created_at.replace('Z', '+00:00'))
                else:
                    start = doc.created_at
            else:
                return None
            
            return (updated - start).total_seconds()
        except Exception:
            return None
    return None


def _attach_parse_meta(doc: DocumentResponse) -> DocumentResponse:
    meta = _load_index_meta_brief(doc.index_path)
    doc.parse_requested_mode = meta.get("requested_mode")
    doc.parse_execution_mode = meta.get("execution_mode")
    doc.parse_reasons = meta.get("reasons") or []
    doc.parse_completion = _parse_completion_from_status(doc.status)
    doc.parse_error_code = _parse_error_code(doc.status)
    doc.processing_duration = _calculate_processing_duration(doc)
    return doc


def _mark_document_failed_sync(
    db_path: str, doc_id: str, status: str, error_message: str
) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute(
            "UPDATE documents SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, error_message, doc_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_document_status_sync(
    db_path: str,
    doc_id: str,
    status: str,
    index_path: Optional[str] = None,
    error_message: Optional[str] = None,
    page_count: Optional[int] = None,
    processed_pages: Optional[int] = None,
):
    """同步更新文档状态（供后台进程使用）"""
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            """
            UPDATE documents
            SET status = ?, index_path = ?, error_message = ?, 
                page_count = COALESCE(?, page_count),
                processed_pages = COALESCE(?, processed_pages)
            WHERE id = ?
            """,
            (status, index_path, error_message, page_count, processed_pages, doc_id),
        )
        conn.commit()


def _update_processed_pages_sync(db_path: str, doc_id: str, processed_pages: int):
    """仅更新处理进度，避免覆盖主流程状态。"""
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            "UPDATE documents SET processed_pages = ? WHERE id = ?",
            (processed_pages, doc_id),
        )
        conn.commit()


def recover_stuck_indexing_tasks_sync(db_path: str):
    """回收长时间卡在 processing 状态的任务。"""
    threshold = INDEXING_STUCK_THRESHOLD_MINUTES
    if threshold <= 0:
        return

    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, index_path, status
            FROM documents
            WHERE status LIKE 'processing:%'
              AND datetime(updated_at) < datetime('now', ?)
            """,
            (f"-{threshold} minutes",),
        ).fetchall()

        for row in rows:
            doc_id = row["id"]
            index_path = row["index_path"]

            if index_path and os.path.exists(index_path):
                description = None
                page_count = None
                try:
                    with open(index_path, "r", encoding="utf-8") as f:
                        index_data = json.load(f)
                    description = index_data.get("doc_description")
                    page_count = index_data.get("page_count")
                except Exception:
                    pass

                conn.execute(
                    """
                    UPDATE documents
                    SET status = 'completed',
                        description = COALESCE(description, ?),
                        page_count = COALESCE(?, page_count),
                        processed_pages = COALESCE(processed_pages, page_count),
                        error_message = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (description, page_count, doc_id),
                )
                print(f"[RECOVER] Marked stuck task as completed: {doc_id}")
            else:
                conn.execute(
                    """
                    UPDATE documents
                    SET status = 'failed:indexing_interrupted',
                        error_message = 'Indexing interrupted: no finalized index output',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (doc_id,),
                )
                print(f"[RECOVER] Marked stuck task as failed: {doc_id}")

        conn.commit()


def _run_index_job(
    doc_id: str, file_path: str, mode_override: Optional[str] = None
) -> None:
    """Run one index job inside its own event loop."""
    if os.name == "nt":
        loop = asyncio.SelectorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _generate_index_async(doc_id, file_path, mode_override=mode_override)
        )
    except Exception as e:
        crash_msg = f"INDEX_RUNTIME_EVENT_LOOP_CRASH: {e}"
        print(f"[INDEX] Runtime crash for {doc_id}: {crash_msg}")
        traceback.print_exc()
        try:
            db_path = str(DATA_DIR / "knowclaw.db")
            _mark_document_failed_sync(
                db_path,
                doc_id,
                "failed:index_runtime_event_loop_crash",
                crash_msg,
            )
        except Exception as write_err:
            print(f"[INDEX] Failed to persist runtime crash status: {write_err}")
    finally:
        loop.close()


def _index_queue_worker(generation: int) -> None:
    """Consume queued index jobs with a process-wide worker limit."""
    global _index_running_jobs

    while True:
        with _index_queue_condition:
            if generation != _index_queue_generation:
                return
            while not _index_queue:
                _index_queue_condition.wait()
                if generation != _index_queue_generation:
                    return
            doc_id, file_path, mode_override = _index_queue.pop(0)
            _index_running_jobs += 1
            _index_queue_condition.notify_all()

        try:
            print(f"[INDEX] Starting queued job for {doc_id}")
            _run_index_job(doc_id, file_path, mode_override=mode_override)
        finally:
            with _index_queue_condition:
                _index_running_jobs = max(0, _index_running_jobs - 1)
                _index_queue_condition.notify_all()


def _ensure_index_queue_worker_started() -> None:
    global _index_worker_started

    with _index_queue_condition:
        if _index_worker_started:
            return
        _index_worker_started = True
        for idx in range(PAGEINDEX_MAX_CONCURRENT_JOBS):
            worker = threading.Thread(
                target=_index_queue_worker,
                args=(_index_queue_generation,),
                name=f"pageindex-queue-worker-{idx + 1}",
                daemon=True,
            )
            worker.start()


def _enqueue_index_job(
    doc_id: str, file_path: str, mode_override: Optional[str] = None
) -> None:
    try:
        _update_document_status_sync(
            str(DATA_DIR / "knowclaw.db"),
            doc_id,
            "processing:queued",
        )
    except Exception as e:
        print(f"[INDEX] Failed to mark {doc_id} as queued: {e}")

    _ensure_index_queue_worker_started()
    with _index_queue_condition:
        _index_queue.append((doc_id, file_path, mode_override))
        queued = len(_index_queue)
        _index_queue_condition.notify_all()
    print(f"[INDEX] Queued index job for {doc_id} (queue={queued})")


def _reset_index_queue_for_tests() -> None:
    global _index_worker_started, _index_running_jobs, _index_queue_generation

    with _index_queue_condition:
        _index_queue.clear()
        _index_running_jobs = 0
        _index_worker_started = False
        _index_queue_generation += 1
        _index_queue_condition.notify_all()


def _wait_for_index_queue_state_for_tests(
    *, running: int, queued: int, timeout: float
) -> bool:
    deadline = datetime.now().timestamp() + timeout
    with _index_queue_condition:
        while True:
            if _index_running_jobs == running and len(_index_queue) == queued:
                return True
            remaining = deadline - datetime.now().timestamp()
            if remaining <= 0:
                return False
            _index_queue_condition.wait(timeout=min(remaining, 0.05))


def start_index_process(
    doc_id: str, file_path: str, mode_override: Optional[str] = None
):
    """启动索引生成（使用线程代替进程避免 Windows spawn 问题）"""
    if PAGEINDEX_QUEUE_ENABLED:
        _enqueue_index_job(doc_id, file_path, mode_override=mode_override)
        return

    import threading

    def run_index():
        """在线程中运行索引"""
        import asyncio

        # Windows 下优先使用 SelectorEventLoop，降低 Proactor 并发网络异常概率
        if os.name == "nt":
            loop = asyncio.SelectorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                _generate_index_async(doc_id, file_path, mode_override=mode_override)
            )
        except Exception as e:
            crash_msg = f"INDEX_RUNTIME_EVENT_LOOP_CRASH: {e}"
            print(f"[INDEX] Runtime crash for {doc_id}: {crash_msg}")
            traceback.print_exc()
            try:
                db_path = str(DATA_DIR / "knowclaw.db")
                _mark_document_failed_sync(
                    db_path,
                    doc_id,
                    "failed:index_runtime_event_loop_crash",
                    crash_msg,
                )
            except Exception as write_err:
                print(f"[INDEX] Failed to persist runtime crash status: {write_err}")
        finally:
            loop.close()

    thread = threading.Thread(target=run_index, daemon=True)
    thread.start()
    print(f"[INDEX] Started thread for {doc_id}")


async def _update_processed_pages(db, doc_id: int, processed_pages: int):
    """更新已处理页数"""
    await db.execute(
        "UPDATE documents SET processed_pages = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (processed_pages, doc_id),
    )
    await db.commit()


async def _generate_index_async(
    doc_id: str, file_path: str, mode_override: Optional[str] = None
):
    """异步生成索引（供线程调用）"""
    import aiosqlite
    import asyncio

    db_path = str(DATA_DIR / "knowclaw.db")
    progress_stop_event = threading.Event()
    progress_thread = None

    async with aiosqlite.connect(db_path) as db:
        try:
            print(f"[INDEX] Starting index for {doc_id}")

            # 更新状态为 queued
            await db.execute(
                "UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("processing:queued", doc_id),
            )
            await db.commit()

            file_suffix = Path(file_path).suffix.lower()

            # 仅对 PDF 预先读取页数（避免对 docx/xlsx 等触发不必要的慢解析）
            total_pages = 0
            if file_suffix == ".pdf":
                try:
                    import pymupdf

                    doc = pymupdf.open(file_path)
                    total_pages = len(doc)
                    doc.close()
                    await db.execute(
                        "UPDATE documents SET page_count = ? WHERE id = ?",
                        (total_pages, doc_id),
                    )
                    await db.commit()
                except Exception as e:
                    print(f"[INDEX] Failed to get PDF page count: {e}")

            # 更新状态为 indexing
            await db.execute(
                "UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("processing:indexing", doc_id),
            )
            await db.commit()

            # 使用同步的进度更新（避免阻塞事件循环）
            if total_pages > 0:
                print(
                    f"[INDEX] Starting progress thread for {doc_id}, pages: {total_pages}"
                )
                progress_thread = threading.Thread(
                    target=_update_progress_sync,
                    args=(db_path, doc_id, total_pages, progress_stop_event),
                    daemon=True,
                )
                progress_thread.start()
                print(f"[INDEX] Progress thread started for {doc_id}")

            # 执行索引
            pageindex_service = PageIndexService()
            if PAGEINDEX_MAX_INDEX_SECONDS > 0:
                result = await asyncio.wait_for(
                    pageindex_service.generate_index(
                        file_path, doc_id, mode_override=mode_override
                    ),
                    timeout=PAGEINDEX_MAX_INDEX_SECONDS,
                )
            else:
                result = await pageindex_service.generate_index(
                    file_path, doc_id, mode_override=mode_override
                )

            # 更新状态为 writing_index（90%）
            await db.execute(
                "UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("processing:writing_index", doc_id),
            )
            await db.commit()
            print(f"[INDEX] Writing index for {doc_id}")

            # 提取文档描述与实际单元数（多格式）
            doc_description = None
            computed_page_count = None
            if isinstance(result, dict):
                # 从结果中提取 doc_description（PageIndex生成）
                doc_description = result.get("doc_description")
                computed_page_count = result.get("page_count")
                # 如果是Markdown格式，可能在structure中
                if not doc_description and "structure" in result:
                    structure = result.get("structure", {})
                    if isinstance(structure, dict):
                        doc_description = structure.get("doc_description")

            if doc_description:
                print(
                    f"[INDEX] Generated doc description for {doc_id}: {doc_description[:50]}..."
                )

            # 更新状态为 completed，同时保存文档描述
            await db.execute(
                """UPDATE documents 
                   SET status = ?, index_path = ?, description = ?, error_message = NULL,
                       page_count = COALESCE(?, page_count),
                       processed_pages = COALESCE(?, page_count),
                       updated_at = CURRENT_TIMESTAMP 
                   WHERE id = ?""",
                (
                    "completed",
                    result.get("index_path"),
                    doc_description,
                    computed_page_count,
                    computed_page_count,
                    doc_id,
                ),
            )
            await db.commit()
            print(f"[INDEX] Completed index for {doc_id}")

            # 重建搜索索引（独立线程执行，避免事件循环关闭导致任务丢失）
            try:
                trigger_search_rebuild_background()
                print(f"[INDEX] Search index rebuild triggered for {doc_id}")
            except Exception as e:
                print(f"[INDEX] Failed to trigger search index rebuild: {e}")

        except asyncio.TimeoutError:
            timeout_msg = (
                f"Indexing exceeded {PAGEINDEX_MAX_INDEX_SECONDS}s limit"
                if PAGEINDEX_MAX_INDEX_SECONDS > 0
                else "Indexing timed out"
            )
            print(f"[INDEX] Timeout for {doc_id}: {timeout_msg}")
            if await _mark_completed_from_partial_index_if_exists(db, doc_id, timeout_msg):
                return
            await db.execute(
                "UPDATE documents SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("failed:indexing_timeout", timeout_msg, doc_id),
            )
            await db.commit()
        except Exception as e:
            print(f"[INDEX] Failed index for {doc_id}: {e}")
            import traceback

            traceback.print_exc()
            error_message = str(e)
            status_code = _extract_failure_status_code(error_message)
            failure_index_path = str(INDEXES_DIR / f"{doc_id}.json")
            if not os.path.exists(failure_index_path):
                failure_index_path = None
            await db.execute(
                "UPDATE documents SET status = ?, error_message = ?, index_path = COALESCE(?, index_path), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (f"failed:{status_code}", error_message, failure_index_path, doc_id),
            )
            await db.commit()
        finally:
            # 安全清理：确保进度线程停止
            if progress_thread and progress_thread.is_alive():
                progress_stop_event.set()
                progress_thread.join(timeout=1)
            
            # 安全检查：如果状态仍为 processing，说明处理未正常完成
            # 可能是 asyncio.wait_for 超时但异常未被正确捕获
            try:
                cursor = await db.execute(
                    "SELECT status FROM documents WHERE id = ?",
                    (doc_id,)
                )
                row = await cursor.fetchone()
                if row and row[0] and row[0].startswith('processing'):
                    print(f"[INDEX] Safety check: doc {doc_id} still in {row[0]}, marking as failed")
                    await db.execute(
                        "UPDATE documents SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            "failed:indexing_timeout",
                            f"处理超时：超过{PAGEINDEX_MAX_INDEX_SECONDS}秒未完成，可能是VLM调用超时",
                            doc_id
                        ),
                    )
                    await db.commit()
            except Exception as safety_err:
                print(f"[INDEX] Safety check failed for {doc_id}: {safety_err}")


async def _mark_completed_from_partial_index_if_exists(
    db,
    doc_id: str,
    timeout_msg: str,
) -> bool:
    partial_index_path = str(INDEXES_DIR / f"{doc_id}.json")
    if not os.path.exists(partial_index_path):
        return False

    await db.execute(
        """UPDATE documents
           SET status = ?, index_path = COALESCE(index_path, ?),
               error_message = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (
            "completed",
            partial_index_path,
            f"{timeout_msg}; using base index without full enrichment",
            doc_id,
        ),
    )
    await db.commit()
    print(f"[INDEX] Timeout after base index save for {doc_id}; marked completed")
    try:
        trigger_search_rebuild_background()
        print(f"[INDEX] Search index rebuild triggered for {doc_id}")
    except Exception as e:
        print(f"[INDEX] Failed to trigger search index rebuild: {e}")
    return True


def _update_progress_sync(
    db_path: str, doc_id: str, total_pages: int, stop_event: threading.Event
):
    """使用同步数据库连接定期更新已处理页数"""
    # 估算每页处理时间（秒），基于经验值调整
    estimated_time_per_page = 3.0

    for current_page in range(1, total_pages + 1):
        # 检查是否应停止
        if stop_event.wait(timeout=estimated_time_per_page):
            break

        try:
            _update_processed_pages_sync(db_path, doc_id, processed_pages=current_page)
        except Exception as e:
            print(f"[INDEX] Failed to update progress for {doc_id}: {e}")

    # 所有页处理完成后，仅更新处理进度，不在这里切换 writing_index
    if not stop_event.is_set():
        try:
            _update_processed_pages_sync(db_path, doc_id, processed_pages=total_pages)
        except Exception as e:
            print(f"[INDEX] Failed to finalize progress for {doc_id}: {e}")


def trigger_search_rebuild_background():
    """合并并串行化搜索索引重建请求，避免并发重建导致短时卡顿。"""
    import threading
    import asyncio

    global _search_rebuild_running, _search_rebuild_pending

    with _search_rebuild_lock:
        _search_rebuild_pending = True
        if _search_rebuild_running:
            return
        _search_rebuild_running = True

    def _runner():
        global _search_rebuild_running, _search_rebuild_pending

        while True:
            with _search_rebuild_lock:
                if not _search_rebuild_pending:
                    _search_rebuild_running = False
                    return
                _search_rebuild_pending = False

            async def _do_rebuild():
                from app.services.search_service import search_service

                await search_service.rebuild_index()

            try:
                asyncio.run(_do_rebuild())
                print("[INDEX] Search index rebuild completed (background)")
            except Exception as e:
                print(f"[INDEX] Search index rebuild failed (background): {e}")

    threading.Thread(target=_runner, daemon=True).start()


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    parse_mode: Optional[str] = Form(None),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """上传文档"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]

    # 读取文件内容
    content = await file.read()
    file_size = len(content)

    # 检查文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    filename: str = file.filename  # type: ignore

    # 验证文件
    is_valid, error_msg = doc_service.validate_file(filename, file_size)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 验证文件夹存在
    folder_path = ""
    if folder_id:
        from app.services.folder_service import FolderService

        folder_service = FolderService(db)
        folder = await folder_service.get_folder(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="文件夹不存在")
        folder_path = folder.path

    # 保存文档（记录用户ID）
    file_type = Path(filename).suffix.lower()
    doc = await doc_service.save_document(
        content, filename, file_size, file_type, folder_id, folder_path, user_id
    )

    # PDF 文件立即读取页数
    if file_type == ".pdf":
        try:
            import pymupdf
            from io import BytesIO

            pdf_doc = pymupdf.open(stream=BytesIO(content), filetype="pdf")
            page_count = len(pdf_doc)
            pdf_doc.close()
            await db.execute(
                "UPDATE documents SET page_count = ? WHERE id = ?",
                (page_count, doc.id),
            )
            await db.commit()
        except Exception:
            pass

    # 使用独立进程后台生成索引
    # parse_mode: smart/fast/balanced, None defaults to smart
    mode_override = parse_mode if parse_mode in ("smart", "fast", "balanced") else None
    start_index_process(doc.id, doc.file_path, mode_override=mode_override)

    return doc


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    folder_id: Optional[str] = Query(None, description="文件夹ID，null表示根目录"),
    include_subfolders: bool = Query(True, description="是否包含子文件夹"),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档列表（支持文件夹筛选和搜索，按用户隔离）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]

    folder_path = None
    if folder_id:
        from app.services.folder_service import FolderService

        folder_service = FolderService(db)
        folder = await folder_service.get_folder(folder_id)
        if folder:
            folder_path = folder.path

    items, total = await doc_service.list_documents(
        page, page_size, search, folder_id, folder_path, include_subfolders, user_id
    )
    items = [_attach_parse_meta(item) for item in items]
    return DocumentListResponse(items=items, total=total)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取单个文档（用户权限验证）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]
    doc = await doc_service.get_document(doc_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")
    return _attach_parse_meta(doc)


@router.get("/{doc_id}/processing-steps", response_model=ProcessingStepsResponse)
async def get_document_processing_steps(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档索引处理的详细步骤和时间线（始终返回完整5步pipeline）"""
    from app.services.pageindex_service import PageIndexService
    from pageindex.utils import structure_to_list

    doc_service = DocumentService(db)
    user_id = current_user["id"]

    doc = await doc_service.get_document(doc_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    status = doc.status or ""
    is_processing = status.startswith("processing")
    is_completed = status == "completed"
    is_failed = status.startswith("failed")

    # 加载索引数据
    pageindex_service = PageIndexService()
    index_data = await pageindex_service.load_index(doc_id)
    route = index_data.get("route_decision", {}) if isinstance(index_data, dict) else {}
    mode = route.get("execution_mode", "unknown") if isinstance(route, dict) else "unknown"
    structure = index_data.get("structure", []) if isinstance(index_data, dict) else []
    nodes = structure_to_list(structure) if structure else []

    # 确定当前运行中的步骤（必须在 stage_order 使用之前定义）
    current_step = None
    if status.startswith("processing:analyze"):
        current_step = "analyze"
    elif status.startswith("processing:indexing"):
        current_step = "toc_extraction"
    elif status.startswith("processing:writing_index"):
        current_step = "node_filling"
    elif status.startswith("processing:generating_summaries"):
        current_step = "summary_generation"

    def step_status(completed: bool, running: bool = False) -> str:
        if completed:
            return "completed"
        if running:
            return "running"
        return "pending"

    # 确定各阶段状态（基于阶段顺序推断）
    # 阶段顺序：upload → analyze → toc_extraction → node_filling → summary_generation
    # 如果当前在 X 阶段或之后，说明 X 之前的步骤已完成
    stage_order = [
        "upload",
        "analyze",
        "toc_extraction",
        "node_filling",
        "summary_generation",
    ]
    current_stage_idx = stage_order.index(current_step) if current_step else -1
    
    analyze_done = True  # analyze 在 upload 之后立即执行
    toc_done = current_stage_idx >= 2 or is_completed
    writing_done = current_stage_idx >= 3 or is_completed
    summary_done = is_completed

    # 构建5步完整pipeline
    steps = [
        {
            "step_type": "upload",
            "title": "文件上传",
            "description": "文件已上传至服务器",
            "status": "completed",
        },
        {
            "step_type": "analyze",
            "title": "文档分析",
            "description": f"分析文档结构，共 {doc.page_count or '?'} 页，文本覆盖率评估",
            "status": step_status(analyze_done, current_step == "analyze"),
            "details": {"page_count": doc.page_count},
        },
        {
            "step_type": "toc_extraction",
            "title": "目录提取",
            "description": f"使用 {mode} 模式提取目录结构，共 {len(nodes)} 个节点",
            "status": step_status(toc_done, current_step == "toc_extraction"),
            "details": {"mode": mode, "node_count": len(nodes)},
        },
        {
            "step_type": "node_filling",
            "title": "内容填充",
            "description": "提取各节点文本内容并关联页面",
            "status": step_status(writing_done, current_step == "node_filling"),
        },
        {
            "step_type": "summary_generation",
            "title": "摘要生成",
            "description": "为各章节生成检索摘要",
            "status": step_status(summary_done, current_step == "summary_generation"),
        },
    ]

    # 失败状态：将失败步骤标记为 failed
    if is_failed:
        for step in reversed(steps):
            if step["status"] == "running":
                step["status"] = "failed"
                break

    # 计算总用时
    total_duration = _calculate_processing_duration(doc)

    return ProcessingStepsResponse(
        doc_id=doc_id,
        doc_name=doc.original_name,
        status=doc.status,
        total_duration_seconds=total_duration,
        steps=[ProcessingStep(**s) for s in steps],
        current_step=current_step,
    )


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """删除文档（用户权限验证）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]
    success = await doc_service.delete_document(doc_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档不存在或无权限删除")

    try:
        trigger_search_rebuild_background()
    except Exception as e:
        print(f"[INDEX] Failed to trigger rebuild after delete: {e}")

    return {"message": "删除成功"}


@router.post("/{doc_id}/move")
async def move_document(
    doc_id: str,
    folder_id: Optional[str] = Form(None, description="目标文件夹ID，null表示根目录"),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """移动文档到指定文件夹（仅当前用户）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]

    # 检查文档是否存在且属于当前用户
    doc = await doc_service.get_document(doc_id, user_id=user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    if folder_id:
        from app.services.folder_service import FolderService

        folder_service = FolderService(db)
        folder = await folder_service.get_folder(folder_id, user_id=user_id)
        if not folder:
            raise HTTPException(status_code=404, detail="目标文件夹不存在")

    try:
        await doc_service.move_document(doc_id, folder_id, user_id=user_id)
        return {"message": "移动成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{doc_id}/rename")
async def rename_document(
    doc_id: str,
    name: str = Form(..., description="新文档名称"),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """重命名文档（仅当前用户）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]

    doc = await doc_service.get_document(doc_id, user_id=user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    try:
        await doc_service.rename_document(doc_id, name, user_id=user_id)
        return {"message": "重命名成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    payload: Optional[ReindexRequest] = None,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """重新索引文档（仅当前用户）"""
    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    mode_override: Optional[str] = None
    selected_mode = payload.mode if payload is not None else "smart"
    if selected_mode in {"smart", "fast", "balanced"}:
        mode_override = selected_mode

    # 记录重新解析开始时间
    await db.execute(
        "UPDATE documents SET last_reindex_at = CURRENT_TIMESTAMP WHERE id = ?",
        (doc_id,)
    )
    await db.commit()

    # 使用独立进程后台生成索引
    start_index_process(doc_id, doc.file_path, mode_override=mode_override)

    return {
        "message": "已开始重新索引",
        "mode": selected_mode,
    }


@router.get("/{doc_id}/page/{page_num}")
async def get_document_page(
    doc_id: str,
    page_num: int,
    include_image: bool = Query(True, description="是否包含页面图片"),
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档指定页面的内容（仅当前用户）"""
    from app.services.tool_executor import ToolExecutor
    from app.services.pageindex_service import PageIndexService

    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    # 使用 ToolExecutor 获取页面内容
    pageindex_service = PageIndexService()
    tool_executor = ToolExecutor(
        pageindex_service,
        doc_service,
        user_id=current_user["id"],
        allowed_doc_ids=[doc_id],
    )

    try:
        # 调用批量获取接口（传入单页数组）
        result = await tool_executor._get_page_content(
            doc_id=doc_id, page_nums=[page_num]
        )

        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error", "获取失败"))

        # 从批量结果中提取单页数据
        pages = result.get("data", {}).get("pages", [])
        if not pages:
            raise HTTPException(status_code=404, detail="页面不存在")

        page_data = pages[0]
        if "error" in page_data:
            raise HTTPException(status_code=404, detail=page_data["error"])

        # 检查页面是否有视觉内容（图片/图表）
        has_visual_content = page_data.get("has_visual_content", False)

        # 如果有视觉内容，渲染整页为图片
        page_image_base64 = None
        if has_visual_content and include_image:
            try:
                from app.core.llm import pdf_page_to_base64

                file_type = (doc.file_type or "").lower()
                if file_type == ".pdf":
                    page_image_base64 = pdf_page_to_base64(doc.file_path, page_num)
            except Exception as img_error:
                print(f"[API Warning] Failed to render page image: {img_error}")

        # 构建响应
        response_data = {
            "doc_id": doc_id,
            "doc_name": doc.original_name,
            "page_num": page_num,
            "node_title": page_data.get("node_title", ""),
            "text_content": page_data.get("text_content", ""),
            "has_image": has_visual_content,
            "cache_hit": page_data.get("cache_hit", False),
        }

        # 如果渲染了图片，添加到响应
        if page_image_base64:
            response_data["page_image_base64"] = page_image_base64

        return response_data
    except Exception as e:
        import traceback

        print(f"[API Error] get_document_page: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取页面内容失败: {str(e)}")


@router.get("/{doc_id}/page/{page_num}/image")
async def get_document_page_image(
    doc_id: str,
    page_num: int,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档指定页面的图片（仅当前用户）"""
    from app.services.tool_executor import ToolExecutor
    from app.services.pageindex_service import PageIndexService
    from app.core.llm import pdf_page_to_base64

    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    file_type = (doc.file_type or "").lower()
    if file_type != ".pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    try:
        page_image_base64 = pdf_page_to_base64(doc.file_path, page_num)
        if not page_image_base64:
            raise HTTPException(status_code=404, detail="无法生成页面图片")

        return {
            "doc_id": doc_id,
            "doc_name": doc.original_name,
            "page_num": page_num,
            "image_base64": page_image_base64,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取页面图片失败: {str(e)}")


@router.get("/{doc_id}/preview")
async def get_document_preview(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档预览信息（仅当前用户）"""
    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    # page_count 兜底：若数据库为空则从 PDF 读取
    page_count = doc.page_count
    if not page_count and (doc.file_type or "").lower() == ".pdf":
        try:
            import pymupdf

            pdf_doc = pymupdf.open(doc.file_path)
            page_count = len(pdf_doc)
            pdf_doc.close()
            await db.execute(
                "UPDATE documents SET page_count = ? WHERE id = ?",
                (page_count, doc_id),
            )
            await db.commit()
        except Exception:
            pass

    # 获取索引信息
    pageindex_service = PageIndexService()
    index_data = await pageindex_service.load_index(doc_id)

    # 构建目录结构
    toc = _build_toc_from_index(index_data)

    # 预览接口只读，不在这里做耗时生成，避免“点击预览无响应”
    description = doc.description

    # 计算统计信息
    from pageindex.utils import structure_to_list

    nodes = (
        structure_to_list(index_data.get("structure", index_data)) if index_data else []
    )
    node_count = len(nodes)
    text_chars = sum(len(node.get("text", "") or "") for node in nodes)
    has_summaries = sum(1 for node in nodes if node.get("summary"))
    route_decision = (
        index_data.get("route_decision") if isinstance(index_data, dict) else None
    )
    pre_analysis = (
        index_data.get("pre_analysis") if isinstance(index_data, dict) else None
    )
    toc_quality = (
        index_data.get("toc_quality") if isinstance(index_data, dict) else None
    )
    visual_page_summaries = (
        index_data.get("visual_page_summaries")
        if isinstance(index_data, dict)
        else None
    )

    return {
        "id": doc.id,
        "name": doc.original_name,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "status": doc.status,
        "page_count": page_count,
        "index_path": doc.index_path,
        "description": description,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at),
        "processing_duration": _calculate_processing_duration(doc),
        "toc": toc,
        "index_meta": {
            "route_decision": route_decision,
            "pre_analysis": pre_analysis,
            "toc_quality": toc_quality,
            "visual_page_summaries_count": len(visual_page_summaries or []),
        },
        "stats": {
            "node_count": node_count,
            "text_chars": text_chars,
            "has_summaries": has_summaries,
            "summary_coverage": f"{has_summaries}/{node_count}"
            if node_count > 0
            else "0/0",
        },
    }


@router.get("/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档文件（仅当前用户）"""
    from fastapi.responses import FileResponse

    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    file_path = doc.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    # 获取MIME类型
    mime_type = (
        "application/pdf" if doc.file_type == ".pdf" else "application/octet-stream"
    )

    return FileResponse(
        file_path,
        media_type=mime_type,
        filename=doc.original_name,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """获取文档内容用于预览（仅当前用户）"""
    from app.services.content_extraction_service import content_extraction_service
    from fastapi.responses import JSONResponse

    doc_service = DocumentService(db)
    doc = await doc_service.get_document(doc_id, user_id=current_user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或无权限访问")

    file_path = doc.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    # PDF 直接返回提示，仍使用现有 PDF 预览
    file_type = (doc.file_type or "").lower()
    if file_type == ".pdf":
        return JSONResponse(
            content={
                "format": "pdf",
                "message": "PDF 文件请使用 /file 接口配合 PDF.js 预览",
                "file_url": f"/api/documents/{doc_id}/file",
            }
        )

    # 检查是否支持该格式
    supported_formats = {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".tsv",
        ".xlsx",
        ".docx",
        ".pptx",
    }
    if file_type not in supported_formats:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {file_type}")

    try:
        # 提取内容
        result = content_extraction_service.extract_content(Path(file_path), file_type)

        # 统一左侧目录来源：使用索引 TOC
        pageindex_service = PageIndexService()
        index_data = await pageindex_service.load_index(doc_id)
        result["toc"] = _build_toc_from_index(index_data)

        # 添加文档元信息
        result["document"] = {
            "id": doc.id,
            "name": doc.original_name,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
        }

        return result
    except Exception as e:
        import traceback

        print(f"[Content Extraction Error] {doc_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"提取文档内容失败: {str(e)}")


@router.post("/batch-download")
async def batch_download(
    doc_ids: List[str],
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """批量下载文档（打包为ZIP）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]

    # 验证所有文档存在且属于当前用户
    docs = []
    for doc_id in doc_ids:
        doc = await doc_service.get_document(doc_id, user_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
        if not os.path.exists(doc.file_path):
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 文件不存在")
        docs.append(doc)

    # 创建 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            zf.write(doc.file_path, arcname=doc.original_name)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=batch_download_{len(docs)}.zip"
        },
    )
