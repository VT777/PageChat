"""
工具执行器 - PageChat Agent
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
from app.services.retrieval_policy import normalize_folder_id
from app.services.cache_service import cache_service
from app.services.table_analysis_service import TableAnalysisService
from app.services.source_anchor_resolver import resolve_source_anchor
from app.services.document_keyword_locator import locate_keywords_in_index
from app.core.config import DATA_DIR, INDEXES_DIR


MAX_PAGE_CONTENT_PAGES = 10
MAX_TEXT_PAGE_CHARS = 4000
MAX_STRUCTURE_ITEMS_PER_PART = 80
DEFAULT_BROWSE_PAGE_SIZE = 20
INDEX_ASSET_ROOTS = (INDEXES_DIR, DATA_DIR / "index_assets")


# ============================================================
# 工具定义 (Function Calling) - 匹配 PageIndex 官方流程
# ============================================================
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "view_folder_structure",
            "description": "View the current user's folder tree when folder location or available subfolders matter. Returns folder metadata only, never document text.",
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
            "description": "Browse or search documents in a folder/library scope when the user asks about available files or candidate documents. Returns compact metadata only, not document evidence.",
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
            "description": "Read the document structure, including section titles, page ranges, and summaries, when section/page-range context is useful. Prefer doc_id; doc_name + folder_id is supported when unique.",
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
            "name": "get_page_content",
            "description": "Read specific source pages. Text pages return text; visual pages return image references only so the model can inspect images with get_document_image or get_page_image.",
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
                        "description": "1-based pages as a string such as 1-3,8,10-12, a number, or a list of numbers.",
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
                    "doc_name": {
                        "type": "string",
                        "description": "Document name when doc_id is not available.",
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "Folder ID used with doc_name disambiguation.",
                    },
                    "page": {
                        "type": "integer",
                        "description": "1-based page number.",
                    },
                },
                "required": ["page"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_within_document",
            "description": "Deterministic keyword/phrase search within one specified document only. Requires doc_id and returns compact page/image matches, not full document text.",
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
            "name": "aggregate_tables",
            "description": "Run aggregate analysis across table documents (csv/tsv/xlsx). Supports sum, avg, count, groupby, and concat. Returns structured source citations for PageChat to render.",
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

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    @classmethod
    def _is_controlled_asset_path(cls, storage_path: Path) -> bool:
        return any(cls._path_is_under(storage_path, root) for root in INDEX_ASSET_ROOTS)

    @staticmethod
    def _browse_offset_to_page(offset: str) -> int:
        try:
            return max(int(offset or "1"), 1)
        except Exception:
            return 1

    @staticmethod
    def _doc_matches_folder_scope(
        doc,
        folder_id: Optional[str],
        recursive: bool,
        folder_path: Optional[str] = None,
    ) -> bool:
        folder_id = ToolExecutor._normalize_root_folder_id(folder_id)
        if not folder_id:
            return True
        if getattr(doc, "folder_id", None) == folder_id:
            return True
        if not recursive:
            return False
        doc_folder_path = getattr(doc, "folder_path", None) or ""
        if folder_path and doc_folder_path:
            return doc_folder_path == folder_path or doc_folder_path.startswith(
                f"{folder_path}/"
            )
        return False

    async def _resolve_document(
        self,
        doc_id: Optional[str] = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ):
        if doc_id:
            if self._is_doc_allowed(doc_id):
                doc = await self.document_service.get_document(doc_id, user_id=self.user_id)
                if doc:
                    return doc, None

            doc, error = await self._resolve_document_by_name(
                doc_id,
                folder_id=folder_id,
                original_input_kind="doc_id",
            )
            if doc:
                return doc, None
            return None, error

        if not doc_name:
            return None, self._document_error(
                "doc_id or doc_name is required",
                "Use browse_documents() to find a document id before reading document content.",
            )

        return await self._resolve_document_by_name(doc_name, folder_id=folder_id)

    async def _resolve_document_by_name(
        self,
        doc_name: str,
        *,
        folder_id: Optional[str] = None,
        original_input_kind: str = "doc_name",
    ):
        docs = await self.document_service.get_indexed_documents(user_id=self.user_id)
        if self.allowed_doc_ids is not None:
            docs = [doc for doc in docs if doc.id in self.allowed_doc_ids]
        candidates = [
            doc
            for doc in docs
            if (doc.original_name == doc_name or doc.name == doc_name)
            and (not folder_id or doc.folder_id == folder_id)
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if not candidates:
            return None, self._document_error(
                f"Document {doc_name} was not found or is outside the current scope.",
                f"Use browse_documents(query='{doc_name}') to find the correct document id.",
            )
        return None, {
            "status": "error",
            "error": (
                f"{original_input_kind} '{doc_name}' matches multiple documents. "
                "Use a specific doc_id."
            ),
            "candidates": [self._compact_document_item(doc) for doc in candidates],
            "next_steps": [
                "Choose one candidate document id and retry the same tool call with doc_id."
            ],
        }

    @staticmethod
    def _document_error(message: str, *next_steps: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "error": message,
            "next_steps": [step for step in next_steps if step],
        }

    @staticmethod
    def _normalize_root_folder_id(folder_id: Optional[str]) -> Optional[str]:
        return normalize_folder_id(folder_id)

    @staticmethod
    def _parse_page_request(
        page_nums: Any = None, pages: Any = None, limit: bool = True
    ) -> List[int]:
        raw = pages if pages is not None else page_nums
        if raw is None:
            return []
        values: List[int] = []
        if isinstance(raw, int):
            values = [raw]
        elif isinstance(raw, str):
            text = raw.strip().replace("，", ",").replace("–", "-").replace("—", "-")
            for part in (segment.strip() for segment in text.split(",")):
                if not part:
                    continue
                if "-" in part:
                    left, right = part.split("-", 1)
                    if not left.strip() or not right.strip():
                        raise ValueError(f"Invalid page range: {part}")
                    start = int(left.strip())
                    end = int(right.strip())
                    if end < start:
                        raise ValueError(f"Invalid descending page range: {part}")
                    values.extend(range(start, end + 1))
                else:
                    values.append(int(part))
        elif isinstance(raw, list):
            values = [int(item) for item in raw]
        else:
            values = [int(raw)]

        normalized: List[int] = []
        for page in values:
            if page > 0 and page not in normalized:
                normalized.append(page)
        return normalized[:MAX_PAGE_CONTENT_PAGES] if limit else normalized

    @staticmethod
    def _page_range_label(pages: List[int]) -> str:
        if not pages:
            return ""
        if len(pages) == 1:
            return str(pages[0])
        parts: List[str] = []
        start = pages[0]
        previous = pages[0]
        for page in pages[1:]:
            if page == previous + 1:
                previous = page
                continue
            parts.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = page
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        return ",".join(parts)

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

    @staticmethod
    def _paginate_structure(
        structure: Any, part: int
    ) -> tuple[Any, bool, int]:
        if not isinstance(structure, list):
            return structure, False, 1
        safe_part = max(int(part or 1), 1)
        start = (safe_part - 1) * MAX_STRUCTURE_ITEMS_PER_PART
        end = start + MAX_STRUCTURE_ITEMS_PER_PART
        return structure[start:end], end < len(structure), safe_part

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具并返回结果"""
        try:
            if tool_name == "get_document_image":
                doc_id = arguments.get("doc_id")
                if doc_id and not self._is_doc_allowed(doc_id):
                    return {"success": False, "status": "error", "error": "文档不存在或无访问权限"}

            if tool_name == "view_folder_structure":
                return await self._view_folder_structure(**arguments)
            elif tool_name == "browse_documents":
                return await self._browse_documents(**arguments)
            elif tool_name == "web_search":
                return await self._web_search(**arguments)
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
            paged_toc, has_more_parts, safe_part = self._paginate_structure(
                cached_toc, part
            )
            return {
                "success": True,
                "doc_id": doc_id,
                "doc_name": doc.original_name,
                "file_type": doc.file_type,
                "total_pages": doc.page_count,
                "part": safe_part,
                "has_more_parts": has_more_parts,
                "structure": paged_toc,
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

        paged_toc, has_more_parts, safe_part = self._paginate_structure(toc, part)
        result = {
            "success": True,
            "doc_id": doc_id,
            "doc_name": doc.original_name,
            "file_type": doc.file_type,
            "total_pages": doc.page_count,
            "part": safe_part,
            "has_more_parts": has_more_parts,
            "structure": paged_toc,
            "cache_hit": False,
            "next_steps": (
                "Structure part retrieved; request the next part only if missing sections matter."
                if has_more_parts
                else "Structure retrieved; choose page, search, or image tools only if the question needs more source evidence."
            ),
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
        try:
            requested_page_numbers = self._parse_page_request(
                page_nums=page_nums, pages=pages, limit=False
            )
        except (TypeError, ValueError) as exc:
            return {
                "success": False,
                "status": "error",
                "data": {},
                "error": f"Invalid pages: {exc}",
                "next_steps": ['Use pages like "1-3,8,10-12".'],
            }
        page_numbers = requested_page_numbers[:MAX_PAGE_CONTENT_PAGES]
        if not page_numbers:
            return {
                "success": False,
                "status": "error",
                "data": {},
                "error": "Invalid pages: pages is required",
                "next_steps": ['Use pages like "1-3,8,10-12".'],
            }
        request_truncated = len(requested_page_numbers) > len(page_numbers)

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

        all_nodes = self._flatten_structure_nodes(nodes)

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
            next_steps = (
                f"Pages {has_visual_pages} need visual evidence; use get_document_image(image_path) "
                "when an image_path exists, otherwise get_page_image for the page."
            )
        else:
            next_steps = (
                "Page text retrieved; answer if evidence is enough, or read/search only for a specific remaining gap."
            )
        if request_truncated:
            next_steps = (
                f"{next_steps} Returned at most {MAX_PAGE_CONTENT_PAGES} pages; 继续 request later pages separately if needed."
            )

        return {
            "status": "success",
            "data": {
                "doc_id": doc_id,
                "doc_name": doc.original_name,
                "content": content,
                "pages": content,
                "total_pages": doc.page_count,
                "requested_pages": self._page_range_label(requested_page_numbers),
                "returned_pages": self._page_range_label(
                    [p["page"] for p in content if "error" not in p]
                ),
                "request_truncated": request_truncated,
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

        # Prefer the most specific section covering the page; root TOC nodes often
        # span the whole document and would otherwise hide the real page section.
        target_node = self._find_best_node_for_page(all_nodes, page_num)

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

        images = self._images_for_page(index_data, target_node, page_num, doc)
        has_visual = self._is_visual_or_ocr_page(
            index_data=index_data,
            page_entry=page_entry,
            target_node=target_node,
            page_num=page_num,
            images=images,
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

        if not has_visual and target_node and target_node.get("summary"):
            result["node_summary"] = target_node.get("summary", "")[:300]

        return result

    @staticmethod
    def _flatten_structure_nodes(nodes: Any) -> List[Dict[str, Any]]:
        flattened: List[Dict[str, Any]] = []
        if isinstance(nodes, dict):
            nodes = [nodes]
        if not isinstance(nodes, list):
            return flattened
        for node in nodes:
            if not isinstance(node, dict):
                continue
            flattened.append(node)
            flattened.extend(ToolExecutor._flatten_structure_nodes(node.get("nodes") or []))
            flattened.extend(ToolExecutor._flatten_structure_nodes(node.get("children") or []))
        return flattened

    @staticmethod
    def _find_best_node_for_page(all_nodes: List[Dict[str, Any]], page_num: int) -> Optional[Dict[str, Any]]:
        containing: List[tuple[tuple[int, int, int, int], Dict[str, Any]]] = []
        for index, node in enumerate(all_nodes):
            start, end = ToolExecutor._node_page_range(node)
            if start and end and start <= page_num <= end:
                title = str(node.get("title") or "").strip().lower()
                toc_penalty = 1 if title in {"目录", "preface", "contents", "table of contents"} else 0
                auxiliary_penalty = 1 if node.get("is_auxiliary") else 0
                containing.append(((end - start, toc_penalty, auxiliary_penalty, index), node))
        if containing:
            return min(containing, key=lambda item: item[0])[1]

        for node in all_nodes:
            start, _ = ToolExecutor._node_page_range(node)
            if start and start >= page_num:
                return node
        return all_nodes[-1] if all_nodes else None

    @staticmethod
    def _node_page_range(node: Dict[str, Any]) -> tuple[int, int]:
        try:
            start = int(node.get("start_index") or node.get("physical_index") or 0)
        except (TypeError, ValueError):
            start = 0
        try:
            end = int(node.get("end_index") or start or 0)
        except (TypeError, ValueError):
            end = start
        if start and end and end < start:
            end = start
        return start, end

    @staticmethod
    def _page_entry(index_data: Any, page_num: int) -> Dict[str, Any]:
        if not isinstance(index_data, dict):
            return {}
        for page in index_data.get("pages") or []:
            if isinstance(page, dict) and int(page.get("page") or 0) == int(page_num):
                return page
        return {}

    @classmethod
    def _is_visual_or_ocr_page(
        cls,
        *,
        index_data: Any,
        page_entry: Any,
        target_node: Any,
        page_num: int,
        images: List[Dict[str, Any]],
    ) -> bool:
        if images:
            return True
        for record in (page_entry, target_node):
            if not isinstance(record, dict):
                continue
            if record.get("ocr_used") or record.get("has_visual_content") or record.get("images"):
                return True
        if isinstance(index_data, dict):
            for key in ("page_text_map_ocr_pages", "ocr_pages", "visual_pages"):
                if cls._page_in_marker_list(index_data.get(key), page_num):
                    return True
        return False

    @staticmethod
    def _page_in_marker_list(values: Any, page_num: int) -> bool:
        if not isinstance(values, list):
            return False
        for value in values:
            try:
                if int(value) == int(page_num):
                    return True
            except (TypeError, ValueError):
                if isinstance(value, dict):
                    for key in ("page", "page_num", "physical_index", "start_index"):
                        try:
                            if int(value.get(key) or 0) == int(page_num):
                                return True
                        except (TypeError, ValueError):
                            continue
        return False

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
            if not self._is_doc_allowed(doc_id):
                return {"success": False, "error": "文档不存在或无访问权限"}
            return await self._get_page_image(doc_id=doc_id, page=page or page_num)
        if not image_path:
            return {"success": False, "error": "image_path is required"}

        image_path = str(image_path).strip()
        if image_path.startswith("page://"):
            try:
                _, rest = image_path.split("://", 1)
                fallback_doc_id, fallback_page = rest.strip("/").split("/", 1)
                if not self._is_doc_allowed(fallback_doc_id):
                    return {"success": False, "error": "文档不存在或无访问权限"}
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
                if not self._is_controlled_asset_path(storage_path):
                    return {
                        "success": False,
                        "error": "Indexed image asset access denied",
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

    async def _get_page_image(
        self,
        doc_id: Optional[str] = None,
        page: Optional[int] = None,
        page_num: Optional[int] = None,
        doc_name: Optional[str] = None,
        folder_id: Optional[str] = None,
    ) -> dict:
        """获取指定页面的整页图片（base64格式）- 视觉 fallback。"""
        page_num = int(page if page is not None else page_num or 0)
        doc, error = await self._resolve_document(doc_id, doc_name, folder_id)
        if error:
            return {"status": "error", "data": {}, **error}
        doc_id = doc.id

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
            "next_steps": (
                f"{total_folders} folder(s), {self._folder_tree_depth(folders)} level(s) deep. "
                "Use a folder id with browse_documents only if folder contents matter."
            ),
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
        scope_folder_path = None
        if folder_id:
            for doc in docs:
                if getattr(doc, "folder_id", None) == folder_id and getattr(
                    doc, "folder_path", None
                ):
                    scope_folder_path = doc.folder_path
                    break
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
                    if not self._doc_matches_folder_scope(
                        doc, folder_id, recursive, scope_folder_path
                    ):
                        continue
                    item = self._compact_document_item(doc)
                else:
                    if folder_id:
                        continue
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
        elif recursive:
            folders = []
            if folder_id and not scope_folder_path:
                folder = await FolderService().get_folder(folder_id, user_id=self.user_id)
                scope_folder_path = folder.path if folder else None
            document_items = [
                self._compact_document_item(doc)
                for doc in docs
                if self._doc_matches_folder_scope(
                    doc, folder_id, True, scope_folder_path
                )
            ]
            has_more = False
            current_page = 1
        else:
            folder_service = FolderService()
            page = self._browse_offset_to_page(offset)
            data = await folder_service.get_compact_folder_contents(
                folder_id=folder_id,
                page=page,
                page_size=DEFAULT_BROWSE_PAGE_SIZE,
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
            total_documents = int(data.get("total_documents") or len(document_items))
            page_size = int(data.get("page_size") or DEFAULT_BROWSE_PAGE_SIZE)
            current_page = int(data.get("page") or page)
            has_more = total_documents > current_page * page_size

        if sort in {"name", "created_at", "updated_at"} and sort != "relevance":
            document_items.sort(key=lambda item: str(item.get(sort) or item.get("name") or ""))

        if query or explicit_doc_ids:
            has_more = False
            current_page = 1

        return {
            "success": True,
            "sort": sort or ("relevance" if query else "updated_at"),
            "folders": folders,
            "documents": document_items,
            "has_more": has_more,
            "next_offset": str(current_page + 1) if has_more else "",
            "next_steps": (
                f"Showing {len(folders)} folder(s) and {len(document_items)} document(s). "
                "If contents matter, choose structure, search, page, or image tools based on the information gap; "
                "retry with recursive=true or a refined query if candidates miss the intent."
            ),
        }

    async def _web_search(self, query: str, **_kwargs) -> dict:
        query = (query or "").strip()
        if not query:
            return {
                "success": False,
                "status": "error",
                "tool_name": "web_search",
                "query": query,
                "results": [],
                "error": "Web Search query is required.",
            }
        return {
            "success": False,
            "status": "error",
            "tool_name": "web_search",
            "query": query,
            "results": [],
            "error": (
                "Web Search is not configured. Configure a search provider before "
                "enabling Web Search."
            ),
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

        structure = await self.pageindex_service.load_index(doc.id)
        if not structure:
            return {"success": False, "error": f"文档 {doc.id} 的索引不存在"}

        return locate_keywords_in_index(
            index_data=structure,
            query=query,
            doc_id=doc.id,
            doc_name=doc.original_name,
        )
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
                    "suggested_tool": "browse_documents",
                    "reason": "聚合文档列表为空或不可访问",
                    "options": ["先浏览文档并确认ID", "重新传入 document_ids"],
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
