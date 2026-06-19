"""Read-only TOC diagnostics for the AI Knowledge PDF baseline.

The baseline phase does not call OCR, LLMs, or index writers. Later phases may
call the same OCR preprocessing used by the service when that is required to
diagnose the planned TOC route, but they still do not write indexes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
from typing import Any

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FIXTURE_PATH = BACKEND_DIR / "tests" / "fixtures" / "toc" / "ai_knowledge_expected_routes.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pageindex.pdf_analyzer import analyze_pdf_structure  # noqa: E402
from pageindex.preprocess_page_text import (  # noqa: E402
    PAGE_TEXT_OCR_PROMPT,
    infer_content_type,
    preprocess_page_text_map,
)


SLIDE_EXPORT_PATTERNS = (
    re.compile(r"^\s*幻灯片\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*slide\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*page\s*\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*默认节\s*$", re.IGNORECASE),
)


def _load_fixture() -> dict[str, Any]:
    if not FIXTURE_PATH.exists():
        return {"input_dir": "", "documents": []}
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_doc_by_file() -> dict[str, dict[str, Any]]:
    return {
        doc["file"]: doc
        for doc in (_load_fixture().get("documents") or [])
        if isinstance(doc, dict) and doc.get("file")
    }


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip()


def _is_slide_export_title(title: str) -> bool:
    clean = _clean_title(title)
    return any(pattern.match(clean) for pattern in SLIDE_EXPORT_PATTERNS)


def _collect_raw_bookmarks(doc: pymupdf.Document) -> dict[str, Any]:
    raw = doc.get_toc(simple=True)
    titles = [_clean_title(row[1]) for row in raw if len(row) >= 2]
    slide_noise = [title for title in titles if _is_slide_export_title(title)]
    return {
        "count": len(raw),
        "slide_export_noise_count": len(slide_noise),
        "sample_titles": titles[:8],
    }


def _collect_raw_links(
    doc: pymupdf.Document,
    *,
    max_scan_pages: int = 30,
    toc_like_threshold: int = 5,
) -> dict[str, Any]:
    pages: list[int] = []
    toc_like_pages: list[int] = []
    per_page: list[dict[str, int]] = []
    total_internal_links = 0

    for page_idx in range(min(max_scan_pages, len(doc))):
        links = doc[page_idx].get_links()
        internal_links = [
            link
            for link in links
            if link.get("kind") == pymupdf.LINK_GOTO and int(link.get("page", -1)) >= 0
        ]
        count = len(internal_links)
        if count == 0:
            continue
        physical_page = page_idx + 1
        pages.append(physical_page)
        total_internal_links += count
        per_page.append({"page": physical_page, "internal_links": count})
        if count >= toc_like_threshold:
            toc_like_pages.append(physical_page)

    return {
        "pages": pages,
        "toc_like_pages": toc_like_pages,
        "total_internal_links": total_internal_links,
        "per_page": per_page,
    }


def _summarize_current_analyzer(file_path: Path) -> dict[str, Any]:
    analysis = analyze_pdf_structure(str(file_path))
    code_toc = analysis.get("code_toc") or {}
    code_toc_items = code_toc.get("items") or []
    return {
        "code_toc_source": code_toc.get("source"),
        "code_toc_items": len(code_toc_items),
        "layout_type": analysis.get("layout_type"),
        "text_layer_quality": analysis.get("text_layer_quality"),
        "structure_policy": analysis.get("structure_policy"),
        "ocr_policy": analysis.get("ocr_policy"),
        "is_image_only_pdf": bool(analysis.get("is_image_only_pdf")),
        "is_garbled_pdf": bool(analysis.get("is_garbled_pdf")),
    }


def _detect_bookmark_link_complement(raw_bookmarks: dict[str, Any], raw_links: dict[str, Any]) -> bool:
    return bool(raw_bookmarks.get("count")) and bool(raw_links.get("total_internal_links"))


def collect_pdf_diagnostics(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)
    with pymupdf.open(path) as doc:
        raw_bookmarks = _collect_raw_bookmarks(doc)
        raw_links = _collect_raw_links(doc)
        page_count = len(doc)

    current_analyzer = _summarize_current_analyzer(path)
    text_pages = 0
    with pymupdf.open(path) as doc:
        for page in doc:
            if (page.get_text() or "").strip():
                text_pages += 1

    text_coverage = text_pages / page_count if page_count else 0.0
    weak_slide = raw_bookmarks["slide_export_noise_count"] >= 3 or (
        raw_bookmarks["count"] > 0
        and raw_bookmarks["slide_export_noise_count"] / raw_bookmarks["count"] >= 0.35
    )

    return {
        "file": path.name,
        "page_count": page_count,
        "text_coverage": round(text_coverage, 4),
        "raw_bookmarks": raw_bookmarks,
        "raw_links": raw_links,
        "current_analyzer": current_analyzer,
        "weak_slide_export_outline": weak_slide,
        "bookmarks_links_complementary": _detect_bookmark_link_complement(raw_bookmarks, raw_links),
    }


def _iter_target_files(input_dir: Path, selected_file: str | None) -> list[Path]:
    if selected_file:
        return [input_dir / selected_file]

    fixture = _load_fixture()
    names = [doc["file"] for doc in fixture.get("documents") or []]
    if names:
        return [input_dir / name for name in names]
    return sorted(input_dir.glob("*.pdf"))


def run_diagnostics(input_dir: Path, selected_file: str | None = None) -> dict[str, Any]:
    documents = []
    for pdf_path in _iter_target_files(input_dir, selected_file):
        if not pdf_path.exists():
            documents.append({"file": pdf_path.name, "status": "missing"})
            continue
        result = collect_pdf_diagnostics(pdf_path)
        result["status"] = "ok"
        documents.append(result)
        print(
            "[TOC-DIAG] "
            f"file={result['file']} pages={result['page_count']} "
            f"text_coverage={result['text_coverage']:.0%} "
            f"bookmarks={result['raw_bookmarks']['count']} "
            f"link_pages={result['raw_links']['toc_like_pages']} "
            f"links={result['raw_links']['total_internal_links']} "
            f"code_toc={result['current_analyzer']['code_toc_source']} "
            f"code_items={result['current_analyzer']['code_toc_items']} "
            f"weak_slide={result['weak_slide_export_outline']}"
        )

    return {
        "phase": "baseline",
        "input_dir": str(input_dir),
        "documents": documents,
        "summary": {
            "total": len(documents),
            "ok": sum(1 for doc in documents if doc.get("status") == "ok"),
            "missing": sum(1 for doc in documents if doc.get("status") == "missing"),
        },
    }


async def collect_preprocess_diagnostics(
    file_path: str | Path,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    from app.services.pageindex_service import PageIndexService

    path = Path(file_path)
    analysis = analyze_pdf_structure(str(path))
    analysis["document_path"] = str(path)
    analysis["file_path"] = str(path)

    service = PageIndexService(user_id=user_id)

    async def ocr_pages(file_path, page_indices, *, prompt, analysis):
        return await service._run_pdf_ocr_pages_by_images(
            Path(file_path),
            list(page_indices),
            analysis=analysis,
            prompt=prompt,
        )

    page_map = await preprocess_page_text_map(
        path,
        analysis,
        ocr_pages_fn=ocr_pages,
        prompt=PAGE_TEXT_OCR_PROMPT,
    )
    diagnostics = page_map.to_diagnostics()
    text_lengths = [len(text) for text in page_map.page_texts()]
    sample_pages = []
    for entry in page_map.entries:
        if entry.ocr_used or len(sample_pages) < 3:
            sample_pages.append(
                {
                    "page": entry.physical_page,
                    "source": entry.source,
                    "quality": entry.quality,
                    "ocr_used": entry.ocr_used,
                    "text_head": entry.text[:180],
                }
            )
        if len(sample_pages) >= 8:
            break

    return {
        "file": path.name,
        "status": "ok",
        "page_count": analysis.get("page_count"),
        "content_type": analysis.get("content_type"),
        "layout_type": analysis.get("layout_type"),
        "text_layer_quality": analysis.get("text_layer_quality"),
        "text_coverage": round(float(analysis.get("text_coverage") or 0.0), 4),
        "image_coverage": round(float(analysis.get("image_coverage") or 0.0), 4),
        "image_only_pages": list(analysis.get("image_only_pages") or []),
        "garbled_pages": list(analysis.get("garbled_pages") or []),
        "page_text_map": diagnostics,
        "empty_pages": [
            entry.physical_page for entry in page_map.entries if not entry.text.strip()
        ],
        "text_length": {
            "min": min(text_lengths) if text_lengths else 0,
            "max": max(text_lengths) if text_lengths else 0,
            "total": sum(text_lengths),
        },
        "ocr_calls_summary": analysis.get("ocr_calls_summary") or {},
        "sample_pages": sample_pages,
    }


async def run_preprocess_diagnostics(
    input_dir: Path,
    selected_file: str | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    documents = []
    for pdf_path in _iter_target_files(input_dir, selected_file):
        if not pdf_path.exists():
            documents.append({"file": pdf_path.name, "status": "missing"})
            continue
        try:
            result = await collect_preprocess_diagnostics(pdf_path, user_id=user_id)
        except Exception as exc:
            result = {
                "file": pdf_path.name,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        documents.append(result)
        if result.get("status") == "ok":
            page_map = result.get("page_text_map") or {}
            print(
                "[TOC-DIAG] phase=preprocess "
                f"file={result['file']} pages={result['page_count']} "
                f"content_type={result['content_type']} "
                f"ocr_pages={page_map.get('ocr_page_count')} "
                f"sources={page_map.get('sources')} "
                f"empty_pages={len(result.get('empty_pages') or [])}"
            )
        else:
            print(
                "[TOC-DIAG] phase=preprocess "
                f"file={result['file']} status={result.get('status')} "
                f"error={result.get('error_type')}"
            )

    return {
        "phase": "preprocess",
        "input_dir": str(input_dir),
        "documents": documents,
        "summary": {
            "total": len(documents),
            "ok": sum(1 for doc in documents if doc.get("status") == "ok"),
            "missing": sum(1 for doc in documents if doc.get("status") == "missing"),
            "error": sum(1 for doc in documents if doc.get("status") == "error"),
        },
    }


def _expected_route_matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not expected:
        return True
    content_type = result.get("content_type")
    expected_content = expected.get("content_type")
    content_options = expected.get("content_type_options") or []
    if expected_content and content_type != expected_content:
        return False
    if content_options and content_type not in content_options:
        return False
    route = result.get("route_decision") or {}
    expected_path = expected.get("selected_path")
    if expected_path and route.get("selected_path") != expected_path:
        return False
    return True


def _embedded_expected_matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Match only the S2 embedded-TOC gate, not later balanced routing."""
    if not expected:
        return True
    expected_path = expected.get("selected_path")
    quality = result.get("code_toc_quality") if isinstance(result.get("code_toc_quality"), dict) else {}
    accepted = bool(quality.get("accepted"))
    if expected_path == "embedded_toc":
        return accepted and _expected_route_matches(result, expected)
    return not accepted


def collect_embedded_diagnostics(file_path: str | Path) -> dict[str, Any]:
    from app.services.pageindex_service import PageIndexService
    from pageindex.code_toc_quality import evaluate_code_toc

    path = Path(file_path)
    analysis = analyze_pdf_structure(str(path))
    code_toc = analysis.get("code_toc") if isinstance(analysis.get("code_toc"), dict) else {}
    quality = evaluate_code_toc(analysis)
    route_decision = PageIndexService._build_state_machine_route_decision("smart", analysis)
    sources = code_toc.get("sources") if isinstance(code_toc.get("sources"), dict) else {}
    source_summary = {}
    for name, source in sources.items():
        if not isinstance(source, dict):
            continue
        source_summary[name] = {
            "count": source.get("count"),
            "raw_count": source.get("raw_count"),
            "toc_pages": list(source.get("toc_pages") or []),
            "sample_titles": list(source.get("sample_titles") or []),
        }

    return {
        "file": path.name,
        "status": "ok",
        "page_count": analysis.get("page_count"),
        "content_type": route_decision.get("content_type"),
        "code_toc_source": code_toc.get("source"),
        "code_toc_items": len(code_toc.get("items") or []),
        "section_kinds": [
            section.get("kind")
            for section in code_toc.get("toc_sections") or []
            if isinstance(section, dict)
        ],
        "sources": source_summary,
        "quality_flags": list(code_toc.get("quality_flags") or []),
        "code_toc_quality": {
            key: value
            for key, value in quality.items()
            if key != "items"
        },
        "route_decision": route_decision,
    }


def run_embedded_diagnostics(input_dir: Path, selected_file: str | None = None) -> dict[str, Any]:
    expected_by_file = _fixture_doc_by_file()
    documents = []
    for pdf_path in _iter_target_files(input_dir, selected_file):
        if not pdf_path.exists():
            documents.append({"file": pdf_path.name, "status": "missing"})
            continue
        try:
            result = collect_embedded_diagnostics(pdf_path)
            expected = (expected_by_file.get(pdf_path.name) or {}).get("expected_route") or {}
            result["expected_route"] = expected
            result["route_matches_expected"] = _embedded_expected_matches(result, expected)
        except Exception as exc:
            result = {
                "file": pdf_path.name,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        documents.append(result)
        if result.get("status") == "ok":
            route = result.get("route_decision") or {}
            quality = result.get("code_toc_quality") or {}
            print(
                "[TOC-DIAG] phase=embedded "
                f"file={result['file']} source={result.get('code_toc_source')} "
                f"items={result.get('code_toc_items')} "
                f"sections={result.get('section_kinds')} "
                f"accepted={quality.get('accepted')} "
                f"reasons={quality.get('reasons')} "
                f"selected_path={route.get('selected_path')} "
                f"match={result.get('route_matches_expected')}"
            )
        else:
            print(
                "[TOC-DIAG] phase=embedded "
                f"file={result['file']} status={result.get('status')} "
                f"error={result.get('error_type')}"
            )

    return {
        "phase": "embedded",
        "input_dir": str(input_dir),
        "documents": documents,
        "summary": {
            "total": len(documents),
            "ok": sum(1 for doc in documents if doc.get("status") == "ok"),
            "missing": sum(1 for doc in documents if doc.get("status") == "missing"),
            "error": sum(1 for doc in documents if doc.get("status") == "error"),
            "route_mismatch": sum(
                1
                for doc in documents
                if doc.get("status") == "ok" and doc.get("route_matches_expected") is False
            ),
        },
    }


async def collect_route_diagnostics(
    file_path: str | Path,
    *,
    user_id: str | None = None,
    model: str = "qwen3.6-flash",
    preprocess: bool = True,
) -> dict[str, Any]:
    from app.services.pageindex_service import PageIndexService
    from pageindex.toc_detector import find_toc_pages

    path = Path(file_path)
    analysis = analyze_pdf_structure(str(path))
    analysis["document_path"] = str(path)
    analysis["file_path"] = str(path)
    service = PageIndexService(user_id=user_id)

    if preprocess:
        await preprocess_page_text_map(
            path,
            analysis,
            ocr_pages_fn=lambda fp, pages, prompt, analysis: service._run_pdf_ocr_pages_by_images(
                Path(fp),
                list(pages),
                analysis=analysis,
                prompt=prompt,
            ),
            prompt=PAGE_TEXT_OCR_PROMPT,
        )
    else:
        analysis["content_type"] = infer_content_type(analysis)
        analysis["page_texts"] = [
            str(page[0] if isinstance(page, (list, tuple)) and page else page or "")
            for page in (analysis.get("page_list") or [])
        ]

    initial_route = PageIndexService._build_state_machine_route_decision("smart", analysis)
    route_decision = initial_route
    if route_decision.get("execution_mode") == "balanced":
        await find_toc_pages(analysis, str(path), model=model)
        route_decision = PageIndexService._build_state_machine_route_decision("smart", analysis)

    toc_detection = analysis.get("toc_page_detection") if isinstance(analysis.get("toc_page_detection"), dict) else {}
    page_map = analysis.get("page_text_map")
    page_map_diagnostics = (
        page_map.to_diagnostics()
        if hasattr(page_map, "to_diagnostics")
        else analysis.get("page_text_map_diagnostics") or {}
    )
    return {
        "file": path.name,
        "status": "ok",
        "page_count": analysis.get("page_count"),
        "content_type": analysis.get("content_type"),
        "text_coverage": round(float(analysis.get("text_coverage") or 0.0), 4),
        "route_decision": route_decision,
        "initial_route_decision": initial_route,
        "toc_page_detection": {
            "status": toc_detection.get("status"),
            "pages": list(toc_detection.get("pages") or []),
            "has_page_numbers": bool(toc_detection.get("has_page_numbers")),
            "reason": toc_detection.get("reason"),
        },
        "page_text_map": page_map_diagnostics,
    }


async def run_route_diagnostics(
    input_dir: Path,
    selected_file: str | None = None,
    *,
    user_id: str | None = None,
    model: str = "qwen3.6-flash",
    preprocess: bool = True,
) -> dict[str, Any]:
    expected_by_file = _fixture_doc_by_file()
    documents = []
    for pdf_path in _iter_target_files(input_dir, selected_file):
        if not pdf_path.exists():
            documents.append({"file": pdf_path.name, "status": "missing"})
            continue
        try:
            result = await collect_route_diagnostics(
                pdf_path,
                user_id=user_id,
                model=model,
                preprocess=preprocess,
            )
            expected = (expected_by_file.get(pdf_path.name) or {}).get("expected_route") or {}
            result["expected_route"] = expected
            result["route_matches_expected"] = _expected_route_matches(result, expected)
        except Exception as exc:
            result = {
                "file": pdf_path.name,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        documents.append(result)
        if result.get("status") == "ok":
            route = result.get("route_decision") or {}
            toc_detection = result.get("toc_page_detection") or {}
            print(
                "[TOC-DIAG] phase=route "
                f"file={result['file']} content_type={result.get('content_type')} "
                f"selected_path={route.get('selected_path')} "
                f"execution={route.get('execution_mode')} "
                f"toc_pages={toc_detection.get('pages')} "
                f"has_page_numbers={toc_detection.get('has_page_numbers')} "
                f"match={result.get('route_matches_expected')}"
            )
        else:
            print(
                "[TOC-DIAG] phase=route "
                f"file={result['file']} status={result.get('status')} "
                f"error={result.get('error_type')}"
            )

    return {
        "phase": "route",
        "input_dir": str(input_dir),
        "documents": documents,
        "summary": {
            "total": len(documents),
            "ok": sum(1 for doc in documents if doc.get("status") == "ok"),
            "missing": sum(1 for doc in documents if doc.get("status") == "missing"),
            "error": sum(1 for doc in documents if doc.get("status") == "error"),
            "route_mismatch": sum(
                1
                for doc in documents
                if doc.get("status") == "ok" and doc.get("route_matches_expected") is False
            ),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    fixture = _load_fixture()
    default_input = fixture.get("input_dir") or r"D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=default_input, help="Directory containing AI Knowledge PDFs")
    parser.add_argument("--file", help="Run diagnostics for one PDF file name")
    parser.add_argument("--all", action="store_true", help="Explicitly run diagnostics for all fixture PDFs")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--user-id", help="Optional user id for OCR profile resolution")
    parser.add_argument("--model", default="qwen3.6-flash", help="Model name passed through route probes")
    parser.add_argument(
        "--phase",
        default="baseline",
        choices=["baseline", "preprocess", "embedded", "route"],
        help="Diagnostic phase to run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"[TOC-DIAG] input directory does not exist: {input_dir}", file=sys.stderr)
        return 2

    if args.phase == "preprocess":
        report = asyncio.run(
            run_preprocess_diagnostics(
                input_dir,
                selected_file=args.file,
                user_id=args.user_id,
            )
        )
    elif args.phase == "embedded":
        report = run_embedded_diagnostics(input_dir, selected_file=args.file)
    elif args.phase == "route":
        report = asyncio.run(
            run_route_diagnostics(
                input_dir,
                selected_file=args.file,
                user_id=args.user_id,
                model=args.model,
                preprocess=True,
            )
        )
    else:
        report = run_diagnostics(input_dir, selected_file=args.file)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[TOC-DIAG] wrote {output_path}")
    else:
        print(json.dumps(report["summary"], ensure_ascii=False))

    summary = report["summary"]
    return (
        0
        if summary.get("missing", 0) == 0
        and summary.get("error", 0) == 0
        and summary.get("route_mismatch", 0) == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
