import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_service import ChatService  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402
from phase0_chat_helpers import (  # noqa: E402
    create_chat_history_schema,
    parse_sse_frames,
    sse_frame,
)
from app.agent.loop_runtime import ObservationBuilder  # noqa: E402
from app.agent.nodes import compact_tool_result  # noqa: E402


LEGACY_STREAM_EVENTS = {"thinking", "content", "tool_call", "tool_result", "done"}


def test_compact_tool_result_preserves_error_and_next_steps() -> None:
    result = compact_tool_result(
        {
            "success": False,
            "error": "Document report.pdf does not exist. Use doc_id='doc-a'.",
            "next_steps": {
                "summary": "Retry with the resolved document id.",
                "options": [
                    "Retry search_within_document(doc_id='doc-a', query='alpha')."
                ],
            },
        },
        tool_name="search_within_document",
    )

    assert result == {
        "success": False,
        "status": "error",
        "summary": "Document report.pdf does not exist. Use doc_id='doc-a'.",
        "error": "Document report.pdf does not exist. Use doc_id='doc-a'.",
        "items": [],
        "citations": [],
        "next_steps": [
            "Retry with the resolved document id.",
            "Retry search_within_document(doc_id='doc-a', query='alpha').",
        ],
    }


def test_observation_builder_surfaces_tool_error_instead_of_empty_result() -> None:
    observation = ObservationBuilder().build(
        tool_name="search_within_document",
        arguments={"doc_id": "report.pdf", "query": "alpha"},
        result={
            "success": False,
            "error": "Document report.pdf does not exist. Use doc_id='doc-a'.",
            "next_steps": ["Retry with doc_id='doc-a'."],
        },
        step=1,
    )

    assert observation["message"] == "Document report.pdf does not exist. Use doc_id='doc-a'."
    assert observation["success"] is False
    assert observation["status"] == "error"
    assert observation["error"] == "Document report.pdf does not exist. Use doc_id='doc-a'."
    assert observation["next_steps"] == ["Retry with doc_id='doc-a'."]
    assert observation["evidence_sufficient"] is False


class FakeDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-alpha")]


class FakeProviderAgent:
    async def run_agent_stream(self, **kwargs):
        yield sse_frame(
            "tool_started",
            {
                "tool_name": "get_page_content",
                "arguments": {"doc_id": "doc-alpha", "pages": "2"},
            },
        )
        yield sse_frame(
            "tool_completed",
            {
                "tool_name": "get_page_content",
                "result": {
                    "status": "success",
                    "page_image_base64": "raw-image-payload",
                    "text_content": "raw page text that must not reach clients",
                    "citations": [
                        {
                            "citation_key": "c1",
                            "document_id": "doc-alpha",
                            "document_name": "alpha.pdf",
                            "source_anchor": {"format": "pdf", "start_page": 2},
                            "display_label": "alpha.pdf p.2",
                            "preview_kind": "pdf",
                        }
                    ],
                },
                "elapsed_ms": 12,
            },
        )
        yield sse_frame("answer_delta", {"content": "Alpha"})


class FailingProviderAgent:
    async def run_agent_stream(self, **kwargs):
        yield sse_frame("answer_delta", {"content": "partial"})
        raise RuntimeError("provider connection lost")


class DuplicateCitationAgent:
    async def run_agent_stream(self, **kwargs):
        citation = {
            "citation_key": "c-alpha",
            "document_id": "doc-alpha",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 2},
            "display_label": "alpha.pdf p.2",
            "preview_kind": "pdf",
        }
        for step in range(2):
            yield sse_frame(
                "tool_started",
                {
                    "tool_name": "get_page_content",
                    "arguments": {"doc_id": "doc-alpha", "pages": "2"},
                    "step": step,
                },
            )
            yield sse_frame(
                "tool_completed",
                {
                    "tool_name": "get_page_content",
                    "result": {"status": "success", "citations": [dict(citation)]},
                    "elapsed_ms": 10 + step,
                },
            )
        yield sse_frame(
            "citation_added",
            {
                "citation": {
                    "citation_key": "c-duplicate-direct",
                    "document_id": "doc-alpha",
                    "document_name": "alpha.pdf",
                    "source_anchor": {"format": "pdf", "start_page": 2},
                    "display_label": "same source, different label",
                    "preview_kind": "pdf",
                }
            },
        )
        yield sse_frame("answer_delta", {"content": "Alpha"})


class AnswerOnlyAgent:
    async def run_agent_stream(self, **kwargs):
        yield sse_frame("answer_delta", {"content": "Alpha"})


class FakeNoToolDelta:
    content = "final answer"
    tool_calls = None


class FakeNoToolChunk:
    choices = [SimpleNamespace(delta=FakeNoToolDelta())]


class FakeNoToolStream:
    def __aiter__(self):
        self._done = False
        return self

    async def __anext__(self):
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return FakeNoToolChunk()


def _planner_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _is_planner_request(kwargs: dict) -> bool:
    messages = kwargs.get("messages") or []
    if not messages:
        return False
    return "Choose the next single PageChat agent action" in str(
        messages[0].get("content", "")
    )


def test_agent_service_emits_loop_runtime_tool_events_without_initial_retrieval(
    monkeypatch,
) -> None:
    async def run() -> None:
        from app.services.agent_service import AgentService

        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = object()
        service.document_service = FakeDocumentService()
        planner_actions = [
            {
                "thought": "I will inspect the selected document structure.",
                "action": {
                    "type": "call_tool",
                    "tool_name": "get_document_structure",
                    "arguments": {"compact": True},
                },
            },
            {
                "thought": "I will read likely source pages next.",
                "action": {
                    "type": "call_tool",
                    "tool_name": "get_page_content",
                    "arguments": {"pages": "1"},
                },
            },
            {
                "thought": "I have enough observed evidence to answer.",
                "action": {"type": "answer", "content": "final answer"},
            },
        ]

        async def fake_chat_by_scenario(**_kwargs):
            assert "allow_deterministic_tools" not in _kwargs
            if _is_planner_request(_kwargs):
                return _planner_response(
                    json.dumps(planner_actions.pop(0), ensure_ascii=False)
                )
            return FakeNoToolStream()

        async def fail_initial_retrieval_plan(**_kwargs):
            raise AssertionError("legacy initial retrieval must not run")

        monkeypatch.setattr(
            "app.services.agent_service.chat_by_scenario",
            fake_chat_by_scenario,
        )
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fail_initial_retrieval_plan),
        )

        frames = [
            frame
            async for frame in service.run_agent_stream(
                question="Summarize alpha",
                conversation_id="conv-deterministic",
                document_ids=["doc-alpha"],
                preferred_document_ids=["doc-alpha"],
                strict_scope=True,
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "progress",
            "answer_delta",
        ]
        assert not (LEGACY_STREAM_EVENTS & {event["event"] for event in events})
        assert events[0]["data"]["kind"] == "plan"
        assert events[1]["data"]["tool_name"] == "get_document_structure"
        assert events[2]["data"]["result"]["status"] in {"", "error"}
        assert events[3]["data"]["kind"] == "observation"
        assert events[4]["data"]["kind"] == "plan"
        assert events[5]["data"]["tool_name"] == "get_page_content"
        assert events[7]["data"]["kind"] == "observation"
        assert events[8]["data"]["kind"] == "plan"

    asyncio.run(run())


def test_chat_service_emits_normalized_pagechat_run_events() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-phase0-events', 'Event protocol regression', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: FakeProviderAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-phase0-events",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT event_type, payload_json
                FROM agent_run_events
                ORDER BY seq
                """
            )
            persisted_events = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT protocol
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT agent_steps
                FROM messages
                WHERE conversation_id = 'conv-phase0-events' AND role = 'assistant'
                ORDER BY sequence
                LIMIT 1
                """
            )
            assistant_steps_row = await cursor.fetchone()

        events = parse_sse_frames(frames)
        raw_payload = json.dumps(events, ensure_ascii=False)
        persisted_payload = json.dumps(
            [json.loads(row[1]) for row in persisted_events],
            ensure_ascii=False,
        )
        assistant_steps_payload = assistant_steps_row[0] if assistant_steps_row else ""
        actual_protocol = {
            "event_types": [event["event"] for event in events],
            "seqs": [event["data"].get("seq") for event in events],
            "all_events_have_run_metadata": all(
                event["data"].get("run_id")
                and event["data"].get("conversation_id") == "conv-phase0-events"
                and event["data"].get("message_id")
                for event in events
            ),
            "all_events_have_ts": all(event["data"].get("ts") for event in events),
            "leaked_raw_provider_thinking": (
                "raw provider chain-of-thought" in raw_payload
                or any(event["event"] == "thinking" for event in events)
            ),
            "leaked_raw_tool_payload": any(
                leaked in (raw_payload + persisted_payload + assistant_steps_payload)
                for leaked in ("page_image_base64", "raw page text")
            ),
            "run_protocol": run_row[0],
            "run_protocol_has_fallback_marker": any(
                marker in run_row[0] for marker in ("->", ",", "fallback")
            ),
            "persisted_event_types": [row[0] for row in persisted_events],
        }

        assert actual_protocol == {
            "event_types": [
                "run_started",
                "tool_started",
                "tool_completed",
                "answer_delta",
                "answer_delta",
                "citation_added",
                "run_completed",
            ],
            "seqs": [1, 2, 3, 4, 5, 6, 7],
            "all_events_have_run_metadata": True,
            "all_events_have_ts": True,
            "leaked_raw_provider_thinking": False,
            "leaked_raw_tool_payload": False,
            "run_protocol": "chat_completions",
            "run_protocol_has_fallback_marker": False,
            "persisted_event_types": [
                "run_started",
                "tool_started",
                "tool_completed",
                "answer_delta",
                "answer_delta",
                "citation_added",
                "run_completed",
            ],
        }

    asyncio.run(run())


def test_chat_service_emits_and_persists_run_failed_on_agent_exception() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-phase0-failed', 'Failure protocol regression', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: FailingProviderAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-phase0-failed",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT event_type, payload_json
                FROM agent_run_events
                ORDER BY seq
                """
            )
            persisted_events = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                WHERE conversation_id = 'conv-phase0-failed'
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()

        events = parse_sse_frames(frames)
        actual_protocol = {
            "event_types": [event["event"] for event in events],
            "all_events_have_ts": all(event["data"].get("ts") for event in events),
            "all_events_have_run_metadata": all(
                event["data"].get("run_id")
                and event["data"].get("conversation_id") == "conv-phase0-failed"
                and event["data"].get("message_id")
                for event in events
            ),
            "persisted_event_types": [row[0] for row in persisted_events],
            "run_status": run_row[0],
            "run_error": run_row[1],
            "message_statuses": [(row[0], row[2]) for row in message_rows],
            "assistant_content": message_rows[1][1],
        }

        assert actual_protocol == {
            "event_types": ["run_started", "answer_delta", "run_failed"],
            "all_events_have_ts": True,
            "all_events_have_run_metadata": True,
            "persisted_event_types": ["run_started", "answer_delta", "run_failed"],
            "run_status": "failed",
            "run_error": "provider connection lost",
            "message_statuses": [("user", "completed"), ("assistant", "failed")],
            "assistant_content": "partial",
        }

    asyncio.run(run())


def test_chat_service_fails_same_run_when_run_started_event_cannot_persist() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-run-start-failed', 'Run start failure', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: AnswerOnlyAgent()
            original_append = service.run_repository.append_run_event

            async def flaky_append(run_id, event_type, payload):
                if event_type == "run_started":
                    raise RuntimeError("event store unavailable")
                return await original_append(run_id, event_type, payload)

            service.run_repository.append_run_event = flaky_append

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-run-start-failed",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                WHERE conversation_id = 'conv-run-start-failed'
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == ["run_failed"]
        assert message_rows == [
            ("user", "Summarize alpha", "completed"),
            ("assistant", "", "failed"),
        ]
        assert run_row == ("failed", "event store unavailable")
        assert [row[0] for row in event_rows] == ["run_failed"]

    asyncio.run(run())


def test_chat_service_complete_run_failure_does_not_emit_run_completed() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-complete-failed', 'Complete failure', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: AnswerOnlyAgent()

            async def failing_complete_run(*_args, **_kwargs):
                raise RuntimeError("final persistence exploded")

            service.run_repository.complete_run = failing_complete_run

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-complete-failed",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            persisted_events = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT content, status
                FROM messages
                WHERE conversation_id = 'conv-complete-failed' AND role = 'assistant'
                ORDER BY sequence
                LIMIT 1
                """
            )
            assistant_row = await cursor.fetchone()

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "run_started",
            "answer_delta",
            "run_failed",
        ]
        assert [row[0] for row in persisted_events] == [
            "run_started",
            "answer_delta",
            "run_failed",
        ]
        assert "run_completed" not in [event["event"] for event in events]
        assert run_row == ("failed", "final persistence exploded")
        assert assistant_row == ("Alpha", "failed")

    asyncio.run(run())


def test_chat_service_dedupes_citations_across_multiple_tool_results() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-duplicate-citations', 'Duplicate citation regression', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = FakeDocumentService()
            service._get_agent_service = lambda: DuplicateCitationAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-duplicate-citations",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT citation_key, document_id, display_label
                FROM message_citations
                ORDER BY created_at, id
                """
            )
            persisted_citations = await cursor.fetchall()

        events = parse_sse_frames(frames)
        emitted_citations = [
            event["data"]["citation"]
            for event in events
            if event["event"] == "citation_added"
        ]

        assert emitted_citations == [
            {
                "id": emitted_citations[0]["id"],
                "citation_key": "c-alpha",
                "document_id": "doc-alpha",
                "document_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 2},
                "display_label": "alpha.pdf p.2",
                "preview_kind": "pdf",
            }
        ]
        assert persisted_citations == [
            ("c-alpha", "doc-alpha", "alpha.pdf p.2")
        ]

    asyncio.run(run())
