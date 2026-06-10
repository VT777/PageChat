import os
from pathlib import Path
from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_value(env: dict[str, str] | os._Environ[str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def app_env(env: dict[str, str] | os._Environ[str] = os.environ) -> str:
    return (_env_value(env, "APP_ENV") or "development").lower()


def is_production(env: dict[str, str] | os._Environ[str] = os.environ) -> bool:
    return app_env(env) in {"prod", "production"}


def resolve_jwt_secret(env: dict[str, str] | os._Environ[str] = os.environ) -> str:
    secret = _env_value(env, "JWT_SECRET") or _env_value(env, "SECRET_KEY")
    if secret:
        return secret
    if is_production(env):
        raise RuntimeError(
            "JWT_SECRET or SECRET_KEY is required in production; refusing to use "
            "the development fallback signing secret."
        )
    return "dev-only-change-me-page-chat-jwt-secret"


# 项目根目录
BASE_DIR = Path(__file__).parent.parent.parent

# 优先加载 backend/.env，并覆盖进程中遗留的同名变量
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

# 数据目录
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
INDEXES_DIR = DATA_DIR / "indexes"
PREVIEWS_DIR = DATA_DIR / "previews"
VISUAL_DAILY_STATS_PATH = DATA_DIR / "visual_daily_stats.json"

# 数据库
DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR}/knowclaw.db"

# JWT signing configuration. Keep local/test fallback stable across restarts.
APP_ENV = app_env()
IS_PRODUCTION = is_production()
JWT_SECRET = resolve_jwt_secret()

# LLM 基础配置
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-plus")
LLM_FLASH_MODEL = os.getenv("LLM_FLASH_MODEL", "qwen3.6-flash")
LLM_PLUS_MODEL = os.getenv("LLM_PLUS_MODEL", "qwen3.6-plus")
MODEL_FLASH_TIMEOUT_SECONDS = int(os.getenv("MODEL_FLASH_TIMEOUT_SECONDS", "8"))
MODEL_PLUS_TIMEOUT_SECONDS = int(os.getenv("MODEL_PLUS_TIMEOUT_SECONDS", "20"))
MODEL_TIMEOUT_RETRIES = int(os.getenv("MODEL_TIMEOUT_RETRIES", "1"))
MODEL_ROUTE_FLASH_MAX_INPUT_TOKENS = int(
    os.getenv("MODEL_ROUTE_FLASH_MAX_INPUT_TOKENS", "4000")
)

# MVP 阈值与运行时配置
FIRST_EVENT_P95_MS = 300
FIRST_EVENT_P99_MS = 500
SSE_SLA_WINDOW_SECONDS = 300
SSE_SLA_MIN_SAMPLES = 100
CITATION_MIN_CONFIDENCE = 0.65
MULTITURN_MAX_USER_ROUNDS = 6
MULTITURN_MAX_EVIDENCE = 20
EVIDENCE_REUSE_SIMILARITY_MIN = 0.72
ALLOW_CROSS_SESSION_EVIDENCE_REUSE = False
VISUAL_COVERAGE_TARGET = 0.95
VISUAL_SINGLE_DAY_FLOOR = 0.90
VISUAL_MAX_DAILY_DOWNGRADE_RATE = 0.05
VISUAL_MAX_CONSECUTIVE_FAIL_PAGES = 3
VISUAL_PAGE_TIMEOUT_SECONDS = 12
VISUAL_VLM_MAX_CONCURRENCY = int(os.getenv("VISUAL_VLM_MAX_CONCURRENCY", "4"))
VISUAL_VLM_PAGE_MAX_ATTEMPTS = int(os.getenv("VISUAL_VLM_PAGE_MAX_ATTEMPTS", "2"))

# OCR 配置（使用 DashScope qwen-vl-ocr-latest）
OCR_API_KEY = os.getenv("OCR_API_KEY", os.getenv("LLM_API_KEY"))  # 优先独立配置，否则复用 LLM Key
OCR_BASE_URL = os.getenv("OCR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
OCR_MODEL = os.getenv("OCR_MODEL", "qwen-vl-ocr-latest")
OCR_MAX_CONCURRENCY = int(os.getenv("OCR_MAX_CONCURRENCY", "15"))
OCR_RATE_LIMIT_RPS = int(os.getenv("OCR_RATE_LIMIT_RPS", "15"))
OCR_MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "2"))
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "60"))
OCR_MIN_IMAGE_SIDE_PX = int(os.getenv("OCR_MIN_IMAGE_SIDE_PX", "30"))
OCR_MIN_IMAGE_AREA_RATIO = float(os.getenv("OCR_MIN_IMAGE_AREA_RATIO", "0.005"))

# 保留旧配置名兼容性（避免其他代码引用报错）
BIGMODEL_API_KEY = OCR_API_KEY
BIGMODEL_BASE_URL = OCR_BASE_URL
BIGMODEL_OCR_MODEL = OCR_MODEL

# 多模型配置 - 分层调用（优化版）
# 注：qwen3.6-plus 原生支持视觉理解（image_url），无需单独的视觉模型
MODEL_CONFIG = {
    # 意图分类：flash 模型，追求速度（token 优化后减少 46%）
    "intent": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 80,  # 减少 20%，优化后的 JSON 更精简
    },
    # 闲聊：flash 模型，追求速度
    "chat": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0.7,
        "max_tokens": 500,  # 添加限制防止过长
    },
    # 文档问答：plus 模型，追求质量（温度降低以提高一致性）
    "qa": {
        "model": LLM_PLUS_MODEL,
        "temperature": 0.3,  # 从 0.7 降低以提高一致性
        "max_tokens": 1000,  # 添加限制
    },
    # PageIndex 索引生成：flash 模型（优化提示词后质量足够）
    "index": {
        "model": LLM_FLASH_MODEL,  # 从 plus 改为 flash，提示词优化后质量足够
        "temperature": 0,
        "max_tokens": 200,  # 目录/摘要类任务简短
    },
    # 新增：查询扩展，用于检索优化
    "query_expansion": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 150,
    },
    # 新增：节点摘要生成
    "node_summary": {
        "model": LLM_FLASH_MODEL,  # 使用 flash 即可
        "temperature": 0,
        "max_tokens": 80,
    },
    # 新增：搜索相关性评分
    "relevance": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 100,
    },
}

# 页面文本太短时自动获取页面图片让模型看图的阈值（字符数）
PAGE_TEXT_SHORT_THRESHOLD = int(os.getenv("PAGE_TEXT_SHORT_THRESHOLD", "200"))

# PageIndex 配置（优化版）
PAGEINDEX_CONFIG = {
    "model": "qwen3.6-flash",  # 保持 flash 模型，提示词优化后质量足够
    "toc_check_page_num": 15,  # 增加到15页，平衡准确率和速度
    "max_page_num_each_node": 6,  # 降低阈值确保大章节递归拆分为子节点
    "max_token_num_each_node": 15000,  # 配合页数阈值，保证检索粒度
    "if_add_node_id": "yes",
    "if_add_node_summary": "yes",
    "if_add_doc_description": "yes",
    "if_add_node_text": "yes",
    # 新增：启用并行处理提示词（性能优化）
    "use_optimized_prompts": True,
    "prompt_batch_size": 5,  # 每批并行处理的提示词数量
}

# 索引模式：smart(智能路由) / balanced(平衡模式) / fast(精简模式)
PAGEINDEX_MODE = os.getenv("PAGEINDEX_MODE", "balanced").strip().lower()
if PAGEINDEX_MODE not in {"smart", "balanced", "fast"}:
    PAGEINDEX_MODE = "balanced"

PAGEINDEX_FAST_ENABLED = PAGEINDEX_MODE in {"fast", "smart"} or _env_bool(
    "PAGEINDEX_FAST_ENABLED", False
)

# 单文档索引全局超时（秒）
# 从1800秒改为600秒：改进后的Branch B增加了VLM调用次数，10次调用*60秒=600秒
# 如果超过10分钟仍未完成，说明处理卡住，应标记为失败
PAGEINDEX_MAX_INDEX_SECONDS = int(os.getenv("PAGEINDEX_MAX_INDEX_SECONDS", "600"))

# Batch indexing controls. Upload bursts enqueue jobs and let a small worker pool
# consume them, preventing per-document LLM/VLM concurrency from multiplying.
PAGEINDEX_QUEUE_ENABLED = _env_bool("PAGEINDEX_QUEUE_ENABLED", True)
PAGEINDEX_MAX_CONCURRENT_JOBS = max(
    1, int(os.getenv("PAGEINDEX_MAX_CONCURRENT_JOBS", "1"))
)

# Balanced-mode summary enrichment budgets. The base index should remain usable
# even when individual summary requests are slow or rate-limited.
PAGEINDEX_SUMMARY_CONCURRENCY = max(
    1, int(os.getenv("PAGEINDEX_SUMMARY_CONCURRENCY", "2"))
)
PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS = float(
    os.getenv("PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS", "25")
)
PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS = float(
    os.getenv("PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS", "120")
)
PAGEINDEX_SUMMARY_MAX_LLM_NODES = max(
    0, int(os.getenv("PAGEINDEX_SUMMARY_MAX_LLM_NODES", "30"))
)

# 启动时回收长时间处于 processing 的任务（分钟）
INDEXING_STUCK_THRESHOLD_MINUTES = int(
    os.getenv("INDEXING_STUCK_THRESHOLD_MINUTES", "30")
)

# Fast 模式：基于目录结构生成轻量文档摘要（同流程内，超时跳过）
PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED = _env_bool(
    "PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED", True
)
PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = float(
    os.getenv("PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS", "15")
)
PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES = int(
    os.getenv("PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES", "20")
)

# 预分析路由阈值（fast -> balanced）
PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD = int(
    os.getenv("PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD", "60")
)
PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD = float(
    os.getenv("PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD", "0.15")
)
PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD = float(
    os.getenv("PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD", "0.78")
)

# Vision TOC 严格模式阈值（balanced + vision-first）
VISION_TOC_STRICT_TARGET_RATIO = float(
    os.getenv("VISION_TOC_STRICT_TARGET_RATIO", "0.65")
)
VISION_TOC_STRICT_MAX_GAP_PAGES = int(os.getenv("VISION_TOC_STRICT_MAX_GAP_PAGES", "2"))
VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS = int(
    os.getenv("VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS", "4")
)


def build_effective_pageindex_config(mode: str | None = None) -> dict:
    cfg = dict(PAGEINDEX_CONFIG)
    effective_mode = (
        (mode or ("smart" if PAGEINDEX_FAST_ENABLED else "balanced")).strip().lower()
    )
    if effective_mode not in {"smart", "balanced", "fast"}:
        effective_mode = "balanced"

    if effective_mode != "fast":
        if effective_mode == "smart":
            cfg.update(
                {
                    "toc_check_page_num": int(
                        os.getenv("PAGEINDEX_FAST_TOC_CHECK_PAGE_NUM", "6")
                    ),
                    "max_page_num_each_node": int(
                        os.getenv("PAGEINDEX_FAST_MAX_PAGE_NUM_EACH_NODE", "10")
                    ),
                    "max_token_num_each_node": int(
                        os.getenv("PAGEINDEX_FAST_MAX_TOKEN_NUM_EACH_NODE", "20000")
                    ),
                    "if_add_node_summary": "no",
                    "if_add_doc_description": "no",
                    "if_add_node_text": "yes",
                    "index_mode": "smart",
                }
            )
            return cfg
        cfg["index_mode"] = "balanced"
        return cfg

    cfg.update(
        {
            "toc_check_page_num": int(
                os.getenv("PAGEINDEX_FAST_TOC_CHECK_PAGE_NUM", "6")
            ),
            "max_page_num_each_node": int(
                os.getenv("PAGEINDEX_FAST_MAX_PAGE_NUM_EACH_NODE", "10")
            ),
            "max_token_num_each_node": int(
                os.getenv("PAGEINDEX_FAST_MAX_TOKEN_NUM_EACH_NODE", "20000")
            ),
            "if_add_node_summary": "no",
            "if_add_doc_description": "no",
            "if_add_node_text": "yes",
            "index_mode": "fast",
        }
    )
    return cfg


EFFECTIVE_PAGEINDEX_CONFIG = build_effective_pageindex_config()

# 文件上传限制
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".md",
    ".markdown",
    ".txt",
    ".csv",
    ".tsv",
    ".xlsx",
    ".docx",
    ".pptx",
}


def validate_required_settings() -> None:
    if not os.getenv("LLM_API_KEY"):
        raise RuntimeError(
            "LLM_API_KEY is required. Set it in environment or backend/.env"
        )
