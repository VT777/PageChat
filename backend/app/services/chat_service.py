"""
问答服务 - KnowClaw
直接转发 Agent 事件，不添加假的阶段事件
支持流式消息的增量保存和恢复
"""

import json
import re
import uuid
import asyncio
import logging
from typing import AsyncGenerator, List, Optional
import aiosqlite

from app.core import config
from app.services.document_service import DocumentService
from app.services.chat_attachment_service import ChatAttachmentService
from app.services.web_search_settings_service import WebSearchSettingsService
from app.agent.events import (
    PageChatEventEmitter,
    citation_events_from_tool_result,
    parse_sse_frame,
    sse_frame,
)
from app.agent.citations import citation_dedupe_key, dedupe_citations, normalize_citation
from app.agent.nodes import compact_tool_result
from app.agent.provider_adapter import CHAT_COMPLETIONS_PROTOCOL
from app.services.chat_run_repository import ChatRunRepository
from app.services.conversation_evidence_repository import ConversationEvidenceRepository
from app.services.tool_executor import AGENT_TOOLS
from app.services.web_search_tool import WEB_SEARCH_TOOL
from app.services.folder_service import FolderService
from app.services.retrieval_policy import normalize_folder_id
from app.services.citation_binding_service import has_document_citation
from app.services.model_settings_service import (
    ModelRouteNotConfiguredError,
    model_route_not_configured_payload,
)
from app.prompts import build_tool_catalog


chat_logger = logging.getLogger("chat")


class ChatService:
    """问答服务 - 直接转发 Agent SSE 事件"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.agent_service = None
        self.document_service = DocumentService(db)
        self.folder_service = FolderService(db)
        self.run_repository = ChatRunRepository(db)
        self.evidence_repository = ConversationEvidenceRepository(db)

    def _get_agent_service(self):
        if self.agent_service is None:
            from app.services.agent_service import AgentService

            self.agent_service = AgentService(self.db)
        return self.agent_service

    def _get_attachment_service(self) -> ChatAttachmentService:
        return ChatAttachmentService(self.db)

    def _history_message_limit(self) -> int:
        return max(1, config.MULTITURN_MAX_USER_ROUNDS * 2)

    async def _runtime_tools_for_request(
        self,
        *,
        user_id: str | None,
        web_search_requested: bool,
        web_search_enabled: bool,
    ) -> list[dict]:
        enabled = bool(web_search_requested or web_search_enabled)
        if not enabled and self.db is not None and user_id:
            settings = await WebSearchSettingsService(self.db).resolve_for_request(
                user_id=user_id,
                requested=web_search_requested,
            )
            enabled = bool(settings.get("enabled"))
        tools = [
            tool
            for tool in AGENT_TOOLS
            if tool.get("function", {}).get("name") != "web_search"
        ]
        if enabled:
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

    async def _record_tool_evidence(
        self,
        *,
        conversation_id: str,
        run_id: str,
        tool_name: str,
        tool_arguments: dict,
        compact_result: dict,
        scope_key: str,
    ) -> None:
        try:
            await self.evidence_repository.record_tool_result(
                conversation_id=conversation_id,
                run_id=run_id,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                compact_result=compact_result,
                scope_key=scope_key,
            )
        except Exception as exc:
            chat_logger.warning("Failed to record conversation evidence: %s", exc)

    def _compact_tool_result_for_client(self, result: dict, tool_name: str) -> dict:
        if self._looks_like_compact_tool_result(result):
            return result
        return compact_tool_result(result, tool_name=tool_name)

    def _looks_like_compact_tool_result(self, result: object) -> bool:
        if not isinstance(result, dict):
            return False
        if any(key in result for key in ("page_image_base64", "image_base64", "data")):
            return False
        return any(key in result for key in ("items", "citations", "structure", "next_steps"))

    async def _resolve_valid_folder_id(
        self, folder_id: Optional[str], user_id: Optional[str]
    ) -> tuple[Optional[str], bool]:
        normalized = normalize_folder_id(folder_id)
        if not normalized:
            return None, False
        folder = await self.folder_service.get_folder(normalized, user_id=user_id)
        if not folder:
            return None, True
        return normalized, False

    async def get_history_messages(
        self, conversation_id: str, limit: int = 20
    ) -> List[dict]:
        """获取历史消息"""
        cursor = await self.db.execute(
            """
            SELECT role, content, thinking_content, agent_steps, status
            FROM messages
            WHERE conversation_id = ?
            ORDER BY COALESCE(sequence, 999999), created_at, id
            LIMIT ?
            """,
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "role": row[0],
                "content": row[1],
                "thinking": row[2] or "",
                "tool_steps": json.loads(row[3]) if row[3] else [],
                "status": row[4] or "completed",
            }
            for row in rows
        ]

    async def ensure_conversation(
        self, conversation_id: Optional[str], user_id: str = None
    ) -> str:
        """确保对话存在，返回 conversation_id（关联到用户）"""
        if conversation_id:
            query = "SELECT id FROM conversations WHERE id = ?"
            params = [conversation_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await self.db.execute(query, params)
            if await cursor.fetchone():
                return conversation_id

        new_id = __import__("uuid").uuid4().hex[:16]
        await self.db.execute(
            "INSERT INTO conversations (id, title, user_id) VALUES (?, ?, ?)",
            (new_id, "新对话", user_id),
        )
        await self.db.commit()
        return new_id

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        thinking_content: str = "",
        agent_steps: str = "[]",
        status: str = "completed",
        attachments: Optional[List[dict]] = None,
        run_id: str = None,
    ) -> str:
        """保存消息，返回消息 ID"""
        return await self.run_repository.create_message(
            conversation_id,
            role,
            content,
            thinking_content=thinking_content,
            agent_steps=agent_steps,
            status=status,
            run_id=run_id,
            attachments=self._attachment_metadata(attachments),
        )

    @staticmethod
    def _attachment_metadata(attachments: Optional[List[dict]]) -> Optional[List[dict]]:
        if not attachments:
            return None
        metadata = []
        for item in attachments:
            attachment_id = item.get("attachment_id")
            if not attachment_id:
                continue
            metadata.append(
                {
                    "attachment_id": attachment_id,
                    "original_name": item.get("original_name") or "image",
                    "mime_type": item.get("mime_type"),
                    "size_bytes": item.get("size_bytes"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "content_url": f"/api/chat/attachments/{attachment_id}/content",
                }
            )
        if not metadata:
            return None
        return metadata

    @staticmethod
    def _missing_inline_citation_suffix(content: str, citations: list[dict]) -> str:
        if not citations or has_document_citation(content):
            return ""
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            anchor = citation.get("source_anchor") or {}
            anchor_format = (
                str(anchor.get("format") or "").lower()
                if isinstance(anchor, dict)
                else ""
            )
            preview_kind = str(citation.get("preview_kind") or "").lower()
            if preview_kind == "web" or anchor_format == "web":
                continue
            unit_type = str(anchor.get("unit_type") or "").lower() if isinstance(anchor, dict) else ""
            has_precise_anchor = (
                any(
                    anchor.get(key) not in (None, "")
                    for key in (
                        "start_page",
                        "page",
                        "start_line",
                        "start_row",
                        "start_paragraph",
                        "start_slide",
                        "slide",
                    )
                )
                if isinstance(anchor, dict)
                else False
            )
            if unit_type == "document" or not has_precise_anchor:
                continue
            display_label = str(citation.get("display_label") or "").strip()
            if display_label:
                return f" [[{display_label}]]"
        return ""

    @staticmethod
    def _tool_result_can_cite_answer(tool_name: str) -> bool:
        return tool_name in {
            "get_page_content",
            "get_page_image",
            "get_document_image",
            "search_within_document",
            "web_search",
        }

    async def update_message(
        self,
        message_id: str,
        content: str = None,
        thinking_content: str = None,
        agent_steps: str = None,
        status: str = None,
    ):
        """更新消息的增量内容"""
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if thinking_content is not None:
            updates.append("thinking_content = ?")
            params.append(thinking_content)
        if agent_steps is not None:
            updates.append("agent_steps = ?")
            params.append(agent_steps)
        if status is not None:
            updates.append("status = ?")
            params.append(status)

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(message_id)

        await self.db.execute(
            f"UPDATE messages SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        cursor = await self.db.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (message_id,)
        )
        row = await cursor.fetchone()
        if row:
            await self.run_repository.touch_conversation(row[0])
        else:
            await self.db.commit()

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
        web_search: bool = False,
        web_search_requested: bool = False,
        web_search_enabled: bool = False,
        attachment_ids: Optional[List[str]] = None,
        user_id: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式问答 - 直接转发 Agent 事件
        实时保存所有中间状态到数据库

        SSE 事件：
        - run_started / progress
        - tool_started / tool_completed
        - answer_delta
        - citation_added
        - run_completed / run_failed / run_cancelled
        """
        conversation_id = await self.ensure_conversation(
            conversation_id, user_id=user_id
        )
        web_search_requested = bool(web_search_requested or web_search)
        web_search_enabled = bool(web_search_enabled or web_search)

        request_attachments = []
        attachment_error: Optional[str] = None
        attachment_ids = list(dict.fromkeys(attachment_ids or []))
        if attachment_ids:
            try:
                request_attachments = await self._get_attachment_service().attachments_for_model(
                    user_id, attachment_ids
                )
            except ValueError as exc:
                attachment_error = str(exc)

        # 保存用户消息
        user_message_id = await self.save_message(
            conversation_id, "user", question, attachments=request_attachments
        )
        if attachment_ids and not attachment_error:
            try:
                await self._get_attachment_service().bind_to_message(
                    user_id,
                    attachment_ids,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                )
            except ValueError as exc:
                attachment_error = str(exc)
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        full_content = ""
        full_thinking = ""
        tool_steps = []
        pending_citations = []
        emitted_citation_keys: set[str] = set()
        last_tool_name = ""
        last_tool_call_id = ""
        last_tool_arguments: dict = {}
        assistant_message_id: Optional[str] = None
        emitter: Optional[PageChatEventEmitter] = None
        run_created = False
        run_protocol = CHAT_COMPLETIONS_PROTOCOL

        async def ensure_run(protocol: str = CHAT_COMPLETIONS_PROTOCOL) -> None:
            nonlocal assistant_message_id, emitter, run_created, run_protocol
            run_protocol = protocol
            if assistant_message_id is None:
                assistant_message_id = await self.save_message(
                    conversation_id,
                    "assistant",
                    "",
                    "",
                    "[]",
                    "streaming",
                    run_id=run_id,
                )
            if not run_created:
                await self.run_repository.create_run(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    protocol=protocol,
                )
                run_created = True
            if emitter is None:
                emitter = PageChatEventEmitter(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                )

        async def emit(event_type: str, payload: dict) -> str:
            if emitter is None:
                raise RuntimeError("Cannot emit run event before run is created")
            built_event_type, data = emitter.build(event_type, payload)
            seq = await self.run_repository.append_run_event(
                run_id,
                built_event_type,
                data,
            )
            data["seq"] = seq
            return sse_frame(built_event_type, data)

        async def fail_current_run(
            error_message: str,
            error_payload: Optional[dict] = None,
        ) -> str:
            try:
                await self.db.rollback()
            except Exception:
                pass
            payload = {
                "status": "failed",
                "error": error_message,
            }
            if error_payload:
                payload.update(error_payload)
            persisted_error = str(
                payload.get("message") or payload.get("error") or error_message
            )
            await ensure_run(run_protocol)
            await self.update_message(
                assistant_message_id,
                content=full_content,
                thinking_content=full_thinking,
                agent_steps=json.dumps(tool_steps, ensure_ascii=False),
                status="failed",
            )
            try:
                frame = await emit(
                    "run_failed",
                    payload,
                )
            except Exception:
                if emitter is None:
                    raise
                built_event_type, data = emitter.build(
                    "run_failed",
                    payload,
                )
                frame = sse_frame(built_event_type, data)
            await self.run_repository.fail_run(run_id, persisted_error)
            return frame

        def citation_identity(citation: dict) -> str:
            return citation_dedupe_key(citation)

        async def emit_citation_once(citation: dict) -> Optional[str]:
            key = citation_identity(citation)
            if key in emitted_citation_keys:
                return None
            emitted_citation_keys.add(key)
            return await emit("citation_added", {"citation": citation})

        if attachment_error:
            try:
                await ensure_run("attachment_validation")
                yield await emit("run_started", {"status": "running"})
                yield await fail_current_run(f"图片附件不可用：{attachment_error}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                yield sse_frame("run_failed", {"error": str(e), "status": "failed"})
            return

        # 工具查询走确定性响应，避免模型漏报工具
        if re.search(
            r"(有哪些|有什么|能用|可用|支持|available|support|use).*(工具|tools?|tooling)"
            r"|(工具|tools?|tooling).*(有哪些|有什么|能用|可用|支持|available|support|use)",
            question,
            re.IGNORECASE,
        ):
            runtime_tools = await self._runtime_tools_for_request(
                user_id=user_id,
                web_search_requested=web_search_requested,
                web_search_enabled=web_search_enabled,
            )
            content = "当前可用工具如下：\n" + build_tool_catalog(runtime_tools)
            try:
                await ensure_run("deterministic")
                yield await emit("run_started", {"status": "running"})
                full_content = content
                yield await emit("answer_delta", {"content": content})
                await self.run_repository.complete_run(
                    run_id,
                    final_content=content,
                    citations=[],
                )
                yield await emit("run_completed", {"status": "completed"})
            except asyncio.CancelledError:
                raise
            except Exception as e:
                yield await fail_current_run(str(e))
            return

        # 获取历史消息
        try:
            history = await self.get_history_messages(
                conversation_id,
                limit=self._history_message_limit(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield await fail_current_run(str(e))
            return
        # 去掉最后一条（当前问题）
        if history and history[-1].get("content") == question:
            history = history[:-1]

        try:
            await ensure_run(CHAT_COMPLETIONS_PROTOCOL)
            yield await emit("run_started", {"status": "running"})

            folder_id, invalid_folder_scope = await self._resolve_valid_folder_id(
                folder_id, user_id
            )

        # 获取可用文档
            docs = await self.document_service.get_indexed_documents(user_id=user_id)
            available_doc_ids = [d.id for d in docs]
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield await fail_current_run(str(e))
            return

        # 前端可指定文档范围：默认严格限制在选中文档；strict_scope=false 时才扩展到用户库。
        preferred_document_ids: Optional[List[str]] = None
        requested_document_scope = document_ids is not None
        valid_ids: List[str] = []
        if document_ids:
            valid_ids = [did for did in document_ids if did in available_doc_ids]
            preferred_document_ids = valid_ids

        can_expand_to_user_library = bool(valid_ids or folder_id)
        suppress_user_library_fallback = bool(
            (requested_document_scope and not valid_ids and not folder_id)
            or (invalid_folder_scope and not valid_ids)
        )

        if requested_document_scope and strict_scope is not False:
            document_ids = valid_ids
        elif strict_scope is False and can_expand_to_user_library:
            document_ids = available_doc_ids if available_doc_ids else None
        else:
            document_ids = None

        try:
            agent = self._get_agent_service()
        except Exception as e:
            yield await fail_current_run(str(e))
            return

        from app.services.agent_service import AgentService

        effective_strict_scope = (
            strict_scope if strict_scope is not None else bool(document_ids or folder_id)
        )
        evidence_scope_key = AgentService._scope_cache_key(
            user_id,
            document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=effective_strict_scope,
        )

        # 累积的内容
        full_content = ""
        # 上次保存的时间
        last_save_time = __import__("time").time()
        save_interval = 1.0  # 每秒保存一次

        async def agent_events():
            try:
                async for agent_event in agent.run_agent_stream(
                    question=question,
                    conversation_id=conversation_id,
                    document_ids=document_ids,
                    preferred_document_ids=preferred_document_ids,
                    folder_id=folder_id,
                    include_subfolders=include_subfolders,
                    strict_scope=strict_scope,
                    web_search_requested=web_search_requested,
                    web_search_enabled=web_search_enabled,
                    request_attachments=request_attachments,
                    suppress_user_library_fallback=suppress_user_library_fallback,
                    user_id=user_id,
                    history_messages=history,
                    run_id=run_id,
                    message_id=assistant_message_id or "",
                ):
                    yield agent_event
            except asyncio.CancelledError:
                await self.update_message(
                    assistant_message_id,
                    content=full_content,
                    thinking_content=full_thinking,
                    agent_steps=json.dumps(tool_steps, ensure_ascii=False),
                    status="cancelled",
                )
                try:
                    await emit("run_cancelled", {"status": "cancelled"})
                except Exception:
                    pass
                await self.run_repository.cancel_run(run_id)
                raise
            except ModelRouteNotConfiguredError as exc:
                yield sse_frame(
                    "__agent_error__",
                    model_route_not_configured_payload(exc),
                )
            except Exception as e:
                yield sse_frame("__agent_error__", {"error": str(e)})

        async for event in agent_events():
            try:
                # 解析事件类型和内容
                if event.startswith("event: "):
                    event_type, data = parse_sse_frame(event)

                    # 根据事件类型更新累积内容并转为 PageChat 标准事件。
                    if event_type == "__agent_error__":
                        error_message = (
                            data.get("message")
                            or data.get("error")
                            or "Agent stream failed"
                        )
                        yield await fail_current_run(error_message, dict(data))
                        return
                    elif event_type == "processing_delta":
                        processing_payload = dict(data)
                        for metadata_key in (
                            "run_id",
                            "conversation_id",
                            "message_id",
                            "seq",
                            "ts",
                        ):
                            processing_payload.pop(metadata_key, None)
                        content_delta = str(processing_payload.get("content") or "")
                        if content_delta:
                            full_thinking += content_delta
                        yield await emit("processing_delta", processing_payload)
                    elif event_type == "tool_call_delta":
                        tool_delta_payload = dict(data)
                        for metadata_key in (
                            "run_id",
                            "conversation_id",
                            "message_id",
                            "seq",
                            "ts",
                        ):
                            tool_delta_payload.pop(metadata_key, None)
                        yield await emit("tool_call_delta", tool_delta_payload)
                    elif event_type == "progress":
                        progress_payload = dict(data)
                        for metadata_key in (
                            "run_id",
                            "conversation_id",
                            "message_id",
                            "seq",
                            "ts",
                        ):
                            progress_payload.pop(metadata_key, None)
                        yield await emit("progress", progress_payload)
                    elif event_type == "answer_delta":
                        content_delta = data.get("content", "")
                        full_content += content_delta
                        yield await emit("answer_delta", {"content": content_delta})
                    elif event_type == "tool_started":
                        last_tool_name = data.get("tool_name", "")
                        last_tool_call_id = data.get("tool_call_id", "") or last_tool_call_id
                        arguments = data.get("arguments", {})
                        last_tool_arguments = dict(arguments or {})
                        tool_steps.append(
                            {
                                "toolCallId": last_tool_call_id or None,
                                "toolName": last_tool_name,
                                "arguments": arguments,
                                "status": "calling",
                                "result": None,
                            }
                        )
                        yield await emit(
                            "tool_started",
                            {
                                "tool_call_id": last_tool_call_id or None,
                                "tool_name": last_tool_name,
                                "arguments": arguments,
                            },
                        )
                    elif event_type == "tool_completed":
                        result = data.get("result", {})
                        elapsed_ms = data.get("elapsed_ms")
                        tool_name = data.get("tool_name") or last_tool_name
                        tool_call_id = data.get("tool_call_id") or last_tool_call_id
                        tool_arguments = data.get("arguments")
                        if not isinstance(tool_arguments, dict):
                            tool_arguments = last_tool_arguments
                        compact_result = self._compact_tool_result_for_client(
                            result,
                            str(tool_name or ""),
                        )
                        if tool_steps:
                            tool_steps[-1]["status"] = "done"
                            tool_steps[-1]["result"] = compact_result
                            tool_steps[-1]["elapsedMs"] = elapsed_ms
                            if tool_call_id:
                                tool_steps[-1]["toolCallId"] = tool_call_id
                        if self._tool_result_can_cite_answer(str(tool_name or "")):
                            pending_citations = dedupe_citations(
                                pending_citations
                                + citation_events_from_tool_result(result)
                            )
                        await self._record_tool_evidence(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            tool_name=str(tool_name or ""),
                            tool_arguments=dict(tool_arguments or {}),
                            compact_result=compact_result,
                            scope_key=evidence_scope_key,
                        )
                        yield await emit(
                            "tool_completed",
                            {
                                "tool_call_id": tool_call_id or None,
                                "tool_name": tool_name,
                                "arguments": tool_arguments,
                                "result": compact_result,
                                "elapsed_ms": elapsed_ms,
                            },
                        )
                    elif event_type == "citation_added":
                        citation = data.get("citation")
                        if isinstance(citation, dict):
                            citation = normalize_citation(citation)
                            previous_count = len(pending_citations)
                            pending_citations = dedupe_citations(
                                pending_citations + [citation]
                            )
                            if len(pending_citations) > previous_count:
                                citation_frame = await emit_citation_once(citation)
                                if citation_frame:
                                    yield citation_frame
                    elif event_type == "run_failed":
                        error_message = data.get("error") or "Agent stream failed"
                        yield await fail_current_run(error_message)
                        return
                    else:
                        yield await fail_current_run(
                            f"Unsupported agent event: {event_type}"
                        )
                        return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                yield await fail_current_run(str(e))
                return

            # 定期保存到数据库
            current_time = __import__("time").time()
            if current_time - last_save_time >= save_interval:
                try:
                    await self.update_message(
                        assistant_message_id,
                        content=full_content,
                        thinking_content=full_thinking,
                        agent_steps=json.dumps(tool_steps, ensure_ascii=False),
                        status="streaming",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    yield await fail_current_run(str(e))
                    return
                last_save_time = current_time

        # 最终保存（标记为完成）
        try:
            pending_citations = dedupe_citations(pending_citations)
            citation_suffix = self._missing_inline_citation_suffix(
                full_content,
                pending_citations,
            )
            if citation_suffix:
                full_content += citation_suffix
                yield await emit("answer_delta", {"content": citation_suffix})
            for citation in pending_citations:
                citation_frame = await emit_citation_once(citation)
                if citation_frame:
                    yield citation_frame
            await self.update_message(
                assistant_message_id,
                content=full_content,
                thinking_content=full_thinking,
                agent_steps=json.dumps(tool_steps, ensure_ascii=False),
                status="streaming",
            )
            await self.run_repository.complete_run(
                run_id,
                final_content=full_content,
                citations=dedupe_citations(pending_citations),
            )
            yield await emit("run_completed", {"status": "completed"})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield await fail_current_run(str(e))
            return
