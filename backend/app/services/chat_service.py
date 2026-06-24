"""
问答服务 - KnowClaw
直接转发 Agent 事件，不添加假的阶段事件
支持流式消息的增量保存和恢复
"""

import json
import re
from typing import AsyncGenerator, List, Optional
import aiosqlite

from app.core import config
from app.services.document_service import DocumentService
from app.core.llm import chat_by_scenario
from app.prompts import CHAT_SYSTEM_PROMPT, build_tool_catalog
from app.services.tool_executor import AGENT_TOOLS


class ChatService:
    """问答服务 - 直接转发 Agent SSE 事件"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.agent_service = None
        self.document_service = DocumentService(db)

    def _get_agent_service(self):
        if self.agent_service is None:
            from app.services.agent_service import AgentService

            self.agent_service = AgentService(self.db)
        return self.agent_service

    def _history_message_limit(self) -> int:
        return max(1, config.MULTITURN_MAX_USER_ROUNDS * 2)

    async def get_history_messages(
        self, conversation_id: str, limit: int = 20
    ) -> List[dict]:
        """获取历史消息"""
        cursor = await self.db.execute(
            "SELECT role, content, thinking_content, agent_steps, status FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
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
    ) -> str:
        """保存消息，返回消息 ID"""
        message_id = __import__("uuid").uuid4().hex[:16]
        await self.db.execute(
            """INSERT INTO messages 
               (id, conversation_id, role, content, thinking_content, agent_steps, status) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                conversation_id,
                role,
                content,
                thinking_content,
                agent_steps,
                status,
            ),
        )
        await self.db.commit()
        return message_id

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
        await self.db.commit()

    async def stream_chat(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        folder_id: Optional[str] = None,
        include_subfolders: bool = False,
        strict_scope: Optional[bool] = None,
        user_id: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式问答 - 直接转发 Agent 事件
        实时保存所有中间状态到数据库

        SSE 事件：
        - thinking: 模型思考过程
        - content: 答案内容
        - tool_call: 工具调用
        - tool_result: 工具结果
        - done: 完成
        """
        conversation_id = await self.ensure_conversation(
            conversation_id, user_id=user_id
        )

        # 尽早告知前端后端会话ID，避免页面切换时丢失映射
        yield f"event: conversation\ndata: {json.dumps({'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

        # 保存用户消息
        await self.save_message(conversation_id, "user", question)

        # 工具查询走确定性响应，避免模型漏报工具
        if re.search(
            r"(有哪些|有什么|能用|可用|支持).*(工具|tool)|(工具|tool).*(有哪些|有什么|能用|可用|支持)",
            question,
            re.IGNORECASE,
        ):
            content = "当前可用工具如下：\n" + build_tool_catalog(AGENT_TOOLS)
            yield f"event: content\ndata: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"
            await self.save_message(
                conversation_id, "assistant", content, status="completed"
            )
            return

        # 获取历史消息
        history = await self.get_history_messages(
            conversation_id,
            limit=self._history_message_limit(),
        )
        # 去掉最后一条（当前问题）
        if history and history[-1].get("content") == question:
            history = history[:-1]

        # 获取可用文档
        docs = await self.document_service.get_indexed_documents(user_id=user_id)
        available_doc_ids = [d.id for d in docs]

        # 前端可指定文档范围：默认严格限制在选中文档；strict_scope=false 时才扩展到用户库。
        preferred_document_ids: Optional[List[str]] = None
        requested_document_scope = document_ids is not None
        valid_ids: List[str] = []
        if document_ids:
            valid_ids = [did for did in document_ids if did in available_doc_ids]
            if valid_ids:
                preferred_document_ids = valid_ids

        if requested_document_scope and strict_scope is not False:
            document_ids = valid_ids
        else:
            document_ids = available_doc_ids if available_doc_ids else None

        agent = self._get_agent_service()

        # 创建助手消息并获取 ID
        assistant_message_id = await self.save_message(
            conversation_id, "assistant", "", "", "[]", "streaming"
        )

        # 累积的内容
        full_content = ""
        full_thinking = ""
        tool_steps = []

        # 上次保存的时间
        last_save_time = __import__("time").time()
        save_interval = 1.0  # 每秒保存一次

        async for event in agent.run_agent_stream(
            question=question,
            conversation_id=conversation_id,
            document_ids=document_ids,
            preferred_document_ids=preferred_document_ids,
            folder_id=folder_id,
            include_subfolders=include_subfolders,
            strict_scope=strict_scope,
            user_id=user_id,
            history_messages=history,
        ):
            yield event

            try:
                # 解析事件类型和内容
                if event.startswith("event: "):
                    lines = event.strip().split("\n")
                    event_type = lines[0][7:].strip()  # 去掉 "event: "

                    if len(lines) >= 2 and lines[1].startswith("data: "):
                        data_str = lines[1][6:]  # 去掉 "data: "
                        data = json.loads(data_str)

                        # 根据事件类型更新累积内容
                        if event_type == "thinking":
                            full_thinking += data.get("content", "")
                        elif event_type == "content":
                            full_content += data.get("content", "")
                        elif event_type == "tool_call":
                            tool_steps.append(
                                {
                                    "toolName": data.get("tool_name", ""),
                                    "arguments": data.get("arguments", {}),
                                    "status": "calling",
                                    "result": None,
                                }
                            )
                        elif event_type == "tool_result":
                            # 更新最后一个工具调用的结果
                            if tool_steps:
                                tool_steps[-1]["status"] = "done"
                                tool_steps[-1]["result"] = data.get("result", {})
                                tool_steps[-1]["elapsedMs"] = data.get("elapsed_ms")
                        elif event_type == "done":
                            # 标记完成
                            pass
            except Exception as e:
                print(f"[ChatService] Error processing event: {e}")

            # 定期保存到数据库
            current_time = __import__("time").time()
            if current_time - last_save_time >= save_interval:
                await self.update_message(
                    assistant_message_id,
                    content=full_content,
                    thinking_content=full_thinking,
                    agent_steps=json.dumps(tool_steps, ensure_ascii=False),
                    status="streaming",
                )
                last_save_time = current_time

        # 最终保存（标记为完成）
        await self.update_message(
            assistant_message_id,
            content=full_content,
            thinking_content=full_thinking,
            agent_steps=json.dumps(tool_steps, ensure_ascii=False),
            status="completed",
        )
