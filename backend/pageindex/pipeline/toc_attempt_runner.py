"""Run TOC draft attempts through the unified S4 -> S5 -> S6 lifecycle."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from pageindex.toc_contracts import (
    TocContractError,
    assert_s4_draft_contract,
    normalize_mapped_toc,
    normalize_toc_draft,
)

Builder = Callable[[Mapping[str, Any]], Any]
Mapper = Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], Any]
QualityGate = Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], Any]


class TocAttemptRunner:
    """Execute deterministic TOC attempts without candidate competition."""

    def __init__(
        self,
        *,
        builders: Mapping[str, Builder],
        mapper: Mapper,
        quality_gate: QualityGate,
    ) -> None:
        self.builders = dict(builders)
        self.mapper = mapper
        self.quality_gate = quality_gate

    async def run(self, plan: Mapping[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
        attempts = _attempts_from_plan(plan)
        attempt_chain: list[dict[str, Any]] = []
        failure_reasons: list[str] = []
        best_candidate: Optional[dict[str, Any]] = None

        for index, attempt in enumerate(attempts, start=1):
            path = str(attempt.get("path") or "").strip()
            record: dict[str, Any] = {
                "attempt_id": index,
                "path": path,
                "builder": path,
                "mapping_status": "not_run",
                "quality_status": "not_run",
                "failure_reasons": [],
                "can_be_best_candidate": False,
            }

            builder = self.builders.get(path)
            if builder is None:
                _record_failure(record, f"builder_missing:{path or 'unknown'}")
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            try:
                raw_draft = await _maybe_await(builder(context))
                draft = normalize_toc_draft(raw_draft) if isinstance(raw_draft, Mapping) else raw_draft
                assert_s4_draft_contract(draft)
            except Exception as exc:
                _record_failure(record, f"draft_failed:{_brief_error(exc)}")
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            draft_items = _item_count(draft)
            record["draft_item_count"] = draft_items
            record["item_count"] = draft_items
            record["sample_titles"] = _sample_titles(draft)
            if draft_items <= 0:
                _record_failure(record, "draft_empty")
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            try:
                mapped = await _maybe_await(self.mapper(draft, context, attempt))
            except Exception as exc:
                _record_failure(record, f"mapping_exception:{_brief_error(exc)}")
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            mapping_report = mapped.get("mapping_report") if isinstance(mapped, Mapping) else {}
            mapping_status = str((mapping_report or {}).get("status") or mapped.get("status") or "ok").strip() if isinstance(mapped, Mapping) else "failed"
            record["mapping_status"] = mapping_status or "ok"
            if record["mapping_status"] == "failed":
                _record_failure(record, *((mapping_report or {}).get("reasons") or ["mapping_failed"]))
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            try:
                mapped = normalize_mapped_toc(mapped)
            except TocContractError as exc:
                _record_failure(record, f"mapped_contract:{_brief_error(exc)}")
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            record["can_be_best_candidate"] = True
            if best_candidate is None:
                best_candidate = dict(mapped)

            try:
                quality = await _maybe_await(self.quality_gate(mapped, context, attempt))
            except Exception as exc:
                quality = {"status": "failed", "hard_fail_reasons": [f"quality_exception:{_brief_error(exc)}"]}

            quality_status = str((quality or {}).get("status") or "failed").strip() or "failed"
            record["quality_status"] = quality_status
            hard_fail_reasons = list((quality or {}).get("hard_fail_reasons") or [])
            if quality_status == "failed" or hard_fail_reasons:
                _record_failure(record, *(hard_fail_reasons or ["quality_failed"]))
                record["status"] = "rejected"
                attempt_chain.append(record)
                failure_reasons.extend(record["failure_reasons"])
                continue

            record["status"] = "selected"
            attempt_chain.append(record)
            provider_source = str(mapped.get("provider_source") or mapped.get("source") or path)
            result = dict(mapped)
            result.update(
                {
                    "status": quality_status,
                    "source": path,
                    "selected_path": path,
                    "provider_source": provider_source,
                    "attempt_chain": attempt_chain,
                    "quality_report": dict(quality or {}),
                }
            )
            return result

        return {
            "status": "failed",
            "source": (attempts[-1].get("path") if attempts else ""),
            "selected_path": (attempts[-1].get("path") if attempts else ""),
            "items": [],
            "best_candidate": best_candidate,
            "attempt_chain": attempt_chain,
            "failure_reasons": _unique(failure_reasons),
        }


def _attempts_from_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = plan.get("attempts") or plan.get("attempt_chain") or []
    if attempts:
        return [dict(item) for item in attempts if isinstance(item, Mapping)]
    path = plan.get("path") or plan.get("selected_path")
    return [{"path": path}] if path else []


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _item_count(payload: Mapping[str, Any]) -> int:
    def count(items: Any) -> int:
        total = 0
        for item in items or []:
            if not isinstance(item, Mapping):
                continue
            total += 1 + count(item.get("children"))
        return total

    total = count(payload.get("items"))
    for section in payload.get("toc_sections") or []:
        if isinstance(section, Mapping):
            total += count(section.get("items"))
    return total


def _sample_titles(payload: Mapping[str, Any], *, limit: int = 50) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        title = str(value or "").strip()
        key = "".join(title.casefold().split())
        if not title or not key or key in seen:
            return
        seen.add(key)
        titles.append(title)

    def walk(items: Any) -> None:
        for item in items or []:
            if not isinstance(item, Mapping) or len(titles) >= limit:
                continue
            add(item.get("title"))
            walk(item.get("children") or item.get("nodes"))

    walk(payload.get("items"))
    for section in payload.get("toc_sections") or []:
        if isinstance(section, Mapping) and len(titles) < limit:
            walk(section.get("items"))
    return titles[:limit]


def _record_failure(record: dict[str, Any], *reasons: Any) -> None:
    record["quality_status"] = "failed" if record.get("quality_status") == "not_run" else record["quality_status"]
    record.setdefault("status", "rejected")
    normalized = [str(reason) for reason in reasons if str(reason or "").strip()]
    record["failure_reasons"].extend(normalized or ["failed"])


def _brief_error(exc: Exception) -> str:
    return str(exc).splitlines()[0][:160] or exc.__class__.__name__


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
