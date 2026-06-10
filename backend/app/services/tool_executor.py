"""
工具执行器 - KnowClaw Agent
基于 PageIndex 官方工具定义
"""

import json
import base64
from typing import Dict, Any, List, Optional
from app.services.pageindex_service import PageIndexService
from app.services.document_service import DocumentService
from app.services.cache_service import cache_service
from app.services.table_analysis_service import TableAnalysisService


# ============================================================
# 工具定义 (Function Calling) - 匹配 PageIndex 官方流程
# ============================================================
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_document_structure",
            "description": "获取文档的目录结构，包括各章节的标题、页码范围和摘要。用于判断相关内容在哪些页面。获取后引用时使用 [[文档名 p.页码]] 格式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "文档ID",
                    },
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": "批量获取指定页码的文本内容（最多5页）。返回内容包含页码信息，引用时必须使用 [[文档名 p.页码]] 格式。若标记 has_visual_content=true 则需要调用 get_document_image 查看图片。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "文档ID",
                    },
                    "page_nums": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "页码列表（从1开始），最多支持5页",
                    },
                },
                "required": ["doc_id", "page_nums"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_image",
            "description": "获取指定页面的图片（base64格式）。仅当 get_page_content 返回 has_visual_content=true 时调用。一次只能获取1页图片，避免token超限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "文档ID",
                    },
                    "page_num": {
                        "type": "integer",
                        "description": "页码（从1开始），一次只能1页",
                    },
                },
                "required": ["doc_id", "page_num"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_related_documents",
            "description": "根据查询内容，从可用文档中找出最相关的文档。当有多个文档可用时，先调此工具确定在哪些文档中查找。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容或关键词",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "获取所有已上传文档的列表。当用户问'我有哪些文档'时使用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_tables",
            "description": "对多个表格文档执行聚合分析（csv/tsv/xlsx）。支持 sum、avg、count、groupby、concat。分析结果需标注来源文档，使用 [[文档名 p.x]] 格式引用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与分析的文档ID列表",
                    },
                    "operation_spec": {
                        "type": "object",
                        "description": "聚合参数，如 operation/group_by/target_column/metric",
                    },
                },
                "required": ["document_ids", "operation_spec"],
            },
        },
    },
]


class ToolExecutor:
    """工具执行器 - 基于 PageIndex 官方流程"""

    def __init__(
        self,
        pageindex_service: PageIndexService,
        document_service: DocumentService,
        user_id: str = None,
        allowed_doc_ids: Optional[List[str]] = None,
    ):
        if not user_id:
            raise ValueError("ToolExecutor requires user_id")
        self.pageindex_service = pageindex_service
        self.document_service = document_service
        self.table_analysis_service = TableAnalysisService()
        self.user_id = user_id
        self.allowed_doc_ids: Optional[set[str]] = (
            set(allowed_doc_ids) if allowed_doc_ids is not None else None
        )

    def set_allowed_doc_ids(self, document_ids: Optional[List[str]]):
        """设置当前会话允许访问的文档范围（用户隔离）"""
        if document_ids is None:
            self.allowed_doc_ids = None
        else:
            self.allowed_doc_ids = set(document_ids)

    def _is_doc_allowed(self, doc_id: str) -> bool:
        if self.allowed_doc_ids is None:
            return True
        return doc_id in self.allowed_doc_ids

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具并返回结果"""
        try:
            if tool_name in {
                "get_document_structure",
                "get_page_content",
                "get_document_image",
            }:
                doc_id = arguments.get("doc_id")
                if doc_id and not self._is_doc_allowed(doc_id):
                    return {"error": "文档不存在或无访问权限"}

            if tool_name == "get_document_structure":
                return await self._get_document_structure(**arguments)
            elif tool_name == "get_page_content":
                return await self._get_page_content(**arguments)
            elif tool_name == "get_document_image":
                return await self._get_document_image(**arguments)
            elif tool_name == "find_related_documents":
                return await self._find_related_documents(**arguments)
            elif tool_name == "list_documents":
                return await self._list_documents()
            elif tool_name == "aggregate_tables":
                return await self._aggregate_tables(**arguments)
            else:
                return {"error": f"未知工具: {tool_name}"}
        except Exception as e:
            return {"error": f"工具 {tool_name} 执行失败: {str(e)}"}

    async def _get_document_structure(self, doc_id: str) -> dict:
        """获取文档目录结构 - PageIndex 核心工具"""
        doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
        if not doc:
            return {"error": f"文档 {doc_id} 不存在"}

        cached_toc = cache_service.get_structure(self.user_id, doc_id)
        if cached_toc is not None:
            return {
                "doc_id": doc_id,
                "doc_name": doc.original_name,
                "file_type": doc.file_type,
                "total_pages": doc.page_count,
                "structure": cached_toc,
                "cache_hit": True,
            }

        structure = await self.pageindex_service.load_index(doc_id)
        if not structure:
            return {"error": f"文档 {doc_id} 的索引不存在，请等待索引完成"}

        # 提取目录结构（标题、页码范围、摘要）
        nodes = structure.get("structure", structure)
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            nodes = []

        toc = self._extract_structure(nodes, doc.file_type)
        cache_service.set_structure(self.user_id, doc_id, toc)

        return {
            "doc_id": doc_id,
            "doc_name": doc.original_name,
            "file_type": doc.file_type,
            "total_pages": doc.page_count,
            "structure": toc,
            "cache_hit": False,
        }

    def _extract_structure(self, nodes: list, file_type: str, level: int = 0) -> list:
        """提取结构化目录信息"""
        result = []
        for node in nodes:
            item = {
                "node_id": node.get("node_id", ""),
                "title": node.get("title", ""),
                "level": level,
                "start_page": node.get("start_index"),
                "end_page": node.get("end_index"),
                "summary": (node.get("summary", "") or "")[:200],
            }
            result.append(item)
            child_nodes = node.get("nodes")
            if isinstance(child_nodes, list) and child_nodes:
                result.extend(
                    self._extract_structure(child_nodes, file_type, level + 1)
                )
        return result

    async def _get_page_content(
        self, doc_id: str, page_nums: list
    ) -> dict:
        """批量获取页面内容（最多5页）- 仅返回文本，图片需单独调用 get_document_image"""
        # 限制最多5页
        if not isinstance(page_nums, list):
            page_nums = [page_nums]
        page_nums = page_nums[:5]

        doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
        if not doc:
            return {"status": "error", "data": {}, "error": f"文档 {doc_id} 不存在"}

        structure = await self.pageindex_service.load_index(doc_id)
        if not structure:
            return {
                "status": "error",
                "data": {},
                "error": f"文档 {doc_id} 的索引不存在",
            }

        # 解析文档结构
        nodes = structure.get("structure", structure)
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            nodes = []

        from pageindex.utils import structure_to_list

        all_nodes = structure_to_list(nodes)

        # 批量获取页面
        pages = []
        has_visual_pages = []

        for page_num in page_nums:
            try:
                page_data = await self._get_single_page_info(doc, page_num, all_nodes)
                pages.append(page_data)
                if page_data.get("has_visual_content"):
                    has_visual_pages.append(page_num)
            except Exception as e:
                pages.append({"page_num": page_num, "error": str(e)})

        # 构建 next_steps
        if has_visual_pages:
            next_steps = {
                "options": [
                    f"页面文本已获取，第 {has_visual_pages} 页包含图表/图片内容",
                    "建议调用 get_document_image 获取这些页面的图片以查看具体数据",
                ],
                "auto_retry": f"调用 get_document_image 获取第 {has_visual_pages[0]} 页图片",
                "summary": f"获取成功，{len(has_visual_pages)} 页包含视觉内容",
            }
        else:
            next_steps = {
                "options": [
                    "页面文本内容已获取，可直接基于文本回答",
                    "如需查看更多页面，继续调用 get_page_content",
                ],
                "auto_retry": "基于当前页面内容组织答案",
                "summary": "文本内容获取成功",
            }

        return {
            "status": "success",
            "data": {
                "doc_id": doc_id,
                "doc_name": doc.original_name,
                "pages": pages,
                "total_requested": len(page_nums),
                "total_returned": len([p for p in pages if "error" not in p]),
                "has_errors": any("error" in p for p in pages),
                "has_visual_content": len(has_visual_pages) > 0,
                "visual_pages": has_visual_pages,
            },
            "next_steps": next_steps,
        }

    async def _get_single_page_info(self, doc, page_num, all_nodes):
        """获取单页信息（内部方法）"""
        # 检查页码有效性
        if doc.page_count and (page_num < 1 or page_num > doc.page_count):
            raise Exception(f"页码 {page_num} 超出范围（文档共 {doc.page_count} 页）")

        # 找到包含该页码的节点
        target_node = None
        for node in all_nodes:
            start = node.get("start_index", 0)
            end = node.get("end_index", 0)
            if start and end and start <= page_num <= end:
                target_node = node
                break

        if not target_node:
            for node in all_nodes:
                if node.get("start_index") and node["start_index"] >= page_num:
                    target_node = node
                    break
            if not target_node and all_nodes:
                target_node = all_nodes[-1]

        text_content = target_node.get("text", "") if target_node else ""
        text_source = "node"

        file_type = (doc.file_type or "").lower()
        page_text = None
        if file_type == ".pdf":
            page_text = self._extract_pdf_page_text(doc.file_path, page_num)
            if page_text:
                text_content = page_text
                text_source = "pdf_page"

        # 检查是否有视觉内容（从 node 的 has_visual_content 字段）
        has_visual = (
            target_node.get("has_visual_content", False) if target_node else False
        )

        # 索引中未标注视觉内容时，回退到单页图片检测（PDF）
        if not has_visual and file_type == ".pdf":
            has_visual = self._pdf_page_has_images(doc.file_path, page_num)

        result = {
            "page_num": page_num,
            "node_id": target_node.get("node_id", "") if target_node else "",
            "node_title": target_node.get("title", "") if target_node else "",
            "text_content": text_content,
            "text_source": text_source,
            "has_visual_content": has_visual,
            "cache_hit": False,
        }

        if target_node and target_node.get("summary"):
            result["node_summary"] = target_node.get("summary", "")[:300]

        return result

    @staticmethod
    def _pdf_page_has_images(pdf_path: str, page_num: int) -> bool:
        """检测 PDF 指定页是否包含图片对象。"""
        try:
            import pymupdf

            doc = pymupdf.open(pdf_path)
            if page_num < 1 or page_num > len(doc):
                doc.close()
                return False
            page = doc[page_num - 1]
            has_images = len(page.get_images(full=True)) > 0
            doc.close()
            return has_images
        except Exception:
            return False

    async def _get_document_image(self, doc_id: str, page_num: int) -> dict:
        """获取指定页面的图片（base64格式）- 单独调用避免token超限"""
        doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
        if not doc:
            return {"status": "error", "data": {}, "error": f"文档 {doc_id} 不存在"}

        # 检查页码有效性
        if doc.page_count and (page_num < 1 or page_num > doc.page_count):
            return {
                "status": "error",
                "data": {},
                "error": f"页码 {page_num} 超出范围（文档共 {doc.page_count} 页）",
            }

        file_type = (doc.file_type or "").lower()
        if file_type != ".pdf":
            return {"status": "error", "data": {}, "error": "仅支持PDF文档的图片提取"}

        try:
            from app.core.llm import pdf_page_to_base64

            # 获取图片
            page_image_base64 = pdf_page_to_base64(doc.file_path, page_num)
            if not page_image_base64:
                return {
                    "status": "error",
                    "data": {},
                    "error": f"无法提取第 {page_num} 页的图片",
                }

            # 计算图片大小（粗略估计）
            image_size_kb = (
                len(page_image_base64) * 0.75 / 1024
            )  # base64 编码约为原始大小的 4/3

            return {
                "status": "success",
                "data": {
                    "doc_id": doc_id,
                    "doc_name": doc.original_name,
                    "page_num": page_num,
                    "image_base64": page_image_base64,
                    "image_format": "jpeg",
                    "image_size_kb": round(image_size_kb, 1),
                },
                "next_steps": {
                    "options": ["图片已获取，可基于图片内容回答用户问题"],
                    "auto_retry": "分析图片中的数据并回答",
                    "summary": "图片获取成功",
                },
            }
        except Exception as e:
            return {"status": "error", "data": {}, "error": f"提取图片失败: {str(e)}"}

    @staticmethod
    def _extract_pdf_page_text(pdf_path: str, page_num: int) -> str:
        """直接提取 PDF 单页文本，优先于节点级聚合文本。"""
        try:
            import pymupdf

            doc = pymupdf.open(pdf_path)
            if page_num < 1 or page_num > len(doc):
                doc.close()
                return ""
            text = (doc[page_num - 1].get_text("text") or "").strip()
            doc.close()
            return text
        except Exception:
            return ""

    async def _find_related_documents(
        self,
        query: str,
        expanded_query: str = None,
        user_selected_document_ids: Optional[List[str]] = None,
        allow_global_expansion: bool = True,
        **kwargs,
    ) -> dict:
        """根据查询内容找相关文档（优先用户指定范围，不自动回退 legacy）"""
        from app.services.search_service import search_service

        selected_ids = set(user_selected_document_ids or [])
        if kwargs.get("doc_id"):
            selected_ids.add(kwargs.get("doc_id"))

        try:
            response = await search_service.search(
                query=query,
                expanded_query=expanded_query,
                top_k=5,
                recall_k=min(20, len(search_service.doc_corpus)),
                high_confidence_threshold=0.7,
                user_id=self.user_id,
                allowed_doc_ids=list(self.allowed_doc_ids)
                if self.allowed_doc_ids is not None
                else None,
                preferred_doc_ids=list(selected_ids) if selected_ids else None,
            )

            all_docs = []
            for r in response.documents:
                if not self._is_doc_allowed(r.doc_id):
                    continue
                all_docs.append(
                    {
                        "doc_id": r.doc_id,
                        "doc_name": r.doc_name,
                        "relevance": round(r.score, 3),
                        "reason": r.reason,
                        "matched_segments": getattr(r, "matched_segments", []),
                    }
                )

            selected_docs = [d for d in all_docs if d["doc_id"] in selected_ids]
            retrieval_mode = "selected_only"
            used_docs = selected_docs if selected_ids else all_docs

            selected_confidence = "none"
            if selected_docs:
                top_sel = selected_docs[0]["relevance"]
                if top_sel >= 0.7:
                    selected_confidence = "high"
                elif top_sel >= 0.3:
                    selected_confidence = "medium"
                else:
                    selected_confidence = "low"

            if selected_ids and allow_global_expansion:
                need_expand = not selected_docs or selected_docs[0]["relevance"] < 0.55
                if need_expand and all_docs:
                    retrieval_mode = "selected_then_global"
                    used_docs = all_docs

            confidence = response.confidence if used_docs else "low"

            if not used_docs:
                return {
                    "status": "success",
                    "data": {
                        "documents": [],
                        "confidence": "low",
                        "total_candidates": 0,
                        "search_method": response.search_method,
                        "query_used": getattr(response, "query_used", query),
                        "query_effective": getattr(response, "query_effective", query),
                        "retrieval_mode": retrieval_mode,
                        "relevance_to_selected": selected_confidence,
                        "recommended_document_ids": [],
                        "fallback_available": True,
                        "fallback_suggested": True,
                        "index_snapshot": search_service.get_index_snapshot(
                            user_id=self.user_id,
                            allowed_doc_ids=(
                                list(self.allowed_doc_ids)
                                if self.allowed_doc_ids is not None
                                else None
                            ),
                        ),
                    },
                    "next_steps": {
                        "action": "call_tool",
                        "suggested_tool": "list_documents",
                        "reason": "BM25+rereank 未命中，不自动回退 legacy",
                        "options": [
                            "先调用 list_documents 查看可用文档",
                            "再尝试 get_document_structure 手动验证目录",
                        ],
                    },
                }

            is_stats_query = self._is_stats_query(query)

            if is_stats_query and used_docs:
                next_steps = {
                    "action": "call_tool",
                    "suggested_tool": "aggregate_tables",
                    "reason": "检测到统计/汇总问题，优先使用 aggregate_tables 获取稳定结果",
                    "options": [
                        "传入 recommended_document_ids 调用 aggregate_tables",
                        "若列名不确定，先 get_page_content 查看表头",
                    ],
                }
            elif confidence == "high":
                next_steps = {
                    "action": "call_tool",
                    "suggested_tool": "get_document_structure",
                    "reason": "相关度高，建议先看目录再定位正文",
                    "options": [
                        f"查看《{used_docs[0]['doc_name']}》目录结构",
                        "继续调用 get_page_content 读取关键内容",
                    ],
                }
            elif confidence == "medium":
                next_steps = {
                    "action": "call_tool",
                    "suggested_tool": "get_document_structure",
                    "reason": "相关度中等，建议先验证文档结构",
                    "options": ["查看目录验证后再读取页面", "必要时调整查询词重试"],
                }
            else:
                next_steps = {
                    "action": "call_tool",
                    "suggested_tool": "list_documents",
                    "reason": "相关度低，不自动回退 legacy，由 agent 决策下一步",
                    "options": ["查看文档列表", "补充关键词后重新检索"],
                }

            return {
                "status": response.status,
                "data": {
                    "documents": used_docs,
                    "confidence": confidence,
                    "total_candidates": len(used_docs),
                    "search_method": response.search_method,
                    "query_used": getattr(response, "query_used", query),
                    "query_effective": getattr(response, "query_effective", query),
                    "retrieval_mode": retrieval_mode,
                    "relevance_to_selected": selected_confidence,
                    "recommended_document_ids": [d["doc_id"] for d in used_docs],
                    "matched_segments": {
                        d["doc_id"]: d.get("matched_segments", [])[:2]
                        for d in used_docs
                    },
                    "fallback_available": True,
                    "fallback_suggested": confidence == "low",
                    "index_snapshot": search_service.get_index_snapshot(
                        user_id=self.user_id,
                        allowed_doc_ids=(
                            list(self.allowed_doc_ids)
                            if self.allowed_doc_ids is not None
                            else None
                        ),
                    ),
                },
                "related_documents": used_docs,
                "next_steps": next_steps,
            }

        except Exception as e:
            print(f"[Search] Error using search service: {e}")
            return {
                "status": "partial",
                "data": {
                    "documents": [],
                    "confidence": "low",
                    "total_candidates": 0,
                    "search_method": "error",
                    "query_used": query,
                    "query_effective": query,
                    "retrieval_mode": "selected_only",
                    "relevance_to_selected": "none",
                    "recommended_document_ids": [],
                    "fallback_available": True,
                    "fallback_suggested": True,
                    "index_snapshot": search_service.get_index_snapshot(
                        user_id=self.user_id,
                        allowed_doc_ids=(
                            list(self.allowed_doc_ids)
                            if self.allowed_doc_ids is not None
                            else None
                        ),
                    ),
                },
                "next_steps": {
                    "action": "call_tool",
                    "suggested_tool": "list_documents",
                    "reason": "检索服务异常，不自动回退 legacy",
                    "options": ["先列文档后手动定位", "稍后重试检索"],
                },
            }

    @staticmethod
    def _is_stats_query(query: str) -> bool:
        q = (query or "").lower()
        keywords = [
            "多少",
            "人数",
            "统计",
            "汇总",
            "总数",
            "总计",
            "平均",
            "占比",
            "分组",
            "group by",
            "count",
            "sum",
            "avg",
        ]
        return any(k in q for k in keywords)

    @staticmethod
    def _format_search_results(results: List[Dict[str, Any]]) -> dict:
        return {
            "results": [
                {
                    "doc_id": r.get("document_id"),
                    "doc_name": r.get("document_name"),
                    "node_title": r.get("node_title"),
                    "page_range": f"{r.get('start_index', '?')}-{r.get('end_index', '?')}",
                    "snippet": (r.get("full_text", "") or "")[:500],
                    "relevance": r.get("relevance", 0),
                }
                for r in results
            ]
        }

    async def _list_documents(self) -> dict:
        """获取文档列表"""
        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        if self.allowed_doc_ids is not None:
            docs = [d for d in docs if d.id in self.allowed_doc_ids]
        return {
            "documents": [
                {
                    "id": doc.id,
                    "name": doc.original_name,
                    "status": doc.status,
                    "file_type": doc.file_type,
                    "page_count": doc.page_count,
                }
                for doc in docs
            ]
        }

    async def _aggregate_tables(
        self, document_ids: List[str], operation_spec: Dict[str, Any]
    ) -> dict:
        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        doc_map = {d.id: d for d in docs}

        selected = []
        for doc_id in document_ids:
            if self.allowed_doc_ids is not None and doc_id not in self.allowed_doc_ids:
                continue
            doc = doc_map.get(doc_id)
            if doc is not None:
                selected.append(doc)

        if not selected:
            return {
                "status": "success",
                "data": {
                    "result_table": [],
                    "schema_mapping": {},
                    "quality_notes": ["未找到可访问的目标文档"],
                    "citations": [],
                },
                "next_steps": {
                    "action": "call_tool",
                    "suggested_tool": "list_documents",
                    "reason": "聚合文档列表为空或不可访问",
                    "options": ["先列出文档并确认ID", "重新传入 document_ids"],
                },
            }

        loaded = self.table_analysis_service.load_table_documents(selected)
        result = self.table_analysis_service.aggregate(
            loaded.get("datasets", []), operation_spec
        )
        quality_notes = loaded.get("quality_notes", []) + result.get(
            "quality_notes", []
        )
        table_rows = result.get("result_table", [])

        return {
            "status": "success",
            "data": {
                "result_table": table_rows,
                "schema_mapping": result.get("schema_mapping", {}),
                "quality_notes": quality_notes,
                "citations": result.get("citations", []),
                "document_count": len(selected),
            },
            "next_steps": {
                "action": "answer" if table_rows else "ask_user",
                "suggested_tool": "aggregate_tables" if not table_rows else "",
                "reason": "聚合结果已生成"
                if table_rows
                else "当前聚合结果为空，请调整参数后重试",
                "options": [
                    "可直接基于 result_table 回答",
                    "如为空请调整 operation_spec",
                ],
            },
        }
