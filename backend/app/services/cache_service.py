"""
缓存服务 - 提供搜索结果和LLM响应的内存缓存
"""

import time
import hashlib
import json
from typing import Any, Optional, Dict, List
from functools import lru_cache
from collections import OrderedDict
import threading


class LRUCache:
    """线程安全的LRU缓存"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]
            # 检查是否过期
            if time.time() - entry["timestamp"] > self._ttl_seconds:
                del self._cache[key]
                self._misses += 1
                return None

            # 移到最新位置
            self._cache.move_to_end(key)
            self._hits += 1
            return entry["value"]

    def set(self, key: str, value: Any):
        with self._lock:
            if key in self._cache:
                # 更新现有条目
                self._cache[key]["value"] = value
                self._cache[key]["timestamp"] = time.time()
                self._cache.move_to_end(key)
            else:
                # 添加新条目
                if len(self._cache) >= self._max_size:
                    # 删除最旧的条目
                    self._cache.popitem(last=False)

                self._cache[key] = {
                    "value": value,
                    "timestamp": time.time(),
                }

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0,
                "ttl_seconds": self._ttl_seconds,
            }


class CacheService:
    """缓存服务单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True

        # 搜索结果缓存（10分钟TTL）
        self._search_cache = LRUCache(max_size=500, ttl_seconds=600)

        # LLM响应缓存（1小时TTL）
        self._llm_cache = LRUCache(max_size=1000, ttl_seconds=3600)

        # 文档结构缓存（24小时TTL）
        self._structure_cache = LRUCache(max_size=100, ttl_seconds=86400)

        # 页面内容缓存（30分钟TTL）
        self._page_content_cache = LRUCache(max_size=2000, ttl_seconds=1800)

    def _make_key(self, *args) -> str:
        """生成缓存键"""
        content = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()

    # ==================== 搜索结果缓存 ====================

    def get_search_result(
        self, user_id: str, query: str, doc_ids: List[str]
    ) -> Optional[List[Dict]]:
        key = self._make_key("search", user_id, query, sorted(doc_ids))
        return self._search_cache.get(key)

    def set_search_result(
        self, user_id: str, query: str, doc_ids: List[str], results: List[Dict]
    ):
        key = self._make_key("search", user_id, query, sorted(doc_ids))
        self._search_cache.set(key, results)

    # ==================== LLM响应缓存 ====================

    def get_llm_response(self, messages: List[Dict], model: str) -> Optional[str]:
        key = self._make_key("llm", model, messages)
        return self._llm_cache.get(key)

    def set_llm_response(self, messages: List[Dict], model: str, response: str):
        key = self._make_key("llm", model, messages)
        self._llm_cache.set(key, response)

    # ==================== 文档结构缓存 ====================

    def get_structure(self, user_id: str, doc_id: str) -> Optional[Dict]:
        key = self._make_key("structure", user_id, doc_id)
        return self._structure_cache.get(key)

    def set_structure(self, user_id: str, doc_id: str, structure: Dict):
        key = self._make_key("structure", user_id, doc_id)
        self._structure_cache.set(key, structure)

    # ==================== 页面内容缓存 ====================

    def get_page_content(
        self,
        user_id: str,
        doc_id: str,
        page_num: int,
        include_image: bool,
    ) -> Optional[Dict[str, Any]]:
        key = self._make_key("page", user_id, doc_id, page_num, include_image)
        return self._page_content_cache.get(key)

    def set_page_content(
        self,
        user_id: str,
        doc_id: str,
        page_num: int,
        include_image: bool,
        result: Dict[str, Any],
    ):
        key = self._make_key("page", user_id, doc_id, page_num, include_image)
        self._page_content_cache.set(key, result)

    # ==================== 统计信息 ====================

    def get_stats(self) -> Dict[str, Any]:
        return {
            "search_cache": self._search_cache.get_stats(),
            "llm_cache": self._llm_cache.get_stats(),
            "structure_cache": self._structure_cache.get_stats(),
            "page_content_cache": self._page_content_cache.get_stats(),
        }

    def clear_all(self):
        self._search_cache.clear()
        self._llm_cache.clear()
        self._structure_cache.clear()
        self._page_content_cache.clear()

    def clear_search_cache(self):
        self._search_cache.clear()


# 全局缓存实例
cache_service = CacheService()
