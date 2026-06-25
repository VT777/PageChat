from pathlib import Path
import sys
import asyncio
import json
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService
from app.services.citation_binding_service import (
    bind_answer_citations,
    build_missing_citation_suffix,
    collect_citation_evidence,
    has_document_citation,
)


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


def test_agent_stream_repairs_missing_citation_and_emits_bindings(monkeypatch) -> None:
    class FakeDocumentService:
        async def get_indexed_documents(self, user_id=None):
            return [SimpleNamespace(id="doc-cq")]

    class FakeToolExecutor:
        def __init__(self, *args, **kwargs):
            pass

    class FakeContentChunk:
        choices = [
            SimpleNamespace(
                delta=SimpleNamespace(
                    content="重庆工业投资增长来自制造业升级。",
                    reasoning_content=None,
                    tool_calls=None,
                )
            )
        ]

    class FakeStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_sent", False):
                raise StopAsyncIteration
            self._sent = True
            return FakeContentChunk()

    async def run() -> None:
        agent = AgentService.__new__(AgentService)
        agent.db = None
        agent.pageindex_service = object()
        agent.document_service = FakeDocumentService()

        async def fake_execute_initial_retrieval_plan(**kwargs):
            return [
                {
                    "tool_name": "get_page_content",
                    "arguments": {"doc_id": "doc-cq", "page_nums": [12]},
                    "result": {
                        "doc_id": "doc-cq",
                        "doc_name": "重庆统计年鉴.pdf",
                        "page_num": 12,
                        "text_content": "工业投资增长来自制造业升级。",
                    },
                }
            ]

        async def fake_chat_by_scenario(**kwargs):
            return FakeStream()

        monkeypatch.setattr("app.services.agent_service.ToolExecutor", FakeToolExecutor)
        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fake_execute_initial_retrieval_plan),
        )
        monkeypatch.setattr("app.services.agent_service.chat_by_scenario", fake_chat_by_scenario)

        events = [
            event
            async for event in agent.run_agent_stream(
                question="重庆工业投资增长原因是什么？",
                document_ids=["doc-cq"],
                user_id="user-a",
                max_steps=1,
            )
        ]

        assert any("[[重庆统计年鉴.pdf p.12]]" in event for event in events if event.startswith("event: content"))
        done = [event for event in events if event.startswith("event: done")][-1]
        payload = json.loads(done.split("data: ", 1)[1])
        assert payload["citation_bindings"][0]["doc_id"] == "doc-cq"
        assert payload["citation_bindings"][0]["source_anchor"]["start_page"] == 12

    asyncio.run(run())
