"""Run AI Knowledge PDFs through the real TOC index builder one file at a time."""

from __future__ import annotations

import argparse
import asyncio
from difflib import SequenceMatcher
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


def _load_fixture(fixture_path: str | Path = FIXTURE_PATH) -> dict[str, Any]:
    path = Path(fixture_path)
    if not path.exists():
        return {"input_dir": "", "documents": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_expected_docs(
    input_dir: Path,
    selected_file: str | None,
    *,
    fixture: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    fixture = fixture if isinstance(fixture, dict) else _load_fixture()
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


def _max_depth(nodes: list[dict[str, Any]]) -> int:
    if not nodes:
        return 0
    max_depth = 0

    def visit(items: list[dict[str, Any]], depth: int) -> None:
        nonlocal max_depth
        for node in items or []:
            if not isinstance(node, dict):
                continue
            max_depth = max(max_depth, depth)
            visit(_children(node), depth + 1)

    visit(nodes, 1)
    return max_depth


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
    node = _find_node_by_title(nodes, title)
    if not node:
        return None
    value = node.get("start_index") or node.get("physical_index")
    return value if isinstance(value, int) else None


def _candidate_nodes_by_title(nodes: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    needles = [_normal_title(alias) for alias in _title_aliases(title) if _normal_title(alias)]
    if not needles:
        return []
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    for node in _walk(nodes):
        node_title = _normal_title(str(node.get("title") or ""))
        if not node_title:
            continue
        if any(node_title == needle for needle in needles):
            exact.append(node)
        elif any(needle in node_title for needle in needles):
            partial.append(node)
        elif any(_titles_match_fuzzy(needle, node_title) for needle in needles):
            fuzzy.append(node)
    return exact or partial or fuzzy


def _titles_match_fuzzy(expected_key: str, actual_key: str) -> bool:
    if min(len(expected_key), len(actual_key)) < 18:
        return False
    if expected_key[:2].isdigit() and actual_key[:2] != expected_key[:2]:
        return False
    return SequenceMatcher(None, expected_key, actual_key).ratio() >= 0.78


def _title_match_type(expected_title: str, node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return "missing"
    node_title = _normal_title(str(node.get("title") or ""))
    needles = [_normal_title(alias) for alias in _title_aliases(expected_title) if _normal_title(alias)]
    if any(node_title == needle for needle in needles):
        return "exact"
    if any(needle in node_title for needle in needles):
        return "partial"
    if any(_titles_match_fuzzy(needle, node_title) for needle in needles):
        return "fuzzy"
    return "none"


def _find_node_by_title(nodes: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    candidates = _candidate_nodes_by_title(nodes, title)
    return candidates[0] if candidates else None


def _find_node_by_title_and_range(
    nodes: list[dict[str, Any]],
    title: str,
    *,
    expected_start: Any = None,
    expected_end: Any = None,
) -> dict[str, Any] | None:
    candidates = _candidate_nodes_by_title(nodes, title)
    if not candidates:
        return None

    def score(node: dict[str, Any]) -> tuple[int, int, int]:
        matched = 0
        if isinstance(expected_start, int) and _node_start(node) == expected_start:
            matched += 2
        if isinstance(expected_end, int) and _node_end(node) == expected_end:
            matched += 1
        has_children = 1 if _children(node) else 0
        return matched, has_children, -abs((_node_start(node) or 0) - expected_start) if isinstance(expected_start, int) else 0

    if isinstance(expected_start, int) or isinstance(expected_end, int):
        return max(candidates, key=score)
    return candidates[0]


def _node_start(node: dict[str, Any] | None) -> int | None:
    if not isinstance(node, dict):
        return None
    value = node.get("start_index") or node.get("physical_index")
    return value if isinstance(value, int) else None


def _node_end(node: dict[str, Any] | None) -> int | None:
    if not isinstance(node, dict):
        return None
    value = node.get("end_index") or node.get("start_index") or node.get("physical_index")
    return value if isinstance(value, int) else None


def _is_auxiliary_node(node: dict[str, Any] | None) -> bool:
    if not isinstance(node, dict):
        return False
    catalog_type = str(node.get("catalog_type") or "").strip().lower()
    node_type = str(node.get("node_type") or "").strip().lower()
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    kind = str(metadata.get("toc_section_kind") or node.get("toc_section_kind") or "").strip().lower()
    return bool(
        node.get("is_auxiliary")
        or node_type in {"auxiliary_catalog", "auxiliary_catalog_item"}
        or catalog_type in {"figure", "table", "figure_toc", "table_toc"}
        or kind in {"figure_toc", "table_toc"}
    )


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


def _route_matches_expected(route: dict[str, Any], expected: dict[str, Any]) -> bool:
    route_options = expected.get("expected_route_options") or []
    if isinstance(route_options, list) and route_options:
        return any(
            isinstance(option, dict) and _route_matches(route, option)
            for option in route_options
        )
    return _route_matches(route, dict(expected.get("expected_route") or {}))


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


def _effective_root_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(nodes or []) != 1:
        return nodes or []
    root = nodes[0]
    title_key = _normal_title(str(root.get("title") or ""))
    if title_key in {"目录", "目次", "contents", "tableofcontents"} and _children(root):
        return _children(root)
    return nodes or []


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


def _must_have_node_checks(
    nodes: list[dict[str, Any]],
    must_have_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: dict[str, Any] = {"ok": True, "items": {}}
    if not must_have_nodes:
        return checks

    for expected in must_have_nodes:
        if not isinstance(expected, dict):
            continue
        title = str(expected.get("title") or "")
        if not title:
            continue
        expected_start = expected.get("start_index")
        expected_end = expected.get("end_index")
        node = _find_node_by_title_and_range(
            nodes,
            title,
            expected_start=expected_start,
            expected_end=expected_end,
        )
        actual_start = _node_start(node)
        actual_end = _node_end(node)
        auxiliary_end_ignored = _is_auxiliary_node(node) and isinstance(expected_end, int)
        adjacent_overlap_accepted = False
        item_ok = node is not None
        if isinstance(expected_start, int):
            item_ok = item_ok and actual_start == expected_start
        if isinstance(expected_end, int) and not auxiliary_end_ignored:
            end_ok, adjacent_overlap_accepted = _end_matches_expected_range(
                nodes,
                node,
                expected_end=expected_end,
                actual_end=actual_end,
            )
            item_ok = item_ok and end_ok
        item = {
            "expected_start": expected_start,
            "expected_end": expected_end,
            "actual_start": actual_start,
            "actual_end": actual_end,
            "auxiliary_end_ignored": auxiliary_end_ignored,
            "adjacent_overlap_accepted": adjacent_overlap_accepted,
            "title_match": _title_match_type(title, node),
            "ok": bool(item_ok),
        }
        checks["items"][title] = item
        checks["ok"] = checks["ok"] and bool(item_ok)
    return checks


def _end_matches_expected_range(
    nodes: list[dict[str, Any]],
    node: dict[str, Any] | None,
    *,
    expected_end: int,
    actual_end: Any,
) -> tuple[bool, bool]:
    if actual_end == expected_end:
        return True, False
    if actual_end == expected_end + 1 and _has_other_node_starting_at(nodes, actual_end, exclude=node):
        return True, True
    return False, False


def _has_other_node_starting_at(
    nodes: list[dict[str, Any]],
    page: Any,
    *,
    exclude: dict[str, Any] | None,
) -> bool:
    if not isinstance(page, int):
        return False
    for candidate in _walk(nodes):
        if candidate is exclude:
            continue
        if _node_start(candidate) == page:
            return True
    return False


def _count_leaf_nodes(nodes: list[dict[str, Any]]) -> int:
    count = 0
    for node in _walk(nodes):
        if not _children(node):
            count += 1
    return count


def _physical_pages_check(nodes: list[dict[str, Any]], page_count: Any) -> dict[str, Any]:
    if not isinstance(page_count, int) or page_count <= 0:
        return {"ok": True, "invalid": []}
    invalid = []
    for node in _walk(nodes):
        start = _node_start(node)
        end = _node_end(node)
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 1
            or end < 1
            or start > page_count
            or end > page_count
            or start > end
        ):
            invalid.append(
                {
                    "title": str(node.get("title") or ""),
                    "start": start,
                    "end": end,
                }
            )
    return {"ok": not invalid, "invalid": invalid[:10]}


def _required_behavior_checks(
    nodes: list[dict[str, Any]],
    expected: dict[str, Any],
    index_payload: dict[str, Any],
) -> dict[str, Any]:
    spec = dict(expected.get("required_checks") or {})
    if expected.get("reference_status") == "needs_child_expansion":
        spec.setdefault("requires_child_expansion", True)
        spec.setdefault("min_child_expansion_span", 6)
    checks: dict[str, Any] = {"ok": True}
    if not spec:
        return checks

    page_count = index_payload.get("page_count")

    if spec.get("physical_pages_only"):
        check = _physical_pages_check(nodes, page_count)
        checks["physical_pages_only"] = check
        checks["ok"] = checks["ok"] and bool(check.get("ok"))

    if spec.get("full_document_ocr"):
        ok = bool(index_payload.get("ocr_used") or index_payload.get("page_text_map_ocr_completed"))
        checks["full_document_ocr"] = {"expected": True, "actual": ok, "ok": ok}
        checks["ok"] = checks["ok"] and ok

    expected_leaf_count = spec.get("expected_leaf_count")
    if isinstance(expected_leaf_count, int):
        actual = _count_leaf_nodes(nodes)
        ok = actual >= expected_leaf_count
        checks["expected_leaf_count"] = {"expected_min": expected_leaf_count, "actual": actual, "ok": ok}
        checks["ok"] = checks["ok"] and ok

    visible_toc_pages = spec.get("visible_toc_pages")
    if isinstance(visible_toc_pages, list):
        diagnostics = index_payload.get("diagnostics") if isinstance(index_payload.get("diagnostics"), dict) else {}
        detection = diagnostics.get("toc_page_detection") if isinstance(diagnostics.get("toc_page_detection"), dict) else {}
        mapping = diagnostics.get("toc_content_mapping") if isinstance(diagnostics.get("toc_content_mapping"), dict) else {}
        actual_pages = detection.get("pages") or mapping.get("toc_pages") or []
        actual_set = {page for page in actual_pages if isinstance(page, int)}
        missing = [page for page in visible_toc_pages if isinstance(page, int) and page not in actual_set]
        ok = not missing
        checks["visible_toc_pages"] = {"expected": visible_toc_pages, "actual": sorted(actual_set), "missing": missing, "ok": ok}
        checks["ok"] = checks["ok"] and ok

    if spec.get("requires_child_expansion"):
        min_children = int(spec.get("min_children_per_long_chapter") or 1)
        min_span = int(spec.get("min_child_expansion_span") or 8)
        missing: list[dict[str, Any]] = []
        expected_nodes = [item for item in (expected.get("must_have_nodes") or []) if isinstance(item, dict)]
        targets: list[tuple[str, dict[str, Any], int, int]] = []
        for item in expected_nodes:
            title = str(item.get("title") or "")
            start = item.get("start_index")
            end = item.get("end_index")
            if not title or not isinstance(start, int) or not isinstance(end, int):
                continue
            if end - start + 1 >= min_span:
                node = _find_node_by_title(nodes, title) or {}
                targets.append((title, node, start, end))
        if not targets:
            for node in _effective_root_nodes(nodes):
                start = _node_start(node)
                end = _node_end(node)
                if isinstance(start, int) and isinstance(end, int) and end - start + 1 >= min_span:
                    targets.append((str(node.get("title") or ""), node, start, end))
        for title, node, start, end in targets:
            child_count = len(_children(node)) if isinstance(node, dict) else 0
            if child_count < min_children:
                missing.append(
                    {
                        "title": title,
                        "start": start,
                        "end": end,
                        "child_count": child_count,
                        "expected_min_children": min_children,
                    }
                )
        ok = not missing
        checks["requires_child_expansion"] = {"ok": ok, "missing": missing[:10]}
        checks["ok"] = checks["ok"] and ok

    return checks


def _minimum_shape_check(nodes: list[dict[str, Any]], acceptance_spec: dict[str, Any]) -> dict[str, Any]:
    effective_roots = _effective_root_nodes(nodes)
    root_count = len(effective_roots)
    node_count = _count_nodes(nodes)
    max_depth = _max_depth(nodes)
    checks = {
        "root_count": root_count,
        "node_count": node_count,
        "max_depth": max_depth,
        "min_root_count": acceptance_spec.get("min_root_count"),
        "min_node_count": acceptance_spec.get("min_node_count"),
        "min_depth": acceptance_spec.get("min_depth"),
        "ok": True,
    }
    if acceptance_spec.get("min_root_count") is not None:
        checks["ok"] = checks["ok"] and root_count >= int(acceptance_spec.get("min_root_count") or 0)
    if acceptance_spec.get("min_node_count") is not None:
        checks["ok"] = checks["ok"] and node_count >= int(acceptance_spec.get("min_node_count") or 0)
    if acceptance_spec.get("min_depth") is not None:
        checks["ok"] = checks["ok"] and max_depth >= int(acceptance_spec.get("min_depth") or 0)
    return checks


def _required_pages_checks(nodes: list[dict[str, Any]], required_pages: dict[str, Any]) -> dict[str, Any]:
    return _known_page_checks(nodes, required_pages or {})


def _forbidden_pattern_checks(nodes: list[dict[str, Any]], forbidden: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {"ok": True, "evaluated": []}
    if forbidden.get("no_generic_single_node"):
        node_count = _count_nodes(nodes)
        title = str(nodes[0].get("title") or "") if len(nodes or []) == 1 else ""
        generic_titles = {
            "documentcontent",
            "full document",
            "fulldocument",
            "content",
            "目录",
            "正文",
        }
        generic_single = node_count <= 1 and (_normal_title(title) in generic_titles or not title.strip())
        checks["no_generic_single_node"] = not generic_single
        checks["evaluated"].append("no_generic_single_node")
        checks["ok"] = checks["ok"] and not generic_single
    forbidden_start_pages = [
        page for page in (forbidden.get("forbidden_start_pages") or []) if isinstance(page, int)
    ]
    if forbidden_start_pages:
        hits = [
            {"title": str(node.get("title") or ""), "start": _node_start(node)}
            for node in _effective_root_nodes(nodes)
            if _node_start(node) in forbidden_start_pages
        ]
        checks["forbidden_start_pages"] = {"expected_absent": forbidden_start_pages, "hits": hits[:10], "ok": not hits}
        checks["evaluated"].append("forbidden_start_pages")
        checks["ok"] = checks["ok"] and not hits

    max_same_page = forbidden.get("max_nodes_on_same_non_toc_page")
    forbidden_mass_page = forbidden.get("forbidden_mass_page")
    if isinstance(max_same_page, int) and max_same_page >= 0:
        counts: dict[int, int] = {}
        for node in _walk(nodes):
            page = _node_start(node)
            if not isinstance(page, int):
                continue
            counts[page] = counts.get(page, 0) + 1
        if isinstance(forbidden_mass_page, int):
            violating = {forbidden_mass_page: counts.get(forbidden_mass_page, 0)}
            ok = violating[forbidden_mass_page] <= max_same_page
        else:
            violating = {
                page: count
                for page, count in counts.items()
                if count > max_same_page
            }
            ok = not violating
        checks["max_nodes_on_same_non_toc_page"] = {
            "max": max_same_page,
            "violating": violating,
            "ok": ok,
        }
        checks["evaluated"].append("max_nodes_on_same_non_toc_page")
        checks["ok"] = checks["ok"] and ok
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
    llm_quality_check = dict(index_payload.get("llm_quality_check") or {})
    top_titles = [str(node.get("title") or "") for node in structure if isinstance(node, dict)]
    effective_root_titles = [
        str(node.get("title") or "")
        for node in _effective_root_nodes(structure)
        if isinstance(node, dict)
    ]
    section_kinds = _section_kinds(structure)
    known_pages = _known_page_checks(structure, expected.get("known_pages") or {})
    must_have_nodes = _must_have_node_checks(structure, list(expected.get("must_have_nodes") or []))
    required_checks = _required_behavior_checks(structure, expected, index_payload)
    acceptance_spec = dict(expected.get("acceptance") or {})
    required_pages = _required_pages_checks(structure, acceptance_spec.get("required_pages") or {})
    required_sections = list(expected.get("must_have_sections") or [])
    missing_sections = [kind for kind in required_sections if kind not in section_kinds]
    top_level_check = _top_level_matches(
        _main_catalog_title_candidates(structure),
        list(expected.get("expected_top_level") or []),
    )
    required_root_check = _top_level_matches(
        effective_root_titles,
        list(acceptance_spec.get("required_root_titles") or []),
    )
    minimum_shape = _minimum_shape_check(structure, acceptance_spec)
    forbidden_spec = dict(acceptance_spec.get("forbidden_patterns") or {})
    forbidden_spec.update(dict(expected.get("forbidden_patterns") or {}))
    forbidden_patterns = _forbidden_pattern_checks(structure, forbidden_spec)
    route_ok = _route_matches_expected(route, expected)
    quality_status = str(quality_report.get("status") or "")
    hard_fail_reasons = list(quality_report.get("hard_fail_reasons") or [])
    llm_needs_repair = bool(llm_quality_check.get("needs_repair"))
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
        "must_have_nodes": bool(must_have_nodes.get("ok")),
        "required_checks": bool(required_checks.get("ok")),
        "minimum_shape": bool(minimum_shape.get("ok")),
        "required_root_titles": bool(required_root_check.get("ok")),
        "required_pages": all(item.get("ok") for item in required_pages.values()),
        "forbidden_patterns": bool(forbidden_patterns.get("ok")),
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
            "effective_root_count": len(_effective_root_nodes(structure)),
            "node_count": _count_nodes(structure),
            "max_depth": _max_depth(structure),
            "top_level_titles": top_titles,
            "effective_root_titles": effective_root_titles,
            "section_kinds": section_kinds,
            "missing_sections": missing_sections,
            "top_level_check": top_level_check,
            "required_root_check": required_root_check,
        },
        "quality": {
            "status": quality_status,
            "hard_fail_reasons": hard_fail_reasons,
            "warnings": list(quality_report.get("warnings") or []),
            "llm_needs_repair": llm_needs_repair,
            "llm_overall_score": llm_quality_check.get("overall_score"),
        },
        "key_checks": {
            "known_pages": known_pages,
            "must_have_nodes": must_have_nodes,
            "required_checks": required_checks,
            "required_pages": required_pages,
            "minimum_shape": minimum_shape,
            "forbidden_patterns": forbidden_patterns,
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
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for expected in _iter_expected_docs(input_dir, selected_file, fixture=fixture):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="Expected route/reference fixture JSON")
    parser.add_argument("--input", help="Directory containing PDFs. Defaults to fixture input_dir")
    parser.add_argument("--file", help="Run E2E for one PDF file name")
    parser.add_argument("--all", action="store_true", help="Explicitly run every fixture PDF")
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "toc_e2e"), help="Directory for report JSON files")
    parser.add_argument("--user-id", help="Optional user id for model/OCR profile resolution")
    parser.add_argument("--mode", default="smart", help="PageIndex generation mode")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop after the first non-ok report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    fixture = _load_fixture(args.fixture)
    default_input = fixture.get("input_dir") or r"D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge"
    input_dir = Path(args.input or default_input)
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
            fixture=fixture,
        )
    )
    print(json.dumps(result["summary"], ensure_ascii=False))
    summary = result["summary"]
    return 0 if summary.get("failed", 0) == 0 and summary.get("error", 0) == 0 and summary.get("missing", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
