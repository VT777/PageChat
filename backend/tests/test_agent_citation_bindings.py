from pathlib import Path
import sys
import asyncio
import json
from types import SimpleNamespace

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations
from app.agent.citations import citation_events_from_tool_result
from app.services.chat_service import ChatService
from app.services.citation_binding_service import (
    bind_answer_citations,
    build_missing_citation_suffix,
    collect_citation_evidence,
    has_document_citation,
)
from phase0_chat_helpers import create_chat_history_schema, parse_sse_frames, sse_frame


def test_collect_citation_evidence_from_tool_results() -> None:
    evidence = collect_citation_evidence(
        [
            {
                "tool_name": "get_page_content",
                "result": {
                    "doc_id": "doc-cq",
                    "doc_name": "重庆统计年鉴.pdf",
                    "page_num": 12,
                    "text_content": "工业投资增长来自制造业升级，更多长文本不应完整进入引用绑定。",
                },
            }
        ]
    )

    assert evidence[0] == {
        "doc_id": "doc-cq",
        "document_name": "重庆统计年鉴.pdf",
        "display_label": "重庆统计年鉴.pdf p.12",
        "source_anchor": {
            "format": "pdf",
            "unit_type": "page",
            "start_page": 12,
            "end_page": 12,
        },
        "snippet": "工业投资增长来自制造业升级，更多长文本不应完整进入引用绑定。",
    }


def test_bind_answer_citations_matches_marker_to_source_anchor() -> None:
    bindings = bind_answer_citations(
        "重庆工业投资增长来自制造业升级 [[重庆统计年鉴.pdf p.12]]。",
        [
            {
                "tool_name": "get_page_content",
                "result": {
                    "doc_id": "doc-cq",
                    "doc_name": "重庆统计年鉴.pdf",
                    "page_num": 12,
                    "source_anchor": {
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 12,
                        "end_page": 12,
                    },
                },
            }
        ],
    )

    assert bindings == [
        {
            "marker": "[[重庆统计年鉴.pdf p.12]]",
            "label": "重庆统计年鉴.pdf p.12",
            "doc_id": "doc-cq",
            "document_name": "重庆统计年鉴.pdf",
            "display_label": "重庆统计年鉴.pdf p.12",
            "source_anchor": {
                "format": "pdf",
                "unit_type": "page",
                "start_page": 12,
                "end_page": 12,
            },
            "resolved": True,
        }
    ]


def test_missing_citation_suffix_uses_first_document_evidence() -> None:
    tool_results = [
        {
            "tool_name": "search_within_document",
            "result": {
                "matches": [
                    {
                        "doc_id": "doc-cq",
                        "doc_name": "重庆统计年鉴.pdf",
                        "display_label": "重庆统计年鉴.pdf p.8",
                        "source_anchor": {
                            "format": "pdf",
                            "unit_type": "page",
                            "start_page": 8,
                            "end_page": 8,
                        },
                    }
                ]
            },
        }
    ]

    assert has_document_citation("已有引用 [[重庆统计年鉴.pdf p.8]]") is True
    assert build_missing_citation_suffix("没有引用的回答", tool_results) == " [[重庆统计年鉴.pdf p.8]]"
    assert build_missing_citation_suffix("已有引用 [[重庆统计年鉴.pdf p.8]]", tool_results) == ""


def test_chat_service_missing_inline_citation_suffix_ignores_document_inventory_citations() -> None:
    citations = [
        {
            "citation_key": "doc-a:{document}",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "display_label": "alpha.pdf",
            "source_anchor": {"format": "pdf", "unit_type": "document"},
            "preview_kind": "pdf",
        }
    ]

    assert ChatService._missing_inline_citation_suffix("当前库中有 alpha.pdf。", citations) == ""


def test_citation_events_ignore_document_inventory_without_page_anchor() -> None:
    citations = citation_events_from_tool_result(
        {
            "status": "success",
            "documents": [
                {
                    "doc_id": "doc-a",
                    "name": "alpha.pdf",
                    "file_type": ".pdf",
                    "page_count": 12,
                }
            ],
        }
    )

    assert citations == []


def test_chat_stream_repairs_missing_inline_citation_and_emits_bindings() -> None:
    class FakeDocumentService:
        async def get_indexed_documents(self, user_id=None):
            return [SimpleNamespace(id="doc-cq")]

    class EvidenceAgent:
        async def run_agent_stream(self, **kwargs):
            yield sse_frame(
                "progress",
                {"kind": "plan", "message": "先读取文档页面证据。", "step": 1},
            )
            yield sse_frame(
                "tool_started",
                {
                    "tool_name": "get_page_content",
                    "arguments": {"doc_id": "doc-cq", "pages": "12"},
                },
            )
            yield sse_frame(
                "tool_completed",
                {
                    "tool_name": "get_page_content",
                    "arguments": {"doc_id": "doc-cq", "pages": "12"},
                    "result": {
                        "status": "success",
                        "doc_id": "doc-cq",
                        "doc_name": "重庆统计年鉴.pdf",
                        "page_num": 12,
                        "text_content": "工业投资增长来自制造业升级。",
                    },
                    "elapsed_ms": 8,
                },
            )
            yield sse_frame(
                "answer_delta",
                {"content": "重庆工业投资增长来自制造业升级。"},
            )

    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-citation-repair', 'Citation repair', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: EvidenceAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="重庆工业投资增长原因是什么？",
                    conversation_id="conv-citation-repair",
                    document_ids=["doc-cq"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT content
                FROM messages
                WHERE conversation_id = 'conv-citation-repair' AND role = 'assistant'
                ORDER BY sequence
                LIMIT 1
                """
            )
            assistant_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT document_id, display_label, source_anchor_json
                FROM message_citations
                ORDER BY created_at, id
                """
            )
            persisted_citations = await cursor.fetchall()

        events = parse_sse_frames(frames)
        answer_text = "".join(
            event["data"].get("content", "")
            for event in events
            if event["event"] == "answer_delta"
        )
        citation_events = [
            event["data"]["citation"]
            for event in events
            if event["event"] == "citation_added"
        ]

        assert [event["event"] for event in events] == [
            "run_started",
            "progress",
            "tool_started",
            "tool_completed",
            "answer_delta",
            "answer_delta",
            "citation_added",
            "run_completed",
        ]
        assert answer_text.endswith("[[重庆统计年鉴 p.12]]")
        assert assistant_row[0].endswith("[[重庆统计年鉴 p.12]]")
        assert citation_events[0]["document_id"] == "doc-cq"
        assert citation_events[0]["source_anchor"]["start_page"] == 12
        assert persisted_citations == [
            (
                "doc-cq",
                "重庆统计年鉴 p.12",
                json.dumps(
                    {
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 12,
                        "end_page": 12,
                    },
                    ensure_ascii=False,
                ),
            )
        ]

    asyncio.run(run())


def test_chat_stream_uses_page_evidence_not_structure_ranges_for_citations() -> None:
    class FakeDocumentService:
        async def get_indexed_documents(self, user_id=None):
            return [SimpleNamespace(id="doc-cq")]

    class StructureThenPageAgent:
        async def run_agent_stream(self, **kwargs):
            yield sse_frame(
                "tool_completed",
                {
                    "tool_name": "get_document_structure",
                    "result": {
                        "status": "success",
                        "doc_id": "doc-cq",
                        "doc_name": "重庆案例.pdf",
                        "structure": [
                            {
                                "title": "案例分类",
                                "source_anchor": {
                                    "format": "pdf",
                                    "unit_type": "page",
                                    "start_page": 3,
                                    "end_page": 16,
                                },
                            }
                        ],
                    },
                },
            )
            yield sse_frame(
                "tool_completed",
                {
                    "tool_name": "get_page_content",
                    "result": {
                        "status": "success",
                        "doc_id": "doc-cq",
                        "doc_name": "重庆案例.pdf",
                        "page_num": 12,
                        "text_content": "重庆智慧交通案例提到信号灯优化。",
                    },
                },
            )
            yield sse_frame(
                "answer_delta",
                {"content": "重庆智慧交通案例提到信号灯优化。"},
            )

    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-page-citation', 'Page citation', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: StructureThenPageAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="重庆智慧交通案例说了什么？",
                    conversation_id="conv-page-citation",
                    document_ids=["doc-cq"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

        events = parse_sse_frames(frames)
        answer_text = "".join(
            event["data"].get("content", "")
            for event in events
            if event["event"] == "answer_delta"
        )
        citation_events = [
            event["data"]["citation"]
            for event in events
            if event["event"] == "citation_added"
        ]

        assert answer_text.endswith("[[重庆案例 p.12]]")
        assert citation_events == [
            {
                "id": citation_events[0]["id"],
                "citation_key": citation_events[0]["citation_key"],
                "document_id": "doc-cq",
                "document_name": "重庆案例.pdf",
                "source_anchor": {
                    "format": "pdf",
                    "unit_type": "page",
                    "start_page": 12,
                    "end_page": 12,
                },
                "display_label": "重庆案例 p.12",
                "preview_kind": "pdf",
            }
        ]

    asyncio.run(run())
