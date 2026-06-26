"""Manual QA runner for PageChat agent runtime scenarios.

The script is intentionally HTTP/SSE based so it verifies the same API that the
frontend uses. Unit tests cover the pure validation helpers; real model and
document checks should be run manually against a prepared backend.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request


LEGACY_EVENTS = {"thinking", "content", "tool_call", "tool_result", "done"}
DOCUMENT_TOOL_NAMES = {
    "browse_documents",
    "find_related_documents",
    "search_within_document",
    "get_document_structure",
    "get_page_content",
    "get_document_image",
}
WEB_TOOL_NAMES = {"web_search", "search_web", "anysearch", "anysearch_search"}


@dataclass(frozen=True)
class Scenario:
    id: str
    question: str
    scope: str
    expected_tools: str
    require_citation: bool
    description: str
    expected_tool_chain: tuple[str, ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="cq-ai-innovation",
        question="重庆师范大学有什么 AI 应用的创新？",
        scope="document",
        expected_tools="document",
        require_citation=True,
        description="Selected Chongqing document should drive document tools and inline citations.",
        expected_tool_chain=(
            "browse_documents",
            "search_within_document",
            "get_page_content",
        ),
    ),
    Scenario(
        id="cq-compare-themes",
        question="对比文档中 AI 应用、数据治理、教学改革三类内容。",
        scope="document",
        expected_tools="document",
        require_citation=True,
        description="A broader comparison should show multiple document evidence steps.",
    ),
    Scenario(
        id="cq-chapter-3-requirements",
        question="只看第 3 章，提炼可落地的功能需求。",
        scope="document",
        expected_tools="document",
        require_citation=True,
        description="Page/chapter-scoped document questions should not expand to unrelated library content.",
    ),
    Scenario(
        id="beijing-weather",
        question="北京天气怎么样？",
        scope="none",
        expected_tools="web_or_none",
        require_citation=False,
        description="General weather question should not trigger document retrieval; web search is optional.",
    ),
)


def parse_sse_frames(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_type = ""
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_type, data_lines
        if not event_type and not data_lines:
            return
        payload = "\n".join(data_lines).strip()
        data: Any = {}
        if payload:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"raw": payload}
        events.append({"event": event_type or "message", "data": data})
        event_type = ""
        data_lines = []

    for line in raw.splitlines():
        if not line.strip():
            flush()
            continue
        if line.startswith("event: "):
            event_type = line[7:].strip()
        elif line.startswith("data: "):
            data_lines.append(line[6:])
    flush()
    return events


def scenario_payload(
    scenario: Scenario,
    *,
    document_id: str | None,
    web_search_enabled: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": scenario.question}
    if scenario.scope == "document":
        if not document_id:
            raise ValueError(f"Scenario {scenario.id} requires --document-id")
        payload.update({"document_ids": [document_id], "strict_scope": True})
    if scenario.expected_tools == "web_or_none":
        payload.update(
            {
                "web_search_requested": bool(web_search_enabled),
                "web_search_enabled": bool(web_search_enabled),
            }
        )
    return payload


def _tool_name(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    return str(data.get("tool_name") or data.get("name") or "")


def _has_ordered_tool_chain(tool_names: list[str], expected_chain: tuple[str, ...]) -> bool:
    if not expected_chain:
        return True
    cursor = 0
    for name in tool_names:
        if name == expected_chain[cursor]:
            cursor += 1
            if cursor == len(expected_chain):
                return True
    return False


def validate_scenario_events(
    scenario: Scenario,
    events: list[dict[str, Any]],
    *,
    web_search_enabled: bool = False,
) -> list[str]:
    failures: list[str] = []
    names = [str(event.get("event") or "") for event in events]
    tool_names = [_tool_name(event) for event in events if str(event.get("event")) == "tool_started"]
    citations = [
        (event.get("data") or {}).get("citation") or {}
        for event in events
        if str(event.get("event")) == "citation_added"
    ]

    leaked_legacy = [name for name in names if name in LEGACY_EVENTS]
    if leaked_legacy:
        failures.append(f"legacy events leaked: {', '.join(leaked_legacy)}")

    if not events:
        failures.append("no SSE events received")
        return failures

    if names[-1] != "run_completed":
        failures.append(f"terminal event should be run_completed, got {names[-1]!r}")

    for index, event in enumerate(events):
        data = event.get("data") or {}
        if event.get("event") in {"run_started", "tool_started", "tool_completed", "answer_delta", "citation_added", "run_completed"}:
            missing = [key for key in ("run_id", "conversation_id", "message_id", "seq", "ts") if key not in data]
            if missing:
                failures.append(f"event {index}:{event.get('event')} missing metadata {missing}")

    if scenario.expected_tools == "document":
        if not any(name in DOCUMENT_TOOL_NAMES for name in tool_names):
            failures.append("document scenario did not start a document tool")
        if any(name in WEB_TOOL_NAMES for name in tool_names):
            failures.append("document scenario unexpectedly used a web tool")
        if scenario.expected_tool_chain and not _has_ordered_tool_chain(
            tool_names,
            scenario.expected_tool_chain,
        ):
            failures.append(
                "required tool chain was not observed: "
                + " -> ".join(scenario.expected_tool_chain)
            )
    elif scenario.expected_tools == "web_or_none":
        if any(name in DOCUMENT_TOOL_NAMES for name in tool_names):
            failures.append("general web scenario unexpectedly used document tools")
        if web_search_enabled and not any(name in WEB_TOOL_NAMES for name in tool_names):
            failures.append("web search was enabled/requested but no web tool started")

    if scenario.require_citation and not citations:
        failures.append("required citation_added event was not emitted")

    if citations:
        for citation in citations:
            if not citation.get("display_label") or not citation.get("source_anchor"):
                failures.append("citation is missing display_label or source_anchor")

    return failures


def post_stream(
    base_url: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = base_url.rstrip("/") + "/api/chat/stream"
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return parse_sse_frames(raw)


def run_scenarios(
    *,
    base_url: str,
    token: str,
    document_id: str | None,
    web_search_enabled: bool,
    timeout: int,
) -> list[dict[str, Any]]:
    results = []
    for scenario in SCENARIOS:
        payload = scenario_payload(
            scenario,
            document_id=document_id,
            web_search_enabled=web_search_enabled,
        )
        events = post_stream(base_url, token, payload, timeout=timeout)
        failures = validate_scenario_events(
            scenario,
            events,
            web_search_enabled=web_search_enabled,
        )
        results.append(
            {
                "scenario": scenario,
                "payload": payload,
                "events": events,
                "failures": failures,
            }
        )
    return results


def build_markdown_report(
    results: list[dict[str, Any]],
    *,
    base_url: str,
    document_name: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# PageChat Agent Runtime Verification",
        "",
        f"- Generated: `{now}`",
        f"- Backend: `{base_url}`",
        f"- Document: `{document_name}`",
        "",
        "| Scenario | Status | Event Summary | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        scenario: Scenario = result["scenario"]
        failures = result["failures"]
        status = "PASS" if not failures else "FAIL"
        event_summary = ", ".join(event["event"] for event in result["events"])
        notes = "; ".join(failures) if failures else scenario.description
        lines.append(f"| `{scenario.id}` | {status} | `{event_summary}` | {notes} |")
    lines.append("")
    lines.append("## Raw Event Counts")
    lines.append("")
    for result in results:
        scenario = result["scenario"]
        lines.append(f"- `{scenario.id}`: {len(result['events'])} events")
    lines.append("")
    return "\n".join(lines)


def build_dry_run_report(document_name: str) -> str:
    rows = [
        "# PageChat Agent Runtime Verification Plan",
        "",
        f"- Target document: `{document_name}`",
        "",
        "| Scenario | Question | Expected |",
        "| --- | --- | --- |",
    ]
    for scenario in SCENARIOS:
        rows.append(
            f"| `{scenario.id}` | {scenario.question} | {scenario.description} |"
        )
    rows.append("")
    return "\n".join(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", help="Bearer token for a logged-in PageChat user")
    parser.add_argument("--document-id", help="Parsed Chongqing document id")
    parser.add_argument(
        "--document-name",
        default="2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--web-search-enabled", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        report = build_dry_run_report(args.document_name)
    else:
        if not args.token:
            raise SystemExit("--token is required unless --dry-run is used")
        results = run_scenarios(
            base_url=args.base_url,
            token=args.token,
            document_id=args.document_id,
            web_search_enabled=args.web_search_enabled,
            timeout=args.timeout,
        )
        report = build_markdown_report(
            results,
            base_url=args.base_url,
            document_name=args.document_name,
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
