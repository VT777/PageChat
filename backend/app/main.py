import logging
import os
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

tool_logger = logging.getLogger("tool")
tool_logger.setLevel(logging.INFO)
tool_handler = logging.FileHandler(LOG_DIR / "backend-manual.log", encoding="utf-8")
tool_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
)
tool_logger.addHandler(tool_handler)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_handler = logging.StreamHandler(sys.stdout)
root_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
root_logger.addHandler(root_handler)

# 禁用 uvicorn access log — 在 Windows 上 stdout 重定向到文件时
# 同步 IO 会间歇性阻塞 asyncio event loop 导致请求延迟 5-15 秒
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").propagate = False

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import (
    DATA_DIR,
    DOCUMENTS_DIR,
    INDEXES_DIR,
    PREVIEWS_DIR,
    validate_required_settings,
)
from app.models.database import init_db
from app.api import documents, chat, folders, auth, tools, settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    validate_required_settings()
    for dir_path in [DATA_DIR, DOCUMENTS_DIR, INDEXES_DIR, PREVIEWS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)

    # 启动时 VACUUM 数据库防止 disk I/O error（用同步 sqlite3，在 init_db 之前）
    try:
        import sqlite3

        db_path = str(DATA_DIR / "knowclaw.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 3000")
            conn.execute("VACUUM")
            conn.close()
            print("[OK] Database VACUUM + WAL completed")
    except Exception as e:
        print(f"[WARN] Database VACUUM failed: {e}")

    # 启动时初始化数据库
    await init_db()
    print("[OK] Database initialized")

    # 启动时回收卡住的索引任务
    try:
        documents.recover_stuck_indexing_tasks_sync(str(DATA_DIR / "knowclaw.db"))
    except Exception as e:
        print(f"[WARN] Failed to recover stuck indexing tasks: {e}")

    # 启动时初始化搜索服务（后台构建索引）
    try:
        from app.services.search_service import search_service

        # 使用create_task在后台初始化，不阻塞启动
        import asyncio

        asyncio.create_task(search_service.initialize())
        print("[OK] Search service initialization started (background)")
    except Exception as e:
        print(f"[WARN] Failed to start search service: {e}")

    yield
    # 关闭时的清理工作
    print("[BYE] Shutting down...")


# 创建 FastAPI 应用
app = FastAPI(
    title="KnowClaw API",
    description="智能知识问答系统 - 基于 PageIndex 树状索引",
    version="0.1.0",
    lifespan=lifespan,
)


# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vue dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router)
app.include_router(tools.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(folders.router)
app.include_router(settings.router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "KnowClaw API",
        "version": "0.1.0",
        "description": "智能知识问答系统 - 基于 PageIndex 树状索引",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@app.get("/cache/stats")
async def cache_stats():
    """获取缓存统计信息"""
    from app.services.cache_service import cache_service

    return cache_service.get_stats()


@app.post("/cache/clear")
async def clear_cache():
    """清除所有缓存"""
    from app.services.cache_service import cache_service

    cache_service.clear_all()
    return {"message": "缓存已清除"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
