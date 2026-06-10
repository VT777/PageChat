"""节点填充：文本页直取 + 图片页 OCR + 摘要生成。"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import (
    PAGEINDEX_SUMMARY_CONCURRENCY,
    PAGEINDEX_SUMMARY_MAX_LLM_NODES,
    PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS,
    PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS,
)


# ---------------------------------------------------------------------------
# 节点文本填充
# ---------------------------------------------------------------------------


def fill_node_text(
    toc_tree: List[Dict],
    page_list: List[Tuple[str, int]],
) -> None:
    """递归填充节点文本。文本页用 pymupdf 直取的文本。

    Args:
        toc_tree: post_processing 输出的树结构
        page_list: [(text, token_count), ...] 0-indexed
    """
    for node in toc_tree:
        if node.get("exclude_from_text") or node.get("node_type") in {
            "auxiliary_catalog",
            "auxiliary_catalog_item",
        }:
            node["text"] = ""
            if "nodes" in node and node["nodes"]:
                fill_node_text(node["nodes"], page_list)
            continue

        start = node.get("start_index")
        end = node.get("end_index")
        if start is not None and end is not None:
            # start_index / end_index 是 1-indexed
            text_parts = []
            for page_idx in range(start - 1, min(end, len(page_list))):
                if 0 <= page_idx < len(page_list):
                    text_parts.append(page_list[page_idx][0])
            node["text"] = "\n".join(text_parts)
        else:
            node["text"] = ""

        if "nodes" in node and node["nodes"]:
            fill_node_text(node["nodes"], page_list)


async def ocr_image_pages(
    analysis: Dict[str, Any],
    page_list: List[Tuple[str, int]],
    ocr_service_fn=None,
) -> List[Tuple[str, int]]:
    """对图片页和乱码页执行 OCR，覆盖 page_list 中的文本。

    Args:
        analysis: pdf_analyzer 输出
        page_list: 原始 page_list（会被修改）
        ocr_service_fn: OCR 服务函数（异步），签名 (file_path, page_count) -> dict

    Returns:
        更新后的 page_list
    """
    image_pages = analysis.get("image_only_pages", [])
    garbled_pages = analysis.get("garbled_pages", [])
    pages_to_ocr = sorted(set(image_pages + garbled_pages))

    if not pages_to_ocr or not ocr_service_fn:
        return page_list

    file_path = analysis["file_path"]
    page_count = analysis["page_count"]

    try:
        ocr_result = await ocr_service_fn(file_path, page_count)
        ocr_pages = ocr_result.get("ocr_pages", [])

        for ocr_page in ocr_pages:
            page_num = ocr_page.get("page_num")
            text = ocr_page.get("text", "")
            if page_num and text and 1 <= page_num <= len(page_list):
                idx = page_num - 1
                if idx in pages_to_ocr or not page_list[idx][0].strip():
                    # 覆盖空文本或图片/乱码页
                    token_approx = max(1, int(len(text) * 0.7))
                    page_list[idx] = (text, token_approx)

        print(
            f"[NODE-FILL] OCR覆盖 {len(ocr_pages)} 页 (需OCR: {len(pages_to_ocr)} 页)"
        )
    except Exception as e:
        print(f"[NODE-FILL] OCR failed: {e}")

    return page_list


# ---------------------------------------------------------------------------
# 摘要生成
# ---------------------------------------------------------------------------


async def generate_summaries(
    toc_tree: List[Dict],
    model: Optional[str] = None,
    mode: str = "balanced",
) -> None:
    """递归生成节点摘要。

    - fast: 代码生成（标题+前150字）
    - balanced: LLM 生成
    """
    if mode == "fast":
        _generate_summaries_fast(toc_tree)
    else:
        await _generate_summaries_balanced(toc_tree, model)


def _generate_summaries_fast(toc_tree: List[Dict]) -> None:
    """Fast 模式：纯代码生成摘要。
    
    改进：如果节点文本为空（未OCR），使用子节点标题构建摘要。
    """
    for node in toc_tree:
        title = node.get("title", "")
        text = node.get("text", "")
        
        # 策略1：如果有文本，取前150字符
        preview = text[:200].replace("\n", " ").strip()
        
        # 策略2：如果文本为空但有子节点，用子节点标题补充
        if not preview and node.get("nodes"):
            child_titles = []
            for child in node["nodes"][:5]:  # 最多取5个子节点
                child_title = child.get("title", "")
                if child_title and child_title != title:  # 避免重复
                    child_titles.append(child_title)
            if child_titles:
                preview = "；".join(child_titles)
        
        # 策略3：完全为空，只用标题
        if preview:
            node["summary"] = f"{title}。{preview}"
        else:
            node["summary"] = title

        if "nodes" in node and node["nodes"]:
            _generate_summaries_fast(node["nodes"])


async def _generate_summaries_balanced(
    toc_tree: List[Dict],
    model: Optional[str] = None,
) -> None:
    """Balanced 模式：LLM 生成摘要（并发）。"""
    # 收集所有需要生成摘要的节点
    all_nodes = []
    _collect_nodes(toc_tree, all_nodes)
    all_nodes = [
        node
        for node in all_nodes
        if not node.get("exclude_from_llm_qc")
        and node.get("node_type") not in {"auxiliary_catalog", "auxiliary_catalog_item"}
    ]
    if not all_nodes:
        return

    llm_nodes = all_nodes[:PAGEINDEX_SUMMARY_MAX_LLM_NODES]
    fallback_nodes = all_nodes[PAGEINDEX_SUMMARY_MAX_LLM_NODES:]
    for node in fallback_nodes:
        _set_fast_summary(node)

    # 并发生成（限制并发度）
    semaphore = asyncio.Semaphore(PAGEINDEX_SUMMARY_CONCURRENCY)

    async def _gen(node):
        async with semaphore:
            try:
                summary = await asyncio.wait_for(
                    _call_generate_node_summary(node, model=model),
                    timeout=PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS,
                )
                node["summary"] = summary
            except Exception:
                # Fallback to fast summary
                _set_fast_summary(node)

    try:
        await asyncio.wait_for(
            asyncio.gather(*[_gen(node) for node in llm_nodes]),
            timeout=PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS,
        )
    except Exception:
        for node in llm_nodes:
            if not node.get("summary"):
                _set_fast_summary(node)


async def _call_generate_node_summary(
    node: Dict,
    model: Optional[str] = None,
) -> str:
    from pageindex.utils import generate_node_summary

    return await generate_node_summary(node, model=model)


def _set_fast_summary(node: Dict) -> None:
    title = node.get("title", "")
    text = node.get("text", "")
    preview = str(text or "")[:150]
    node["summary"] = f"{title} {preview}".strip() if preview else title


def _collect_nodes(tree: List[Dict], result: List[Dict]) -> None:
    """递归收集所有节点。"""
    for node in tree:
        result.append(node)
        if "nodes" in node and node["nodes"]:
            _collect_nodes(node["nodes"], result)


# ---------------------------------------------------------------------------
# 文档描述
# ---------------------------------------------------------------------------


def _build_toc_outline(tree: List[Dict], lines: List[str], indent: int = 0) -> None:
    """递归构建TOC层级结构文本。"""
    for node in tree:
        prefix = "  " * indent + "- "
        title = node.get("title", "")
        if title:
            lines.append(f"{prefix}{title}")
        if node.get("nodes"):
            _build_toc_outline(node["nodes"], lines, indent + 1)


async def generate_doc_description(
    toc_tree: List[Dict],
    model: Optional[str] = None,
    file_name: str = "",
) -> str:
    """生成文档一句话描述。
    
    改进：使用文件名 + 递归完整TOC（而非仅顶层节点）。
    """
    from pageindex.utils import ChatGPT_API_async
    from app.prompts.pageindex_prompts import DOC_DESCRIPTION_PROMPT

    # 构建完整层级结构
    lines = []
    if file_name:
        lines.append(f"文件名：{file_name}")
    lines.append("目录结构：")
    _build_toc_outline(toc_tree, lines)
    structure_summary = "\n".join(lines)

    prompt = DOC_DESCRIPTION_PROMPT.format(structure_summary=structure_summary)
    try:
        response = await ChatGPT_API_async(model=model, prompt=prompt)
        return response.strip()[:200]
    except Exception:
        # Fallback：返回文件名 + 前3个顶层标题
        fallback = file_name + "：" if file_name else ""
        top_titles = [n.get("title", "") for n in toc_tree[:3]]
        fallback += "、".join(filter(None, top_titles))
        return fallback[:100]


# ---------------------------------------------------------------------------
# 节点 ID
# ---------------------------------------------------------------------------


def write_node_ids(toc_tree: List[Dict]) -> None:
    """深度优先分配 4 位节点 ID。"""
    counter = [0]

    def _assign(nodes: List[Dict]):
        for node in nodes:
            node["node_id"] = f"{counter[0]:04d}"
            counter[0] += 1
            if "nodes" in node and node["nodes"]:
                _assign(node["nodes"])

    _assign(toc_tree)
