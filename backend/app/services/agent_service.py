"""
Agent 核心服务 - PageChat
基于 PageIndex 官方流程的 Function Calling Agent
支持 thinking 流式展示和多模态 PDF 页面
"""

import json
import time
import logging
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any, Optional
import aiosqlite

tool_logger = logging.getLogger("tool")
agent_logger = logging.getLogger("agent")

from app.services.pageindex_service import PageIndexService
from app.services.document_service import DocumentService
from app.services.folder_service import FolderService
from app.services.tool_executor import ToolExecutor, AGENT_TOOLS
from app.services.web_search_settings_service import (
    DEFAULT_WEB_SEARCH_SETTINGS,
    WebSearchSettingsService,
)
from app.services.web_search_tool import WEB_SEARCH_TOOL, execute_web_search_tool
from app.services.retrieval_planner import RetrievalPlanner
from app.core.config import CHAT_ATTACHMENT_MAX_PER_MESSAGE
from app.services.retrieval_policy import (
    normalize_folder_id,
    question_needs_document_retrieval,
)
from app.core.llm import chat_by_scenario, async_chat_completion
from app.models.retrieval import RetrievalScope
from app.prompts import build_agent_system_prompt, QA_SYSTEM_PROMPT
from app.agent.state import AgentRunState


# 全局会话级缓存（跨请求持久化）
_CONVERSATION_CACHES: Dict[str, Dict[str, Any]] = {}
# 每个会话的完整消息历史（包含工具调用记录，用于多轮对话记忆）
_CONVERSATION_MESSAGES: Dict[str, List[Dict[str, Any]]] = {}

# 不缓存的工具列表（需要实时数据或可能携带大 payload 的工具）
_NON_CACHEABLE_TOOLS = {
    "view_folder_structure",
    "browse_documents",
    "get_document_image",
    "get_page_image",
    "web_search",
}


class AgentLoopToolRunner:
    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        web_search_settings: Dict[str, Any],
    ) -> None:
        self.tool_executor = tool_executor
        self.web_search_settings = web_search_settings

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "web_search":
            return await execute_web_search_tool(
                arguments=arguments,
                settings=self.web_search_settings,
            )
        return await self.tool_executor.execute(tool_name, arguments)


def clear_conversation_cache(conversation_id: Optional[str] = None):
    """清除会话缓存

    Args:
        conversation_id: 指定会话ID则清除该会话缓存，None则清除所有缓存
    """
    global _CONVERSATION_CACHES, _CONVERSATION_MESSAGES
    if conversation_id:
        cache_keys_to_delete = [
            key
            for key in _CONVERSATION_CACHES
            if key == conversation_id or key.startswith(f"{conversation_id}:")
        ]
        message_keys_to_delete = [
            key
            for key in _CONVERSATION_MESSAGES
            if key == conversation_id or key.startswith(f"{conversation_id}:")
        ]
        for key in cache_keys_to_delete:
            del _CONVERSATION_CACHES[key]
        for key in message_keys_to_delete:
            del _CONVERSATION_MESSAGES[key]
        if cache_keys_to_delete or message_keys_to_delete:
            print(f"[CACHE] Cleared cache for conversation: {conversation_id}")
    else:
        _CONVERSATION_CACHES.clear()
        _CONVERSATION_MESSAGES.clear()
        print("[CACHE] Cleared all conversation caches")


def detect_language(text: str) -> str:
    """检测用户输入的主要语言。返回 'zh' 或 'en'。"""
    if not text:
        return "zh"
    # 统计中日韩字符占比
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff")
    alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    # CJK 占比超过 15% 视为中文
    if cjk > 0 and cjk / max(len(text), 1) >= 0.15:
        return "zh"
    if alpha > len(text) * 0.5:
        return "en"
    return "zh"


class AgentService:
    """Agent 服务 - 基于 PageIndex 官方流程"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.pageindex_service = PageIndexService()
        self.document_service = DocumentService(db)
        self.folder_service = FolderService(db)

    def build_explicit_agent_graph(
        self,
        *,
        tool_executor: Any | None = None,
        answer_generator: Any | None = None,
        finalizer: Any | None = None,
        failure_handler: Any | None = None,
        user_id: str | None = None,
    ):
        from app.agent.graph import PageChatAgentGraph
        from app.agent.nodes import AgentNodeDependencies

        return PageChatAgentGraph(
            AgentNodeDependencies(
                tool_executor=tool_executor,
                document_service=getattr(self, "document_service", None),
                folder_service=getattr(self, "folder_service", None),
                user_id=user_id,
                answer_generator=answer_generator or self._generate_graph_answer,
                finalizer=finalizer or self._finalize_graph_run,
                failure_handler=failure_handler or self._fail_graph_run,
            )
        )

    def build_agent_loop_runtime(
        self,
        *,
        tool_executor: Any,
        web_search_settings: Dict[str, Any],
        runtime_tools: Optional[List[Dict[str, Any]]] = None,
        answer_generator: Any | None = None,
        user_id: str | None = None,
        max_steps: int = 8,
    ):
        from app.agent.loop_runtime import AgentLoopRuntime
        from app.agent.planner import StructuredLLMPlanner
        from app.agent.policy import AgentPolicy

        generator = answer_generator or self._stream_graph_answer
        tools = list(
            runtime_tools
            if runtime_tools is not None
            else self._tools_for_request(bool(web_search_settings.get("enabled")))
        )
        planner = StructuredLLMPlanner(
            completion_fn=chat_by_scenario,
            tools=tools,
            user_id=user_id,
        )
        return AgentLoopRuntime(
            planner=planner,
            tool_runner=AgentLoopToolRunner(
                tool_executor=tool_executor,
                web_search_settings=web_search_settings,
            ),
            policy=AgentPolicy(tools=tools),
            answer_generator=generator,
            max_steps=max_steps,
        )

    async def _resolve_valid_folder_id(
        self, folder_id: Optional[str], user_id: Optional[str]
    ) -> tuple[Optional[str], bool]:
        normalized = normalize_folder_id(folder_id)
        if not normalized:
            return None, False
        folder_service = getattr(self, "folder_service", None)
        if folder_service is None:
            return normalized, False
        folder = await folder_service.get_folder(normalized, user_id=user_id)
        if not folder:
            return None, True
        return normalized, False

    async def _list_folder_document_ids(
        self,
        folder_id: str,
        *,
        include_subfolders: bool,
        user_id: Optional[str],
        page_size: int = 500,
    ) -> List[str]:
        document_ids: List[str] = []
        page = 1
        while True:
            docs, total = await self.document_service.list_documents(
                page=page,
                page_size=page_size,
                folder_id=folder_id,
                include_subfolders=include_subfolders,
                user_id=user_id,
            )
            document_ids.extend(doc.id for doc in docs)
            if len(document_ids) >= total or not docs:
                break
            page += 1
        return document_ids

    @staticmethod
    def _match_document_ids_from_question(
        question: str,
        docs: List[Any],
    ) -> List[str]:
        q = (question or "").casefold()
        if not q:
            return []
        matches: List[str] = []
        for doc in docs:
            names = {
                str(getattr(doc, "name", "") or ""),
                str(getattr(doc, "original_name", "") or ""),
            }
            stems = {Path(name).stem for name in names if name}
            for candidate in {*(name.casefold() for name in names if name), *(stem.casefold() for stem in stems if stem)}:
                if candidate and candidate in q:
                    matches.append(doc.id)
                    break
        return matches

    @staticmethod
    def _should_use_document_library(
        question: str,
        *,
        has_documents: bool,
        has_valid_explicit_scope: bool,
        web_search_active: bool,
    ) -> bool:
        if not has_documents or has_valid_explicit_scope or web_search_active:
            return False
        if question_needs_document_retrieval(question):
            return True
        q = (question or "").strip().lower()
        if not q:
            return False
        current_fact_hints = (
            "天气",
            "几点",
            "时间",
            "今天",
            "新闻",
            "股价",
            "汇率",
            "weather",
            "time",
            "today",
            "news",
            "stock",
        )
        if any(hint in q for hint in current_fact_hints):
            return False
        simple_chat_hints = ("你好", "hello", "hi", "谢谢", "thanks")
        if q in simple_chat_hints or len(q) <= 4:
            return False
        library_question_hints = (
            "什么",
            "哪些",
            "如何",
            "为什么",
            "分析",
            "总结",
            "概括",
            "主要",
            "讲",
            "提到",
            "应用",
            "创新",
            "趋势",
            "案例",
            "对比",
            "what",
            "which",
            "how",
            "why",
            "analyze",
            "summarize",
            "summary",
            "case",
            "trend",
            "compare",
        )
        return any(hint in q for hint in library_question_hints)

    async def _stream_graph_answer(self, state):
        messages = [{"role": "system", "content": QA_SYSTEM_PROMPT}]
        for item in state.history[-6:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})

        evidence_pack = state.scope.get("evidence_pack") or []
        if evidence_pack:
            messages.append(
                {
                    "role": "assistant",
                    "content": "Evidence pack:\n"
                    + json.dumps(evidence_pack, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": state.question})

        response = await chat_by_scenario(
            scenario="qa",
            messages=messages,
            stream=True,
            user_id=state.scope.get("user_id"),
            disable_thinking=True,
        )
        async for chunk in response:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    async def _generate_graph_answer(self, state) -> str:
        answer = ""
        async for content in self._stream_graph_answer(state):
            answer += content
        return answer

    async def _finalize_graph_run(self, state) -> None:
        from app.services.chat_run_repository import ChatRunRepository

        await ChatRunRepository(self.db).complete_run(
            state.run_id,
            final_content=state.answer,
            citations=state.citations,
        )

    async def _fail_graph_run(self, state, error: str) -> None:
        from app.services.chat_run_repository import ChatRunRepository

        await ChatRunRepository(self.db).fail_run(state.run_id, error)

    def _format_sse(self, event: str, data: dict) -> str:
        """格式化 SSE 事件"""
        import json as _json

        return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def _tools_for_request(web_search_enabled: bool = False) -> List[Dict[str, Any]]:
        tools = [
            tool
            for tool in AGENT_TOOLS
            if tool.get("function", {}).get("name") != "web_search"
        ]
        if web_search_enabled:
            web_tool = next(
                (
                    tool
                    for tool in AGENT_TOOLS
                    if tool.get("function", {}).get("name") == "web_search"
                ),
                WEB_SEARCH_TOOL,
            )
            tools.append(web_tool)
        return tools

    async def _web_search_settings_for_request(
        self, user_id: str, requested: bool
    ) -> Dict[str, Any]:
        if self.db is None:
            settings = dict(DEFAULT_WEB_SEARCH_SETTINGS)
            settings.update(
                {
                    "api_key": None,
                    "enabled": bool(requested),
                    "requested": bool(requested),
                }
            )
            return settings
        return await WebSearchSettingsService(self.db).resolve_for_request(
            user_id=user_id,
            requested=requested,
        )

    @staticmethod
    def _scope_cache_key(
        user_id: str,
        document_ids: Optional[List[str]],
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
    ) -> str:
        allowed_doc_ids = (
            tuple(document_ids) if document_ids is not None else None
        )
        base = json.loads(
            RetrievalScope(
                user_id=user_id, allowed_doc_ids=allowed_doc_ids
            ).cache_key
        )
        base.update(
            {
                "folder_id": folder_id,
                "include_subfolders": bool(include_subfolders),
                "strict_scope": strict_scope,
            }
        )
        return json.dumps(base, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_tool_cache_key(
        tool_name: str,
        tool_args: Dict[str, Any],
        user_id: str,
        document_ids: Optional[List[str]],
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
    ) -> str:
        if tool_name == "get_page_content":
            norm_args = {
                k: v for k, v in tool_args.items() if k != "include_image"
            }
        else:
            norm_args = dict(tool_args)
        scope_key = AgentService._scope_cache_key(
            user_id,
            document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=strict_scope,
        )
        return (
            f"{scope_key}:{tool_name}:"
            f"{json.dumps(norm_args, ensure_ascii=False, sort_keys=True)}"
        )

    @staticmethod
    def _conversation_state_key(
        conversation_id: str,
        user_id: str,
        document_ids: Optional[List[str]],
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
    ) -> str:
        scope_key = AgentService._scope_cache_key(
            user_id,
            document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=strict_scope,
        )
        return f"{conversation_id}:{scope_key}"

    @staticmethod
    def _build_document_registry(
        docs: List[Any],
        visible_document_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        visible = set(visible_document_ids) if visible_document_ids is not None else None
        registry: List[Dict[str, Any]] = []
        for doc in docs:
            doc_id = getattr(doc, "id", None) or getattr(doc, "doc_id", None)
            if not doc_id:
                continue
            doc_id = str(doc_id)
            if visible is not None and doc_id not in visible:
                continue
            doc_name = (
                getattr(doc, "original_name", None)
                or getattr(doc, "name", None)
                or doc_id
            )
            doc_name = str(doc_name)
            folder_path = getattr(doc, "folder_path", None)
            registry.append(
                {
                    "document_id": doc_id,
                    "document_name": doc_name,
                    "folder_id": getattr(doc, "folder_id", None),
                    "path": AgentService._document_registry_path(folder_path, doc_name),
                }
            )
        return registry

    @staticmethod
    def _document_registry_path(folder_path: Any, doc_name: str) -> str:
        folder = str(folder_path or "root").strip() or "root"
        normalized = " / ".join(
            part.strip()
            for part in folder.replace("\\", "/").split("/")
            if part.strip()
        )
        normalized = normalized or "root"
        if normalized.lower().endswith(doc_name.lower()):
            return normalized
        return f"{normalized} / {doc_name}"

    async def run_agent_stream(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        preferred_document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
        web_search_requested: bool = False,
        web_search_enabled: bool = False,
        suppress_user_library_fallback: bool = False,
        request_attachments: Optional[List[Dict[str, Any]]] = None,
        user_id: str = None,
        max_steps: int = 8,
        history_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Agent 流式执行 - 基于 PageIndex 官方流程

        内部 SSE 事件类型：
        - progress: 简短运行进度
        - tool_started: 工具调用开始
        - tool_completed: 工具调用完成
        - answer_delta: 答案增量
        - citation_added: 结构化引用（如由运行节点直接产生）
        """
        # 检查是否有可用文档
        if not user_id:
            raise ValueError("user_id is required")

        folder_id, invalid_folder_scope = await self._resolve_valid_folder_id(
            folder_id, user_id
        )

        docs = await self.document_service.get_indexed_documents(user_id=user_id)
        available_doc_ids = {doc.id for doc in docs}
        if document_ids is None:
            matched_doc_ids = self._match_document_ids_from_question(question, docs)
            if matched_doc_ids:
                document_ids = matched_doc_ids
                preferred_document_ids = matched_doc_ids
        requested_document_ids = list(document_ids or [])
        if document_ids is not None:
            document_ids = [
                doc_id for doc_id in requested_document_ids if doc_id in available_doc_ids
            ]
            if requested_document_ids and not document_ids and not folder_id:
                suppress_user_library_fallback = True
        if invalid_folder_scope and not document_ids:
            suppress_user_library_fallback = True
        if preferred_document_ids is not None:
            preferred_document_ids = [
                doc_id for doc_id in preferred_document_ids if doc_id in available_doc_ids
            ]
        doc_count = len(document_ids) if document_ids is not None else len(docs)
        conversation_state_key = (
            self._conversation_state_key(
                conversation_id,
                user_id,
                document_ids,
                folder_id=folder_id,
                include_subfolders=include_subfolders,
                strict_scope=strict_scope,
            )
            if conversation_id
            else None
        )

        has_valid_explicit_scope = bool(document_ids or folder_id)
        effective_strict_scope = strict_scope
        if effective_strict_scope is None:
            effective_strict_scope = has_valid_explicit_scope
        needs_document_retrieval = question_needs_document_retrieval(question)
        skip_initial_retrieval = bool(request_attachments) and self._is_image_only_question(question)
        folder_allowed_doc_ids: Optional[List[str]] = None
        if folder_id and effective_strict_scope and not skip_initial_retrieval:
            folder_allowed_doc_ids = await self._list_folder_document_ids(
                folder_id,
                include_subfolders=include_subfolders,
                user_id=user_id,
            )
        executor_allowed_doc_ids = None
        if effective_strict_scope:
            if document_ids is not None and folder_allowed_doc_ids is not None:
                folder_allowed_set = set(folder_allowed_doc_ids)
                executor_allowed_doc_ids = [
                    doc_id for doc_id in document_ids if doc_id in folder_allowed_set
                ]
            elif document_ids is not None:
                executor_allowed_doc_ids = document_ids
            elif folder_allowed_doc_ids is not None:
                executor_allowed_doc_ids = folder_allowed_doc_ids

        # 将当前请求允许访问的文档范围注入工具执行器（防止越权）
        tool_executor = ToolExecutor(
            self.pageindex_service,
            self.document_service,
            user_id=user_id,
            allowed_doc_ids=executor_allowed_doc_ids,
        )

        # 检测用户语言，注入 prompt
        user_lang = detect_language(question)
        web_search_settings = await self._web_search_settings_for_request(
            user_id=user_id,
            requested=bool(web_search_requested or web_search_enabled),
        )
        web_search_active = bool(web_search_settings.get("enabled"))
        needs_document_retrieval = needs_document_retrieval or self._should_use_document_library(
            question,
            has_documents=bool(docs),
            has_valid_explicit_scope=has_valid_explicit_scope,
            web_search_active=web_search_active,
        )
        runtime_tools = self._tools_for_request(web_search_enabled=web_search_active)

        if request_attachments and self._is_image_only_question(question):
            async for event in self._attachment_chat_stream(
                question=question,
                request_attachments=request_attachments,
                history_messages=history_messages,
                user_id=user_id,
            ):
                yield event
            return

        scope = {
            "user_id": user_id,
            "document_ids": list(document_ids or []),
            "preferred_document_ids": list(preferred_document_ids or []),
            "folder_id": folder_id,
            "include_subfolders": bool(include_subfolders),
            "strict_scope": bool(effective_strict_scope),
            "web_search_requested": bool(web_search_requested),
            "web_search_enabled": bool(web_search_active),
            "suppress_user_library_fallback": bool(suppress_user_library_fallback),
            "available_document_ids": sorted(available_doc_ids),
            "document_registry": self._build_document_registry(
                docs,
                visible_document_ids=executor_allowed_doc_ids,
            ),
        }
        runtime = self.build_agent_loop_runtime(
            tool_executor=tool_executor,
            web_search_settings=web_search_settings,
            runtime_tools=runtime_tools,
            answer_generator=self._stream_graph_answer,
            user_id=user_id,
            max_steps=max_steps,
        )
        state = AgentRunState(
            question=question,
            conversation_id=conversation_id or "",
            run_id="",
            message_id="",
            scope=scope,
            history=history_messages or [],
        )
        async for runtime_event in runtime.stream(state):
            yield self._format_sse(runtime_event.event_type, runtime_event.payload)
        return

    def _build_tool_content(self, tool_name: str, result: dict) -> str:
        """
        构建工具结果内容

        对于 get_page_content，如果包含 page_image_base64，
        返回纯文本描述（模型通过 text_content 已能看到内容）
        图片内容会通过单独的多模态消息传递
        """
        if tool_name == "get_page_content":
            page_image = result.get("page_image_base64")
            text_content = result.get("text_content", "")

            # 构建文字描述（不含base64图片）
            desc = {
                "doc_id": result.get("doc_id"),
                "doc_name": result.get("doc_name"),
                "page_num": result.get("page_num"),
                "node_title": result.get("node_title"),
                "text_content": text_content,
            }
            if page_image:
                desc["has_page_image"] = True
            return json.dumps(desc, ensure_ascii=False)

        # 其他工具结果直接序列化
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    async def _execute_initial_retrieval_plan(
        question: str,
        tool_executor: ToolExecutor,
        document_ids: Optional[List[str]] = None,
        preferred_document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
        web_search_requested: bool = False,
        web_search_enabled: bool = False,
        web_search_settings: Optional[Dict[str, Any]] = None,
        suppress_user_library_fallback: bool = False,
    ) -> List[Dict[str, Any]]:
        folder_id = normalize_folder_id(folder_id)
        if web_search_requested and web_search_enabled:
            arguments = {"query": question}
            result = await execute_web_search_tool(
                arguments=arguments,
                settings=web_search_settings or DEFAULT_WEB_SEARCH_SETTINGS,
            )
            return [
                {
                    "tool_name": "web_search",
                    "arguments": arguments,
                    "result": result,
                    "retrieval_plan_route": "web_search",
                }
            ]
        if suppress_user_library_fallback:
            return []

        planner = RetrievalPlanner()
        planner_document_ids = (
            preferred_document_ids
            if preferred_document_ids is not None
            else document_ids
        )
        plan = planner.plan(
            question=question,
            document_ids=planner_document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=strict_scope,
        )

        evidence: List[Dict[str, Any]] = []
        for step in plan.steps[:1]:
            arguments = {
                key: value
                for key, value in step.arguments.items()
                if value is not None
            }
            result = await tool_executor.execute(step.tool_name, arguments)
            evidence.append(
                {
                    "tool_name": step.tool_name,
                    "arguments": arguments,
                    "result": result,
                    "retrieval_plan_route": plan.route.value,
                }
            )
        return evidence

    @staticmethod
    def _planner_evidence_message(evidence: Dict[str, Any]) -> Dict[str, str]:
        cleaned = AgentService._sanitize_tool_result_for_history(evidence)
        return {
            "role": "assistant",
            "content": (
                "Initial retrieval evidence:\n"
                f"{json.dumps(cleaned, ensure_ascii=False)}"
            ),
        }

    @staticmethod
    def _sanitize_tool_result_for_history(result: Any) -> Any:
        """移除工具结果中的大体积 base64 字段，避免上下文膨胀。"""
        if isinstance(result, dict):
            if result.get("type") == "image" and isinstance(result.get("data"), str):
                cleaned = dict(result)
                cleaned["data"] = "[omitted-base64-image]"
                return cleaned
            is_anysearch_result = (
                result.get("source") == "anysearch"
                or "content_preview" in result
            )
            cleaned = {}
            for k, v in result.items():
                if k in {"page_image_base64", "image_base64"}:
                    continue
                if is_anysearch_result and k == "content":
                    continue
                cleaned[k] = AgentService._sanitize_tool_result_for_history(v)
            return cleaned
        if isinstance(result, list):
            return [AgentService._sanitize_tool_result_for_history(v) for v in result]
        return result

    @staticmethod
    def _sanitize_tool_result_for_client(result: Any) -> Any:
        """移除 SSE 和持久化 UI 状态中的大体积图片字段。"""
        return AgentService._sanitize_tool_result_for_history(result)

    @staticmethod
    def _user_message_with_attachments(
        question: str, attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        if not attachments:
            return {"role": "user", "content": question}

        content: List[Dict[str, Any]] = [{"type": "text", "text": question}]
        for item in attachments[:CHAT_ATTACHMENT_MAX_PER_MESSAGE]:
            mime_type = item.get("mime_type")
            data_base64 = item.get("data_base64")
            if not mime_type or not data_base64:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{data_base64}",
                    },
                }
            )

        if len(content) == 1:
            return {"role": "user", "content": question}
        return {"role": "user", "content": content}

    @staticmethod
    def _sanitize_messages_for_conversation_history(messages: Any) -> Any:
        """Remove multimodal base64 payloads before storing reusable in-memory history."""
        if isinstance(messages, list):
            return [
                AgentService._sanitize_messages_for_conversation_history(item)
                for item in messages
            ]
        if isinstance(messages, dict):
            if messages.get("type") == "image_url":
                return {
                    "type": "text",
                    "text": "[image payload omitted from conversation history]",
                }
            return {
                key: AgentService._sanitize_messages_for_conversation_history(value)
                for key, value in messages.items()
            }
        if isinstance(messages, str) and messages.startswith("data:image/"):
            return "[omitted-base64-image-url]"
        return messages

    @staticmethod
    def _vision_message_for_tool_result(
        tool_name: str, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Build a multimodal message for visual tools without storing base64 in tool history."""
        if tool_name not in {"get_document_image", "get_page_image"}:
            return None
        if not isinstance(result, dict):
            return None

        image_base64 = ""
        mime_type = result.get("mimeType") or "image/jpeg"
        doc_name = result.get("doc_name") or "文档"
        page_num = result.get("page") or result.get("page_num")
        image_path = result.get("image_path")

        data = result.get("data")
        if isinstance(data, str):
            image_base64 = data
        elif isinstance(data, dict):
            image_base64 = data.get("image_base64") or data.get("data") or ""
            mime_type = data.get("mimeType") or data.get("image_format") or mime_type
            if mime_type and "/" not in str(mime_type):
                mime_type = f"image/{mime_type}"
            doc_name = data.get("doc_name") or doc_name
            page_num = data.get("page_num") or data.get("page") or page_num
            image_path = data.get("image_path") or image_path

        if not image_base64:
            return None

        if image_path:
            location = f"{doc_name} 中的图片 {image_path}"
            if page_num:
                location += f"（第{page_num}页）"
        elif page_num:
            location = f"{doc_name}第{page_num}页的完整页面截图"
        else:
            location = f"{doc_name}中的图片"

        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}"
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"这是{location}。请用视觉能力识别图中内容，再基于识别结果回答。"
                        "若只能识别到部分信息，请明确指出不确定项，不要猜测。"
                    ),
                },
            ],
        }

    async def _simple_chat_stream(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        history_messages: Optional[List[Dict[str, Any]]] = None,
        user_id: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        简单聊天模式 - 当没有文档时使用
        直接调用 LLM，不使用任何工具
        """
        from app.prompts import CHAT_SYSTEM_PROMPT

        try:
            print(f"[SimpleChat] Starting simple chat for question: {question[:50]}...")

            # 构建消息
            messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

            # 添加历史消息
            if history_messages:
                for msg in history_messages[-6:]:
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        messages.append(
                            {"role": msg["role"], "content": msg["content"]}
                        )

            messages.append({"role": "user", "content": question})

            print(f"[SimpleChat] Messages prepared, calling LLM...")

            # 调用 LLM（不带工具）
            response = await chat_by_scenario(
                scenario="qa",
                messages=messages,
                stream=True,
                user_id=user_id,
                temperature=0.7,
                disable_thinking=True,
            )

            print(f"[SimpleChat] Got response from LLM, streaming...")

            # 流式输出
            full_content = ""
            chunk_count = 0
            async for chunk in response:
                chunk_count += 1
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # 输出 reasoning_content（思考过程）
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    pass

                # 输出内容
                if delta.content:
                    full_content += delta.content
                    yield self._format_sse("answer_delta", {"content": delta.content})

            print(
                f"[SimpleChat] Stream complete, {chunk_count} chunks, {len(full_content)} chars"
            )
            if not full_content:
                raise RuntimeError("No final answer generated by the selected model")

        except Exception as e:
            print(f"[SimpleChat] Error: {e}")
            import traceback

            traceback.print_exc()
            raise

    async def _attachment_chat_stream(
        self,
        *,
        question: str,
        request_attachments: Optional[List[Dict[str, Any]]] = None,
        history_messages: Optional[List[Dict[str, Any]]] = None,
        user_id: str = None,
    ) -> AsyncGenerator[str, None]:
        from app.prompts import CHAT_SYSTEM_PROMPT

        messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
        if history_messages:
            for msg in history_messages[-6:]:
                if msg.get("role") in ("user", "assistant") and msg.get("content"):
                    messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append(self._user_message_with_attachments(question, request_attachments))

        response = await chat_by_scenario(
            scenario="qa",
            messages=messages,
            stream=True,
            user_id=user_id,
            temperature=0.7,
            disable_thinking=True,
        )
        full_content = ""
        async for chunk in response:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                full_content += content
                yield self._format_sse("answer_delta", {"content": content})
        if not full_content:
            raise RuntimeError("No final answer generated by the selected model")

    def _trim_history(
        self, history_messages: List[Dict[str, Any]], current_question: str
    ) -> List[Dict[str, Any]]:
        """裁剪历史消息，保留最近的对话，过滤已废弃工具引用"""
        if not history_messages:
            return []

        # 只保留最近的几轮对话
        trimmed = []
        for msg in history_messages[-6:]:  # 最近3轮对话
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                trimmed.append({"role": role, "content": content})

        return trimmed

    @staticmethod
    def _is_image_only_question(question: str) -> bool:
        text = (question or "").lower()
        image_terms = [
            "图片",
            "截图",
            "图里",
            "图中",
            "这张图",
            "这张图片",
            "screen",
            "screenshot",
            "image",
            "picture",
        ]
        document_terms = [
            "文档",
            "文件",
            "资料库",
            "文件夹",
            "报告",
            "pdf",
            "document",
            "file",
            "folder",
            "library",
        ]
        return any(term in text for term in image_terms) and not any(
            term in text for term in document_terms
        )

    @staticmethod
    def _build_doc_scope_instruction(document_ids: List[str]) -> str:
        if len(document_ids) == 1:
            return (
                "Only document ID is allowed this turn: "
                f"{document_ids[0]}. If tool input is missing doc_id, use this value."
            )
        joined = ", ".join(document_ids[:10])
        return (
            "Available document ID scope this turn: "
            f"{joined}. When calling get_document_structure/get_page_content, "
            "doc_id must stay within this scope."
        )
    @staticmethod
    def _inject_default_doc_id(
        tool_name: str,
        tool_args: Dict[str, Any],
        document_ids: Optional[List[str]],
        preferred_document_ids: Optional[List[str]],
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
    ) -> Dict[str, Any]:
        folder_id = normalize_folder_id(folder_id)
        patched = dict(tool_args)
        preferred_scope_ids = list(preferred_document_ids or [])
        request_scope_ids = list(document_ids or [])
        strict_or_unspecified = strict_scope is not False
        single_doc_id = None
        if len(preferred_scope_ids) == 1:
            single_doc_id = preferred_scope_ids[0]
        elif len(request_scope_ids) == 1:
            single_doc_id = request_scope_ids[0]

        if tool_name in {
            "get_document_structure",
            "get_page_content",
            "get_page_image",
            "search_within_document",
        }:
            if single_doc_id and not patched.get("doc_id"):
                patched["doc_id"] = single_doc_id
            return patched

        if tool_name == "get_document_image":
            if (
                single_doc_id
                and not patched.get("doc_id")
                and not patched.get("image_path")
            ):
                patched["doc_id"] = single_doc_id
            return patched

        if tool_name == "browse_documents":
            scope_ids = preferred_scope_ids or (
                request_scope_ids if len(request_scope_ids) == 1 else []
            )
            if scope_ids and strict_or_unspecified and not patched.get("document_ids"):
                patched["document_ids"] = scope_ids
            if folder_id and strict_or_unspecified and not patched.get("folder_id"):
                patched["folder_id"] = folder_id
            if include_subfolders and strict_or_unspecified and "recursive" not in patched:
                patched["recursive"] = include_subfolders
            return patched

        return tool_args
