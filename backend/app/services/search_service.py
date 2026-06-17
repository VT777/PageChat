"""
文档搜索服务 - BM25 + bge-small 轻量级重排序架构
优化目标：<2秒搜索，支持高/低置信度判断
"""

import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"jieba(\.|$)")
warnings.filterwarnings("ignore", category=UserWarning, module=r"jieba\._compat")

import bm25s
import jieba
import numpy as np
import aiosqlite
from datetime import datetime
from app.models.retrieval import build_source_display_label

# 设置HuggingFace镜像以加速下载
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 导入轻量级语义模型
try:
    from sentence_transformers import SentenceTransformer, util

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None
    util = None
    SENTENCE_TRANSFORMERS_AVAILABLE = False


@dataclass
class SearchResult:
    """搜索结果"""

    doc_id: str
    doc_name: str
    score: float
    reason: str
    matched_segments: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_source: str = "document_search"
    confidence: float = 0.0
    why_selected: str = ""
    source_anchor: Optional[Dict[str, Any]] = None
    display_label: Optional[str] = None


@dataclass
class SearchResponse:
    """搜索响应（统一格式）"""

    status: str  # "success", "partial", "none"
    documents: List[SearchResult]
    confidence: str  # "high", "medium", "low"
    total_candidates: int
    search_method: str  # "bm25", "bm25_rerank"
    query_used: str = ""
    query_effective: str = ""


# Query expansion prompt
EXPAND_QUERY_PROMPT = """Expand the user query with helpful synonyms and aliases to improve document retrieval recall.

User query: {query}

Requirements:
1. Preserve the query's core meaning.
2. Add English equivalents when useful.
3. Add common abbreviations, aliases, and synonyms.
4. Keep the expansion concise; do not over-expand.
5. Output only the expanded query string. Do not explain.

Examples:
Input: introduce Bilibili
Output: introduce Bilibili video platform company profile

Input: AI Agent market analysis
Output: AI Agent market analysis artificial intelligence agent autonomous agent market

Expanded query:"""


class DocumentSearchService:
    """
    文档搜索服务 - BM25 + bge-small轻量级重排序 + 自动查询扩展

    性能目标：
    - 查询扩展(LLM): ~500ms（首次）/ 0ms（缓存）
    - BM25召回: ~50ms
    - bge-small重排: ~500ms
    - 总计: ~1秒
    """

    def __init__(self):
        self.bm25_index = None
        self.doc_corpus = []  # [segment_text]
        self.segment_metadata = []  # [segment_meta]
        self.doc_metadata = {}  # doc_id -> {name, description}
        self.rerank_model = None
        self._initialized = False
        self._query_cache = {}  # {(user_id, route_version, query): (...)}
        self._cache_ttl = 300  # 缓存5分钟
        self._rebuild_lock: Optional[asyncio.Lock] = None
        self.last_rebuild_at: Optional[str] = None
        self.last_index_doc_count: int = 0
        self.last_index_max_updated: Optional[str] = None

    def _get_rebuild_lock(self) -> asyncio.Lock:
        if self._rebuild_lock is None:
            self._rebuild_lock = asyncio.Lock()
        return self._rebuild_lock

    @staticmethod
    def _format_from_metadata(meta: Dict[str, Any]) -> str:
        file_type = str(meta.get("file_type") or "").lstrip(".").lower()
        if file_type:
            return file_type
        suffix = os.path.splitext(str(meta.get("doc_name") or ""))[1].lstrip(".")
        return suffix.lower() or "pdf"

    @classmethod
    def _source_anchor_from_segment(
        cls, meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        anchor = meta.get("source_anchor")
        if isinstance(anchor, dict) and anchor:
            normalized = dict(anchor)
            if not normalized.get("unit_type"):
                if "start_line" in normalized or "end_line" in normalized:
                    normalized["unit_type"] = "line"
                elif "start_paragraph" in normalized or "end_paragraph" in normalized:
                    normalized["unit_type"] = "paragraph"
                elif "start_row" in normalized or "end_row" in normalized:
                    normalized["unit_type"] = "row_range"
                elif "start_slide" in normalized or "end_slide" in normalized or "slide" in normalized:
                    normalized["unit_type"] = "slide"
                    if "slide" in normalized and "start_slide" not in normalized:
                        normalized["start_slide"] = normalized["slide"]
                    if "slide" in normalized and "end_slide" not in normalized:
                        normalized["end_slide"] = normalized["slide"]
                elif "start_page" in normalized or "end_page" in normalized or "page" in normalized:
                    normalized["unit_type"] = "page"
                    if "page" in normalized and "start_page" not in normalized:
                        normalized["start_page"] = normalized["page"]
                    if "page" in normalized and "end_page" not in normalized:
                        normalized["end_page"] = normalized["page"]
            return normalized
        start_index = meta.get("start_index")
        if start_index is None:
            return None
        end_index = meta.get("end_index") if meta.get("end_index") is not None else start_index
        return {
            "format": cls._format_from_metadata(meta),
            "unit_type": "page",
            "start_page": start_index,
            "end_page": end_index,
        }

    @classmethod
    def _trace_for_segment(
        cls, meta: Dict[str, Any], score: float
    ) -> Dict[str, Any]:
        anchor = cls._source_anchor_from_segment(meta)
        doc_name = str(meta.get("doc_name") or "")
        display_label = (
            build_source_display_label(doc_name, anchor) if anchor else None
        )
        return {
            "retrieval_source": "document_search",
            "confidence": round(float(score), 4),
            "why_selected": "Matched document search index.",
            "source_anchor": anchor,
            "display_label": display_label,
        }

    async def initialize(self):
        """初始化索引和模型"""
        if self._initialized:
            return

        print("[SearchService] Initializing search service...")

        # 加载轻量级重排序模型
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            print("[SearchService] Loading bge-small model...")
            try:
                # 使用bge-small轻量级模型（~100MB vs ~2.3GB）
                self.rerank_model = SentenceTransformer(
                    "BAAI/bge-small-zh-v1.5", device="cpu"
                )
                print("[SearchService] bge-small model loaded")
            except Exception as e:
                print(f"[SearchService] Warning: Failed to load bge-small: {e}")
                self.rerank_model = None

        # 构建BM25索引
        try:
            await self.rebuild_index()
        except Exception as e:
            print(f"[SearchService] Warning: Failed to build initial index: {e}")

        self._initialized = True
        print("[SearchService] Initialization complete!")

    async def _fetch_db_index_state(self) -> Dict[str, Any]:
        from app.models.database import DB_PATH

        async with aiosqlite.connect(str(DB_PATH)) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) as cnt, MAX(updated_at) as max_updated
                FROM documents
                WHERE status = 'completed'
                """
            )
            row = await cursor.fetchone()
            return {
                "count": int(row[0] or 0),
                "max_updated": row[1],
            }

    async def ensure_index_fresh(self) -> None:
        """确保搜索索引与数据库已完成文档状态一致。"""
        if not self._initialized:
            await self.initialize()
            return

        state = await self._fetch_db_index_state()
        needs_rebuild = (
            state["count"] != self.last_index_doc_count
            or state["max_updated"] != self.last_index_max_updated
            or self.bm25_index is None
        )

        if needs_rebuild:
            await self.rebuild_index()

    async def _expand_query(self, query: str, user_id: str) -> str:
        """使用轻量级LLM自动扩展查询（带缓存）

        Args:
            query: 原始查询

        Returns:
            expanded_query: 扩展后的查询
        """
        import time

        route = await self._resolve_query_expansion_route(user_id)
        cache_key = (user_id, route["route_version"], query)

        # 检查缓存
        if cache_key in self._query_cache:
            expanded, timestamp = self._query_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                print(
                    f"[SearchService] Query cache hit: '{query}' -> '{expanded[:50]}...'"
                )
                return expanded

        # 调用LLM扩展查询
        try:
            from app.core.llm import async_chat_completion

            print(f"[SearchService] Expanding query with LLM: '{query}'")
            start_time = time.time()

            prompt = EXPAND_QUERY_PROMPT.format(query=query)

            response = await async_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=route["model"],
                provider_config=route.get("provider_config"),
                temperature=0,
                max_tokens=100,
            )

            expanded = response.choices[0].message.content.strip()

            # 清理输出（移除可能的引号）
            expanded = expanded.strip('"').strip("'")

            elapsed = time.time() - start_time
            print(
                f"[SearchService] Query expanded in {elapsed:.2f}s: '{query}' -> '{expanded[:50]}...'"
            )

            # 缓存结果
            self._query_cache[cache_key] = (expanded, time.time())

            return expanded

        except Exception as e:
            print(f"[SearchService] Warning: Query expansion failed: {e}")
            # 失败时返回原查询
            return query

    async def _resolve_query_expansion_route(self, user_id: str) -> Dict[str, Any]:
        try:
            from app.models.database import DB_PATH
            from app.services.model_settings_service import ModelSettingsService

            async with aiosqlite.connect(str(DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                resolved = await ModelSettingsService(db).resolve_route(
                    user_id, "query_expansion"
                )
                return {
                    "route_version": resolved["route_version"],
                    "provider_config": resolved
                    if resolved.get("source") == "user"
                    else None,
                    "model": resolved["model"],
                }
        except Exception:
            return {
                "route_version": "environment:qwen-turbo",
                "provider_config": None,
                "model": "qwen-turbo",
            }

    async def rebuild_index(self):
        """全量重建索引"""
        from app.services.pageindex_service import PageIndexService
        from app.models.database import DB_PATH
        from pageindex.utils import structure_to_list

        lock = self._get_rebuild_lock()
        async with lock:
            await self._rebuild_index_locked(DB_PATH, structure_to_list)

    async def _rebuild_index_locked(self, db_path, structure_to_list):
        """执行真正的索引重建（需在锁内调用）。"""
        from app.services.pageindex_service import PageIndexService

        index_service = PageIndexService()

        try:
            async with aiosqlite.connect(str(db_path)) as db:
                cursor = await db.execute(
                    """
                    SELECT id, original_name, description, updated_at, user_id, folder_id, folder_path, file_type
                    FROM documents
                    WHERE status = 'completed'
                    """
                )
                rows = await cursor.fetchall()

            docs = []
            for row in rows:
                docs.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "description": row[2],
                        "updated_at": row[3],
                        "user_id": row[4],
                        "folder_id": row[5],
                        "folder_path": row[6],
                        "file_type": row[7],
                    }
                )

            if not docs:
                print("[SearchService] No indexed documents found")
                self.bm25_index = None
                self.doc_corpus = []
                self.segment_metadata = []
                self.doc_metadata = {}
                self.last_index_doc_count = 0
                self.last_index_max_updated = None
                self.last_rebuild_at = datetime.utcnow().isoformat()
                return

            corpus: List[str] = []
            segment_metadata: List[Dict[str, Any]] = []
            metadata = {}

            for doc in docs:
                doc_id = doc["id"]
                doc_name = doc["name"]
                doc_desc = doc["description"]
                doc_user_id = doc.get("user_id")
                doc_folder_id = doc.get("folder_id")
                doc_folder_path = doc.get("folder_path")
                doc_file_type = doc.get("file_type")
                desc = doc_desc or doc_name
                metadata[doc_id] = {
                    "name": doc_name,
                    "description": desc,
                    "user_id": doc_user_id,
                    "folder_id": doc_folder_id,
                    "folder_path": doc_folder_path,
                    "file_type": doc_file_type,
                }

                index_data = await index_service.load_index(doc_id)
                nodes = []
                if isinstance(index_data, dict):
                    structure = index_data.get("structure", index_data)
                    nodes = structure_to_list(structure)

                if nodes:
                    for node in nodes:
                        title = (node.get("title") or "").strip()
                        summary = (node.get("summary") or "").strip()
                        text = (node.get("text") or "").strip()
                        segment_text = " ".join(
                            part for part in [title, summary, text] if part
                        )[:2000]
                        if not segment_text:
                            continue

                        corpus.append(segment_text)
                        segment_metadata.append(
                            {
                                "doc_id": doc_id,
                                "doc_name": doc_name,
                                "user_id": doc_user_id,
                                "folder_id": doc_folder_id,
                                "folder_path": doc_folder_path,
                                "file_type": doc_file_type,
                                "node_id": node.get("node_id"),
                                "title": title,
                                "node_type": node.get("node_type"),
                                "catalog_type": node.get("catalog_type"),
                                "is_auxiliary": bool(node.get("is_auxiliary")),
                                "start_index": node.get("start_index"),
                                "end_index": node.get("end_index"),
                                "source_anchor": node.get("source_anchor"),
                                "snippet": (text or summary or title)[:320],
                            }
                        )
                else:
                    # 索引文件缺失/无节点时兜底到文档级描述
                    fallback_text = desc.strip()
                    if fallback_text:
                        corpus.append(fallback_text)
                        segment_metadata.append(
                            {
                                "doc_id": doc_id,
                                "doc_name": doc_name,
                                "user_id": doc_user_id,
                                "folder_id": doc_folder_id,
                                "folder_path": doc_folder_path,
                                "file_type": doc_file_type,
                                "node_id": None,
                                "title": "文档摘要",
                                "start_index": None,
                                "end_index": None,
                                "source_anchor": None,
                                "snippet": fallback_text[:320],
                            }
                        )

            if corpus:
                tokenized_corpus = [jieba.lcut(doc.lower()) for doc in corpus]
                self.bm25_index = bm25s.BM25()
                self.bm25_index.index(tokenized_corpus)
                self.doc_corpus = corpus
                self.segment_metadata = segment_metadata
                self.doc_metadata = metadata
                self.last_index_doc_count = len(metadata)
                self.last_index_max_updated = max(
                    (d.get("updated_at") for d in docs if d.get("updated_at")),
                    default=None,
                )
                self.last_rebuild_at = datetime.utcnow().isoformat()

                print(
                    f"[SearchService] Index rebuilt: {len(metadata)} documents, {len(corpus)} segments"
                )
        except Exception as e:
            print(f"[SearchService] Error rebuilding index: {e}")
            raise

    async def search(
        self,
        query: str,
        expanded_query: Optional[str] = None,
        top_k: int = 5,
        recall_k: int = 20,
        high_confidence_threshold: float = 0.7,
        auto_expand: bool = True,  # 是否自动扩展查询
        user_id: str = None,
        allowed_doc_ids: Optional[List[str]] = None,
        preferred_doc_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        include_subfolders: bool = False,
        document_ids: Optional[List[str]] = None,
    ) -> SearchResponse:
        """
        搜索主入口 - BM25 + bge-small rerank + 自动查询扩展

        Args:
            query: 原始查询
            expanded_query: 扩展查询（可选，如果提供则跳过自动扩展）
            top_k: 返回结果数
            recall_k: BM25召回数
            high_confidence_threshold: 高置信度阈值
            auto_expand: 是否自动使用LLM扩展查询

        Returns:
            SearchResponse: 统一格式的搜索结果
        """
        if not user_id:
            raise ValueError("user_id is required for document search")

        if not self._initialized:
            await self.initialize()

        await self.ensure_index_fresh()

        if not self.doc_corpus:
            return SearchResponse(
                status="none",
                documents=[],
                confidence="low",
                total_candidates=0,
                search_method="none",
                query_used=query,
                query_effective=query,
            )

        try:
            allowed_set = (
                set(allowed_doc_ids) if allowed_doc_ids is not None else None
            )
            document_set = set(document_ids) if document_ids is not None else None
            scope_folder_path = folder_path or self._folder_path_for_scope(folder_id)

            # ===== Stage 0: 查询扩展（自动）=====
            if expanded_query:
                # 使用提供的扩展查询
                search_query = expanded_query
                print(
                    f"[SearchService] Using provided expanded query: '{search_query[:50]}...'"
                )
            elif auto_expand and self._should_expand_query(query):
                # 自动扩展查询
                search_query = await self._expand_query(query, user_id=user_id)
            else:
                # 使用原查询
                search_query = query

            # ===== Stage 1: BM25召回 =====
            effective_query = search_query
            query_tokens = jieba.lcut(effective_query.lower())
            retrieve_k = len(self.doc_corpus)
            bm25_results = self.bm25_index.retrieve([query_tokens], k=retrieve_k)

            raw_indices = np.asarray(bm25_results[0])
            raw_scores = np.asarray(bm25_results[1], dtype=float)
            indices_row = raw_indices[0] if raw_indices.ndim > 1 else raw_indices
            scores_row = raw_scores[0] if raw_scores.ndim > 1 else raw_scores

            candidate_pairs = []
            for idx_val, score_val in zip(indices_row.tolist(), scores_row.tolist()):
                try:
                    idx = int(idx_val)
                    if idx < 0 or idx >= len(self.doc_corpus):
                        continue
                    candidate_pairs.append((idx, float(score_val)))
                except Exception:
                    continue

            # 先按用户和允许范围过滤，再进行后续重排，避免跨用户候选进入结果
            candidate_pairs = [
                (idx, score)
                for idx, score in candidate_pairs
                if self.segment_metadata[idx].get("user_id") == user_id
            ]
            if allowed_set is not None:
                candidate_pairs = [
                    (idx, score)
                    for idx, score in candidate_pairs
                    if self.segment_metadata[idx].get("doc_id") in allowed_set
                ]
            if document_set is not None:
                candidate_pairs = [
                    (idx, score)
                    for idx, score in candidate_pairs
                    if self.segment_metadata[idx].get("doc_id") in document_set
                ]
            if folder_id or scope_folder_path:
                candidate_pairs = [
                    (idx, score)
                    for idx, score in candidate_pairs
                    if self._segment_matches_folder_scope(
                        self.segment_metadata[idx],
                        folder_id=folder_id,
                        folder_path=scope_folder_path,
                        include_subfolders=include_subfolders,
                    )
                ]

            # 控制重排规模：先保留BM25前N候选
            max_candidates_for_rerank = min(max(recall_k, top_k * 4), 24)
            candidate_pairs = candidate_pairs[:max_candidates_for_rerank]

            if not candidate_pairs:
                return SearchResponse(
                    status="none",
                    documents=[],
                    confidence="low",
                    total_candidates=0,
                    search_method="bm25",
                    query_used=search_query,
                    query_effective=effective_query,
                )

            candidate_indices = [idx for idx, _ in candidate_pairs]
            bm25_scores = np.array([score for _, score in candidate_pairs], dtype=float)
            candidates = [self.doc_corpus[i] for i in candidate_indices]
            candidate_meta = [self.segment_metadata[i] for i in candidate_indices]
            print(
                f"[SearchService] BM25 recalled {len(candidates)} segment candidates (rerank limit={max_candidates_for_rerank})"
            )

            # ===== Stage 2: bge-small重排序（如果可用）=====
            if self.rerank_model and len(candidates) > 0:
                print("[SearchService] Reranking with bge-small...")

                doc_texts = candidates

                # 计算语义相似度
                query_embedding = self.rerank_model.encode(
                    search_query, convert_to_tensor=True
                )
                doc_embeddings = self.rerank_model.encode(
                    doc_texts, convert_to_tensor=True
                )
                similarities = util.cos_sim(query_embedding, doc_embeddings)[0]

                # 合并BM25分数和语义分数
                bm25_norm = (bm25_scores - bm25_scores.min()) / (
                    bm25_scores.max() - bm25_scores.min() + 1e-8
                )
                semantic_norm = (similarities.cpu().numpy() + 1) / 2  # [-1,1] -> [0,1]

                # 加权融合：70%语义 + 30%BM25
                final_scores = 0.7 * semantic_norm + 0.3 * bm25_norm

                search_method = "bm25_rerank"
            else:
                # 只用BM25分数
                bm25_norm = (bm25_scores - bm25_scores.min()) / (
                    bm25_scores.max() - bm25_scores.min() + 1e-8
                )
                final_scores = bm25_norm
                search_method = "bm25"

            # ===== Stage 3: 构建结果 =====
            preferred_set = set(preferred_doc_ids or [])

            doc_grouped: Dict[str, Dict[str, Any]] = {}
            for i, seg_meta in enumerate(candidate_meta):
                doc_id = seg_meta.get("doc_id")
                if not doc_id:
                    continue
                if seg_meta.get("user_id") != user_id:
                    continue
                if allowed_set is not None and doc_id not in allowed_set:
                    continue
                if document_set is not None and doc_id not in document_set:
                    continue
                if folder_id or scope_folder_path:
                    if not self._segment_matches_folder_scope(
                        seg_meta,
                        folder_id=folder_id,
                        folder_path=scope_folder_path,
                        include_subfolders=include_subfolders,
                    ):
                        continue
                score = float(final_scores[i])
                current = doc_grouped.get(doc_id)
                if current is None:
                    doc_grouped[doc_id] = {
                        "doc_name": seg_meta.get("doc_name", ""),
                        "best_score": score,
                        "segments": [],
                    }
                else:
                    current["best_score"] = max(current["best_score"], score)

                segment_trace = self._trace_for_segment(seg_meta, score)
                doc_grouped[doc_id]["segments"].append(
                    {
                        "node_id": seg_meta.get("node_id"),
                        "title": seg_meta.get("title", ""),
                        "node_type": seg_meta.get("node_type"),
                        "catalog_type": seg_meta.get("catalog_type"),
                        "is_auxiliary": bool(seg_meta.get("is_auxiliary")),
                        "snippet": seg_meta.get("snippet", ""),
                        "score": round(score, 4),
                        "start_index": seg_meta.get("start_index"),
                        "end_index": seg_meta.get("end_index"),
                        "source_anchor": segment_trace["source_anchor"],
                        "retrieval_source": segment_trace["retrieval_source"],
                        "confidence": segment_trace["confidence"],
                        "why_selected": segment_trace["why_selected"],
                        "display_label": segment_trace["display_label"],
                    }
                )

            results: List[SearchResult] = []
            for doc_id, info in doc_grouped.items():
                segments = sorted(
                    info["segments"], key=lambda x: x.get("score", 0.0), reverse=True
                )[:3]
                score = float(info["best_score"])
                if preferred_set and doc_id in preferred_set:
                    score = min(score + 0.08, 1.0)
                top_segment = segments[0] if segments else {}
                results.append(
                    SearchResult(
                        doc_id=doc_id,
                        doc_name=info["doc_name"],
                        score=score,
                        reason="语义+BM25节点级匹配"
                        if search_method == "bm25_rerank"
                        else "BM25节点级关键词匹配",
                        matched_segments=segments,
                        retrieval_source="document_search",
                        confidence=score,
                        why_selected="Matched document search index.",
                        source_anchor=top_segment.get("source_anchor"),
                        display_label=top_segment.get("display_label"),
                    )
                )

            results.sort(key=lambda x: x.score, reverse=True)
            top_results = results[:top_k]

            print(
                f"[SearchService] Top score: {top_results[0].score:.3f}"
                if top_results
                else "No results"
            )

            # ===== Stage 4: 置信度判断 =====
            if not top_results:
                confidence = "low"
                status = "none"
            elif top_results[0].score >= high_confidence_threshold:
                confidence = "high"
                status = "success"
            elif top_results[0].score >= 0.3:
                confidence = "medium"
                status = "partial"
            else:
                confidence = "low"
                status = "partial"

            return SearchResponse(
                status=status,
                documents=top_results,
                confidence=confidence,
                total_candidates=len(candidates),
                search_method=search_method,
                query_used=search_query,
                query_effective=effective_query,
            )

        except Exception as e:
            print(f"[SearchService] Search error: {e}")
            import traceback

            traceback.print_exc()
            return SearchResponse(
                status="none",
                documents=[],
                confidence="low",
                total_candidates=0,
                search_method="error",
                query_used=query,
                query_effective=query,
            )

    def _folder_path_for_scope(self, folder_id: Optional[str]) -> Optional[str]:
        if not folder_id:
            return None
        for meta in self.doc_metadata.values():
            if meta.get("folder_id") == folder_id and meta.get("folder_path"):
                return meta.get("folder_path")
        for meta in self.segment_metadata:
            if meta.get("folder_id") == folder_id and meta.get("folder_path"):
                return meta.get("folder_path")
        return None

    @staticmethod
    def _segment_matches_folder_scope(
        meta: Dict[str, Any],
        folder_id: Optional[str] = None,
        folder_path: Optional[str] = None,
        include_subfolders: bool = False,
    ) -> bool:
        segment_folder_id = meta.get("folder_id")
        segment_folder_path = meta.get("folder_path")

        if folder_id and segment_folder_id == folder_id:
            return True

        if not folder_path:
            return False

        if segment_folder_path == folder_path:
            return True

        return bool(
            include_subfolders
            and isinstance(segment_folder_path, str)
            and segment_folder_path.startswith(f"{folder_path}/")
        )

    async def get_document_count(self) -> int:
        """获取文档数量"""
        return len(self.doc_corpus)

    @staticmethod
    def _should_expand_query(query: str) -> bool:
        q = (query or "").strip()
        if not q:
            return False
        # 对较短、较模糊查询才扩展；长查询或多词查询直接检索以降低时延
        if " " in q or len(q) >= 12:
            return False
        return True

    def get_index_snapshot(
        self, user_id: str = None, allowed_doc_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        snapshot = {
            "doc_count": self.last_index_doc_count,
            "segment_count": len(self.doc_corpus),
            "last_rebuild_at": self.last_rebuild_at,
            "last_index_max_updated": self.last_index_max_updated,
        }
        if user_id:
            allowed_set = (
                set(allowed_doc_ids) if allowed_doc_ids is not None else None
            )
            scope_doc_ids = []
            for doc_id, meta in self.doc_metadata.items():
                if meta.get("user_id") != user_id:
                    continue
                if allowed_set is not None and doc_id not in allowed_set:
                    continue
                scope_doc_ids.append(doc_id)
            snapshot["scope_doc_count"] = len(scope_doc_ids)
            snapshot["scope_segment_count"] = len(
                [
                    meta
                    for meta in self.segment_metadata
                    if meta.get("user_id") == user_id
                    and (allowed_set is None or meta.get("doc_id") in allowed_set)
                ]
            )
            snapshot["scope_ids"] = scope_doc_ids[:10]
        elif allowed_doc_ids is not None:
            allowed_set = set(allowed_doc_ids)
            scope_doc_ids = [
                doc_id for doc_id in self.doc_metadata.keys() if doc_id in allowed_set
            ]
            snapshot["scope_doc_count"] = len(scope_doc_ids)
            snapshot["scope_segment_count"] = len(
                [
                    meta
                    for meta in self.segment_metadata
                    if meta.get("doc_id") in allowed_set
                ]
            )
            snapshot["scope_ids"] = scope_doc_ids[:10]
        return snapshot


# 全局实例
search_service = DocumentSearchService()
