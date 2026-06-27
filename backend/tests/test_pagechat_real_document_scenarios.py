import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_pagechat_agent_runtime.py"


def load_script():
    spec = importlib.util.spec_from_file_location("verify_pagechat_agent_runtime", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def event(event_type: str, seq: int, **payload):
    data = {
        "run_id": "run-cq",
        "conversation_id": "conv-cq",
        "message_id": "msg-cq",
        "seq": seq,
        "ts": f"2026-06-26T10:00:{seq:02d}Z",
    }
    data.update(payload)
    return {"event": event_type, "data": data}


def test_chongqing_scenario_catalog_matches_phase_9_plan() -> None:
    module = load_script()

    scenario_ids = [scenario.id for scenario in module.SCENARIOS]
    questions = [scenario.question for scenario in module.SCENARIOS]

    assert scenario_ids == [
        "cq-ai-innovation",
        "cq-compare-themes",
        "cq-chapter-3-requirements",
        "beijing-weather",
    ]
    assert any("重庆师范大学" in question for question in questions)
    assert any("北京天气" in question for question in questions)


def test_document_scenario_payload_requires_strict_selected_document_scope() -> None:
    module = load_script()
    scenario = module.SCENARIOS[0]

    payload = module.scenario_payload(
        scenario,
        document_id="doc-chongqing",
        web_search_enabled=False,
    )

    assert payload == {
        "question": scenario.question,
        "document_ids": ["doc-chongqing"],
        "strict_scope": True,
    }


def test_document_scenario_payload_rejects_missing_document_id() -> None:
    module = load_script()

    with pytest.raises(ValueError, match="document-id"):
        module.scenario_payload(
            module.SCENARIOS[0],
            document_id=None,
            web_search_enabled=False,
        )


def test_parse_sse_frames_reads_pagechat_events() -> None:
    module = load_script()

    events = module.parse_sse_frames(
        "\n".join(
            [
                "event: run_started",
                'data: {"run_id":"run-1","seq":1}',
                "",
                "event: answer_delta",
                'data: {"content":"hello","seq":2}',
                "",
            ]
        )
    )

    assert events == [
        {"event": "run_started", "data": {"run_id": "run-1", "seq": 1}},
        {"event": "answer_delta", "data": {"content": "hello", "seq": 2}},
    ]


def test_document_scenario_accepts_tools_citations_and_completed_run() -> None:
    module = load_script()
    scenario = module.SCENARIOS[0]

    failures = module.validate_scenario_events(
        scenario,
        [
            event("run_started", 1, status="running"),
            event(
                "tool_started",
                2,
                tool_name="browse_documents",
                arguments={"query": "重庆师范大学"},
            ),
            event(
                "tool_completed",
                3,
                tool_name="browse_documents",
                result={"documents": [{"doc_id": "doc-chongqing"}]},
                elapsed_ms=21,
            ),
            event(
                "tool_started",
                4,
                tool_name="search_within_document",
                arguments={"doc_id": "doc-chongqing", "query": "重庆师范大学"},
            ),
            event(
                "tool_completed",
                5,
                tool_name="search_within_document",
                result={"count": 2},
                elapsed_ms=42,
            ),
            event(
                "tool_started",
                6,
                tool_name="get_page_content",
                arguments={"doc_id": "doc-chongqing", "pages": "43"},
            ),
            event(
                "tool_completed",
                7,
                tool_name="get_page_content",
                result={"doc_id": "doc-chongqing", "page_num": 43},
                elapsed_ms=30,
            ),
            event("answer_delta", 8, content="重庆师范大学案例包含 AI 教学创新。"),
            event(
                "citation_added",
                9,
                citation={
                    "citation_key": "c1",
                    "document_id": "doc-chongqing",
                    "document_name": "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf",
                    "display_label": "重庆案例 p.43",
                    "source_anchor": {"format": "pdf", "start_page": 43},
                    "preview_kind": "pdf",
                },
            ),
            event("run_completed", 10, status="completed"),
        ],
    )

    assert failures == []


def test_chongqing_document_scenario_accepts_model_chosen_document_tool_path() -> None:
    module = load_script()
    scenario = module.SCENARIOS[0]

    failures = module.validate_scenario_events(
        scenario,
        [
            event("run_started", 1, status="running"),
            event(
                "tool_started",
                2,
                tool_name="search_within_document",
                arguments={"doc_id": "doc-chongqing", "query": "重庆师范大学"},
            ),
            event(
                "tool_started",
                3,
                tool_name="get_page_content",
                arguments={"doc_id": "doc-chongqing", "pages": "43"},
            ),
            event(
                "citation_added",
                4,
                citation={
                    "display_label": "重庆案例 p.43",
                    "source_anchor": {"format": "pdf", "start_page": 43},
                },
            ),
            event("run_completed", 5, status="completed"),
        ],
    )

    assert failures == []


def test_document_scenario_rejects_legacy_events_and_missing_citations() -> None:
    module = load_script()
    scenario = module.SCENARIOS[0]

    failures = module.validate_scenario_events(
        scenario,
        [
            event("run_started", 1, status="running"),
            {"event": "content", "data": {"content": "legacy"}},
            event("run_completed", 2, status="completed"),
        ],
    )

    assert "legacy events leaked: content" in failures
    assert "document scenario did not start a document tool" in failures
    assert "required citation_added event was not emitted" in failures


def test_general_weather_scenario_rejects_document_retrieval() -> None:
    module = load_script()
    scenario = module.SCENARIOS[-1]

    failures = module.validate_scenario_events(
        scenario,
        [
            event("run_started", 1, status="running"),
            event("tool_started", 2, tool_name="search_within_document"),
            event("run_completed", 3, status="completed"),
        ],
        web_search_enabled=False,
    )

    assert failures == ["general web scenario unexpectedly used document tools"]


def test_dry_run_report_lists_all_scenarios() -> None:
    module = load_script()

    report = module.build_dry_run_report("重庆案例.pdf")

    assert "PageChat Agent Runtime Verification Plan" in report
    assert "cq-ai-innovation" in report
    assert "beijing-weather" in report
