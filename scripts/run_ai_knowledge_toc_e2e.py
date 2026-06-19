"""Run AI Knowledge PDFs through the real TOC index builder one file at a time."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import traceback
import unicodedata
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FIXTURE_PATH = BACKEND_DIR / "tests" / "fixtures" / "toc" / "ai_knowledge_expected_routes.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_fixture() -> dict[str, Any]:
    if not FIXTURE_PATH.exists():
        return {"input_dir": "", "documents": []}
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _iter_expected_docs(input_dir: Path, selected_file: str | None) -> list[dict[str, Any]]:
    fixture = _load_fixture()
    documents = [doc for doc in fixture.get("documents") or [] if isinstance(doc, dict)]
    if selected_file:
        matched = [doc for doc in documents if doc.get("file") == selected_file]
        if matched:
            return matched
        return [{"id": "", "file": selected_file, "expected_route": {}}]
    if documents:
        return documents
    return [{"id": "", "file": path.name, "expected_route": {}} for path in sorted(input_dir.glob("*.pdf"))]


def _safe_stem(value: str) -> str:
    stem = Path(str(value or "")).stem
    stem = re.sub(r"[^\w.-]+", "-", stem, flags=re.UNICODE).strip("-._ ")
    return stem or "report"


def _doc_id_for_e2e(expected: dict[str, Any], file_path: Path) -> str:
    label = str(expected.get("id") or _safe_stem(file_path.name)).lower()
    digest = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()[:8]
    return f"e2e_{label}_{digest}"


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    children = node.get("nodes") or node.get("children") or []
    return [child for child in children if isinstance(child, dict)] if isinstance(children, list) else []


def _walk(nodes: list[dict[str, Any]]):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk(_children(node))


def _count_nodes(nodes: list[dict[str, Any]]) -> int:
    return sum(1 for _ in _walk(nodes))


def _normal_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", normalized)


def _chapter_number_to_cn(value: int) -> str:
    digits = {
        0: "零",
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    if value <= 10:
        return digits.get(value, str(value))
    if value < 20:
        return "十" + digits.get(value % 10, "")
    if value < 100:
        tens, ones = divmod(value, 10)
        return digits.get(tens, str(tens)) + "十" + (digits.get(ones, "") if ones else "")
    return str(value)


def _title_aliases(value: str) -> list[str]:
    aliases = [str(value or "")]
    match = re.fullmatch(r"\s*chapter\s*(\d+)\s*", str(value or ""), flags=re.IGNORECASE)
    if match:
        number = int(match.group(1))
        aliases.extend(
            [
                f"第{number}章",
                f"第{_chapter_number_to_cn(number)}章",
                f"chapter{number}",
            ]
        )
    return aliases


def _find_node_start(nodes: list[dict[str, Any]], title: str) -> int | None:
    needles = [_normal_title(alias) for alias in _title_aliases(title) if _normal_title(alias)]
    if not needles:
        return None
    fallback: int | None = None
    for node in _walk(nodes):
        node_title = _normal_title(str(node.get("title") or ""))
        if not node_title:
            continue
        value = node.get("start_index") or node.get("physical_index")
        page = value if isinstance(value, int) else None
        if any(node_title == needle for needle in needles):
            return page
        if fallback is None and any(needle in node_title for needle in needles):
            fallback = page
    return fallback


def _node_section_kind(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    for key in ("toc_section_kind", "section_kind", "toc_kind", "kind"):
        value = str(metadata.get(key) or node.get(key) or "").strip()
        if value in {"main_toc", "figure_toc", "table_toc"}:
            return value
    title = str(node.get("title") or "")
    if "图目录" in title or title.lower() in {"figures", "list of figures"}:
        return "figure_toc"
    if "表目录" in title or title.lower() in {"tables", "list of tables"}:
        return "table_toc"
    if "目录" in title or title.lower() in {"contents", "table of contents"}:
        return "main_toc"
    return ""


def _section_kinds(nodes: list[dict[str, Any]]) -> list[str]:
    kinds: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        kind = _node_section_kind(node)
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def _route_matches(route: dict[str, Any], expected_route: dict[str, Any]) -> bool:
    if not expected_route:
        return True
    content_type = route.get("content_type")
    selected_path = route.get("selected_path") or route.get("path") or route.get("toc_source")
    expected_content = expected_route.get("content_type")
    expected_options = expected_route.get("content_type_options") or []
    if expected_content and content_type != expected_content:
        return False
    if expected_options and content_type not in expected_options:
        return False
    if expected_route.get("selected_path") and selected_path != expected_route.get("selected_path"):
        return False
    return True


def _top_level_matches(top_titles: list[str], expected_titles: list[str]) -> dict[str, Any]:
    if not expected_titles:
        return {"ok": True, "missing": []}
    normalized_actual = [_normal_title(title) for title in top_titles]
    missing = []
    for title in expected_titles:
        needle = _normal_title(title)
        if not any(needle and (needle in actual or actual in needle) for actual in normalized_actual):
            missing.append(title)
    return {"ok": not missing, "missing": missing}


def _main_catalog_title_candidates(nodes: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        title = str(node.get("title") or "")
        titles.append(title)
        if _node_section_kind(node) == "main_toc":
            titles.extend(str(child.get("title") or "") for child in _children(node))
    return titles


def _known_page_checks(nodes: list[dict[str, Any]], known_pages: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for title, expected_page in (known_pages or {}).items():
        if not isinstance(expected_page, int):
            checks[str(title)] = {"expected": expected_page, "actual": None, "ok": True}
            continue
        actual = _find_node_start(nodes, str(title))
        checks[str(title)] = {
            "expected": expected_page,
            "actual": actual,
            "ok": actual == expected_page,
        }
    return checks


def build_report_from_index_payload(
    *,
    file_path: str | Path,
    doc_id: str,
    index_payload: dict[str, Any],
    expected: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    path = Path(file_path)
    route = dict(index_payload.get("route_decision") or {})
    structure = index_payload.get("structure") or []
    if not isinstance(structure, list):
        structure = []
    quality_report = dict(index_payload.get("quality_report") or {})
    diagnostics = dict(index_payload.get("diagnostics") or {})
    top_titles = [str(node.get("title") or "") for node in structure if isinstance(node, dict)]
    section_kinds = _section_kinds(structure)
    known_pages = _known_page_checks(structure, expected.get("known_pages") or {})
    required_sections = list(expected.get("must_have_sections") or [])
    missing_sections = [kind for kind in required_sections if kind not in section_kinds]
    top_level_check = _top_level_matches(
        _main_catalog_title_candidates(structure),
        list(expected.get("expected_top_level") or []),
    )
    route_ok = _route_matches(route, dict(expected.get("expected_route") or {}))
    quality_status = str(quality_report.get("status") or "")
    hard_fail_reasons = list(quality_report.get("hard_fail_reasons") or [])
    quality_ok = not quality_status.startswith("failed") and not hard_fail_reasons
    page_count_ok = not expected.get("page_count") or index_payload.get("page_count") == expected.get("page_count")
    known_pages_ok = all(item.get("ok") for item in known_pages.values())
    has_toc = bool(structure)
    acceptance = {
        "route": route_ok,
        "page_count": bool(page_count_ok),
        "has_toc": has_toc,
        "quality": quality_ok,
        "required_sections": not missing_sections,
        "top_level": bool(top_level_check.get("ok")),
        "known_pages": known_pages_ok,
    }
    acceptance["ok"] = all(bool(value) for value in acceptance.values())

    report_status = "ok" if acceptance["ok"] else "failed"
    return {
        "id": expected.get("id") or "",
        "file": path.name,
        "doc_id": doc_id,
        "status": report_status,
        "elapsed_ms": int(elapsed_ms),
        "elapsed_seconds": round(int(elapsed_ms) / 1000.0, 3),
        "page_count": index_payload.get("page_count"),
        "expected_path": expected.get("expected_path"),
        "stages": list(route.get("states") or []),
        "route": {
            "content_type": route.get("content_type"),
            "selected_path": route.get("selected_path") or route.get("path") or route.get("toc_source"),
            "execution_mode": route.get("execution_mode") or route.get("final_execution_mode"),
            "fallbacks": list(route.get("fallbacks") or []),
            "fallback_reason": route.get("fallback_reason"),
            "matches_expected": route_ok,
        },
        "toc": {
            "root_count": len(structure),
            "node_count": _count_nodes(structure),
            "top_level_titles": top_titles,
            "section_kinds": section_kinds,
            "missing_sections": missing_sections,
            "top_level_check": top_level_check,
        },
        "quality": {
            "status": quality_status,
            "hard_fail_reasons": hard_fail_reasons,
            "warnings": list(quality_report.get("warnings") or []),
        },
        "key_checks": {
            "known_pages": known_pages,
            "toc_page_detection": diagnostics.get("toc_page_detection") or {},
            "mapping": diagnostics.get("toc_content_mapping") or {},
        },
        "acceptance": acceptance,
        "index_path": index_payload.get("index_path"),
    }


async def run_one_file(
    file_path: Path,
    *,
    expected: dict[str, Any],
    user_id: str | None = None,
    mode: str = "smart",
) -> dict[str, Any]:
    from app.services.pageindex_service import PageIndexService

    doc_id = _doc_id_for_e2e(expected, file_path)
    started = time.perf_counter()
    try:
        service = PageIndexService(user_id=user_id)
        result = await service.generate_index(str(file_path), doc_id, mode_override=mode)
        index_payload = dict(result.get("structure") or {})
        index_payload["index_path"] = result.get("index_path")
        return build_report_from_index_payload(
            file_path=file_path,
            doc_id=doc_id,
            index_payload=index_payload,
            expected=expected,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return {
            "id": expected.get("id") or "",
            "file": file_path.name,
            "doc_id": doc_id,
            "status": "error",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "elapsed_seconds": round(int((time.perf_counter() - started) * 1000) / 1000.0, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=6),
            "acceptance": {"ok": False},
        }


def _report_file_name(report: dict[str, Any]) -> str:
    prefix = str(report.get("id") or "").strip()
    safe = _safe_stem(str(report.get("file") or "report"))
    return f"{prefix + '-' if prefix else ''}{safe}.json"


def write_reports(reports: list[dict[str, Any]], output_dir: str | Path) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for report in reports:
        path = output / _report_file_name(report)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "reports": [_report_file_name(report) for report in reports],
        "durations": [
            {
                "id": report.get("id") or "",
                "file": report.get("file"),
                "status": report.get("status"),
                "elapsed_ms": int(report.get("elapsed_ms") or 0),
                "elapsed_seconds": round(int(report.get("elapsed_ms") or 0) / 1000.0, 3),
            }
            for report in reports
        ],
        "summary": {
            "total": len(reports),
            "ok": sum(1 for report in reports if report.get("status") == "ok"),
            "failed": sum(1 for report in reports if report.get("status") == "failed"),
            "error": sum(1 for report in reports if report.get("status") == "error"),
            "missing": sum(1 for report in reports if report.get("status") == "missing"),
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


async def run_e2e(
    input_dir: Path,
    *,
    selected_file: str | None = None,
    output_dir: str | Path = ROOT / "artifacts" / "toc_e2e",
    user_id: str | None = None,
    mode: str = "smart",
    stop_on_fail: bool = False,
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for expected in _iter_expected_docs(input_dir, selected_file):
        pdf_path = input_dir / str(expected.get("file") or "")
        if not pdf_path.exists():
            report = {
                "id": expected.get("id") or "",
                "file": pdf_path.name,
                "status": "missing",
                "acceptance": {"ok": False},
            }
        else:
            report = await run_one_file(pdf_path, expected=expected, user_id=user_id, mode=mode)
        reports.append(report)
        print(
            "[TOC-E2E] "
            f"id={report.get('id')} file={report.get('file')} status={report.get('status')} "
            f"path={(report.get('route') or {}).get('selected_path')} "
            f"quality={(report.get('quality') or {}).get('status')} "
            f"elapsed_ms={report.get('elapsed_ms')}"
        )
        if stop_on_fail and report.get("status") != "ok":
            break
    summary_path = write_reports(reports, output_dir)
    return {
        "output": str(summary_path),
        "reports": reports,
        "summary": {
            "total": len(reports),
            "ok": sum(1 for report in reports if report.get("status") == "ok"),
            "failed": sum(1 for report in reports if report.get("status") == "failed"),
            "error": sum(1 for report in reports if report.get("status") == "error"),
            "missing": sum(1 for report in reports if report.get("status") == "missing"),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    fixture = _load_fixture()
    default_input = fixture.get("input_dir") or r"D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=default_input, help="Directory containing AI Knowledge PDFs")
    parser.add_argument("--file", help="Run E2E for one PDF file name")
    parser.add_argument("--all", action="store_true", help="Explicitly run every fixture PDF")
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "toc_e2e"), help="Directory for report JSON files")
    parser.add_argument("--user-id", help="Optional user id for model/OCR profile resolution")
    parser.add_argument("--mode", default="smart", help="PageIndex generation mode")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop after the first non-ok report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"[TOC-E2E] input directory does not exist: {input_dir}", file=sys.stderr)
        return 2
    result = asyncio.run(
        run_e2e(
            input_dir,
            selected_file=args.file,
            output_dir=args.output,
            user_id=args.user_id,
            mode=args.mode,
            stop_on_fail=args.stop_on_fail,
        )
    )
    print(json.dumps(result["summary"], ensure_ascii=False))
    summary = result["summary"]
    return 0 if summary.get("failed", 0) == 0 and summary.get("error", 0) == 0 and summary.get("missing", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
