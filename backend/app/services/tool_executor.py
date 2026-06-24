"""
工具执行器 - KnowClaw Agent
基于 PageIndex 官方工具定义
"""

import json
import base64
import mimetypes
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.services.pageindex_service import PageIndexService
from app.services.document_service import DocumentService
from app.services.folder_service import FolderService
from app.services.cache_service import cache_service
from app.services.table_analysis_service import TableAnalysisService
from app.services.source_anchor_resolver import resolve_source_anchor


MAX_PAGE_CONTENT_PAGES = 10
MAX_TEXT_PAGE_CHARS = 4000


# ============================================================
# 工具定义 (Function Calling) - 匹配 PageIndex 官方流程
# ============================================================
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "view_folder_structure",
            "description": "View the current user's folder structure before browsing scoped documents. Returns folder metadata only, never document text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID to focus on. Omit or use root for the root library.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_documents",
            "description": "Browse or search documents in a folder/library scope. Returns compact document metadata only; use get_document_structure and get_page_content for evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Optional folder ID. Omit for root or whole-library search.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional search query. When omitted, browse folder contents.",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to include subfolders.",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["relevance", "created_at", "updated_at", "name"],
                        "description": "Sort mode. Use relevance when query is present.",
                    },
                    "offset": {
                        "type": "string",
                        "description": "Opaque pagination offset.",
                    },
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit document ID scope supplied by the application.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_structure",
            "description": "Read the document structure, including section titles, page ranges, and summaries. Use it before reading pages. Prefer doc_id; doc_name + folder_id is supported when unique.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID",
                    },
                    "doc_name": {
                        "type": "string",
                        "description": "Document name when doc_id is not available.",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID used with doc_name disambiguation.",
                    },
                    "part": {
                        "type": "integer",
                        "description": "Structure page part for long structures.",
                    },
                    "compact": {
                        "type": "boolean",
                        "description": "Return hierarchy-preserving compact tree for agent retrieval.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_folder_tree",
            "description": "Get the current user's folder tree before scoped retrieval when the user mentions a folder, category, library area, or current scope.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_folder_contents",
            "description": "Get compact child folders and documents for a folder without returning full document text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID. Omit for the root folder level.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Document page number for paginated contents.",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Number of documents per page.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": "Read specific pages. Text pages return text; visual pages return image references only so the model can inspect images with get_document_image or get_page_image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID",
                    },
                    "doc_name": {
                        "type": "string",
                        "description": "Document name when doc_id is not available.",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID used with doc_name disambiguation.",
                    },
                    "pages": {
                        "description": "1-based pages as a string range like 28-36, a number, or a list of numbers.",
                    },
                    "page_nums": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Backward-compatible 1-based page number list.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_image",
            "description": "View an indexed embedded document image/figure by image_path returned from get_page_content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "Logical image path such as report.pdf/img-45.jpeg.",
                    },
                },
                "required": ["image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_image",
            "description": "Render a full PDF page image as visual fallback when no indexed embedded image is available or the user needs the whole page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Document ID",
                    },
                    "page": {
                        "type": "integer",
                        "description": "1-based page number.",
                    },
                },
                "required": ["doc_id", "page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_within_document",
            "description": "Search within one specified document only. Requires doc_id and returns compact page/section matches, not full document text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Required document ID scope.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Keyword or phrase to locate inside the document.",
                    },
                },
                "required": ["doc_id", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_related_documents",
            "description": "Compatibility retrieval tool that returns detailed matching diagnostics. Prefer browse_documents for normal document discovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Query text or keywords.",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Optional folder ID for scoped search.",
                    },
                    "include_subfolders": {
                        "type": "boolean",
                        "description": "Whether folder search includes descendants.",
                    },
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional document ID scope.",
                    },
                    "strict_scope": {
                        "type": "boolean",
                        "description": "When true, do not search outside selected scope.",
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
            "description": "List all uploaded documents. Use when the user asks what documents are available.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_tables",
            "description": "Run aggregate analysis across table documents (csv/tsv/xlsx). Supports sum, avg, count, groupby, and concat. Cite source documents with [[document_name p.x]].",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Document ID list for analysis.",
                    },
                    "operation_spec": {
                        "type": "object",
                        "description": "Aggregation parameters such as operation, group_by, target_column, or metric.",
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

    async def _resolve_document(
        self,
        doc_id: Optional[str] = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ):
        if doc_id:
            if not self._is_doc_allowed(doc_id):
                return None, {"error": "文档不存在或无访问权限"}
            doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
            if not doc:
                return None, {"error": f"文档 {doc_id} 不存在"}
            return doc, None

        if not doc_name:
            return None, {"error": "doc_id or doc_name is required"}

        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        if self.allowed_doc_ids is not None:
            docs = [doc for doc in docs if doc.id in self.allowed_doc_ids]
        candidates = [
            doc
            for doc in docs
            if doc.original_name == doc_name
            and (not folder_id or doc.folder_id == folder_id)
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if not candidates:
            return None, {"error": f"未找到文档: {doc_name}"}
        return None, {
            "error": "文档名称不唯一，请使用 doc_id",
            "candidates": [self._compact_document_item(doc) for doc in candidates],
        }

    @staticmethod
    def _normalize_root_folder_id(folder_id: Optional[str]) -> Optional[str]:
        return None if folder_id in {None, "", "root", "null", "undefined"} else folder_id

    @staticmethod
    def _parse_page_request(page_nums: Any = None, pages: Any = None) -> List[int]:
        raw = pages if pages is not None else page_nums
        if raw is None:
            return []
        values: List[int] = []
        if isinstance(raw, int):
            values = [raw]
        elif isinstance(raw, str):
            text = raw.strip()
            if "-" in text:
                left, right = text.split("-", 1)
                start = int(left.strip())
                end = int(right.strip())
                step = 1 if end >= start else -1
                values = list(range(start, end + step, step))
            elif "," in text:
                values = [int(part.strip()) for part in text.split(",") if part.strip()]
            elif text:
                values = [int(text)]
        elif isinstance(raw, list):
            values = [int(item) for item in raw]
        else:
            values = [int(raw)]

        normalized: List[int] = []
        for page in values:
            if page > 0 and page not in normalized:
                normalized.append(page)
        return normalized[:MAX_PAGE_CONTENT_PAGES]

    @staticmethod
    def _page_range_label(pages: List[int]) -> str:
        if not pages:
            return ""
        if len(pages) == 1:
            return str(pages[0])
        if pages == list(range(pages[0], pages[-1] + 1)):
            return f"{pages[0]}-{pages[-1]}"
        return ",".join(str(page) for page in pages)

    @staticmethod
    def _compact_document_item(doc) -> Dict[str, Any]:
        return {
            "doc_id": doc.id,
            "name": doc.original_name,
            "path": doc.folder_path or "root",
            "folder_id": doc.folder_id,
            "status": doc.status,
            "created_at": str(doc.created_at) if doc.created_at is not None else None,
            "description": doc.description or "",
            "page_count": doc.page_count,
        }

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具并返回结果"""
        try:
            if tool_name in {
                "get_document_structure",
                "get_page_content",
                "get_page_image",
                "search_within_document",
            }:
                doc_id = arguments.get("doc_id")
                if doc_id and not self._is_doc_allowed(doc_id):
                    return {"error": "文档不存在或无访问权限"}

            if tool_name == "view_folder_structure":
                return await self._view_folder_structure(**arguments)
            elif tool_name == "browse_documents":
                return await self._browse_documents(**arguments)
            elif tool_name == "get_document_structure":
                return await self._get_document_structure(**arguments)
            elif tool_name == "get_page_content":
                return await self._get_page_content(**arguments)
            elif tool_name == "get_document_image":
                return await self._get_document_image(**arguments)
            elif tool_name == "get_page_image":
                return await self._get_page_image(**arguments)
            elif tool_name == "search_within_document":
                return await self._search_within_document(**arguments)
            elif tool_name == "find_related_documents":
                return await self._find_related_documents(**arguments)
            elif tool_name == "list_folder_tree":
                return await self._list_folder_tree()
            elif tool_name == "list_folder_contents":
                return await self._list_folder_contents(**arguments)
            elif tool_name == "list_documents":
                return await self._list_documents()
            elif tool_name == "aggregate_tables":
                return await self._aggregate_tables(**arguments)
            else:
                return {"error": f"未知工具: {tool_name}"}
        except Exception as e:
            return {"error": f"工具 {tool_name} 执行失败: {str(e)}"}

    async def _get_document_structure(
        self,
        doc_id: Optional[str] = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
        part: int = 1,
        compact: bool = False,
    ) -> dict:
        """获取文档目录结构 - PageIndex 核心工具"""
        doc, error = await self._resolve_document(doc_id, doc_name, folder_id)
        if error:
            return error
        doc_id = doc.id

        cached_toc = cache_service.get_structure(self.user_id, doc_id)
        if cached_toc is not None and not compact:
            return {
                "success": True,
                "doc_id": doc_id,
                "doc_name": doc.original_name,
                "file_type": doc.file_type,
                "total_pages": doc.page_count,
                "part": int(part or 1),
                "has_more_parts": False,
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

        if compact:
            toc = self._build_compact_structure(nodes)
        else:
            toc = self._extract_structure(nodes, doc.file_type)
            cache_service.set_structure(self.user_id, doc_id, toc)

        result = {
            "success": True,
            "doc_id": doc_id,
            "doc_name": doc.original_name,
            "file_type": doc.file_type,
            "total_pages": doc.page_count,
            "part": int(part or 1),
            "has_more_parts": False,
            "structure": toc,
            "cache_hit": False,
            "next_steps": {
                "summary": "Document structure retrieved successfully.",
                "options": ["Use get_page_content() to read specific source pages."],
            },
        }
        if compact:
            result["structure_format"] = "compact_tree"
            quality_report = (
                structure.get("quality_report") if isinstance(structure, dict) else None
            )
            if isinstance(quality_report, dict):
                result["quality_report"] = quality_report
                result["retrieval_guidance"] = self._structure_retrieval_guidance(
                    quality_report
                )
        return result

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
        self,
        doc_id: Optional[str] = None,
        page_nums: Any = None,
        pages: Any = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> dict:
        """读取页面内容。图片页只返回图片引用，不返回 OCR/正文全文。"""
        page_numbers = self._parse_page_request(page_nums=page_nums, pages=pages)
        if not page_numbers:
            return {"status": "error", "data": {}, "error": "pages is required"}

        doc, error = await self._resolve_document(doc_id, doc_name, folder_id)
        if error:
            return {"status": "error", "data": {}, **error}
        doc_id = doc.id

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
        content = []
        has_visual_pages = []

        for page_num in page_numbers:
            try:
                page_data = await self._get_single_page_info(
                    doc, page_num, all_nodes, structure
                )
                content.append(page_data)
                if page_data.get("visual_evidence_required"):
                    has_visual_pages.append(page_num)
            except Exception as e:
                content.append({"page": page_num, "page_num": page_num, "error": str(e)})

        # 构建 next_steps
        if has_visual_pages:
            next_steps = {
                "options": [
                    f"第 {has_visual_pages} 页包含视觉内容，页面文本已省略",
                    "优先使用 get_document_image(image_path) 查看嵌入图片；若 image_path 为 page:// 或没有嵌入图，使用 get_page_image",
                ],
                "auto_retry": "调用图片工具获取视觉证据",
                "summary": f"获取成功，{len(has_visual_pages)} 页需要视觉证据",
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
                "content": content,
                "pages": content,
                "total_pages": doc.page_count,
                "requested_pages": self._page_range_label(page_numbers),
                "returned_pages": self._page_range_label(
                    [p["page"] for p in content if "error" not in p]
                ),
                "total_requested": len(page_numbers),
                "total_returned": len([p for p in content if "error" not in p]),
                "has_errors": any("error" in p for p in content),
                "has_visual_content": len(has_visual_pages) > 0,
                "visual_pages": has_visual_pages,
            },
            "next_steps": next_steps,
        }

    async def _get_single_page_info(self, doc, page_num, all_nodes, index_data):
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

        page_entry = self._page_entry(index_data, page_num)
        text_content = (
            str(page_entry.get("text") or "")
            if page_entry
            else (target_node.get("text", "") if target_node else "")
        )
        text_source = "node"
        if page_entry and page_entry.get("text"):
            text_source = "index_page"

        file_type = (doc.file_type or "").lower()
        page_text = None
        if file_type == ".pdf" and not text_content:
            page_text = self._extract_pdf_page_text(doc.file_path, page_num)
            if page_text:
                text_content = page_text
                text_source = "pdf_page"

        # 检查是否有视觉内容（从 node 的 has_visual_content 字段）
        images = self._images_for_page(index_data, target_node, page_num, doc)
        has_visual = bool(images) or (
            target_node.get("has_visual_content", False) if target_node else False
        )

        # 索引中未标注视觉内容时，回退到单页图片检测（PDF）
        if not has_visual and file_type == ".pdf":
            has_visual = self._pdf_page_has_images(doc.file_path, page_num)
        if has_visual and not images:
            images = [
                {
                    "image_path": f"page://{doc.id}/{page_num}",
                    "alt": f"{doc.original_name} page {page_num}",
                    "mimeType": "image/jpeg",
                    "page": page_num,
                    "fallback_tool": "get_page_image",
                }
            ]

        result = {
            "page": page_num,
            "page_num": page_num,
            "node_id": target_node.get("node_id", "") if target_node else "",
            "node_title": target_node.get("title", "") if target_node else "",
            "text": "",
            "text_source": text_source,
            "images": images,
            "has_visual_content": has_visual,
            "visual_evidence_required": has_visual,
            "cache_hit": False,
        }
        if has_visual:
            result["text_omitted_reason"] = "visual_evidence_required"
        else:
            text = (text_content or "").strip()
            result["text"] = text[:MAX_TEXT_PAGE_CHARS]
            result["text_content"] = result["text"]
            if len(text) > MAX_TEXT_PAGE_CHARS:
                result["text_truncated"] = True
                result["continuation_hint"] = "Read a narrower page range or section."

        if target_node and target_node.get("summary"):
            result["node_summary"] = target_node.get("summary", "")[:300]

        return result

    @staticmethod
    def _page_entry(index_data: Any, page_num: int) -> Dict[str, Any]:
        if not isinstance(index_data, dict):
            return {}
        for page in index_data.get("pages") or []:
            if isinstance(page, dict) and int(page.get("page") or 0) == int(page_num):
                return page
        return {}

    @classmethod
    def _images_for_page(cls, index_data: Any, target_node: Any, page_num: int, doc) -> List[Dict[str, Any]]:
        images: List[Dict[str, Any]] = []
        page_entry = cls._page_entry(index_data, page_num)
        sources = []
        if isinstance(page_entry, dict):
            sources.extend(page_entry.get("images") or [])
        if isinstance(target_node, dict):
            sources.extend(target_node.get("images") or [])
        if isinstance(index_data, dict):
            sources.extend(
                image
                for image in ((index_data.get("assets") or {}).get("images") or [])
                if int(image.get("page") or 0) == int(page_num)
            )

        seen = set()
        for image in sources:
            normalized = cls._normalize_image_ref(image, doc=doc, page_num=page_num)
            image_path = normalized.get("image_path")
            if not image_path or image_path in seen:
                continue
            seen.add(image_path)
            images.append(normalized)
        return images

    @staticmethod
    def _normalize_image_ref(image: Dict[str, Any], doc, page_num: int) -> Dict[str, Any]:
        image_path = str(image.get("image_path") or image.get("path") or "").strip()
        mime_type = (
            image.get("mimeType")
            or image.get("mime_type")
            or mimetypes.guess_type(image_path)[0]
            or "image/jpeg"
        )
        alt = str(image.get("alt") or Path(image_path).name or f"page-{page_num}.jpeg")
        return {
            "image_path": image_path,
            "alt": alt,
            "mimeType": mime_type,
            "page": int(image.get("page") or page_num),
        }

    def _build_compact_structure(self, nodes: list) -> list:
        result = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            item = {
                "node_id": node.get("node_id", ""),
                "title": node.get("title", ""),
                "start_page": node.get("start_index"),
                "end_page": node.get("end_index"),
                "summary": (node.get("summary", "") or "")[:300],
                "children": self._build_compact_structure(node.get("nodes") or []),
            }
            if node.get("source_anchor"):
                item["source_anchor"] = node.get("source_anchor")
            result.append(item)
        return result

    @staticmethod
    def _structure_retrieval_guidance(quality_report: Dict[str, Any]) -> Dict[str, Any]:
        status = quality_report.get("status")
        if status in {"needs_review", "failed:indexing"}:
            return {
                "recommended_next_action": "verify_with_source_content",
                "fallback_suggested": True,
                "reason": "Index quality needs review; verify compact structure against source content before final claims.",
            }
        return {
            "recommended_next_action": "use_structure",
            "fallback_suggested": False,
            "reason": "Index quality is acceptable for tree-first retrieval.",
        }

    async def _resolve_source_anchor_content(self, doc, source_anchor: dict) -> dict:
        return resolve_source_anchor(
            file_path=Path(doc.file_path),
            document_name=doc.original_name,
            anchor=source_anchor,
        )

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

    async def _get_document_image(
        self,
        image_path: Optional[str] = None,
        doc_id: Optional[str] = None,
        page_num: Optional[int] = None,
        page: Optional[int] = None,
    ) -> dict:
        """读取索引阶段持久化的嵌入图片；旧 doc_id/page_num 调用转到 get_page_image。"""
        if not image_path and doc_id:
            return await self._get_page_image(doc_id=doc_id, page=page or page_num)
        if not image_path:
            return {"success": False, "error": "image_path is required"}

        image_path = str(image_path).strip()
        if image_path.startswith("page://"):
            try:
                _, rest = image_path.split("://", 1)
                fallback_doc_id, fallback_page = rest.strip("/").split("/", 1)
                return await self._get_page_image(
                    doc_id=fallback_doc_id, page=int(fallback_page)
                )
            except Exception:
                return {"success": False, "error": "Invalid page image reference"}

        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        if self.allowed_doc_ids is not None:
            docs = [doc for doc in docs if doc.id in self.allowed_doc_ids]

        for doc in docs:
            index_data = await self.pageindex_service.load_index(doc.id)
            if not isinstance(index_data, dict):
                continue
            for image in (index_data.get("assets") or {}).get("images") or []:
                if str(image.get("image_path") or "") != image_path:
                    continue
                storage_path = Path(str(image.get("storage_path") or ""))
                if not storage_path.exists() or not storage_path.is_file():
                    return {
                        "success": False,
                        "error": "Indexed image asset is missing",
                        "image_path": image_path,
                    }
                data = base64.b64encode(storage_path.read_bytes()).decode("ascii")
                mime_type = (
                    image.get("mimeType")
                    or image.get("mime_type")
                    or mimetypes.guess_type(str(storage_path))[0]
                    or "image/jpeg"
                )
                return {
                    "success": True,
                    "status": "success",
                    "data": data,
                    "type": "image",
                    "mimeType": mime_type,
                    "image_path": image_path,
                    "doc_id": doc.id,
                    "doc_name": doc.original_name,
                    "page": image.get("page"),
                }

        return {"success": False, "error": "Image not found or access denied"}

    async def _get_page_image(self, doc_id: str, page: Optional[int] = None, page_num: Optional[int] = None) -> dict:
        """获取指定页面的整页图片（base64格式）- 视觉 fallback。"""
        page_num = int(page if page is not None else page_num or 0)
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
                    "type": "image",
                    "mimeType": "image/jpeg",
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

    async def _view_folder_structure(self, folder_id: Optional[str] = None) -> dict:
        folder_service = FolderService()
        folders = await folder_service.get_compact_folder_tree(user_id=self.user_id)
        total_folders = self._count_folder_nodes(folders)
        tree = {
            "id": "root",
            "name": "root",
            "path": "",
            "children": folders,
            "file_count": 0,
            "children_count": len(folders),
        }
        return {
            "success": True,
            "tree": tree,
            "depth": self._folder_tree_depth(folders),
            "truncated": False,
            "total_folders": total_folders,
            "next_steps": {
                "summary": f"{total_folders} folder(s), {self._folder_tree_depth(folders)} level(s) deep",
                "options": ["Browse folders with documents using browse_documents(folder_id=...)"],
            },
        }

    async def _browse_documents(
        self,
        folder_id: Optional[str] = None,
        query: Optional[str] = None,
        recursive: bool = False,
        sort: str = "relevance",
        offset: str = "",
        document_ids: Optional[List[str]] = None,
        include_subfolders: Optional[bool] = None,
        strict_scope: Optional[bool] = None,
    ) -> dict:
        folder_id = self._normalize_root_folder_id(folder_id)
        if include_subfolders is not None:
            recursive = include_subfolders
        query = (query or "").strip()
        explicit_doc_ids = set(document_ids or [])
        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        if self.allowed_doc_ids is not None:
            docs = [doc for doc in docs if doc.id in self.allowed_doc_ids]
        if explicit_doc_ids:
            docs = [doc for doc in docs if doc.id in explicit_doc_ids]
        doc_map = {doc.id: doc for doc in docs}
        scoped_doc_ids = list(doc_map.keys())
        search_allowed_doc_ids = (
            scoped_doc_ids
            if self.allowed_doc_ids is not None or explicit_doc_ids
            else None
        )

        if query:
            from app.services.search_service import search_service

            response = await search_service.search(
                query=query,
                top_k=10,
                recall_k=min(30, len(search_service.doc_corpus)),
                user_id=self.user_id,
                allowed_doc_ids=search_allowed_doc_ids,
                folder_id=folder_id,
                include_subfolders=recursive,
                document_ids=scoped_doc_ids if explicit_doc_ids else None,
            )
            document_items = []
            seen = set()
            for result in response.documents:
                if result.doc_id in seen or not self._is_doc_allowed(result.doc_id):
                    continue
                seen.add(result.doc_id)
                doc = doc_map.get(result.doc_id)
                if doc is not None:
                    item = self._compact_document_item(doc)
                else:
                    item = {
                        "doc_id": result.doc_id,
                        "name": result.doc_name,
                        "path": "root",
                        "folder_id": None,
                        "status": "completed",
                        "created_at": None,
                        "description": "",
                        "page_count": None,
                    }
                document_items.append(item)
            folders: List[Dict[str, Any]] = []
        elif explicit_doc_ids:
            folders = []
            document_items = [self._compact_document_item(doc) for doc in docs]
        else:
            folder_service = FolderService()
            data = await folder_service.get_compact_folder_contents(
                folder_id=folder_id,
                page=1,
                page_size=20,
                user_id=self.user_id,
            )
            folders = data.get("child_folders") or []
            document_items = [
                {
                    "doc_id": doc.get("doc_id"),
                    "name": doc.get("doc_name"),
                    "path": doc.get("folder_path") or "root",
                    "folder_id": folder_id,
                    "status": doc.get("status"),
                    "created_at": doc.get("created_at"),
                    "description": doc.get("description") or "",
                    "page_count": doc.get("page_count"),
                }
                for doc in (data.get("documents") or [])
                if self._is_doc_allowed(doc.get("doc_id"))
            ]

        if sort in {"name", "created_at", "updated_at"} and sort != "relevance":
            document_items.sort(key=lambda item: str(item.get(sort) or item.get("name") or ""))

        return {
            "success": True,
            "sort": sort or ("relevance" if query else "updated_at"),
            "folders": folders,
            "documents": document_items,
            "has_more": False,
            "next_offset": "",
            "next_steps": {
                "summary": f"Showing {len(folders)} folder(s) and {len(document_items)} document(s)",
                "options": [
                    "Use get_document_structure() before reading pages",
                    "If results do not match the user's intent, retry with recursive=true or a refined query",
                ],
            },
        }

    async def _search_within_document(
        self,
        query: str,
        doc_id: Optional[str] = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> dict:
        if not doc_id and not doc_name:
            return {"success": False, "error": "doc_id is required"}
        doc, error = await self._resolve_document(doc_id, doc_name, folder_id)
        if error:
            return {"success": False, **error}

        from app.services.search_service import search_service

        response = await search_service.search(
            query=query,
            top_k=5,
            recall_k=min(20, len(search_service.doc_corpus)),
            user_id=self.user_id,
            allowed_doc_ids=(
                list(self.allowed_doc_ids)
                if self.allowed_doc_ids is not None
                else None
            ),
            document_ids=[doc.id],
            auto_expand=False,
        )
        matches: List[Dict[str, Any]] = []
        for result in response.documents:
            if result.doc_id != doc.id:
                continue
            for segment in getattr(result, "matched_segments", []) or []:
                matches.append(
                    {
                        "node_id": segment.get("node_id"),
                        "title": segment.get("title", ""),
                        "snippet": segment.get("snippet", ""),
                        "page_range": self._format_page_range(
                            segment.get("start_index"), segment.get("end_index")
                        ),
                    }
                )
        return {
            "success": True,
            "doc_id": doc.id,
            "doc_name": doc.original_name,
            "query": query,
            "matches": matches[:10],
            "next_steps": {
                "summary": f"Found {len(matches[:10])} in-document match(es)",
                "options": ["Use get_page_content() on the cited pages before answering"],
            },
        }

    async def _find_related_documents(
        self,
        query: str,
        expanded_query: str = None,
        user_selected_document_ids: Optional[List[str]] = None,
        allow_global_expansion: bool = True,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        document_ids: Optional[List[str]] = None,
        strict_scope: Optional[bool] = None,
        **kwargs,
    ) -> dict:
        """根据查询内容找相关文档（优先用户指定范围，不自动回退 legacy）"""
        from app.services.search_service import search_service

        uses_explicit_scope = document_ids is not None or folder_id is not None
        requested_document_ids = document_ids if document_ids is not None else user_selected_document_ids
        selected_ids = set(requested_document_ids or [])
        if kwargs.get("doc_id"):
            selected_ids.add(kwargs.get("doc_id"))
        explicit_scope = bool(uses_explicit_scope and (selected_ids or folder_id))
        effective_strict_scope = strict_scope
        if effective_strict_scope is None:
            effective_strict_scope = explicit_scope
        search_document_ids = list(selected_ids) if selected_ids and effective_strict_scope else None
        retrieval_scope = {
            "requested_document_ids": list(selected_ids),
            "requested_folder_id": folder_id,
            "include_subfolders": include_subfolders,
            "strict_scope": bool(effective_strict_scope),
            "expanded_to_user_library": bool(explicit_scope and not effective_strict_scope),
        }

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
                document_ids=search_document_ids,
                folder_id=folder_id if effective_strict_scope else None,
                include_subfolders=include_subfolders,
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
                        "retrieval_source": getattr(
                            r, "retrieval_source", "document_search"
                        ),
                        "confidence": getattr(r, "confidence", r.score),
                        "why_selected": getattr(r, "why_selected", r.reason),
                        "source_anchor": getattr(r, "source_anchor", None),
                        "display_label": getattr(r, "display_label", None),
                    }
                )

            selected_docs = [d for d in all_docs if d["doc_id"] in selected_ids]
            retrieval_mode = "strict_scope" if explicit_scope and effective_strict_scope else "selected_only"
            used_docs = selected_docs if selected_ids else all_docs
            if folder_id and effective_strict_scope:
                used_docs = all_docs

            selected_confidence = "none"
            if selected_docs:
                top_sel = selected_docs[0]["relevance"]
                if top_sel >= 0.7:
                    selected_confidence = "high"
                elif top_sel >= 0.3:
                    selected_confidence = "medium"
                else:
                    selected_confidence = "low"

            if explicit_scope and not effective_strict_scope:
                retrieval_mode = "selected_then_user_library"
                used_docs = all_docs
            elif selected_ids and allow_global_expansion and strict_scope is None:
                need_expand = not selected_docs or selected_docs[0]["relevance"] < 0.55
                if need_expand and all_docs:
                    retrieval_mode = "selected_then_global"
                    used_docs = all_docs

            confidence = response.confidence if used_docs else "low"
            recommended_next_action = self._recommended_next_action(
                used_docs, confidence, is_stats_query=self._is_stats_query(query)
            )

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
                        "scope": retrieval_scope,
                        "relevance_to_selected": selected_confidence,
                        "recommended_document_ids": [],
                        "recommended_next_action": "list_folder_contents" if folder_id else "ask_user",
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
            recommended_next_action = self._recommended_next_action(
                used_docs, confidence, is_stats_query=is_stats_query
            )

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
                    "scope": retrieval_scope,
                    "relevance_to_selected": selected_confidence,
                    "recommended_document_ids": [d["doc_id"] for d in used_docs],
                    "recommended_next_action": recommended_next_action,
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
                    "scope": {
                        "requested_document_ids": list(selected_ids),
                        "requested_folder_id": folder_id,
                        "include_subfolders": include_subfolders,
                        "strict_scope": bool(effective_strict_scope),
                        "expanded_to_user_library": False,
                    },
                    "relevance_to_selected": "none",
                    "recommended_document_ids": [],
                    "recommended_next_action": "ask_user",
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
    def _recommended_next_action(
        documents: List[Dict[str, Any]],
        confidence: str,
        is_stats_query: bool = False,
    ) -> str:
        if is_stats_query and documents:
            return "aggregate_tables"
        if not documents:
            return "ask_user"

        top_segments = documents[0].get("matched_segments") or []
        top_segment = top_segments[0] if top_segments else {}
        if top_segment.get("source_anchor") or top_segment.get("start_index"):
            if confidence in {"high", "medium"}:
                return "get_page_content"
        if confidence in {"high", "medium"}:
            return "get_document_structure"
        return "ask_user"

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

    async def _list_folder_tree(self) -> dict:
        folder_service = FolderService()
        folders = await folder_service.get_compact_folder_tree(user_id=self.user_id)
        return {
            "status": "success",
            "data": {
                "folders": folders,
                "total_folders": self._count_folder_nodes(folders),
            },
            "next_steps": {
                "action": "call_tool",
                "suggested_tool": "list_folder_contents",
                "reason": "Folder tree loaded; inspect a folder before scoped retrieval.",
                "options": ["Call list_folder_contents with the selected folder_id"],
            },
        }

    async def _list_folder_contents(
        self,
        folder_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        folder_service = FolderService()
        data = await folder_service.get_compact_folder_contents(
            folder_id=folder_id,
            page=page,
            page_size=page_size,
            user_id=self.user_id,
        )
        return {
            "status": "success",
            "data": data,
            "next_steps": {
                "action": "call_tool",
                "suggested_tool": "browse_documents",
                "reason": "Folder contents loaded; search within this scope if the question needs evidence.",
                "options": ["Call browse_documents with folder_id and recursive=true when needed"],
            },
        }

    @classmethod
    def _count_folder_nodes(cls, folders: List[Dict[str, Any]]) -> int:
        total = 0
        for folder in folders:
            total += 1
            children = folder.get("children") or []
            if isinstance(children, list):
                total += cls._count_folder_nodes(children)
        return total

    @classmethod
    def _folder_tree_depth(cls, folders: List[Dict[str, Any]]) -> int:
        if not folders:
            return 1
        return 1 + max(
            cls._folder_tree_depth(folder.get("children") or [])
            for folder in folders
        )

    @staticmethod
    def _format_page_range(start: Any, end: Any) -> str:
        if start is None and end is None:
            return ""
        if end is None or end == start:
            return str(start)
        return f"{start}-{end}"

    async def _aggregate_tables(
        self, document_ids: List[str], operation_spec: Dict[str, Any]
    ) -> dict:
        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        doc_map = {d.id: d for d in docs}

        selected = []
        rejected_document_ids = []
        for doc_id in document_ids:
            if self.allowed_doc_ids is not None and doc_id not in self.allowed_doc_ids:
                rejected_document_ids.append(doc_id)
                continue
            doc = doc_map.get(doc_id)
            if doc is not None:
                selected.append(doc)
            else:
                rejected_document_ids.append(doc_id)

        rejected_quality_note = (
            "Some requested document IDs were not accessible or unavailable."
            if rejected_document_ids
            else None
        )

        if not selected:
            quality_notes = ["未找到可访问的目标文档"]
            if rejected_quality_note:
                quality_notes.append(rejected_quality_note)
            return {
                "status": "success",
                "data": {
                    "result_table": [],
                    "schema_mapping": {},
                    "quality_notes": quality_notes,
                    "citations": [],
                    "document_count": 0,
                    "rejected_document_ids": rejected_document_ids,
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
        if rejected_quality_note:
            quality_notes.append(rejected_quality_note)
        table_rows = result.get("result_table", [])

        return {
            "status": "success",
            "data": {
                "result_table": table_rows,
                "schema_mapping": result.get("schema_mapping", {}),
                "quality_notes": quality_notes,
                "citations": result.get("citations", []),
                "document_count": len(selected),
                "rejected_document_ids": rejected_document_ids,
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
