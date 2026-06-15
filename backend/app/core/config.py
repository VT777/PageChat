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


# 椤圭洰鏍圭洰褰?
BASE_DIR = Path(__file__).parent.parent.parent

# 浼樺厛鍔犺浇 backend/.env锛屽苟瑕嗙洊杩涚▼涓仐鐣欑殑鍚屽悕鍙橀噺
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

# 鏁版嵁鐩綍
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
INDEXES_DIR = DATA_DIR / "indexes"
PREVIEWS_DIR = DATA_DIR / "previews"

# 鏁版嵁搴?DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR}/knowclaw.db"

# JWT signing configuration. Keep local/test fallback stable across restarts.
APP_ENV = app_env()
IS_PRODUCTION = is_production()
JWT_SECRET = resolve_jwt_secret()

# LLM 鍩虹閰嶇疆
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

# MVP 闃堝€间笌杩愯鏃堕厤缃?
FIRST_EVENT_P95_MS = 300
FIRST_EVENT_P99_MS = 500
SSE_SLA_WINDOW_SECONDS = 300
SSE_SLA_MIN_SAMPLES = 100
CITATION_MIN_CONFIDENCE = 0.65
MULTITURN_MAX_USER_ROUNDS = 6
MULTITURN_MAX_EVIDENCE = 20
EVIDENCE_REUSE_SIMILARITY_MIN = 0.72
ALLOW_CROSS_SESSION_EVIDENCE_REUSE = False

# OCR 閰嶇疆锛堜娇鐢?DashScope qwen-vl-ocr-latest锛?
OCR_API_KEY = os.getenv("OCR_API_KEY", os.getenv("LLM_API_KEY"))  # 浼樺厛鐙珛閰嶇疆锛屽惁鍒欏鐢?LLM Key
OCR_BASE_URL = os.getenv("OCR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
OCR_MODEL = os.getenv("OCR_MODEL", "qwen-vl-ocr-latest")
OCR_DEFAULT_ENGINE_TYPE = os.getenv("OCR_DEFAULT_ENGINE_TYPE", "openai_compatible_ocr")
OCR_OPENAI_BASE_URL = os.getenv("OCR_OPENAI_BASE_URL", OCR_BASE_URL)
OCR_OPENAI_MODEL = os.getenv("OCR_OPENAI_MODEL", OCR_MODEL)
OCR_OPENAI_API_KEY = os.getenv("OCR_OPENAI_API_KEY", OCR_API_KEY or "")
OCR_PADDLEOCR_JOB_URL = os.getenv(
    "OCR_PADDLEOCR_JOB_URL",
    "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
)
OCR_PADDLEOCR_MODEL = os.getenv("OCR_PADDLEOCR_MODEL", "PP-OCRv6")
OCR_PADDLEOCR_API_KEY = os.getenv(
    "OCR_PADDLEOCR_API_KEY",
    os.getenv("PPOCR_AISTUDIO_TOKEN", OCR_API_KEY or ""),
)
OCR_MAX_CONCURRENCY = int(os.getenv("OCR_MAX_CONCURRENCY", "15"))
OCR_RATE_LIMIT_RPS = int(os.getenv("OCR_RATE_LIMIT_RPS", "15"))
OCR_MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "2"))
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "60"))
OCR_MIN_IMAGE_SIDE_PX = int(os.getenv("OCR_MIN_IMAGE_SIDE_PX", "30"))
OCR_MIN_IMAGE_AREA_RATIO = float(os.getenv("OCR_MIN_IMAGE_AREA_RATIO", "0.005"))

# 淇濈暀鏃ч厤缃悕鍏煎鎬э紙閬垮厤鍏朵粬浠ｇ爜寮曠敤鎶ラ敊锛?
BIGMODEL_API_KEY = OCR_API_KEY
BIGMODEL_BASE_URL = OCR_BASE_URL
BIGMODEL_OCR_MODEL = OCR_MODEL

# 澶氭ā鍨嬮厤缃?- 鍒嗗眰璋冪敤锛堜紭鍖栫増锛?
# 娉細qwen3.6-plus 鍘熺敓鏀寔瑙嗚鐞嗚В锛坕mage_url锛夛紝鏃犻渶鍗曠嫭鐨勮瑙夋ā鍨?
MODEL_CONFIG = {
    # 鎰忓浘鍒嗙被锛歠lash 妯″瀷锛岃拷姹傞€熷害锛坱oken 浼樺寲鍚庡噺灏?46%锛?
    "intent": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 80,  # 鍑忓皯 20%锛屼紭鍖栧悗鐨?JSON 鏇寸簿绠€
    },
    # 闂茶亰锛歠lash 妯″瀷锛岃拷姹傞€熷害
    "chat": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0.7,
        "max_tokens": 500,  # 娣诲姞闄愬埗闃叉杩囬暱
    },
    # 鏂囨。闂瓟锛歱lus 妯″瀷锛岃拷姹傝川閲忥紙娓╁害闄嶄綆浠ユ彁楂樹竴鑷存€э級
    "qa": {
        "model": LLM_PLUS_MODEL,
        "temperature": 0.3,  # 浠?0.7 闄嶄綆浠ユ彁楂樹竴鑷存€?
        "max_tokens": 1000,  # 娣诲姞闄愬埗
    },
    # PageIndex 绱㈠紩鐢熸垚锛歠lash 妯″瀷锛堜紭鍖栨彁绀鸿瘝鍚庤川閲忚冻澶燂級
    "index": {
        "model": LLM_FLASH_MODEL,  # 浠?plus 鏀逛负 flash锛屾彁绀鸿瘝浼樺寲鍚庤川閲忚冻澶?
        "temperature": 0,
        "max_tokens": 200,  # 鐩綍/鎽樿绫讳换鍔＄畝鐭?
    },
    # 鏂板锛氭煡璇㈡墿灞曪紝鐢ㄤ簬妫€绱紭鍖?
    "query_expansion": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 150,
    },
    # 鏂板锛氳妭鐐规憳瑕佺敓鎴?
    "node_summary": {
        "model": LLM_FLASH_MODEL,  # 浣跨敤 flash 鍗冲彲
        "temperature": 0,
        "max_tokens": 80,
    },
    # 鏂板锛氭悳绱㈢浉鍏虫€ц瘎鍒?
    "relevance": {
        "model": LLM_FLASH_MODEL,
        "temperature": 0,
        "max_tokens": 100,
    },
}

# 椤甸潰鏂囨湰澶煭鏃惰嚜鍔ㄨ幏鍙栭〉闈㈠浘鐗囪妯″瀷鐪嬪浘鐨勯槇鍊硷紙瀛楃鏁帮級
PAGE_TEXT_SHORT_THRESHOLD = int(os.getenv("PAGE_TEXT_SHORT_THRESHOLD", "200"))

# PageIndex 閰嶇疆锛堜紭鍖栫増锛?
PAGEINDEX_CONFIG = {
    "model": "qwen3.6-flash",  # 淇濇寔 flash 妯″瀷锛屾彁绀鸿瘝浼樺寲鍚庤川閲忚冻澶?
    "toc_check_page_num": 15,  # 澧炲姞鍒?5椤碉紝骞宠　鍑嗙‘鐜囧拰閫熷害
    "max_page_num_each_node": 6,  # 闄嶄綆闃堝€肩‘淇濆ぇ绔犺妭閫掑綊鎷嗗垎涓哄瓙鑺傜偣
    "max_token_num_each_node": 15000,  # 閰嶅悎椤垫暟闃堝€硷紝淇濊瘉妫€绱㈢矑搴?    "if_add_node_id": "yes",
    "if_add_node_summary": "no",
    "if_add_doc_description": "yes",
    "if_add_node_text": "yes",
    # 鏂板锛氬惎鐢ㄥ苟琛屽鐞嗘彁绀鸿瘝锛堟€ц兘浼樺寲锛?
    "use_optimized_prompts": True,
    "prompt_batch_size": 5,  # 姣忔壒骞惰澶勭悊鐨勬彁绀鸿瘝鏁伴噺
}

# 绱㈠紩妯″紡锛歴mart(鏅鸿兘璺敱) / balanced(骞宠　妯″紡) / fast(绮剧畝妯″紡)
PAGEINDEX_MODE = os.getenv("PAGEINDEX_MODE", "balanced").strip().lower()
if PAGEINDEX_MODE not in {"smart", "balanced", "fast"}:
    PAGEINDEX_MODE = "balanced"

PAGEINDEX_FAST_ENABLED = PAGEINDEX_MODE in {"fast", "smart"} or _env_bool(
    "PAGEINDEX_FAST_ENABLED", False
)

# 鍗曟枃妗ｇ储寮曞叏灞€瓒呮椂锛堢锛?
# 浠?800绉掓敼涓?00绉掞細鏀硅繘鍚庣殑Branch B澧炲姞浜哣LM璋冪敤娆℃暟锛?0娆¤皟鐢?60绉?600绉?
# 濡傛灉瓒呰繃10鍒嗛挓浠嶆湭瀹屾垚锛岃鏄庡鐞嗗崱浣忥紝搴旀爣璁颁负澶辫触
PAGEINDEX_MAX_INDEX_SECONDS = int(os.getenv("PAGEINDEX_MAX_INDEX_SECONDS", "600"))

# Batch indexing controls. Upload bursts enqueue jobs and let a small worker pool
# consume them, preventing per-document model concurrency from multiplying.
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

# 鍚姩鏃跺洖鏀堕暱鏃堕棿澶勪簬 processing 鐨勪换鍔★紙鍒嗛挓锛?
INDEXING_STUCK_THRESHOLD_MINUTES = int(
    os.getenv("INDEXING_STUCK_THRESHOLD_MINUTES", "30")
)

# Fast 妯″紡锛氬熀浜庣洰褰曠粨鏋勭敓鎴愯交閲忔枃妗ｆ憳瑕侊紙鍚屾祦绋嬪唴锛岃秴鏃惰烦杩囷級
PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED = _env_bool(
    "PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED", True
)
PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS = float(
    os.getenv("PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS", "15")
)
PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES = int(
    os.getenv("PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES", "20")
)

# 棰勫垎鏋愯矾鐢遍槇鍊硷紙fast -> balanced锛?
PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD = int(
    os.getenv("PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD", "60")
)
PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD = float(
    os.getenv("PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD", "0.15")
)
PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD = float(
    os.getenv("PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD", "0.78")
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
                    "if_add_doc_description": "yes",
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
            "if_add_doc_description": "yes",
            "if_add_node_text": "yes",
            "index_mode": "fast",
        }
    )
    return cfg


EFFECTIVE_PAGEINDEX_CONFIG = build_effective_pageindex_config()

# 鏂囦欢涓婁紶闄愬埗
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
