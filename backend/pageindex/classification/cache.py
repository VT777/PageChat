"""Classification Cache - Using project standard cache_service"""

import time
from typing import Dict, Optional
from app.services.cache_service import cache_service


class ClassificationCache:
    """Caches document classification results using project standard cache"""

    def __init__(self, ttl_seconds: int = 600):  # 10 minutes default
        self.ttl = ttl_seconds
        self._memory_cache: Dict[str, tuple] = {}  # L1: In-memory cache
        self.cache_service = cache_service  # L2: Project standard cache

    def get(self, doc_id: str) -> Optional[Dict]:
        """Get cached classification result"""
        # L1: Check memory cache first
        if doc_id in self._memory_cache:
            cached_data, timestamp = self._memory_cache[doc_id]
            if time.time() - timestamp < self.ttl:
                return cached_data
            else:
                # Expired, remove from memory
                del self._memory_cache[doc_id]

        # L2: Check project cache service using LLM cache (since classification is LLM-based)
        # Using a classification prefix to namespace the keys
        cache_key = f"classification:{doc_id}"
        cached_result = self.cache_service._llm_cache.get(cache_key)

        if cached_result:
            # Backfill to memory cache
            self._memory_cache[doc_id] = (cached_result, time.time())
            return cached_result

        return None

    def set(self, doc_id: str, result: Dict):
        """Set classification result in cache"""
        # L1: Memory cache
        self._memory_cache[doc_id] = (result, time.time())

        # L2: Project cache service (persistent)
        # Using LLM cache since classification is LLM-based
        cache_key = f"classification:{doc_id}"
        self.cache_service._llm_cache.set(cache_key, result)

    def invalidate(self, doc_id: str):
        """Invalidate cache for specific document"""
        if doc_id in self._memory_cache:
            del self._memory_cache[doc_id]

        cache_key = f"doc_classification:{doc_id}"
        # Note: cache_service doesn't have delete, will expire naturally

    def clear(self):
        """Clear all cached entries"""
        self._memory_cache.clear()
