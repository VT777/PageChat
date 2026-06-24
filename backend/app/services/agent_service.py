"""
Agent 核心服务 - KnowClaw
基于 PageIndex 官方流程的 Function Calling Agent
支持 thinking 流式展示和多模态 PDF 页面
"""

import json
import re
import time
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional
import aiosqlite

tool_logger = logging.getLogger("tool")
agent_logger = logging.getLogger("agent")

from app.services.pageindex_service import PageIndexService
from app.services.document_service import DocumentService
from app.services.tool_executor import ToolExecutor, AGENT_TOOLS
from app.services.retrieval_planner import RetrievalPlanner
from app.core.llm import chat_by_scenario, async_chat_completion
from app.models.retrieval import RetrievalScope
from app.prompts import build_agent_system_prompt, QA_SYSTEM_PROMPT


# 全局会话级缓存（跨请求持久化）
_CONVERSATION_CACHES: Dict[str, Dict[str, Any]] = {}
# 每个会话的完整消息历史（包含工具调用记录，用于多轮对话记忆）
_CONVERSATION_MESSAGES: Dict[str, List[Dict[str, Any]]] = {}

# 不缓存的工具列表（需要实时数据或可能携带大 payload 的工具）
_NON_CACHEABLE_TOOLS = {
    "list_documents",
    "list_folder_tree",
    "list_folder_contents",
    "view_folder_structure",
    "browse_documents",
    "find_related_documents",
    "get_document_image",
    "get_page_image",
}


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

    def _format_sse(self, event: str, data: dict) -> str:
        """格式化 SSE 事件"""
        import json as _json

        return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

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

    async def run_agent_stream(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        preferred_document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
        user_id: str = None,
        max_steps: int = 8,
        history_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Agent 流式执行 - 基于 PageIndex 官方流程

        SSE 事件类型：
        - thinking: 模型思考过程（reasoning_content 流式）
        - tool_call: 工具调用
        - tool_result: 工具返回结果
        - content: 最终答案内容
        - done: 完成
        """
        # 检查是否有可用文档
        if not user_id:
            raise ValueError("user_id is required")

        docs = await self.document_service.get_indexed_documents(user_id=user_id)
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

        has_explicit_scope = bool(document_ids or folder_id)
        effective_strict_scope = strict_scope
        if effective_strict_scope is None:
            effective_strict_scope = has_explicit_scope
        executor_allowed_doc_ids = (
            document_ids if document_ids is not None and effective_strict_scope else None
        )

        # 将当前请求允许访问的文档范围注入工具执行器（防止越权）
        tool_executor = ToolExecutor(
            self.pageindex_service,
            self.document_service,
            user_id=user_id,
            allowed_doc_ids=executor_allowed_doc_ids,
        )

        # 检测用户语言，注入 prompt
        user_lang = detect_language(question)

        # 如果没有文档库且没有显式检索范围，直接走简单聊天模式（不调用工具）
        if doc_count == 0 and not has_explicit_scope:
            print(
                f"[Agent] No documents or no document_ids specified, using simple chat mode"
            )
            async for event in self._simple_chat_stream(
                question, conversation_id, history_messages
            ):
                yield event
            return

        # 使用持久化的会话消息历史（包含工具调用记录）
        if (
            conversation_state_key
            and conversation_state_key in _CONVERSATION_MESSAGES
        ):
            # 复用缓存消息历史，但强制刷新系统提示与文档范围提示，避免旧会话污染
            messages = _CONVERSATION_MESSAGES[conversation_state_key].copy()

            # 更新/补充主系统提示
            system_prompt = build_agent_system_prompt(AGENT_TOOLS, lang=user_lang)
            if messages and messages[0].get("role") == "system":
                messages[0] = {"role": "system", "content": system_prompt}
            else:
                messages.insert(0, {"role": "system", "content": system_prompt})

            # 清理旧的文档范围提示（历史兼容）
            def _is_scope_system_message(msg: Dict[str, Any]) -> bool:
                if msg.get("role") != "system":
                    return False
                content = str(msg.get("content") or "")
                return (
                    content.startswith("Available document ID scope this turn:")
                    or content.startswith("Only document ID is allowed this turn:")
                    or content.startswith("Preferred document IDs this turn:")
                    or content.startswith("本轮可用文档ID范围：")
                    or content.startswith("本轮仅允许使用文档ID:")
                    or content.startswith("优先检索这些文档ID：")
                )

            messages = [m for m in messages if not _is_scope_system_message(m)]

            messages.append({"role": "user", "content": question})
        else:
            # 新建消息历史 - 动态获取文档数量并注入提示词
            system_prompt = build_agent_system_prompt(AGENT_TOOLS, lang=user_lang)
            messages = [{"role": "system", "content": system_prompt}]

            # 添加历史消息（来自数据库）
            if history_messages:
                trimmed = self._trim_history(history_messages, question)
                messages.extend(trimmed)

            messages.append({"role": "user", "content": question})

        # 工具调用历史（用于传递给最终答案生成）
        tool_results_for_answer = []
        assistant_content = ""

        initial_evidence = await self._execute_initial_retrieval_plan(
            question=question,
            tool_executor=tool_executor,
            preferred_document_ids=preferred_document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=strict_scope,
        )
        for evidence in initial_evidence:
            tool_results_for_answer.append(
                self._sanitize_tool_result_for_client(evidence)
            )
            messages.append(self._planner_evidence_message(evidence))

        # Agent 循环
        for step_num in range(max_steps):
            # 流式调用模型（带工具）
            tool_logger.info(
                f"Sending {len(AGENT_TOOLS)} tools: {[t['function']['name'] for t in AGENT_TOOLS]}"
            )
            response = await chat_by_scenario(
                scenario="qa",
                messages=messages,
                tools=AGENT_TOOLS,
                stream=True,
                user_id=user_id,
            )

            # 收集本轮响应
            assistant_content = ""
            reasoning_content = ""
            tool_calls = []
            current_tool_call = None
            has_tool_calls = False

            async for chunk in response:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # 流式输出 thinking（reasoning_content）
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_content += delta.reasoning_content
                    yield self._format_sse(
                        "thinking",
                        {
                            "content": delta.reasoning_content,
                            "step": step_num,
                        },
                    )

                # 流式输出答案内容
                if delta.content:
                    assistant_content += delta.content
                    yield self._format_sse(
                        "content",
                        {
                            "content": delta.content,
                        },
                    )

                # 处理工具调用
                if delta.tool_calls:
                    has_tool_calls = True
                    for tc in delta.tool_calls:
                        if tc.index is not None and tc.index >= len(tool_calls):
                            tool_calls.append(
                                {
                                    "id": tc.id or "",
                                    "function": {"name": "", "arguments": ""},
                                }
                            )
                        if tc.index is not None and tc.index < len(tool_calls):
                            if tc.function and tc.function.name:
                                tool_calls[tc.index]["function"]["name"] = (
                                    tc.function.name
                                )
                            if tc.function and tc.function.arguments:
                                tool_calls[tc.index]["function"]["arguments"] += (
                                    tc.function.arguments
                                )

            # 如果没有工具调用，说明可以生成最终答案了
            if not has_tool_calls:
                # 将 assistant 消息加入历史
                messages.append({"role": "assistant", "content": assistant_content})
                break

            # 构建 assistant 消息（含工具调用）
            assistant_msg = {
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }
                    for tc in tool_calls
                ],
            }
            messages.append(assistant_msg)

            # 执行工具调用
            for tc in tool_calls:
                tool_name = tc["function"]["name"]

                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    tool_args = {}

                # find_related_documents 只接受 query 参数
                if tool_name == "find_related_documents" and "query" not in tool_args:
                    # 当 LLM 遗漏 query 时，使用用户问题作为 fallback
                    fallback_query = tool_args.get("query") or question or ""
                    tool_args = {"query": fallback_query}

                tool_args = self._inject_default_doc_id(
                    tool_name,
                    tool_args,
                    document_ids,
                    preferred_document_ids,
                    folder_id=folder_id,
                    include_subfolders=include_subfolders,
                    strict_scope=strict_scope,
                )

                # 发送工具调用事件
                tool_logger.info(
                    f"Calling {tool_name} with {json.dumps(tool_args, ensure_ascii=False)[:200]}"
                )
                yield self._format_sse(
                    "tool_call",
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "step": step_num,
                        "status": "calling",
                    },
                )

                # 执行工具（带会话缓存，部分工具不缓存）
                started_at = time.perf_counter()

                # 检查是否需要缓存
                should_cache = tool_name not in _NON_CACHEABLE_TOOLS

                if should_cache:
                    # 缓存 key：忽略 include_image 差异，同一页面只缓存一份
                    cache_key = self._build_tool_cache_key(
                        tool_name,
                        tool_args,
                        user_id=user_id,
                        document_ids=document_ids,
                        folder_id=folder_id,
                        include_subfolders=include_subfolders,
                        strict_scope=strict_scope,
                    )

                    conv_cache = _CONVERSATION_CACHES.get(
                        conversation_state_key, {}
                    )
                    if cache_key in conv_cache:
                        result = conv_cache[cache_key]
                        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                        tool_logger.info(
                            f"{tool_name} completed in {elapsed_ms}ms (session cache hit)"
                        )
                    else:
                        result = await tool_executor.execute(tool_name, tool_args)
                        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                        if conversation_state_key:
                            _CONVERSATION_CACHES.setdefault(
                                conversation_state_key, {}
                            )[cache_key] = result
                        tool_logger.info(f"{tool_name} completed in {elapsed_ms}ms")
                else:
                    # 不缓存的工具：直接执行
                    result = await tool_executor.execute(tool_name, tool_args)
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    tool_logger.info(
                        f"{tool_name} completed in {elapsed_ms}ms (no cache)"
                    )
                print(f"[TOOL] {tool_name} completed in {elapsed_ms}ms")
                if isinstance(result, dict):
                    result.setdefault("elapsed_ms", elapsed_ms)

                client_result = self._sanitize_tool_result_for_client(result)

                # 发送工具结果事件
                yield self._format_sse(
                    "tool_result",
                    {
                        "tool_name": tool_name,
                        "result": client_result,
                        "step": step_num,
                        "elapsed_ms": elapsed_ms,
                        "status": "completed",
                    },
                )

                # 将工具结果加入消息历史（移除 base64 图片避免 tool result 过大）
                tool_result_clean = self._sanitize_tool_result_for_history(result)
                tool_content = json.dumps(tool_result_clean, ensure_ascii=False)
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_content,
                }
                messages.append(tool_message)

                vision_message = self._vision_message_for_tool_result(
                    tool_name, result
                )
                if vision_message:
                    messages.append(vision_message)
                    image_url = vision_message["content"][0]["image_url"]["url"]
                    print(
                        f"[VISION] Injected image_url for {tool_name}, size={len(image_url)}"
                    )

                # 收集工具结果用于最终答案生成
                tool_results_for_answer.append(
                    {
                        "tool_name": tool_name,
                        "result": client_result,
                    }
                )

                if conversation_id and tool_name in {
                    "get_page_content",
                    "get_document_structure",
                }:
                    pass  # per-conversation cache handled at execution level

        # 如果有工具调用但没有生成答案，强制调用一次模型生成最终答案
        if tool_results_for_answer and not assistant_content:
            fallback_response = await chat_by_scenario(
                scenario="qa",
                messages=messages,
                stream=True,
                user_id=user_id,
            )
            async for chunk in fallback_response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield self._format_sse(
                        "thinking",
                        {"content": delta.reasoning_content, "step": max_steps},
                    )
                if delta.content:
                    assistant_content += delta.content
                    yield self._format_sse("content", {"content": delta.content})
            if assistant_content:
                messages.append({"role": "assistant", "content": assistant_content})

        # 最终兜底：避免前端长时间等待后无可见输出
        if not assistant_content:
            assistant_content = "我已完成检索，但暂时无法整理出最终回答。请换个问法，或指定文档与页码后我继续回答。"
            yield self._format_sse("content", {"content": assistant_content})
            messages.append({"role": "assistant", "content": assistant_content})

        # 静默日志：检查引用格式（不影响用户，仅用于数据驱动优化 prompt）
        if tool_results_for_answer and assistant_content:
            has_citation = bool(re.search(r'\[\[.*?p\.\d+\]\]', assistant_content))
            if not has_citation:
                agent_logger.warning(
                    f"[CITATION_MISS] conv={conversation_id}, "
                    f"tools={[r['tool_name'] for r in tool_results_for_answer]}, "
                    f"content_len={len(assistant_content)}"
                )

        # 发送完成事件
        yield self._format_sse(
            "done",
            {
                "conversation_id": conversation_id,
                "tool_results": self._sanitize_tool_result_for_client(
                    tool_results_for_answer
                ),
            },
        )

        # 保存完整消息历史到全局缓存（包含工具调用记录，供下一轮使用）
        if conversation_state_key:
            _CONVERSATION_MESSAGES[conversation_state_key] = (
                self._sanitize_messages_for_conversation_history(messages)
            )

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
        preferred_document_ids: Optional[List[str]],
        folder_id: Optional[str],
        include_subfolders: bool,
        strict_scope: Optional[bool],
    ) -> List[Dict[str, Any]]:
        planner = RetrievalPlanner()
        plan = planner.plan(
            question=question,
            document_ids=preferred_document_ids,
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
            cleaned = {}
            for k, v in result.items():
                if k in {"page_image_base64", "image_base64"}:
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
    ) -> AsyncGenerator[str, None]:
        """
        简单聊天模式 - 当没有文档时使用
        直接调用 LLM，不使用任何工具
        """
        from app.prompts import CHAT_SYSTEM_PROMPT
        from app.core.llm import async_chat_completion

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
            response = await async_chat_completion(
                messages=messages,
                model=None,  # 使用默认模型
                stream=True,
                temperature=0.7,
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
                    yield self._format_sse(
                        "thinking", {"content": delta.reasoning_content, "step": 0}
                    )

                # 输出内容
                if delta.content:
                    full_content += delta.content
                    yield self._format_sse("content", {"content": delta.content})

            print(
                f"[SimpleChat] Stream complete, {chunk_count} chunks, {len(full_content)} chars"
            )

            # 发送完成事件
            yield self._format_sse("done", {"content": full_content})

        except Exception as e:
            print(f"[SimpleChat] Error: {e}")
            import traceback

            traceback.print_exc()
            yield self._format_sse("error", {"message": str(e)})

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
            if folder_id and not patched.get("folder_id"):
                patched["folder_id"] = folder_id
            if include_subfolders and "recursive" not in patched:
                patched["recursive"] = include_subfolders
            return patched

        if tool_name == "find_related_documents":
            if preferred_document_ids and not patched.get("user_selected_document_ids"):
                patched["user_selected_document_ids"] = preferred_document_ids
            if preferred_document_ids and not patched.get("document_ids"):
                patched["document_ids"] = preferred_document_ids
            if folder_id and not patched.get("folder_id"):
                patched["folder_id"] = folder_id
            if include_subfolders and "include_subfolders" not in patched:
                patched["include_subfolders"] = include_subfolders
            if strict_scope is not None and "strict_scope" not in patched:
                patched["strict_scope"] = strict_scope
            if "allow_global_expansion" not in patched:
                patched["allow_global_expansion"] = True
            return patched

        return tool_args
