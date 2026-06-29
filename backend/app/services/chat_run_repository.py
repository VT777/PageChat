import json
import uuid
import asyncio
from collections import defaultdict
from typing import Any, Optional

import aiosqlite

from app.agent.citations import dedupe_citations
from app.agent.events import validate_pagechat_event_payload

DEFAULT_CONVERSATION_TITLES = {"新对话", "New chat", "New Chat"}


class ChatRunRepository:
    _message_sequence_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    _run_event_sequence_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _next_message_sequence(self, conversation_id: str) -> int:
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        return int(row[0] or 1)

    async def _next_run_event_sequence(self, run_id: str) -> int:
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_run_events WHERE run_id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        return int(row[0] or 1)

    async def touch_conversation(self, conversation_id: str) -> None:
        await self.db.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
        await self.db.commit()

    async def _title_conversation_from_first_user_message(
        self,
        conversation_id: str,
        content: str,
        sequence: int,
        role: str,
    ) -> None:
        if role != "user" or sequence != 1:
            return
        title = self._conversation_title_from_message(content)
        if not title:
            return
        await self.db.execute(
            """
            UPDATE conversations
            SET title = ?
            WHERE id = ?
              AND (title IN (?, ?, ?) OR TRIM(COALESCE(title, '')) = '')
            """,
            (title, conversation_id, *sorted(DEFAULT_CONVERSATION_TITLES)),
        )

    @staticmethod
    def _conversation_title_from_message(content: str, limit: int = 32) -> str:
        title = " ".join(str(content or "").split())
        if not title:
            return ""
        if len(title) <= limit:
            return title
        return title[: limit - 1].rstrip() + "…"

    async def create_user_message(self, conversation_id: str, content: str) -> str:
        return await self.create_message(conversation_id, "user", content)

    async def create_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        thinking_content: str = "",
        agent_steps: str = "[]",
        status: str = "completed",
        run_id: Optional[str] = None,
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        async with self._message_sequence_locks[conversation_id]:
            message_id = uuid.uuid4().hex[:16]
            sequence = await self._next_message_sequence(conversation_id)
            attachments_json = (
                json.dumps(attachments, ensure_ascii=False) if attachments else None
            )
            await self.db.execute(
                """
                INSERT INTO messages
                    (id, conversation_id, role, content, thinking_content, agent_steps,
                     status, sequence, run_id, attachments_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    thinking_content,
                    agent_steps,
                    status,
                    sequence,
                    run_id,
                    attachments_json,
                ),
            )
            await self._title_conversation_from_first_user_message(
                conversation_id,
                content,
                sequence,
                role,
            )
            await self.touch_conversation(conversation_id)
            return message_id

    async def create_assistant_placeholder(
        self, conversation_id: str, run_id: str, content: str = ""
    ) -> str:
        return await self.create_message(
            conversation_id,
            "assistant",
            content,
            status="streaming",
            run_id=run_id,
        )

    async def create_run(
        self,
        *,
        run_id: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
        protocol: str,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO agent_runs
                (id, conversation_id, user_message_id, assistant_message_id,
                 status, provider_id, model, protocol)
            VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            (
                run_id,
                conversation_id,
                user_message_id,
                assistant_message_id,
                provider_id,
                model,
                protocol,
            ),
        )
        await self.touch_conversation(conversation_id)

    async def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        async with self._run_event_sequence_locks[run_id]:
            seq = await self._next_run_event_sequence(run_id)
            payload_to_store = dict(payload)
            payload_to_store["seq"] = seq
            if payload_to_store.get("run_id") != run_id:
                raise ValueError("PageChat event run_id does not match append run_id")
            validate_pagechat_event_payload(event_type, payload_to_store)
            await self.db.execute(
                """
                INSERT INTO agent_run_events (run_id, seq, event_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, seq, event_type, json.dumps(payload_to_store, ensure_ascii=False)),
            )
            await self.db.commit()
            return seq

    async def complete_run(
        self,
        run_id: str,
        *,
        final_content: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> None:
        cursor = await self.db.execute(
            "SELECT conversation_id, assistant_message_id FROM agent_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return

        conversation_id, assistant_message_id = row[0], row[1]
        await self.db.execute(
            """
            UPDATE agent_runs
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (run_id,),
        )
        await self.db.execute(
            """
            UPDATE messages
            SET content = ?, status = 'completed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (final_content, assistant_message_id),
        )

        citations = dedupe_citations(citations or [])
        if citations:
            await self.db.execute(
                "DELETE FROM message_citations WHERE message_id = ?",
                (assistant_message_id,),
            )
            for citation in citations:
                source_anchor = citation.get("source_anchor") or {}
                citation_id = citation.get("id") or uuid.uuid4().hex[:16]
                await self.db.execute(
                    """
                    INSERT INTO message_citations
                        (id, message_id, citation_key, document_id, document_name,
                         source_anchor_json, display_label, preview_kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        citation_id,
                        assistant_message_id,
                        citation.get("citation_key"),
                        citation.get("document_id"),
                        citation.get("document_name"),
                        json.dumps(source_anchor, ensure_ascii=False),
                        citation.get("display_label"),
                        citation.get("preview_kind"),
                    ),
                )

        await self.touch_conversation(conversation_id)
        await self.db.commit()

    async def fail_run(self, run_id: str, error: str) -> None:
        cursor = await self.db.execute(
            "SELECT conversation_id, assistant_message_id FROM agent_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return
        conversation_id, assistant_message_id = row[0], row[1]
        await self.db.execute(
            """
            UPDATE agent_runs
            SET status = 'failed', error = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error, run_id),
        )
        await self.db.execute(
            """
            UPDATE messages
            SET status = 'failed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (assistant_message_id,),
        )
        await self.touch_conversation(conversation_id)
        await self.db.commit()

    async def cancel_run(self, run_id: str) -> None:
        cursor = await self.db.execute(
            "SELECT conversation_id, assistant_message_id FROM agent_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return
        conversation_id, assistant_message_id = row[0], row[1]
        await self.db.execute(
            """
            UPDATE agent_runs
            SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (run_id,),
        )
        await self.db.execute(
            """
            UPDATE messages
            SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (assistant_message_id,),
        )
        await self.touch_conversation(conversation_id)
        await self.db.commit()

    async def list_run_events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT event_type, payload_json
            FROM agent_run_events
            WHERE run_id = ? AND seq > ?
            ORDER BY seq
            """,
            (run_id, after_seq),
        )
        events = []
        for row in await cursor.fetchall():
            events.append(
                {
                    "event": row[0],
                    "data": json.loads(row[1]) if row[1] else {},
                }
            )
        return events

    async def _message_column_exists(self, column_name: str) -> bool:
        cursor = await self.db.execute("PRAGMA table_info(messages)")
        rows = await cursor.fetchall()
        return any(row[1] == column_name for row in rows)

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        attachments_select = (
            "attachments_json"
            if await self._message_column_exists("attachments_json")
            else "NULL AS attachments_json"
        )
        cursor = await self.db.execute(
            f"""
            SELECT id, role, content, thinking_content, sources, agent_steps, status,
                   created_at, updated_at, sequence, run_id, {attachments_select}
            FROM messages
            WHERE conversation_id = ?
            ORDER BY COALESCE(sequence, 999999), created_at, id
            """,
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        message_ids = [row[0] for row in rows]
        citations_by_message: dict[str, list[dict[str, Any]]] = {mid: [] for mid in message_ids}

        if message_ids:
            placeholders = ",".join(["?"] * len(message_ids))
            citation_cursor = await self.db.execute(
                f"""
                SELECT message_id, citation_key, document_id, document_name,
                       source_anchor_json, display_label, preview_kind
                FROM message_citations
                WHERE message_id IN ({placeholders})
                ORDER BY created_at, id
                """,
                message_ids,
            )
            for row in await citation_cursor.fetchall():
                citations_by_message[row[0]].append(
                    {
                        "citation_key": row[1],
                        "document_id": row[2],
                        "document_name": row[3],
                        "source_anchor": json.loads(row[4]) if row[4] else {},
                        "display_label": row[5],
                        "preview_kind": row[6],
                    }
                )

        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "thinking": row[3] or "",
                    "sources": json.loads(row[4]) if row[4] else [],
                    "agent_steps": json.loads(row[5]) if row[5] else [],
                    "status": row[6] or "completed",
                    "created_at": row[7],
                    "updated_at": row[8],
                    "sequence": row[9],
                    "run_id": row[10],
                    "attachments": json.loads(row[11]) if row[11] else [],
                    "citations": citations_by_message.get(row[0], []),
                }
            )
        return messages

    async def list_messages_for_user(
        self, conversation_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        if not await cursor.fetchone():
            return []
        return await self.list_messages(conversation_id)
