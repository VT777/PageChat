import csv
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


def _safe_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _short_summary(text: str, max_len: int = 180) -> str:
    content = _safe_text(text)
    if len(content) <= max_len:
        return content
    return content[: max_len - 1] + "…"


def _chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _build_result(
    nodes: List[Dict[str, Any]],
    doc_description: str,
    file_type: str,
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "format": file_type,
        "doc_description": _short_summary(doc_description, max_len=240),
        "structure": nodes,
        "page_count": page_count if page_count is not None else len(nodes),
    }


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _normalize_title(text: str) -> str:
    t = _safe_text(text)
    t = re.sub(r"\.{2,}\s*\d+$", "", t)
    t = re.sub(r"\s+\d+$", "", t)
    return _safe_text(t)


def _is_noise_title(text: str) -> bool:
    t = _safe_text(text)
    if not t:
        return True
    # 纯数字/统计值
    if re.fullmatch(r"[0-9\s\.\+\-±]+", t):
        return True
    # 过短或过长
    if len(t) < 2 or len(t) > 120:
        return True
    return False


def _flatten_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    def walk(items: List[Dict[str, Any]]):
        for n in items:
            result.append(n)
            if isinstance(n.get("nodes"), list) and n.get("nodes"):
                walk(n["nodes"])

    walk(nodes)
    return result


def _toc_quality_score(nodes: List[Dict[str, Any]], anchor_key: str) -> float:
    flat = _flatten_nodes(nodes)
    if not flat:
        return 0.0

    score = 1.0
    if len(flat) < 3:
        score -= 0.35

    noise = sum(1 for n in flat if _is_noise_title(str(n.get("title") or "")))
    noise_ratio = noise / max(1, len(flat))
    score -= min(0.5, noise_ratio * 0.8)

    prev = -1
    bad_order = 0
    for n in flat:
        a = n.get("source_anchor") or {}
        cur = int(a.get(anchor_key) or 0)
        if cur and prev and cur < prev:
            bad_order += 1
        if cur:
            prev = cur
    if bad_order > 0:
        score -= min(0.3, bad_order * 0.05)

    return max(0.0, min(1.0, score))


def _llm_build_toc_fallback(
    segments: List[Dict[str, Any]],
    format_name: str,
    index_key: str,
) -> Optional[List[Dict[str, Any]]]:
    if not segments:
        return None
    try:
        from app.core.llm import chat_completion

        sample = segments[:260]
        context = "\n".join(
            f"{s[index_key]}\t{s['text'][:120]}" for s in sample if s.get("text")
        )
        prompt = (
            "你是目录提取器。请从下面文档内容中提取真实目录项，忽略目录页副本和统计数值行。"
            "\n仅输出 JSON 数组，每项包含: title, level(1-4), start。"
            f"\nstart 表示 {index_key} 的数值。"
            "\n如果无法提取，返回空数组。"
            "\n文档内容:\n" + context
        )

        resp = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            timeout=20,
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            return None

        m = re.search(r"\[.*\]", content, re.S)
        payload = m.group(0) if m else content
        import json

        items = json.loads(payload)
        if not isinstance(items, list):
            return None

        valid: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = _normalize_title(str(it.get("title") or ""))
            if _is_noise_title(title):
                continue
            try:
                level = int(it.get("level") or 1)
                start = int(it.get("start"))
            except Exception:
                continue
            valid.append(
                {"title": title, "level": max(1, min(level, 4)), "start": start}
            )

        if len(valid) < 2:
            return None

        valid.sort(key=lambda x: x["start"])
        return valid
    except Exception:
        return None


def _build_nodes_with_anchor(
    chunks: List[List[str]],
    title_prefix: str,
    anchors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks, start=1):
        text = "\n".join(chunk).strip()
        if not text:
            continue
        node: Dict[str, Any] = {
            "node_id": f"node_{i}",
            "title": f"{title_prefix} {i}",
            "start_index": i,
            "end_index": i,
            "summary": _short_summary(text),
            "text": text,
            "nodes": [],
        }
        if len(anchors) >= i:
            node["source_anchor"] = anchors[i - 1]
        nodes.append(node)
    return nodes


def _extract_txt(file_path: Path) -> Dict[str, Any]:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines and text.strip():
        lines = [text.strip()]

    chunks = _chunk_list(lines, 40)
    anchors: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        start_line = i * 40 + 1
        end_line = start_line + len(chunk) - 1
        anchors.append(
            {
                "format": "txt",
                "unit_type": "line",
                "start_line": start_line,
                "end_line": end_line,
            }
        )

    nodes = _build_nodes_with_anchor(chunks, "文本段", anchors)
    doc_description = lines[0] if lines else f"纯文本文件：{file_path.name}"
    return _build_result(nodes, doc_description, file_path.suffix.lower())


def _extract_markdown(file_path: Path) -> Dict[str, Any]:
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    setext_underline = re.compile(r"^\s*(=+|-+)\s*$")

    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_code_block = False

    def close_current(end_line: int):
        nonlocal current
        if current is None:
            return
        current["end_line"] = end_line
        sections.append(current)
        current = None

    for i, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block

        if in_code_block:
            if current is None:
                current = {
                    "title": "文档开头",
                    "level": 1,
                    "start_line": i,
                    "end_line": i,
                    "lines": [],
                }
            current["lines"].append(line)
            continue

        m = heading_pattern.match(line)
        if m:
            close_current(i - 1)
            level = len(m.group(1))
            title = _safe_text(m.group(2)) or f"章节 {len(sections) + 1}"
            current = {
                "title": title,
                "level": level,
                "start_line": i,
                "end_line": i,
                "lines": [line],
            }
            continue

        if i > 1 and setext_underline.match(line):
            prev = _safe_text(lines[i - 2])
            if prev:
                close_current(i - 2)
                level = 1 if line.strip().startswith("=") else 2
                current = {
                    "title": prev,
                    "level": level,
                    "start_line": i - 1,
                    "end_line": i - 1,
                    "lines": [prev],
                }
            continue

        if current is None:
            current = {
                "title": "文档开头",
                "level": 1,
                "start_line": i,
                "end_line": i,
                "lines": [],
            }

        current["lines"].append(line)

    if current is not None:
        current["end_line"] = len(lines) if lines else 1
        sections.append(current)

    flat_nodes: List[Dict[str, Any]] = []
    for i, section in enumerate(sections, start=1):
        section_text = "\n".join(section["lines"]).strip()
        if not section_text:
            continue
        flat_nodes.append(
            {
                "node_id": f"node_{i}",
                "title": section["title"],
                "start_index": i,
                "end_index": i,
                "level": int(section.get("level") or 1),
                "summary": _short_summary(section_text),
                "text": section_text,
                "source_anchor": {
                    "format": "markdown",
                    "unit_type": "line",
                    "start_line": int(section["start_line"]),
                    "end_line": int(section["end_line"]),
                },
                "nodes": [],
            }
        )

    # Low-quality Markdown can still use the line-based fallback.
    if _toc_quality_score(flat_nodes, "start_line") < 0.55:
        llm_items = _llm_build_toc_fallback(
            [
                {"start_line": i, "text": ln}
                for i, ln in enumerate(lines, start=1)
                if _safe_text(ln)
            ],
            "markdown",
            "start_line",
        )
        if llm_items:
            llm_nodes: List[Dict[str, Any]] = []
            for i, it in enumerate(llm_items, start=1):
                start_line = int(it["start"])
                end_line = (
                    int(llm_items[i]["start"]) - 1 if i < len(llm_items) else len(lines)
                )
                content_text = "\n".join(
                    lines[max(0, start_line - 1) : max(start_line, end_line)]
                )
                llm_nodes.append(
                    {
                        "node_id": f"node_{i}",
                        "title": it["title"],
                        "start_index": i,
                        "end_index": i,
                        "level": int(it["level"]),
                        "summary": _short_summary(content_text),
                        "text": content_text,
                        "source_anchor": {
                            "format": "markdown",
                            "unit_type": "line",
                            "start_line": start_line,
                            "end_line": max(start_line, end_line),
                        },
                        "nodes": [],
                    }
                )
            flat_nodes = llm_nodes

    # 构建层级
    nodes: List[Dict[str, Any]] = []
    if flat_nodes:
        stack: List[Tuple[int, Dict[str, Any]]] = []
        for node in flat_nodes:
            level = max(1, min(int(node.get("level") or 1), 6))
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].setdefault("nodes", []).append(node)
            else:
                nodes.append(node)
            stack.append((level, node))

    if not nodes:
        plain_lines = [line.rstrip() for line in lines if line.strip()]
        chunks = _chunk_list(plain_lines, 40)
        anchors: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            start_line = i * 40 + 1
            end_line = start_line + len(chunk) - 1
            anchors.append(
                {
                    "format": "markdown",
                    "unit_type": "line",
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
        nodes = _build_nodes_with_anchor(chunks, "Markdown 区块", anchors)

    doc_description = (
        nodes[0]["summary"] if nodes else f"Markdown 文档：{file_path.name}"
    )
    return _build_result(
        nodes,
        doc_description,
        file_path.suffix.lower(),
        page_count=len(flat_nodes) if flat_nodes else len(nodes),
    )


def _extract_csv_like(file_path: Path, delimiter: str) -> Dict[str, Any]:
    rows: List[str] = []
    row_numbers: List[int] = []
    with open(file_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row_idx, row in enumerate(reader, start=1):
            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            rows.append(f"row {row_idx}: " + " | ".join(cells))
            row_numbers.append(row_idx)

    chunks = _chunk_list(rows, 100)
    num_chunks = _chunk_list([str(n) for n in row_numbers], 100)
    anchors: List[Dict[str, Any]] = []
    fmt = file_path.suffix.lower().lstrip(".")
    for num_chunk in num_chunks:
        if not num_chunk:
            continue
        anchors.append(
            {
                "format": fmt,
                "unit_type": "row_range",
                "start_row": int(num_chunk[0]),
                "end_row": int(num_chunk[-1]),
            }
        )

    nodes = _build_nodes_with_anchor(chunks, "表格区块", anchors)
    doc_description = rows[0] if rows else f"表格文件：{file_path.name}"
    return _build_result(nodes, doc_description, file_path.suffix.lower())


def _extract_docx(file_path: Path) -> Dict[str, Any]:
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }

    def parse_style_level(style_id: str, style_name: str) -> Optional[int]:
        s = style_id or ""
        n = style_name or ""

        for target in (s, n):
            m = re.search(r"heading\s*([1-9])", target, re.IGNORECASE)
            if m:
                return int(m.group(1))

            m2 = re.search(r"标题\s*([1-9])", target)
            if m2:
                return int(m2.group(1))

        return None

    def infer_level_from_text(text: str) -> Optional[int]:
        t = _safe_text(text)
        if not t:
            return None

        # 第X章 / 第1章
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+[章节部篇]", t):
            return 1

        # 一、 / 一． / 一.
        if re.match(r"^[一二三四五六七八九十百千万]+[、\.．]", t):
            return 1

        # （一） / (1)
        if re.match(r"^[（(][一二三四五六七八九十百千万0-9]+[)）]", t):
            return 2

        # 1. / 1.1 / 1.1.1
        m = re.match(r"^(\d+(?:\.\d+){0,3})[、\.．]", t)
        if m:
            depth = m.group(1).count(".") + 1
            return min(depth, 3)

        return None

    def looks_like_toc_entry(text: str) -> bool:
        t = _safe_text(text)
        if not t:
            return False
        # 常见目录项：短文本 + 末尾页码
        if len(t) <= 80 and re.search(r"\d+$", t):
            if re.match(
                r"^(第[一二三四五六七八九十百千万0-9]+[章节部篇]|[一二三四五六七八九十百千万]+[、\.．]|[（(][一二三四五六七八九十百千万0-9]+[)）]|\d+(?:\.\d+){0,3}[、\.．])",
                t,
            ):
                return True
        return False

    def clean_toc_entry_title(text: str) -> str:
        t = _safe_text(text)
        t = re.sub(r"\.{2,}\s*\d+$", "", t)
        t = re.sub(r"\s+\d+$", "", t)
        return _normalize_title(t)

    style_name_map: Dict[str, str] = {}
    toc_style_ids: set[str] = set()
    heading_style_level: Dict[str, int] = {}

    paragraphs: List[Dict[str, Any]] = []
    with zipfile.ZipFile(file_path, "r") as zf:
        if "word/styles.xml" in zf.namelist():
            styles_root = ET.fromstring(zf.read("word/styles.xml"))
            for style in styles_root.findall("w:style", ns):
                style_id = str(
                    style.attrib.get(f"{{{ns['w']}}}styleId")
                    or style.attrib.get("styleId")
                    or ""
                )
                if not style_id:
                    continue

                name_el = style.find("w:name", ns)
                style_name = ""
                if name_el is not None:
                    style_name = str(
                        name_el.attrib.get(f"{{{ns['w']}}}val")
                        or name_el.attrib.get("val")
                        or ""
                    )

                style_name_map[style_id] = style_name

                level = parse_style_level(style_id, style_name)
                if level is not None:
                    heading_style_level[style_id] = level

                if re.search(r"toc|目录|contents", style_name, re.IGNORECASE):
                    toc_style_ids.add(style_id)

        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)

    para_num = 0
    for p in root.iter():
        if _xml_ns(p.tag) != "p":
            continue
        para_num += 1

        texts: List[str] = []
        for child in p.iter():
            if _xml_ns(child.tag) == "t" and child.text:
                texts.append(child.text)

        para = _safe_text("".join(texts))

        style_val = ""
        p_pr = p.find("w:pPr", ns)
        if p_pr is not None:
            p_style = p_pr.find("w:pStyle", ns)
            if p_style is not None:
                style_val = str(
                    p_style.attrib.get(f"{{{ns['w']}}}val")
                    or p_style.attrib.get("val")
                    or ""
                )

        style_name = style_name_map.get(style_val, "")
        is_toc_style = style_val in toc_style_ids

        heading_level = heading_style_level.get(style_val)
        if heading_level is None:
            heading_level = parse_style_level(style_val, style_name)

        if heading_level is None and para and not is_toc_style:
            heading_level = infer_level_from_text(para)

        if para:
            paragraphs.append(
                {
                    "num": para_num,
                    "text": para,
                    "style": style_val,
                    "style_name": style_name,
                    "is_toc_style": is_toc_style,
                    "heading_level": heading_level,
                }
            )

    toc_candidates: List[Dict[str, Any]] = []
    body_heading_candidates: List[Dict[str, Any]] = []
    for para in paragraphs:
        text_val = str(para.get("text") or "")
        if _is_noise_title(text_val):
            continue

        is_toc_entry = para.get("is_toc_style") or looks_like_toc_entry(text_val)
        if is_toc_entry:
            title = clean_toc_entry_title(text_val)
            if _is_noise_title(title):
                continue
            level = int(para.get("heading_level") or infer_level_from_text(title) or 1)
            toc_candidates.append(
                {
                    "title": title,
                    "level": max(1, min(level, 4)),
                }
            )
            continue

        if para.get("heading_level") is not None:
            body_heading_candidates.append(
                {
                    "title": _normalize_title(text_val),
                    "level": int(para.get("heading_level") or 1),
                    "start_paragraph": int(para.get("num") or 0),
                }
            )

    nodes: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    current_section: Optional[Dict[str, Any]] = None

    # 优先：目录候选映射到正文标题（避免把目录页当正文）
    mapped_from_toc: List[Dict[str, Any]] = []
    if len(toc_candidates) >= 3 and body_heading_candidates:
        used_body: set[int] = set()
        for toc in toc_candidates:
            target = toc["title"]
            if _is_noise_title(target):
                continue
            match_idx = None
            for i, b in enumerate(body_heading_candidates):
                if i in used_body:
                    continue
                bt = b["title"]
                if not bt:
                    continue
                if bt == target or bt in target or target in bt:
                    match_idx = i
                    break
            if match_idx is None:
                continue
            used_body.add(match_idx)
            b = body_heading_candidates[match_idx]
            mapped_from_toc.append(
                {
                    "title": b["title"],
                    "level": int(toc.get("level") or b.get("level") or 1),
                    "start_paragraph": int(b["start_paragraph"]),
                }
            )

    # 若目录映射命中率足够，则用映射结果建章节
    if mapped_from_toc and len(mapped_from_toc) >= max(
        3, int(len(toc_candidates) * 0.5)
    ):
        mapped_from_toc.sort(key=lambda x: x["start_paragraph"])
        para_map = {int(p["num"]): str(p["text"]) for p in paragraphs}
        para_numbers = sorted(para_map.keys())
        max_para = para_numbers[-1] if para_numbers else 1

        for i, item in enumerate(mapped_from_toc):
            start_p = int(item["start_paragraph"])
            end_p = (
                int(mapped_from_toc[i + 1]["start_paragraph"]) - 1
                if i < len(mapped_from_toc) - 1
                else max_para
            )
            lines = [
                para_map[n]
                for n in para_numbers
                if start_p <= n <= end_p and para_map[n]
            ]
            if not lines:
                continue
            sections.append(
                {
                    "title": item["title"],
                    "start_paragraph": start_p,
                    "end_paragraph": max(start_p, end_p),
                    "lines": lines,
                    "level": int(item.get("level") or 1),
                }
            )

    # 回退：规则标题切分正文
    if not sections:
        for para in paragraphs:
            if para.get("is_toc_style"):
                continue

            if para["text"] in {"目录", "目 录", "目\u3000录"}:
                continue

            if looks_like_toc_entry(para["text"]):
                continue

            if para["heading_level"] is not None:
                if current_section is not None:
                    sections.append(current_section)

                current_section = {
                    "title": para["text"],
                    "start_paragraph": para["num"],
                    "end_paragraph": para["num"],
                    "lines": [para["text"]],
                    "level": para["heading_level"],
                }
                continue

            if current_section is None:
                current_section = {
                    "title": "文档开头",
                    "start_paragraph": para["num"],
                    "end_paragraph": para["num"],
                    "lines": [],
                    "level": 1,
                }

            current_section["lines"].append(para["text"])
            current_section["end_paragraph"] = para["num"]

        if current_section is not None:
            sections.append(current_section)

    flat_nodes: List[Dict[str, Any]] = []
    for i, section in enumerate(sections, start=1):
        section_text = "\n".join(section["lines"]).strip()
        if not section_text:
            continue

        flat_nodes.append(
            {
                "node_id": f"node_{i}",
                "title": section["title"],
                "start_index": i,
                "end_index": i,
                "level": int(section.get("level") or 1),
                "summary": _short_summary(section_text),
                "text": section_text,
                "source_anchor": {
                    "format": "docx",
                    "unit_type": "paragraph",
                    "start_paragraph": int(section["start_paragraph"]),
                    "end_paragraph": int(section["end_paragraph"]),
                },
                "nodes": [],
            }
        )

    # 根据 heading level 构建层级目录树
    if flat_nodes:
        tree_nodes: List[Dict[str, Any]] = []
        stack: List[Tuple[int, Dict[str, Any]]] = []

        for node in flat_nodes:
            level = max(1, min(int(node.get("level") or 1), 6))
            node["level"] = level

            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                stack[-1][1].setdefault("nodes", []).append(node)
            else:
                tree_nodes.append(node)

            stack.append((level, node))

        nodes = tree_nodes

    if not nodes:
        plain_paragraphs = [p["text"] for p in paragraphs]
        chunks = _chunk_list(plain_paragraphs, 15)
        anchors: List[Dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            start_paragraph = i * 15 + 1
            end_paragraph = start_paragraph + len(chunk) - 1
            anchors.append(
                {
                    "format": "docx",
                    "unit_type": "paragraph",
                    "start_paragraph": start_paragraph,
                    "end_paragraph": end_paragraph,
                }
            )
        nodes = _build_nodes_with_anchor(chunks, "段落组", anchors)

    doc_description = (
        flat_nodes[0]["summary"] if flat_nodes else f"Word 文档：{file_path.name}"
    )
    total_nodes = len(flat_nodes) if flat_nodes else len(nodes)
    return _build_result(
        nodes,
        doc_description,
        file_path.suffix.lower(),
        page_count=total_nodes,
    )


def _slide_sort_key(path: str) -> int:
    m = re.search(r"(\d+)", path)
    return int(m.group(1)) if m else 0


def _extract_pptx(file_path: Path) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    with zipfile.ZipFile(file_path, "r") as zf:
        slide_paths = [
            n
            for n in zf.namelist()
            if n.startswith("ppt/slides/") and n.endswith(".xml") and "_rels" not in n
        ]
        slide_paths.sort(key=_slide_sort_key)

        for i, slide_path in enumerate(slide_paths, start=1):
            root = ET.fromstring(zf.read(slide_path))
            texts: List[str] = []
            for el in root.iter():
                if _xml_ns(el.tag) == "t" and el.text:
                    t = _safe_text(el.text)
                    if t:
                        texts.append(t)

            text = "\n".join(texts).strip()
            if not text:
                continue

            nodes.append(
                {
                    "node_id": f"slide_{i}",
                    "title": f"第 {i} 页幻灯片",
                    "start_index": i,
                    "end_index": i,
                    "summary": _short_summary(text),
                    "text": text,
                    "source_anchor": {
                        "format": "pptx",
                        "unit_type": "slide",
                        "start_slide": i,
                        "end_slide": i,
                    },
                    "nodes": [],
                }
            )

    doc_description = (
        nodes[0]["summary"] if nodes else f"PowerPoint 文档：{file_path.name}"
    )
    return _build_result(nodes, doc_description, file_path.suffix.lower())


def _col_letters(col_num: int) -> str:
    result = ""
    n = col_num
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: List[str] = []
    for si in root:
        if _xml_ns(si.tag) != "si":
            continue
        parts: List[str] = []
        for t in si.iter():
            if _xml_ns(t.tag) == "t" and t.text:
                parts.append(t.text)
        values.append(_safe_text("".join(parts)))
    return values


def _xlsx_sheet_names(zf: zipfile.ZipFile) -> Dict[str, str]:
    if "xl/workbook.xml" not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    name_map: Dict[str, str] = {}
    for sheet in root.iter():
        if _xml_ns(sheet.tag) != "sheet":
            continue
        sheet_name = sheet.attrib.get("name") or "Sheet"
        sheet_id = sheet.attrib.get("sheetId")
        if sheet_id:
            name_map[f"xl/worksheets/sheet{sheet_id}.xml"] = sheet_name
    return name_map


def _cell_value(cell: ET.Element, shared_strings: List[str]) -> str:
    ctype = cell.attrib.get("t")
    value_el = None
    for child in cell:
        if _xml_ns(child.tag) == "v":
            value_el = child
            break
    if value_el is None or value_el.text is None:
        return ""

    raw = value_el.text
    if ctype == "s":
        try:
            idx = int(raw)
            return shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
        except ValueError:
            return ""
    return _safe_text(raw)


def _extract_xlsx(file_path: Path) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    node_idx = 1

    with zipfile.ZipFile(file_path, "r") as zf:
        shared_strings = _parse_shared_strings(zf)
        sheet_name_map = _xlsx_sheet_names(zf)
        sheet_files = [
            n
            for n in zf.namelist()
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        ]
        sheet_files.sort(key=_slide_sort_key)

        for sheet_file in sheet_files:
            sheet_name = sheet_name_map.get(sheet_file, Path(sheet_file).stem)
            root = ET.fromstring(zf.read(sheet_file))
            sheet_rows: List[Tuple[int, str]] = []

            for row in root.iter():
                if _xml_ns(row.tag) != "row":
                    continue
                row_num = row.attrib.get("r", "?")
                values: List[str] = []
                col_idx = 1
                for cell in row:
                    if _xml_ns(cell.tag) != "c":
                        continue
                    val = _cell_value(cell, shared_strings)
                    if val:
                        values.append(f"{_col_letters(col_idx)}={val}")
                    col_idx += 1
                if values:
                    try:
                        row_num_int = int(row_num)
                    except ValueError:
                        row_num_int = 0
                    sheet_rows.append(
                        (
                            row_num_int,
                            f"sheet={sheet_name}, row={row_num}: " + ", ".join(values),
                        )
                    )

            row_chunks = _chunk_list([r[1] for r in sheet_rows], 80)
            row_num_chunks = _chunk_list([str(r[0]) for r in sheet_rows], 80)
            for row_chunk, num_chunk in zip(row_chunks, row_num_chunks):
                text = "\n".join(row_chunk).strip()
                if not text:
                    continue
                start_row = (
                    int(num_chunk[0]) if num_chunk and num_chunk[0].isdigit() else 0
                )
                end_row = (
                    int(num_chunk[-1]) if num_chunk and num_chunk[-1].isdigit() else 0
                )
                nodes.append(
                    {
                        "node_id": f"node_{node_idx}",
                        "title": f"工作表 {sheet_name} 区块 {node_idx}",
                        "start_index": node_idx,
                        "end_index": node_idx,
                        "summary": _short_summary(text),
                        "text": text,
                        "source_anchor": {
                            "format": "xlsx",
                            "unit_type": "row_range",
                            "sheet": sheet_name,
                            "start_row": start_row,
                            "end_row": end_row,
                        },
                        "nodes": [],
                    }
                )
                node_idx += 1

    doc_description = nodes[0]["summary"] if nodes else f"Excel 文档：{file_path.name}"
    return _build_result(nodes, doc_description, file_path.suffix.lower())


def generate_multi_format_index(file_path: Path) -> Optional[Dict[str, Any]]:
    suffix = file_path.suffix.lower()
    if suffix == ".txt":
        return _extract_txt(file_path)
    if suffix in {".md", ".markdown"}:
        return _extract_markdown(file_path)
    if suffix == ".csv":
        return _extract_csv_like(file_path, delimiter=",")
    if suffix == ".tsv":
        return _extract_csv_like(file_path, delimiter="\t")
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix == ".pptx":
        return _extract_pptx(file_path)
    if suffix == ".xlsx":
        return _extract_xlsx(file_path)
    return None
