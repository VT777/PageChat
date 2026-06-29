from __future__ import annotations

import json
import re
from typing import Any

import aiosqlite


REUSABLE_EVIDENCE_TOOLS = {
    "browse_documents",
    "get_document_structure",
    "get_page_content",
    "search_within_document",
    "web_search",
}

_DROP_KEYS = {
    "page_image_base64",
    "image_base64",
    "base64",
    "data_base64",
    "file_path",
    "local_file_path",
    "index_path",
    "embedding",
    "rerank_score",
    "score",
}


class ConversationEvidenceRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def record_tool_result(
        self,
        *,
        conversation_id: str,
        run_id: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
        compact_result: dict[str, Any],
        scope_key: str,
    ) -> int:
        if tool_name not in REUSABLE_EVIDENCE_TOOLS:
            return 0
        if not conversation_id or not scope_key:
            return 0

        payload = self._sanitize(compact_result)
        if not isinstance(payload, dict):
            return 0

        records = self._records_from_payload(
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            payload=payload,
        )
        inserted = 0
        for record in records:
            doc_updated_at = await self._document_updated_at(record.get("doc_id"))
            arguments_json = json.dumps(
                tool_arguments or {},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            payload_json = json.dumps(
                record["payload"],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            citations_json = json.dumps(
                record.get("citations") or [],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            await self.db.execute(
                """
                DELETE FROM conversation_evidence
                WHERE conversation_id = ?
                  AND scope_key = ?
                  AND tool_name = ?
                  AND tool_arguments_json = ?
                  AND COALESCE(doc_id, '') = COALESCE(?, '')
                  AND COALESCE(page, -1) = COALESCE(?, -1)
                """,
                (
                    conversation_id,
                    scope_key,
                    tool_name,
                    arguments_json,
                    record.get("doc_id"),
                    record.get("page"),
                ),
            )
            await self.db.execute(
                """
                INSERT INTO conversation_evidence (
                    conversation_id, run_id, tool_name, tool_arguments_json,
                    doc_id, doc_name, page, snippet, citations_json, payload_json,
                    scope_key, document_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    run_id,
                    tool_name,
                    arguments_json,
                    record.get("doc_id"),
                    record.get("doc_name"),
                    record.get("page"),
                    record.get("snippet"),
                    citations_json,
                    payload_json,
                    scope_key,
                    doc_updated_at,
                ),
            )
            inserted += 1
        if inserted:
            await self.db.commit()
        return inserted

    async def list_relevant(
        self,
        *,
        conversation_id: str,
        scope_key: str,
        question: str,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            """
            SELECT
                e.tool_name,
                e.tool_arguments_json,
                e.doc_id,
                e.doc_name,
                e.page,
                e.snippet,
                e.citations_json,
                e.payload_json,
                e.created_at
            FROM conversation_evidence e
            LEFT JOIN documents d ON d.id = e.doc_id
            WHERE e.conversation_id = ?
              AND e.scope_key = ?
              AND (
                e.doc_id IS NULL
                OR (
                    d.id IS NOT NULL
                    AND (
                        e.document_updated_at IS NULL
                        OR d.updated_at = e.document_updated_at
                    )
                )
              )
              AND (
                e.tool_name != 'web_search'
                OR e.created_at >= datetime('now', '-15 minutes')
              )
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 24
            """,
            (conversation_id, scope_key),
        )
        rows = await cursor.fetchall()
        evidence = [self._row_to_evidence(row) for row in rows]
        if not evidence:
            return []

        scored = [
            (self._score(item, question), index, item)
            for index, item in enumerate(evidence)
        ]
        if any(score > 0 for score, _index, _item in scored):
            scored.sort(key=lambda item: (-item[0], item[1]))
        return [item for _score, _index, item in scored[: max(1, min(limit, 8))]]

    async def delete_for_conversation(self, conversation_id: str) -> None:
        await self.db.execute(
            "DELETE FROM conversation_evidence WHERE conversation_id = ?",
            (conversation_id,),
        )
        await self.db.commit()

    async def _document_updated_at(self, doc_id: Any) -> str | None:
        if not doc_id:
            return None
        cursor = await self.db.execute(
            "SELECT updated_at FROM documents WHERE id = ?",
            (str(doc_id),),
        )
        row = await cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def _records_from_payload(
        self,
        *,
        tool_name: str,
        tool_arguments: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if tool_name == "get_page_content":
            return self._page_records(payload)
        if tool_name == "search_within_document":
            return self._item_records(payload, fallback_arguments=tool_arguments)
        if tool_name == "web_search":
            return self._web_records(payload)
        return [self._single_record(payload, fallback_arguments=tool_arguments)]

    def _page_records(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return [self._single_record(payload, fallback_arguments={})]
        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row_payload = dict(payload)
            row_payload["items"] = [item]
            records.append(
                {
                    "doc_id": self._first(payload, item, keys=("doc_id", "document_id")),
                    "doc_name": self._first(payload, item, keys=("doc_name", "document_name", "name")),
                    "page": self._page_from(item),
                    "snippet": item.get("text") or item.get("snippet") or payload.get("summary") or "",
                    "citations": payload.get("citations") if isinstance(payload.get("citations"), list) else [],
                    "payload": row_payload,
                }
            )
        return records or [self._single_record(payload, fallback_arguments={})]

    def _item_records(
        self,
        payload: dict[str, Any],
        *,
        fallback_arguments: dict[str, Any],
    ) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return [self._single_record(payload, fallback_arguments=fallback_arguments)]
        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row_payload = dict(payload)
            row_payload["items"] = [item]
            records.append(
                {
                    "doc_id": self._first(item, fallback_arguments, payload, keys=("doc_id", "document_id")),
                    "doc_name": self._first(item, payload, keys=("doc_name", "document_name", "name", "title")),
                    "page": self._page_from(item),
                    "snippet": item.get("snippet") or item.get("text") or item.get("summary") or "",
                    "citations": payload.get("citations") if isinstance(payload.get("citations"), list) else [],
                    "payload": row_payload,
                }
            )
        return records or [self._single_record(payload, fallback_arguments=fallback_arguments)]

    def _web_records(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items") or payload.get("results")
        if not isinstance(items, list) or not items:
            return [self._single_record(payload, fallback_arguments={})]
        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row_payload = dict(payload)
            row_payload["items"] = [item]
            records.append(
                {
                    "doc_id": None,
                    "doc_name": item.get("title") or item.get("document_name") or item.get("url"),
                    "page": None,
                    "snippet": item.get("snippet") or item.get("content") or item.get("summary") or "",
                    "citations": payload.get("citations") if isinstance(payload.get("citations"), list) else [],
                    "payload": row_payload,
                }
            )
        return records or [self._single_record(payload, fallback_arguments={})]

    def _single_record(
        self,
        payload: dict[str, Any],
        *,
        fallback_arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "doc_id": self._first(payload, fallback_arguments, keys=("doc_id", "document_id")),
            "doc_name": self._first(payload, keys=("doc_name", "document_name", "name", "title")),
            "page": self._page_from(payload),
            "snippet": payload.get("summary") or payload.get("snippet") or "",
            "citations": payload.get("citations") if isinstance(payload.get("citations"), list) else [],
            "payload": payload,
        }

    def _row_to_evidence(self, row: Any) -> dict[str, Any]:
        payload = json.loads(row[7]) if row[7] else {}
        citations = json.loads(row[6]) if row[6] else []
        arguments = json.loads(row[1]) if row[1] else {}
        evidence = {
            "tool_name": row[0],
            "arguments": arguments,
            "doc_id": row[2],
            "doc_name": row[3],
            "page": row[4],
            "snippet": row[5] or "",
            "citations": citations,
            "result": payload,
            "reused": True,
        }
        if isinstance(payload, dict):
            for key, value in payload.items():
                evidence.setdefault(key, value)
        return evidence

    def _score(self, evidence: dict[str, Any], question: str) -> int:
        text = json.dumps(evidence, ensure_ascii=False).lower()
        tokens = {
            token.lower()
            for token in re.findall(r"[0-9A-Za-z_\u4e00-\u9fff]{2,}", question or "")
        }
        return sum(1 for token in tokens if token and token in text)

    def _sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, child in value.items():
                if key in _DROP_KEYS or key.endswith("_base64"):
                    continue
                cleaned[key] = self._sanitize(child)
            return cleaned
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        return value

    def _first(self, *items: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in keys:
                if item.get(key) not in (None, ""):
                    return item.get(key)
        return None

    def _page_from(self, item: dict[str, Any]) -> int | None:
        for key in ("page", "page_num", "start_page"):
            try:
                value = item.get(key)
                if value not in (None, ""):
                    page = int(value)
                    return page if page > 0 else None
            except (TypeError, ValueError):
                continue
        anchor = item.get("source_anchor")
        if isinstance(anchor, dict):
            return self._page_from(anchor)
        return None
