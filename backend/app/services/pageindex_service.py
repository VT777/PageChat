import sys
import json
import asyncio
import re
import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List

# 娣诲姞 pageindex 鍒?Python 璺緞
sys.path.insert(0, str(Path(__file__).parent.parent))

import PyPDF2

from pageindex.page_index import page_index_main, page_index_main_with_page_list
from pageindex.utils import config, get_nodes, get_page_tokens, structure_to_list
from pageindex.page_index_md import md_to_tree
from pageindex.quality_validation import TocQualityChecker, build_index_quality_report
from app.models.retrieval import build_source_display_label
from app.core.config import (
    INDEXES_DIR,
    build_effective_pageindex_config,
    PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED,
    PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES,
    PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS,
    PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD,
    PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD,
    PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD,
    VISION_TOC_STRICT_TARGET_RATIO,
    VISION_TOC_STRICT_MAX_GAP_PAGES,
    VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS,
    VISUAL_MAX_CONSECUTIVE_FAIL_PAGES,
    VISUAL_VLM_MAX_CONCURRENCY,
    VISUAL_VLM_PAGE_MAX_ATTEMPTS,
    VISUAL_PAGE_TIMEOUT_SECONDS,
    OCR_MAX_CONCURRENCY,
    OCR_MIN_IMAGE_AREA_RATIO,
    OCR_MIN_IMAGE_SIDE_PX,
)
from app.prompts.pageindex_prompts import (
    QUERY_VERIFICATION_PROMPT,
    FAST_DOC_LIGHT_SUMMARY_PROMPT,
)
from app.services.multi_format_adapter import generate_multi_format_index
from app.services.ocr_service import OCRService
from app.services.runtime_settings_service import runtime_settings_service


TREE_HIGH_CONFIDENCE_THRESHOLD = 0.65
TREE_FALLBACK_CONFIDENCE_THRESHOLD = 0.35


async def check_query_appearance(
    query: str, node_text: str, model: str = "qwen3.6-flash"
) -> dict:
    """
    楠岃瘉鐢ㄦ埛鏌ヨ鏄惁鍑虹幇鍦ㄨ妭鐐规枃鏈腑

    Returns:
        {
            "query_appears": "yes" | "no" | "partial",
            "confidence": 0.0-1.0,
            "reasoning": str
        }
    """
    from app.core.llm import async_chat_completion

    if not node_text or len(node_text.strip()) < 10:
        return {
            "query_appears": "no",
            "confidence": 0.0,
            "reasoning": "node text is empty or too short",
        }

    truncated_text = node_text[:800]

    prompt = QUERY_VERIFICATION_PROMPT.format(query=query, content=truncated_text)

    try:
        response = await async_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            model=model,
        )
        content = response.choices[0].message.content

        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {
                "query_appears": "no",
                "confidence": 0.0,
                "reasoning": "failed to parse response",
            }
    except Exception as e:
        print(f"check_query_appearance error: {e}")
        return {"query_appears": "no", "confidence": 0.0, "reasoning": str(e)}


async def verify_candidate_nodes(
    candidates: List[dict],
    query: str,
    nodes: List[dict],
    model: str = "qwen3.6-flash",
) -> List[dict]:
    """
    楠岃瘉 LLM 閫夋嫨鐨勫€欓€夎妭鐐规槸鍚︾湡鐨勫寘鍚煡璇㈠唴瀹?
    Args:
        candidates: LLM 杩斿洖鐨勫€欓€夊垪琛?        query: 鐢ㄦ埛鏌ヨ
        nodes: 鎵€鏈夎妭鐐圭殑瀹屾暣淇℃伅 (from structure_to_list)
        model: 楠岃瘉鐢ㄧ殑妯″瀷

    Returns:
        甯﹂獙璇佸垎鏁扮殑鍊欓€夊垪琛?    """
    node_dict = {n.get("node_id"): n for n in nodes}
    verified_results = []

    async def verify_one(candidate):
        node_id = candidate.get("node_id")
        if node_id in node_dict:
            node = node_dict[node_id]
            text = node.get("text", "") or ""
            return await check_query_appearance(query, text, model)
        else:
            return {
                "query_appears": "no",
                "confidence": 0.0,
                "reasoning": "node not found",
            }

    verification_coroutines = [verify_one(c) for c in candidates]
    verification_results = await asyncio.gather(
        *verification_coroutines, return_exceptions=True
    )

    for candidate, verification in zip(candidates, verification_results):
        if isinstance(verification, Exception):
            candidate["verification_passed"] = False
            candidate["verification_confidence"] = 0.0
            candidate["verification_reasoning"] = str(verification)
        else:
            candidate["verification_passed"] = verification.get("query_appears") in (
                "yes",
                "partial",
            )
            candidate["verification_confidence"] = verification.get("confidence", 0.0)
            candidate["verification_reasoning"] = verification.get("reasoning", "")

            if not candidate["verification_passed"]:
                candidate["relevance"] = candidate.get("relevance", 0.5) * 0.3

        verified_results.append(candidate)

    return verified_results


class PageIndexService:
    """PageIndex service - generate and query tree indexes."""

    def __init__(self):
        self.opt = self._build_opt()

    @staticmethod
    def _persist_failure_diagnostics(doc_id: str, payload: Dict[str, Any]) -> None:
        try:
            INDEXES_DIR.mkdir(parents=True, exist_ok=True)
            index_path = INDEXES_DIR / f"{doc_id}.json"
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[VISION_DIAG] failed to persist diagnostics doc={doc_id}: {e}")

    def _build_opt(self, mode_override: Optional[str] = None):
        condition = mode_override in {"smart", "fast", "balanced"}
        mode = (
            str(mode_override).strip().lower()
            if condition
            else runtime_settings_service.get_settings().get(
                "pageindex_mode", "balanced"
            )
        )
        return config(**build_effective_pageindex_config(mode=mode))

    @staticmethod
    def _normalize_page_text_for_ocr(text: str) -> str:
        t = re.sub(r"\s+", " ", str(text or "")).strip()
        return t

    async def _ocr_pages_for_toc_validation(
        self, file_path: Path, page_indices: List[int]
    ) -> Dict[int, str]:
        """Phase 0.5: run lightweight OCR for selected pages.

        Returns: {physical_page_number(1-indexed): OCR text}
        """
        if not page_indices:
            return {}

        import base64
        import io
        from pageindex.vlm_utils import render_pages_to_images

        images = render_pages_to_images(str(file_path), page_indices, dpi=150)
        if not images:
            return {}

        ocr_service = OCRService()
        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))

        async def ocr_single(img_info):
            page_num = img_info["page_index"] + 1  # 0-indexed 鈫?1-indexed
            async with sem:
                result = await ocr_service.ocr_image_base64(
                    img_info["image_base64"], page_num=page_num
                )
            return page_num, result.text if result.ok else ""

        results = await asyncio.gather(*[ocr_single(img) for img in images])
        return {
            page_num: text for page_num, text in results if text
        }

    async def _run_full_pdf_ocr_by_images(
        self, file_path: Path, page_count: int
    ) -> Dict[str, Any]:
        if page_count <= 0:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": [],
            }

        try:
            import pymupdf
        except Exception:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": list(range(1, page_count + 1)),
            }

        ocr_service = OCRService()
        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))

        def _block_sort_key(bbox: List[float]) -> tuple[float, float]:
            try:
                x0, y0, _, _ = [float(v) for v in bbox]
                return (y0, x0)
            except Exception:
                return (0.0, 0.0)

        def collect_page_blocks(page) -> List[Dict[str, Any]]:
            d = page.get_text("dict") or {}
            blocks = d.get("blocks") or []
            out: List[Dict[str, Any]] = []
            for blk in blocks:
                if not isinstance(blk, dict):
                    continue
                btype = int(blk.get("type") or 0)
                bbox = blk.get("bbox") or [0, 0, 0, 0]
                if len(bbox) != 4:
                    bbox = [0, 0, 0, 0]
                if btype == 0:
                    texts: List[str] = []
                    for ln in blk.get("lines") or []:
                        for sp in ln.get("spans") or []:
                            tx = str(sp.get("text") or "")
                            if tx.strip():
                                texts.append(tx)
                    txt = re.sub(r"\s+", " ", "".join(texts)).strip()
                    if txt:
                        out.append({"kind": "text", "bbox": bbox, "text": txt})
                elif btype == 1:
                    img_bytes = blk.get("image")
                    if isinstance(img_bytes, (bytes, bytearray)) and img_bytes:
                        out.append(
                            {"kind": "image", "bbox": bbox, "image": bytes(img_bytes)}
                        )
            out.sort(key=lambda item: _block_sort_key(item.get("bbox") or [0, 0, 0, 0]))
            return out

        def should_ocr_image_block(page_rect, bbox) -> bool:
            try:
                x0, y0, x1, y1 = [float(v) for v in bbox]
            except Exception:
                return False
            w = max(0.0, x1 - x0)
            h = max(0.0, y1 - y0)
            if w < float(OCR_MIN_IMAGE_SIDE_PX) or h < float(OCR_MIN_IMAGE_SIDE_PX):
                return False
            page_area = max(1.0, float(page_rect.width) * float(page_rect.height))
            ratio = (w * h) / page_area
            return ratio >= float(OCR_MIN_IMAGE_AREA_RATIO)

        page_inputs: List[Dict[str, Any]] = []
        doc = pymupdf.open(str(file_path))
        try:
            for page_num in range(1, min(page_count, len(doc)) + 1):
                page = doc[page_num - 1]
                blocks = collect_page_blocks(page)
                page_rect = page.rect
                ordered_blocks: List[Dict[str, Any]] = []
                for blk in blocks:
                    if blk.get("kind") == "text":
                        ordered_blocks.append(
                            {
                                "kind": "text",
                                "bbox": blk.get("bbox") or [0, 0, 0, 0],
                                "text": str(blk.get("text") or ""),
                            }
                        )
                        continue
                    if blk.get("kind") != "image":
                        continue
                    bbox = blk.get("bbox") or [0, 0, 0, 0]
                    should_ocr = should_ocr_image_block(page_rect, bbox)
                    image_b64 = ""
                    if should_ocr:
                        img_bytes = blk.get("image") or b""
                        if img_bytes:
                            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    ordered_blocks.append(
                        {
                            "kind": "image",
                            "bbox": bbox,
                            "ocr_target": should_ocr and bool(image_b64),
                            "image_b64": image_b64,
                        }
                    )
                page_inputs.append(
                    {
                        "page_num": page_num,
                        "ordered_blocks": ordered_blocks,
                    }
                )
        finally:
            doc.close()

        async def parse_page(page_input: Dict[str, Any]) -> Dict[str, Any]:
            page_num = int(page_input.get("page_num") or 0)
            ordered_blocks = list(page_input.get("ordered_blocks") or [])
            merged_text_parts: List[str] = []
            image_targets = 0
            image_ocr_hits = 0

            for blk in ordered_blocks:
                kind = blk.get("kind")
                if kind == "text":
                    tx = str(blk.get("text") or "")
                    if tx.strip():
                        merged_text_parts.append(tx)
                    continue
                if kind != "image":
                    continue
                if not bool(blk.get("ocr_target")):
                    continue

                image_targets += 1
                image_b64 = str(blk.get("image_b64") or "")
                if not image_b64:
                    continue
                async with sem:
                    r = await ocr_service.ocr_image_base64(image_b64, page_num)
                if r.ok and r.text:
                    merged_text_parts.append(r.text)
                    image_ocr_hits += 1

            merged_text = self._normalize_page_text_for_ocr(
                "\n".join(merged_text_parts)
            )
            return {
                "page_num": page_num,
                "text": merged_text,
                "ok": bool(image_ocr_hits > 0 or merged_text),
                "ocr_image_targets": image_targets,
                "ocr_image_hits": image_ocr_hits,
                "error": "" if merged_text else "no_image_block_ocr_text",
            }

        rows = await asyncio.gather(*(parse_page(x) for x in page_inputs))
        rows = sorted(rows, key=lambda x: int(x.get("page_num") or 0))

        success = sum(1 for x in rows if x.get("text"))
        missing = [int(x["page_num"]) for x in rows if not x.get("text")]
        return {
            "ocr_pages": rows,
            "ocr_coverage": (success / page_count) if page_count > 0 else 0.0,
            "ocr_missing_pages": missing,
        }

    @staticmethod
    def _build_page_list_with_ocr_overlay(
        base_page_list: List[Any], ocr_pages: List[Dict[str, Any]], model: str
    ) -> List[Any]:
        try:
            import litellm
        except Exception:
            litellm = None

        ocr_map = {
            int(item.get("page_num") or 0): str(item.get("text") or "")
            for item in (ocr_pages or [])
            if int(item.get("page_num") or 0) > 0
        }
        merged: List[Any] = []
        for idx, page in enumerate(base_page_list, start=1):
            original_text = ""
            if isinstance(page, (list, tuple)) and len(page) >= 1:
                original_text = str(page[0] or "")

            text = str(ocr_map.get(idx) or original_text)
            if litellm is not None:
                try:
                    token_length = litellm.token_counter(model=model, text=text)
                except Exception:
                    token_length = len(text) // 4
            else:
                token_length = len(text) // 4
            merged.append((text, token_length))
        return merged

    @staticmethod
    def _build_toc_outline_text(
        structure_data: Any, max_titles: int = PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES
    ) -> str:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return ""

        lines: List[str] = []
        for node in nodes[:max_titles]:
            title = PageIndexService._normalize_title(node.get("title") or "")
            if not title or PageIndexService._is_noise_title(title):
                continue
            level = str(node.get("node_id") or "").count(".") + 1
            indent = "  " * max(0, level - 1)
            lines.append(f"{indent}- {title}")
        return "\n".join(lines)

    async def _generate_fast_light_doc_summary(
        self, structure_data: Any, file_path: Path
    ) -> str:
        if not PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED:
            print(
                f"[FAST_SUMMARY] skipped disabled doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')}"
            )
            return ""

        toc_outline = self._build_toc_outline_text(structure_data)
        if not toc_outline:
            print(f"[FAST_SUMMARY] skipped empty_toc doc={file_path.name}")
            return ""

        prompt = FAST_DOC_LIGHT_SUMMARY_PROMPT.format(
            doc_name=file_path.name,
            file_type=file_path.suffix.lower(),
            toc_outline=toc_outline,
        )
        start_time = time.perf_counter()
        deadline = start_time + PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS
        attempt = 0

        from app.core.llm import async_chat_completion

        while True:
            attempt += 1
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[FAST_SUMMARY] status=timeout doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt - 1} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                )
                return ""

            try:
                response = await asyncio.wait_for(
                    async_chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.opt.model,
                        temperature=0,
                        max_tokens=120,
                    ),
                    timeout=remaining,
                )
                summary = (response.choices[0].message.content or "").strip().strip('"')
                summary = summary[:180]
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                if summary:
                    print(
                        f"[FAST_SUMMARY] status=ok doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                    )
                    return summary

                print(
                    f"[FAST_SUMMARY] status=empty_output doc={file_path.name} attempt={attempt} remaining_s={round(max(0.0, deadline - time.perf_counter()), 2)}"
                )
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[FAST_SUMMARY] status=retry_error doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} attempt={attempt} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms} error_type={type(e).__name__} error={e}"
                )

            sleep_time = min(0.8, max(0.1, deadline - time.perf_counter()))
            if sleep_time <= 0:
                continue
            await asyncio.sleep(sleep_time)

    @staticmethod
    def _normalize_title(title: str) -> str:
        t = re.sub(r"\s+", " ", (title or "").strip())
        if not t:
            return ""

        watermark_fragments = [
            "请务必阅读正文之后的免责声明及其项下所有内容",
            "获取更多维度报告数据，请访问亿欧网",
            "获取更多维度报告数据 ，请访问亿欧网",
            "www.iyiou.com",
        ]
        for fragment in watermark_fragments:
            t = t.replace(fragment, " ")

        t = re.sub(r"^[◆•●\-*u\s]+", "", t)
        t = re.sub(r"(?i)^chapter\s*\d+[a-zA-Z]*[\s:：.\-]*", "", t)
        t = re.sub(r"^第\s*\d+\s*[章节部分卷篇]\s*", "", t)
        t = re.sub(r"^\d+(?:\.\d+)*[\s:：.\-]*", "", t)
        t = re.sub(r"\s+", " ", t).strip(" -:：|·")
        return t

    @staticmethod
    def _is_common_readable_char(ch: str) -> bool:
        if "\u4e00" <= ch <= "\u9fff":
            return True
        if ch.isascii() and (
            ch.isalnum() or ch in " \n\t.,:;!?()[]{}<>-_/\\'\"%&+*#@$"
        ):
            return True
        if ch in "·—：，。、《》；（）【】“”‘’、":
            return True
        return False

    @staticmethod
    def _iter_nodes_mutable(structure_data: Any):
        if isinstance(structure_data, list):
            for node in structure_data:
                if isinstance(node, dict):
                    yield node
                    children = node.get("nodes")
                    if isinstance(children, list):
                        yield from PageIndexService._iter_nodes_mutable(children)
        elif isinstance(structure_data, dict):
            yield structure_data
            children = structure_data.get("nodes")
            if isinstance(children, list):
                yield from PageIndexService._iter_nodes_mutable(children)

    @staticmethod
    def _is_noise_title(title: str) -> bool:
        stripped = (title or "").strip()
        if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", stripped):
            return True
        t = PageIndexService._normalize_title(title)
        if not t:
            return True
        if len(t) <= 1:
            return True
        if re.fullmatch(r"\d+", t):
            return True
        if re.fullmatch(r"\d{4}\.\d+", t):
            return True
        if re.fullmatch(r"\d{4}[./-]\d{1,2}([./-]\d{1,2})?", t):
            return True
        if re.fullmatch(r"\d{4}年\d{1,2}月(\d{1,2}日)?", t):
            return True
        if re.fullmatch(r"(?i)chapter\s*\d+", t):
            return True
        if re.fullmatch(r"(?i)(preface|contents|introduction|appendix)", t):
            return True
        if re.fullmatch(r"[A-Z]{2,5}", t):
            return True
        if re.fullmatch(r"[A-Za-z]{1,5}\d*", t):
            return True
        if re.fullmatch(r"[A-Za-z]{1,6}", t):
            return True

        noise_keywords = ["免责声明", "风险提示", "分析师", "邮箱", "电话", "版权", "www.", "@"]
        if any(k in t for k in noise_keywords):
            return True

        readable = sum(1 for ch in t if PageIndexService._is_common_readable_char(ch))
        if readable / max(1, len(t)) < 0.72:
            return True
        return False
    @staticmethod
    def _extract_heading_from_text(text: str) -> str:
        if not text:
            return ""
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        for line in lines[:40]:
            normalized = PageIndexService._normalize_title(line)
            if len(normalized) < 3 or len(normalized) > 60:
                continue
            if PageIndexService._is_noise_title(normalized):
                continue
            return normalized
        return ""

    @staticmethod
    def _compute_structure_quality(structure_data: Any) -> Dict[str, Any]:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return {
                "score": 0.0,
                "node_count": 0,
                "bad_ratio": 1.0,
                "max_depth": 0,
            }

        titles = [
            PageIndexService._normalize_title(n.get("title") or "") for n in nodes
        ]
        bad = sum(1 for t in titles if PageIndexService._is_noise_title(t))
        bad_ratio = bad / len(titles)
        short_ratio = sum(1 for t in titles if len(t) <= 4) / len(titles)
        unique_ratio = len({t for t in titles if t}) / len(titles)
        depths = [str(n.get("node_id") or "").count(".") + 1 for n in nodes]
        max_depth = max(depths) if depths else 0

        score = 1.0 - bad_ratio
        if len(nodes) <= 1:
            score -= 0.35
        if max_depth <= 1 and len(nodes) >= 6:
            score -= 0.15
        if short_ratio > 0.4 and len(nodes) >= 4:
            score -= 0.12
        if unique_ratio < 0.6 and len(nodes) >= 5:
            score -= 0.1
        score = max(0.0, min(1.0, score))

        return {
            "score": score,
            "node_count": len(nodes),
            "bad_ratio": bad_ratio,
            "max_depth": max_depth,
            "short_ratio": short_ratio,
            "unique_ratio": unique_ratio,
        }

    @staticmethod
    def _repair_structure_titles(structure_data: Any) -> Any:
        for node in PageIndexService._iter_nodes_mutable(structure_data):
            title = PageIndexService._normalize_title(node.get("title") or "")
            if title != (node.get("title") or ""):
                node["title"] = title
            if not title or PageIndexService._is_noise_title(title):
                candidate = PageIndexService._extract_heading_from_text(
                    node.get("text", "")
                )
                if candidate:
                    node["title"] = candidate
                continue

            if re.fullmatch(r"(?i)chapter\s*\d+", title) or re.fullmatch(
                r"\d{4}\.\d+", title
            ):
                candidate = PageIndexService._extract_heading_from_text(
                    node.get("text", "")
                )
                if candidate and candidate != title:
                    node["title"] = candidate

        def filter_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = []
            seen_titles = set()
            for n in nodes:
                children = n.get("nodes")
                if isinstance(children, list):
                    n["nodes"] = filter_nodes(children)
                title = PageIndexService._normalize_title(n.get("title") or "")
                n["title"] = title
                title_key = title.lower()
                if (
                    title
                    and not PageIndexService._is_noise_title(title)
                    and title_key not in seen_titles
                ):
                    seen_titles.add(title_key)
                    out.append(n)
            return out

        if isinstance(structure_data, list):
            return filter_nodes(structure_data)
        if isinstance(structure_data, dict):
            title = PageIndexService._normalize_title(structure_data.get("title") or "")
            if not title or PageIndexService._is_noise_title(title):
                candidate = PageIndexService._extract_heading_from_text(
                    structure_data.get("text", "")
                )
                if candidate:
                    structure_data["title"] = candidate
            return structure_data
        return structure_data

    @staticmethod
    def _build_segment_fallback_toc(page_count: Optional[int]) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []
        segment = 8 if total >= 40 else 5
        nodes = []
        idx = 1
        for start in range(1, total + 1, segment):
            end = min(total, start + segment - 1)
            nodes.append(
                {
                    "node_id": f"{idx:04d}",
                    "title": f"Part {idx} (pages {start}-{end})",
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
            idx += 1
        return nodes

    @staticmethod
    def _extract_llm_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts).strip()
        return ""

    async def _generate_fast_visual_page_summaries(
        self,
        file_path: Path,
        page_numbers: List[int],
        max_attempts_override: Optional[int] = None,
        per_page_timeout_override: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not page_numbers:
            return []

        from app.core.llm import pdf_page_to_base64
        from app.services.model_gateway import ModelGateway

        gateway = ModelGateway()
        max_concurrency = max(1, int(VISUAL_VLM_MAX_CONCURRENCY))
        max_attempts = max(
            1,
            int(
                max_attempts_override
                if max_attempts_override is not None
                else VISUAL_VLM_PAGE_MAX_ATTEMPTS
            ),
        )
        per_page_timeout = max(
            5,
            int(
                per_page_timeout_override
                if per_page_timeout_override is not None
                else VISUAL_PAGE_TIMEOUT_SECONDS
            ),
        )
        semaphore = asyncio.Semaphore(max_concurrency)

        async def summarize_one(page_num: int) -> Optional[Dict[str, Any]]:
            async with semaphore:
                image_b64 = pdf_page_to_base64(str(file_path), page_num)
                if not image_b64:
                    return None

                prompt = (
                    "Read this PDF page image and write one concise searchable summary. "
                    "Keep the topic, key terms, chart/table conclusions, and do not invent facts. "
                    "Output no more than 60 Chinese characters when possible."
                )
                image_url = f"data:image/jpeg;base64,{image_b64}"
                for _ in range(max_attempts):
                    try:
                        response = await asyncio.wait_for(
                            gateway.vision_enrich_pdf_page(prompt, image_url),
                            timeout=per_page_timeout,
                        )
                        content = self._extract_llm_text_content(
                            response.choices[0].message.content
                        )
                        content = re.sub(r"\s+", " ", content).strip().strip('"')
                        if content:
                            return {"page_num": page_num, "summary": content[:120]}
                    except Exception:
                        continue
                return None

        unique_pages = sorted({int(p) for p in page_numbers if int(p) > 0})
        batch_size = max(2, max_concurrency * 2)
        results: List[Optional[Dict[str, Any]]] = []
        for i in range(0, len(unique_pages), batch_size):
            batch = unique_pages[i : i + batch_size]
            batch_results = await asyncio.gather(*(summarize_one(p) for p in batch))
            results.extend(batch_results)

        summaries = [r for r in results if r]
        summaries.sort(key=lambda x: x["page_num"])
        return summaries

    @staticmethod
    def _inject_visual_summaries_into_structure(
        structure_data: Any, visual_summaries: List[Dict[str, Any]]
    ) -> None:
        if not visual_summaries:
            return

        nodes = structure_to_list(structure_data)
        if not nodes:
            return

        def _safe_int(v: Any) -> Optional[int]:
            try:
                return int(v)
            except Exception:
                return None

        for item in visual_summaries:
            page_num = _safe_int(item.get("page_num"))
            summary = (item.get("summary") or "").strip()
            if not page_num or not summary:
                continue

            candidates = []
            for n in nodes:
                start = _safe_int(n.get("start_index"))
                end = _safe_int(n.get("end_index"))
                if start is None or end is None:
                    continue
                if start <= page_num <= end:
                    candidates.append((end - start, n))

            if not candidates:
                continue

            _, target = min(candidates, key=lambda x: x[0])
            marker = f"[visual summary p.{page_num}] {summary}"

            text = (target.get("text") or "").strip()
            if marker not in text:
                target["text"] = (text + "\n" + marker).strip()

            node_summary = (target.get("summary") or "").strip()
            if not node_summary:
                target["summary"] = summary
            elif summary not in node_summary:
                target["summary"] = (node_summary + "; " + summary)[:260]

    @staticmethod
    def _looks_like_segment_fallback_toc(structure_data: Any) -> bool:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return False
        sample = nodes[: min(6, len(nodes))]
        fallback_hits = 0
        for node in sample:
            title = (node.get("title") or "").strip()
            if re.match(r"^Part\s+\d+\s+\(pages\s+\d+-\d+\)$", title) or re.match(
                r"^Part\s+\d+\s*:", title
            ):
                fallback_hits += 1
        return fallback_hits >= max(2, len(sample) - 1)

    @staticmethod
    def _summary_to_toc_title(summary: str, max_len: int = 30) -> str:
        text = re.sub(r"\s+", " ", (summary or "").strip())
        if not text:
            return ""

        text = re.sub(
            r"^(该文档|本页|本案例|该案例|该报告|案例展示|文档显示|内容展示)[：:，,\s]*",
            "",
            text,
        )
        first_clause = re.split(r"[。；;]", text, maxsplit=1)[0]
        first_clause = first_clause.strip("，,:：。;； ")
        if len(first_clause) < 8:
            first_clause = text[: max_len + 8]
        if len(first_clause) > max_len:
            first_clause = first_clause[:max_len].rstrip()
        return first_clause

    @staticmethod
    def _extract_title_keywords(title: str) -> set[str]:
        t = (title or "").lower().strip()
        if not t:
            return set()
        tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{1,3}", t)
        return {x for x in tokens if len(x.strip()) >= 1}

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        ka = PageIndexService._extract_title_keywords(a)
        kb = PageIndexService._extract_title_keywords(b)
        if not ka or not kb:
            return 0.0
        inter = len(ka & kb)
        union = len(ka | kb)
        if union == 0:
            return 0.0
        return inter / union

    @staticmethod
    def _is_semantic_toc_title(title: str) -> bool:
        t = (title or "").strip()
        if not t:
            return False
        m = re.match(r"^Part\s+\d+\s*:\s*(.+)$", t)
        if m:
            payload = m.group(1).strip()
            return len(payload) >= 8 and not PageIndexService._is_noise_title(payload)
        return len(t) >= 6 and not PageIndexService._is_noise_title(t)

    @staticmethod
    def _max_toc_span_for_page_count(page_count: int) -> int:
        if page_count <= 60:
            return 4
        if page_count <= 120:
            return 6
        return 8

    @staticmethod
    def _densify_toc_by_max_span(
        toc_nodes: List[Dict[str, Any]], page_count: int
    ) -> List[Dict[str, Any]]:
        if not toc_nodes:
            return toc_nodes

        max_span = PageIndexService._max_toc_span_for_page_count(page_count)
        densified: List[Dict[str, Any]] = []
        for node in toc_nodes:
            start = int(node.get("start_index") or 0)
            end = int(node.get("end_index") or 0)
            if start <= 0 or end <= 0 or end < start:
                continue
            span = end - start + 1
            title = (node.get("title") or "").strip()
            summary = (node.get("summary") or title or "").strip()[:220]

            if span <= max_span:
                normalized = dict(node)
                normalized["summary"] = summary
                normalized["nodes"] = []
                if title and f"pages {start}-{end}" not in title:
                    normalized["title"] = f"{title} (pages {start}-{end})"
                densified.append(normalized)
                continue

            seg_idx = 1
            for seg_start in range(start, end + 1, max_span):
                seg_end = min(end, seg_start + max_span - 1)
                seg_title = title
                if title:
                    seg_title = f"{title} (pages {seg_start}-{seg_end})"
                else:
                    seg_title = f"Chapter segment (pages {seg_start}-{seg_end})"
                densified.append(
                    {
                        "title": seg_title,
                        "summary": summary,
                        "start_index": seg_start,
                        "end_index": seg_end,
                        "nodes": [],
                    }
                )
                seg_idx += 1

        for idx, node in enumerate(densified, start=1):
            node["node_id"] = f"{idx:04d}"
        return densified

    @staticmethod
    def _ensure_structure_node_summaries(structure_data: Any) -> None:
        for node in structure_to_list(structure_data):
            summary = (node.get("summary") or "").strip()
            if summary:
                continue
            title = (node.get("title") or "").strip()
            text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
            fallback = title or text[:120]
            if fallback:
                node["summary"] = fallback[:220]

    @staticmethod
    def _merge_visual_summaries_for_section(summaries: List[str]) -> str:
        cleaned: List[str] = []
        seen = set()
        for item in summaries:
            s = re.sub(r"\s+", " ", str(item or "")).strip().strip("銆傦紱; ")
            if not s:
                continue
            key = s[:80]
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0][:220]
        merged = "; ".join(cleaned[:3])
        return merged[:260]

    @staticmethod
    def _enrich_toc_nodes_with_visual_evidence(
        toc_nodes: List[Dict[str, Any]], visual_summaries: List[Dict[str, Any]]
    ) -> None:
        if not toc_nodes:
            return

        page_summary: Dict[int, str] = {}
        for item in visual_summaries or []:
            try:
                p = int(item.get("page_num") or 0)
            except Exception:
                continue
            s = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if p > 0 and s and p not in page_summary:
                page_summary[p] = s

        for node in toc_nodes:
            try:
                start = int(node.get("start_index") or 0)
                end = int(node.get("end_index") or 0)
            except Exception:
                start, end = 0, 0

            evidence_pages: List[int] = []
            evidence_summaries: List[str] = []
            if start > 0 and end >= start:
                for p in range(start, end + 1):
                    if p in page_summary:
                        evidence_pages.append(p)
                        evidence_summaries.append(page_summary[p])

            section_summary = PageIndexService._merge_visual_summaries_for_section(
                evidence_summaries
            )
            if section_summary:
                node["summary"] = section_summary
                node["summary_source"] = "vision_segment"
            else:
                fallback = (node.get("summary") or "").strip() or (
                    node.get("title") or ""
                ).strip()
                if fallback:
                    node["summary"] = fallback[:260]
                    node["summary_source"] = "fallback"

            node["evidence_pages"] = evidence_pages

    @staticmethod
    def _collect_node_evidence(
        node: Dict[str, Any],
        page_summary: Dict[int, str],
        page_count: int,
    ) -> tuple[List[int], List[str]]:
        try:
            start = int(node.get("start_index") or 0)
            end = int(node.get("end_index") or 0)
        except Exception:
            start, end = 0, 0

        if start <= 0 or end < start:
            return [], []

        pages = [p for p in range(start, end + 1) if p in page_summary]

        min_evidence = 3 if (end - start + 1) <= 2 else 2
        if len(pages) < min_evidence:
            for delta in (1, 2, 3):
                left = start - delta
                right = end + delta
                if left >= 1 and left in page_summary and left not in pages:
                    pages.append(left)
                if right <= page_count and right in page_summary and right not in pages:
                    pages.append(right)
                if len(pages) >= min_evidence:
                    break

        pages = sorted(set(pages))
        summaries = [page_summary[p] for p in pages if p in page_summary]
        return pages, summaries

    @staticmethod
    def _fallback_node_summary(
        node: Dict[str, Any], evidence_summaries: List[str]
    ) -> str:
        merged = PageIndexService._merge_visual_summaries_for_section(
            evidence_summaries
        )
        if merged:
            return merged[:260]
        title = (node.get("title") or "").strip()
        text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
        fallback = title or text[:180]
        return fallback[:260]

    async def _rewrite_balanced_node_summaries(
        self,
        structure_data: Any,
        visual_summaries: List[Dict[str, Any]],
        page_count: int,
    ) -> None:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return

        from app.core.llm import async_chat_completion

        page_summary: Dict[int, str] = {}
        for item in visual_summaries or []:
            try:
                p = int(item.get("page_num") or 0)
            except Exception:
                continue
            s = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if p > 0 and s and p not in page_summary:
                page_summary[p] = s

        sem = asyncio.Semaphore(8)

        async def rewrite_one(node: Dict[str, Any]) -> None:
            evidence_pages, evidence_summaries = self._collect_node_evidence(
                node=node,
                page_summary=page_summary,
                page_count=page_count,
            )
            node["evidence_pages"] = evidence_pages

            title = (node.get("title") or "").strip()
            start = node.get("start_index")
            end = node.get("end_index")
            node_text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()[:500]

            evidence_block = "\n".join(
                f"- p.{p}: {page_summary.get(p, '')}" for p in evidence_pages[:6]
            )
            if not evidence_block:
                evidence_block = "- no visual evidence"

            prompt = (
                "You are a document summarization assistant. Generate a node-level summary "
                "for one chapter or page range based only on the given evidence.\n"
                f"Title: {title or 'Untitled section'}\n"
                f"Page range: {start}-{end}\n"
                f"Text evidence: {node_text or 'none'}\n"
                "Visual evidence:\n"
                f"{evidence_block}\n\n"
                "Requirements:\n"
                "1. Output 1-2 concise Chinese sentences, 40-160 characters when possible.\n"
                "2. Summarize the whole page range, not a single page.\n"
                "3. Do not invent facts. Output only the summary text."
            )

            summary = ""
            try:
                async with sem:
                    resp = await asyncio.wait_for(
                        async_chat_completion(
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.1,
                            model=self.opt.model,
                        ),
                        timeout=8,
                    )
                summary = self._extract_llm_text_content(
                    resp.choices[0].message.content
                )
                summary = re.sub(r"\s+", " ", summary).strip().strip('"')
                if summary == title or "本页" in summary:
                    summary = ""
            except Exception:
                summary = ""

            if not summary:
                summary = self._fallback_node_summary(node, evidence_summaries)

            node["summary"] = summary[:260]
            node["summary_source"] = "llm_node"

        await asyncio.gather(*(rewrite_one(node) for node in nodes))

    @staticmethod
    def _max_visual_gap(page_count: int, visual_summaries: List[Dict[str, Any]]) -> int:
        if page_count <= 0:
            return 0
        pages = sorted(
            {
                int(item.get("page_num"))
                for item in visual_summaries
                if item.get("page_num")
            }
        )
        if not pages:
            return page_count

        max_gap = max(0, pages[0] - 1, page_count - pages[-1])
        for i in range(len(pages) - 1):
            gap = pages[i + 1] - pages[i] - 1
            if gap > max_gap:
                max_gap = gap
        return max_gap

    @staticmethod
    def _build_visual_recovery_targets(
        page_count: int,
        existing_pages: set[int],
        gate_reason: Optional[str],
        target_ratio: float,
        max_gap_target: int = 2,
    ) -> List[int]:
        if page_count <= 0:
            return []

        needed = max(1, int(round(page_count * target_ratio)))
        targets: set[int] = set()

        sample_count = min(page_count, max(needed, 12))
        if sample_count <= 1:
            targets.add(page_count)
        else:
            for i in range(sample_count):
                p = int(round(1 + i * (page_count - 1) / (sample_count - 1)))
                if p not in existing_pages:
                    targets.add(p)

        # Fill large gaps first using midpoint and quartiles.
        all_pages = sorted(existing_pages)
        boundaries = [0] + all_pages + [page_count + 1]
        for i in range(len(boundaries) - 1):
            left = boundaries[i]
            right = boundaries[i + 1]
            gap = right - left - 1
            if gap <= max(1, int(max_gap_target)):
                continue
            candidates = [
                left + (gap // 2),
                left + (gap // 4),
                left + ((gap * 3) // 4),
            ]
            for p in candidates:
                if 1 <= p <= page_count and p not in existing_pages:
                    targets.add(p)

        # Strengthen tail sampling.
        tail_start = max(1, int(page_count * 0.7))
        for p in range(tail_start, page_count + 1, 2):
            if p not in existing_pages:
                targets.add(p)

        # Strengthen front sampling when the structure is sparse.
        if gate_reason in {
            "node_sparse",
            "visual_summary_sparse",
            "coverage_gap_high",
            "coverage_gap_strict",
            "visual_summary_insufficient",
            "node_evidence_sparse",
        }:
            head_end = min(page_count, max(8, int(page_count * 0.25)))
            for p in range(1, head_end + 1, 2):
                if p not in existing_pages:
                    targets.add(p)

        return sorted(targets)

    @staticmethod
    def _build_vision_first_toc_from_visual_summaries(
        page_count: Optional[int], visual_summaries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []

        source = sorted(
            [s for s in visual_summaries if s.get("page_num") and s.get("summary")],
            key=lambda x: int(x["page_num"]),
        )
        if not source:
            return []

        anchors: List[Dict[str, Any]] = []
        prev_title = ""
        for item in source:
            page_num = int(item["page_num"])
            raw_summary = str(item.get("summary") or "").strip()
            title = PageIndexService._summary_to_toc_title(raw_summary)
            if not title:
                continue
            if not anchors:
                anchors.append(
                    {"page_num": page_num, "title": title, "summary": raw_summary}
                )
                prev_title = title
                continue

            prev_page = int(anchors[-1]["page_num"])
            sim = PageIndexService._title_similarity(prev_title, title)
            has_signal_word = any(
                kw in title
                for kw in [
                    "案例",
                    "场景",
                    "系统",
                    "平台",
                    "应用",
                    "项目",
                    "治理",
                    "智能",
                    "模型",
                ]
            )
            if page_num - prev_page >= 2 or sim < 0.62 or has_signal_word:
                anchors.append(
                    {"page_num": page_num, "title": title, "summary": raw_summary}
                )
                prev_title = title

        # 绗簩杞細濡傛灉閿氱偣杩囧皯锛屾斁瀹界浉浼煎害闃堝€艰ˉ閿氱偣
        min_nodes = min(max(6, total // 8), 18)
        if len(anchors) < min_nodes:
            anchors = []
            prev_title = ""
            for item in source:
                page_num = int(item["page_num"])
                raw_summary = str(item.get("summary") or "").strip()
                title = PageIndexService._summary_to_toc_title(raw_summary)
                if not title:
                    continue
                if not anchors:
                    anchors.append(
                        {
                            "page_num": page_num,
                            "title": title,
                            "summary": raw_summary,
                        }
                    )
                    prev_title = title
                    continue
                sim = PageIndexService._title_similarity(prev_title, title)
                if sim < 0.78:
                    anchors.append(
                        {
                            "page_num": page_num,
                            "title": title,
                            "summary": raw_summary,
                        }
                    )
                    prev_title = title

        # 鎺у埗鑺傜偣涓婇檺锛岄伩鍏嶇洰褰曡繃瀵嗭紙淇濈暀鏂囨湯閿氱偣锛岄槻姝㈠熬閮ㄥ唴瀹逛涪澶憋級
        max_nodes = 80 if total <= 80 else 60
        if len(anchors) > max_nodes:
            if max_nodes <= 1:
                anchors = [anchors[-1]]
            else:
                n = len(anchors)
                sampled_indices = sorted(
                    {
                        int(round(i * (n - 1) / (max_nodes - 1)))
                        for i in range(max_nodes)
                    }
                )
                anchors = [anchors[i] for i in sampled_indices]

        if not anchors:
            return []

        nodes: List[Dict[str, Any]] = []
        for idx, anchor in enumerate(anchors):
            start = int(anchor["page_num"])
            end = (
                int(anchors[idx + 1]["page_num"]) - 1
                if idx < len(anchors) - 1
                else total
            )
            end = max(start, min(total, end))
            title = anchor["title"]
            if not PageIndexService._is_semantic_toc_title(title):
                title = f"Part {idx + 1}: {title}" if title else f"Part {idx + 1}"
            nodes.append(
                {
                    "node_id": f"{idx + 1:04d}",
                    "title": title,
                    "summary": str(anchor.get("summary") or title)[:220],
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
        return PageIndexService._densify_toc_by_max_span(nodes, total)

    @staticmethod
    def _vision_first_toc_quality_ok(
        toc_nodes: List[Dict[str, Any]], page_count: int
    ) -> bool:
        metrics = PageIndexService._compute_vision_toc_gate_metrics(
            toc_nodes=toc_nodes,
            page_count=page_count,
            # 鍏煎鏃ф祴璇曡涔夛細浠呰瘎浼扮粨鏋勮川閲忥紝涓嶅洜瑙嗚瑕嗙洊鐜囪鍚﹀喅
            visual_summaries=(
                [{"page_num": i + 1, "summary": "ok"} for i in range(page_count)]
                if page_count > 0
                else []
            ),
        )
        ok, _ = PageIndexService._evaluate_vision_toc_gate(metrics)
        return ok

    @staticmethod
    def _compute_vision_toc_gate_metrics(
        toc_nodes: List[Dict[str, Any]],
        page_count: int,
        visual_summaries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        q = PageIndexService._compute_structure_quality(toc_nodes)
        node_count = int(q.get("node_count") or 0)
        semantic_ratio = (
            sum(
                1
                for n in toc_nodes
                if PageIndexService._is_semantic_toc_title(n.get("title") or "")
            )
            / max(1, node_count)
            if node_count > 0
            else 0.0
        )
        last_end = int(toc_nodes[-1].get("end_index") or 0) if toc_nodes else 0
        coverage_ratio = (last_end / page_count) if page_count > 0 else 0.0

        tail_start = max(1, int(page_count * 0.7)) if page_count > 0 else 1
        tail_anchor_count = sum(
            1 for n in toc_nodes if int(n.get("start_index") or 0) >= tail_start
        )
        tail_anchor_ratio = (
            tail_anchor_count / max(1, node_count) if node_count > 0 else 0.0
        )

        visual_summary_ratio = (
            len(visual_summaries) / page_count if page_count > 0 else 0.0
        )

        max_gap_pages = PageIndexService._max_visual_gap(page_count, visual_summaries)
        adjacent_sims: List[float] = []
        for i in range(max(0, len(toc_nodes) - 1)):
            t1 = str(toc_nodes[i].get("title") or "")
            t2 = str(toc_nodes[i + 1].get("title") or "")
            adjacent_sims.append(PageIndexService._title_similarity(t1, t2))
        if adjacent_sims:
            ranked = sorted(adjacent_sims)
            p95_idx = int(round(0.95 * (len(ranked) - 1)))
            adjacent_title_similarity_p95 = ranked[p95_idx]
        else:
            adjacent_title_similarity_p95 = 0.0

        evidence_ok = 0
        for n in toc_nodes:
            start = int(n.get("start_index") or 0)
            end = int(n.get("end_index") or 0)
            span = (end - start + 1) if (start > 0 and end >= start) else 1
            min_evidence = 1 if span <= 2 else 2
            evidence_pages = n.get("evidence_pages") or []
            try:
                evidence_count = len([int(p) for p in evidence_pages])
            except Exception:
                evidence_count = 0
            if evidence_count >= min_evidence:
                evidence_ok += 1
        node_evidence_ratio = (
            evidence_ok / max(1, node_count) if node_count > 0 else 0.0
        )

        return {
            "node_count": node_count,
            "quality_score": float(q.get("score") or 0.0),
            "semantic_ratio": semantic_ratio,
            "coverage_ratio": coverage_ratio,
            "tail_anchor_ratio": tail_anchor_ratio,
            "tail_anchor_count": tail_anchor_count,
            "visual_summary_ratio": visual_summary_ratio,
            "max_gap_pages": max_gap_pages,
            "adjacent_title_similarity_p95": adjacent_title_similarity_p95,
            "node_evidence_ratio": node_evidence_ratio,
            "page_count": page_count,
        }

    @staticmethod
    def _evaluate_vision_toc_gate(metrics: Dict[str, Any]) -> tuple[bool, str]:
        node_count = int(metrics.get("node_count") or 0)
        quality_score = float(metrics.get("quality_score") or 0.0)
        semantic_ratio = float(metrics.get("semantic_ratio") or 0.0)
        coverage_ratio = float(metrics.get("coverage_ratio") or 0.0)
        tail_anchor_ratio = float(metrics.get("tail_anchor_ratio") or 0.0)
        visual_summary_ratio = float(metrics.get("visual_summary_ratio") or 0.0)
        max_gap_pages = int(metrics.get("max_gap_pages") or 0)
        adjacent_title_similarity_p95 = float(
            metrics.get("adjacent_title_similarity_p95") or 0.0
        )
        page_count = int(metrics.get("page_count") or 0)

        min_nodes = 4 if page_count <= 40 else 5
        if node_count < min_nodes:
            return False, "node_sparse"
        if quality_score < 0.45:
            return False, "quality_low"
        if semantic_ratio < 0.6:
            return False, "semantic_low"
        if coverage_ratio < 0.9:
            return False, "coverage_low"
        if page_count >= 24 and max_gap_pages > max(6, page_count // 5):
            return False, "coverage_gap_high"
        if page_count >= 24 and tail_anchor_ratio < 0.12:
            return False, "anchor_sparse_tail"
        if visual_summary_ratio < 0.12:
            return False, "visual_summary_sparse"
        if page_count >= 24 and adjacent_title_similarity_p95 > 0.92:
            return False, "title_redundant"
        return True, "ok"

    @staticmethod
    def _evaluate_vision_toc_gate_strict(metrics: Dict[str, Any]) -> tuple[bool, str]:
        ok, reason = PageIndexService._evaluate_vision_toc_gate(metrics)
        if not ok:
            return ok, reason

        visual_summary_ratio = float(metrics.get("visual_summary_ratio") or 0.0)
        max_gap_pages = int(metrics.get("max_gap_pages") or 0)
        node_evidence_ratio = float(metrics.get("node_evidence_ratio") or 0.0)

        if visual_summary_ratio < float(VISION_TOC_STRICT_TARGET_RATIO):
            return False, "visual_summary_insufficient"
        if max_gap_pages > int(VISION_TOC_STRICT_MAX_GAP_PAGES):
            return False, "coverage_gap_strict"
        if node_evidence_ratio < 0.9:
            return False, "node_evidence_sparse"
        return True, "ok"

    async def _repair_vision_tail_once(
        self,
        file_path: Path,
        page_count: int,
        visual_summaries: List[Dict[str, Any]],
        gate_reason: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if page_count <= 0:
            return visual_summaries

        target_ratio = float(VISION_TOC_STRICT_TARGET_RATIO)
        max_gap_target = int(VISION_TOC_STRICT_MAX_GAP_PAGES)
        max_rounds = max(1, int(VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS))
        merged = list(visual_summaries)

        for _ in range(max_rounds):
            existing_pages = {
                int(item.get("page_num")) for item in merged if item.get("page_num")
            }
            coverage_ratio = len(existing_pages) / max(1, page_count)
            max_gap_pages = self._max_visual_gap(page_count, merged)
            if coverage_ratio >= target_ratio and max_gap_pages <= max_gap_target:
                break

            target_pages = self._build_visual_recovery_targets(
                page_count=page_count,
                existing_pages=existing_pages,
                gate_reason=gate_reason,
                target_ratio=target_ratio,
                max_gap_target=max_gap_target,
            )
            if not target_pages:
                break

            extra = await self._generate_fast_visual_page_summaries(
                file_path,
                target_pages,
                max_attempts_override=max(3, int(VISUAL_VLM_PAGE_MAX_ATTEMPTS)),
                per_page_timeout_override=max(18, int(VISUAL_PAGE_TIMEOUT_SECONDS)),
            )
            if not extra:
                break

            before = len(existing_pages)
            for item in extra:
                p = int(item.get("page_num") or 0)
                if p > 0 and p not in existing_pages:
                    merged.append(item)
                    existing_pages.add(p)
            if len(existing_pages) == before:
                break

            merged.sort(key=lambda x: int(x["page_num"]))
        return merged

    @staticmethod
    def _vision_gate_reason_to_error(reason: str) -> str:
        mapping = {
            "coverage_low": "VISION_TOC_COVERAGE_LOW",
            "coverage_gap_high": "VISION_TOC_COVERAGE_LOW",
            "coverage_gap_strict": "VISION_TOC_COVERAGE_LOW",
            "anchor_sparse_tail": "VISION_TOC_ANCHOR_SPARSE_TAIL",
            "semantic_low": "VISION_TOC_EVIDENCE_MISMATCH",
            "visual_summary_sparse": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "visual_summary_insufficient": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "node_sparse": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "node_evidence_sparse": "VISION_TOC_EVIDENCE_MISMATCH",
            "title_redundant": "VISION_TOC_EVIDENCE_MISMATCH",
            "quality_low": "VISION_TOC_QUALITY_TOO_LOW",
        }
        return mapping.get(reason, "VISION_TOC_QUALITY_TOO_LOW")

    @staticmethod
    def _build_visual_fallback_toc(
        page_count: Optional[int], visual_summaries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []

        if not visual_summaries:
            return PageIndexService._build_segment_fallback_toc(total)

        sorted_summaries = sorted(
            [s for s in visual_summaries if s.get("page_num") and s.get("summary")],
            key=lambda x: int(x["page_num"]),
        )
        if not sorted_summaries:
            return PageIndexService._build_segment_fallback_toc(total)

        segment = 6 if total >= 36 else 4
        nodes: List[Dict[str, Any]] = []
        idx = 1
        for start in range(1, total + 1, segment):
            end = min(total, start + segment - 1)
            anchor = next(
                (
                    item
                    for item in sorted_summaries
                    if start <= int(item["page_num"]) <= end
                ),
                None,
            )
            anchor_text = ""
            if anchor:
                anchor_text = re.sub(
                    r"\s+", " ", str(anchor.get("summary") or "")
                ).strip()
            if anchor_text:
                title = f"Part {idx}: {anchor_text[:24]}"
            else:
                title = f"Part {idx} (pages {start}-{end})"

            nodes.append(
                {
                    "node_id": f"{idx:04d}",
                    "title": title,
                    "summary": (anchor_text or title)[:220],
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
            idx += 1
        return nodes

    async def _enhance_balanced_fallback_with_visual(
        self,
        result: Dict[str, Any],
        file_path: Path,
        pre_analysis: Dict[str, Any],
    ) -> None:
        if not self._looks_like_segment_fallback_toc(result.get("structure", result)):
            return
        if float(pre_analysis.get("unparseable_ratio") or 0.0) <= 0.5:
            return

        vlm_needed_pages = [
            int(p) for p in (pre_analysis.get("vlm_needed_pages") or [])
        ]
        if not vlm_needed_pages:
            return

        visual_summaries = await self._generate_fast_visual_page_summaries(
            file_path, vlm_needed_pages
        )
        if not visual_summaries:
            return

        result["visual_page_summaries"] = visual_summaries
        result["structure"] = self._build_visual_fallback_toc(
            result.get("page_count"), visual_summaries
        )

        q = self._compute_structure_quality(result.get("structure", []))
        tq = (
            result.get("toc_quality")
            if isinstance(result.get("toc_quality"), dict)
            else {}
        )
        tq["after"] = q
        tq["visual_enhanced"] = True
        result["toc_quality"] = tq

    @staticmethod
    def _score_text_quality(text: str) -> float:
        t = (text or "").strip()
        if not t:
            return 0.0

        length = len(t)
        readable = sum(1 for ch in t if PageIndexService._is_common_readable_char(ch))
        readable_ratio = readable / max(1, length)

        cjk_count = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        ascii_alpha = sum(1 for ch in t if ch.isascii() and ch.isalpha())
        alpha_count = cjk_count + ascii_alpha
        digit_count = sum(1 for ch in t if ch.isdigit())

        structure_signal = 0.0
        if re.search(r"第\s*\d+\s*[章节部分卷篇]", t):
            structure_signal += 0.12
        if re.search(r"\b\d+(?:\.\d+){1,3}\b", t):
            structure_signal += 0.08

        density = min(1.0, length / 280.0)
        alpha_ratio = alpha_count / max(1, length)
        digit_penalty = 0.2 if digit_count / max(1, length) > 0.35 else 0.0
        short_penalty = 0.2 if length < 24 else 0.0

        score = (
            0.42 * readable_ratio
            + 0.22 * alpha_ratio
            + 0.18 * density
            + structure_signal
            - digit_penalty
            - short_penalty
        )
        return max(0.0, min(1.0, score))

    @staticmethod
    def _extract_pdf_text_pypdf2(file_path: Path) -> List[str]:
        texts: List[str] = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    texts.append((page.extract_text() or "").strip())
                except Exception:
                    texts.append("")
        return texts

    @staticmethod
    def _extract_pdf_text_pymupdf(file_path: Path) -> tuple[List[str], List[bool]]:
        import pymupdf

        texts: List[str] = []
        has_images: List[bool] = []
        doc = pymupdf.open(str(file_path))
        try:
            for page in doc:
                texts.append((page.get_text("text") or "").strip())
                has_images.append(len(page.get_images(full=True)) > 0)
        finally:
            doc.close()
        return texts, has_images

    @staticmethod
    def _pre_analyze_pdf(file_path: Path) -> Dict[str, Any]:
        try:
            texts_pymupdf, has_images = PageIndexService._extract_pdf_text_pymupdf(
                file_path
            )
            texts_pypdf2 = PageIndexService._extract_pdf_text_pypdf2(file_path)
        except Exception:
            return {
                "page_count": 0,
                "unparseable_pages": 0,
                "unparseable_ratio": 0.0,
                "vlm_needed_pages": [],
                "preferred_parser": "PyPDF2",
                "parser_quality": {"PyPDF2": 0.0, "PyMuPDF": 0.0},
            }

        page_count = min(len(texts_pymupdf), len(texts_pypdf2))
        unparseable_pages = 0
        vlm_needed_pages: List[int] = []
        parser_scores = {"PyPDF2": 0.0, "PyMuPDF": 0.0}

        for idx in range(page_count):
            text_mu = texts_pymupdf[idx]
            text_py = texts_pypdf2[idx]
            score_mu = PageIndexService._score_text_quality(text_mu)
            score_py = PageIndexService._score_text_quality(text_py)
            parser_scores["PyMuPDF"] += score_mu
            parser_scores["PyPDF2"] += score_py

            best_score = score_mu if score_mu >= score_py else score_py
            parseable = best_score >= 0.42
            if not parseable:
                unparseable_pages += 1

            has_visual = has_images[idx] if idx < len(has_images) else False
            if has_visual or not parseable:
                vlm_needed_pages.append(idx + 1)

        if page_count > 0:
            parser_scores = {
                "PyPDF2": parser_scores["PyPDF2"] / page_count,
                "PyMuPDF": parser_scores["PyMuPDF"] / page_count,
            }

        preferred_parser = (
            "PyMuPDF"
            if parser_scores["PyMuPDF"] >= parser_scores["PyPDF2"]
            else "PyPDF2"
        )

        return {
            "page_count": page_count,
            "unparseable_pages": unparseable_pages,
            "unparseable_ratio": (unparseable_pages / page_count)
            if page_count
            else 0.0,
            "vlm_needed_pages": vlm_needed_pages,
            "preferred_parser": preferred_parser,
            "parser_quality": parser_scores,
            "image_pages": sum(1 for x in has_images[:page_count] if x),
        }

    @staticmethod
    def _decide_pdf_route(
        requested_mode: str, pre_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        requested = (requested_mode or "balanced").strip().lower()
        if requested not in {"smart", "fast", "balanced"}:
            requested = "balanced"

        execution_mode = "fast" if requested == "smart" else requested
        reasons: List[str] = []

        return {
            "requested_mode": requested,
            "execution_mode": execution_mode,
            "escalated_from_pre_analysis": execution_mode == "balanced"
            and requested == "smart",
            "escalated_from_fast_quality": False,
            "reasons": reasons,
        }

    @staticmethod
    def _should_escalate_fast_by_toc_quality(toc_quality_score: float) -> bool:
        try:
            score = float(toc_quality_score)
        except (TypeError, ValueError):
            score = 0.0
        return score < PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD

    @staticmethod
    def _flatten_structure_nodes(nodes: Any) -> List[Dict[str, Any]]:
        if not isinstance(nodes, list):
            return []
        out: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            out.append(node)
            out.extend(
                PageIndexService._flatten_structure_nodes(node.get("nodes") or [])
            )
        return out

    @staticmethod
    def _evaluate_fast_toc_readiness(result: Any) -> Dict[str, Any]:
        structure = result.get("structure") if isinstance(result, dict) else result
        nodes = PageIndexService._flatten_structure_nodes(structure)
        if not nodes:
            return {"ok": False, "reason": "empty_structure"}

        missing_ranges = 0
        invalid_ranges = 0
        max_end = 0
        for node in nodes:
            start = node.get("start_index")
            end = node.get("end_index")
            if not isinstance(start, int) or not isinstance(end, int):
                missing_ranges += 1
                continue
            if end < start:
                invalid_ranges += 1
            if end > max_end:
                max_end = end

        if missing_ranges > 0:
            return {
                "ok": False,
                "reason": f"missing_ranges={missing_ranges}",
                "missing_ranges": missing_ranges,
                "invalid_ranges": invalid_ranges,
            }
        if invalid_ranges > 0:
            return {
                "ok": False,
                "reason": f"invalid_ranges={invalid_ranges}",
                "missing_ranges": missing_ranges,
                "invalid_ranges": invalid_ranges,
            }

        page_count = (
            int(result.get("page_count") or 0) if isinstance(result, dict) else 0
        )
        if page_count > 0 and max_end < page_count:
            return {
                "ok": False,
                "reason": f"coverage_end_lt_page_count={max_end}/{page_count}",
                "max_end": max_end,
                "page_count": page_count,
            }

        return {
            "ok": True,
            "reason": "ok",
            "node_count": len(nodes),
            "max_end": max_end,
            "page_count": page_count,
        }

    @staticmethod
    def _vision_first_required(pre_analysis: Dict[str, Any]) -> bool:
        unparseable_pages = int(pre_analysis.get("unparseable_pages") or 0)
        unparseable_ratio = float(pre_analysis.get("unparseable_ratio") or 0.0)
        return unparseable_ratio >= 0.8 or unparseable_pages >= 60

    @staticmethod
    def _compute_pdf_text_health(
        file_path: Path, pre_analysis: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        pre = pre_analysis or PageIndexService._pre_analyze_pdf(file_path)
        total = int(pre.get("page_count") or 0)
        unparseable = int(pre.get("unparseable_pages") or 0)
        ratio = float(pre.get("unparseable_ratio") or 0.0)
        return {
            "total_pages": total,
            "empty_ratio": ratio,
            "short_ratio": ratio,
            "weird_ratio": ratio,
            "garbled_ratio": ratio,
            "unparseable_pages": unparseable,
            "unparseable_ratio": ratio,
        }

    @staticmethod
    def calculate_visual_coverage(page_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate visual coverage and downgrade reasons for one document."""
        visual_required_pages = 0
        visual_success_pages = 0
        consecutive_failures = 0
        downgrade_reasons: List[Dict[str, Any]] = []

        for index, page in enumerate(page_results, start=1):
            if not page.get("needs_visual", True):
                continue

            visual_required_pages += 1
            page_number = page.get("page", index)
            visual_success = bool(page.get("visual_success", False))
            parseable = page.get("parseable", True)

            processing_seconds = page.get("processing_seconds")
            try:
                processing_seconds = float(processing_seconds)
            except (TypeError, ValueError):
                processing_seconds = None

            timeout_hit = (
                processing_seconds is not None
                and processing_seconds > VISUAL_PAGE_TIMEOUT_SECONDS
            )
            failure = (not visual_success) or (not parseable) or timeout_hit

            if failure:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
                visual_success_pages += 1

            reason: Optional[Dict[str, Any]] = None
            if not parseable:
                reason = {"page": page_number, "code": "UNPARSEABLE_PAGE"}
            elif timeout_hit:
                reason = {
                    "page": page_number,
                    "code": "PAGE_TIMEOUT",
                    "processing_seconds": processing_seconds,
                    "threshold_seconds": VISUAL_PAGE_TIMEOUT_SECONDS,
                }
            elif failure and consecutive_failures >= VISUAL_MAX_CONSECUTIVE_FAIL_PAGES:
                reason = {
                    "page": page_number,
                    "code": "CONSECUTIVE_PAGE_FAILURES",
                    "consecutive_failures": consecutive_failures,
                    "threshold": VISUAL_MAX_CONSECUTIVE_FAIL_PAGES,
                }

            if reason is not None:
                downgrade_reasons.append(reason)

        if visual_required_pages == 0:
            visual_coverage = 1.0
            downgrade_rate = 0.0
        else:
            visual_coverage = visual_success_pages / visual_required_pages
            downgrade_rate = len(downgrade_reasons) / visual_required_pages

        return {
            "visual_required_pages": visual_required_pages,
            "visual_success_pages": visual_success_pages,
            "visual_coverage": visual_coverage,
            "downgraded": bool(downgrade_reasons),
            "downgraded_pages": len(downgrade_reasons),
            "daily_downgrade_rate": downgrade_rate,
            "downgrade_reasons": downgrade_reasons,
        }

    async def _extract_toc_visual(
        self,
        file_path: str,
        toc_pages: List[int],
        page_count: int,
        model: str,
    ) -> Optional[Dict]:
        """Extract TOC from rendered TOC page images using VLM."""
        try:
            from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json
            
            images = render_pages_to_images(file_path, [p - 1 for p in toc_pages])
            
            prompt = """You are analyzing rendered PDF TOC pages. Extract all catalog entries.
Requirements:
1. Keep the original title text.
2. Return physical PDF page numbers as physical_index and hierarchy as level.
3. Return JSON only.

Example:
{
  "toc_items": [
    {"title": "Chapter 1", "level": 1, "physical_index": 5},
    {"title": "1.1 Introduction", "level": 2, "physical_index": 6}
  ]
}"""
            
            raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=3000)
            result = parse_vlm_json(raw)
            
            if isinstance(result, dict) and "toc_items" in result:
                return result
            return None
            
        except Exception as e:
            print(f"[EXTRACT-VISUAL] Failed: {e}")
            return None

    async def _extract_toc_text(
        self,
        analysis: Dict,
        toc_pages: List[int],
        page_count: int,
        model: str,
    ) -> Optional[Dict]:
        """Extract TOC from TOC page text using LLM."""
        try:
            from app.core.llm import async_chat_completion
            
            page_texts = analysis.get("page_texts", [])
            toc_text = "\n".join([page_texts[p - 1] for p in toc_pages if p - 1 < len(page_texts)])
            
            prompt = f"""Extract catalog entries from the following TOC page text.

TOC text:
{toc_text[:3000]}

Requirements:
1. Keep original titles.
2. Return physical PDF page numbers as physical_index and hierarchy as level.
3. Return JSON only.

Example:
{{
  "toc_items": [
    {{"title": "Chapter 1", "level": 1, "physical_index": 5}},
    {{"title": "1.1 Introduction", "level": 2, "physical_index": 6}}
  ]
}}"""
            
            response = await async_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                model=model,
            )
            content = response.choices[0].message.content
            
            import json
            import re
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                if "toc_items" in result:
                    return result
            return None
            
        except Exception as e:
            print(f"[EXTRACT-TEXT] Failed: {e}")
            return None

    @staticmethod
    def _normalize_and_map_fallback_toc(
        fallback_result: Optional[Dict],
        page_count: int,
        toc_pages: List[int],
        ocr_text_map: Optional[Dict[int, str]] = None,
        dividers: Optional[List[int]] = None,
    ) -> Optional[Dict]:
        """Normalize legacy TOC fallback output before post-processing.

        Older VLM/text fallback prompts may put TOC logical page numbers in
        physical_index. The balanced mapper already knows how to detect and map
        that shape, so route fallback results through it before accepting them.
        """
        if not fallback_result or not fallback_result.get("toc_items"):
            return fallback_result

        from pageindex.balanced_toc import _map_toc_physical_pages

        last_toc_page = max(toc_pages) if toc_pages else 0
        first_content_page = last_toc_page + 1 if last_toc_page else 1

        _map_toc_physical_pages(
            fallback_result["toc_items"],
            page_count=page_count,
            first_content_page=first_content_page,
            last_toc_page=last_toc_page,
            ocr_text_map=ocr_text_map,
            dividers=dividers or [],
        )
        fallback_result["mapped"] = True
        fallback_result["mapping_source"] = "legacy_fallback_normalizer"
        return fallback_result

    @staticmethod
    def _sync_toc_context(
        analysis: Dict,
        toc_pages: Optional[List[int]],
        confidence: str = "known",
    ) -> None:
        """Store detected TOC pages in the shared analysis shape."""
        pages = [int(p) for p in (toc_pages or []) if isinstance(p, int) and p > 0]
        if not pages:
            return

        analysis["toc_pages"] = pages
        analysis["toc_page"] = {
            "has_toc_page": True,
            "pages": pages,
            "confidence": confidence,
        }

    @staticmethod
    def _try_text_heading_shortcut(
        analysis: Dict,
        balanced_result: Optional[Dict],
    ) -> Optional[Dict]:
        """Convert deterministic text heading extraction into new-architecture shape."""
        return PageIndexService._try_prevalidated_outline_shortcut(
            analysis,
            balanced_result,
            allowed_sources={"text_heading"},
        )

    @staticmethod
    def _try_prevalidated_outline_shortcut(
        analysis: Dict,
        outline_result: Optional[Dict],
        allowed_sources: Optional[set[str]] = None,
    ) -> Optional[Dict]:
        """Convert deterministic outline extraction into new-architecture shape."""
        sources = allowed_sources or {"text_heading", "slide_outline", "agenda_outline"}
        if not outline_result or outline_result.get("source") not in sources:
            return None
        items = outline_result.get("toc_items") or []
        if not items:
            return None

        source = outline_result.get("source")
        analysis["toc_frozen"] = True
        analysis["toc_frozen_source"] = source
        return {
            "items": items,
            "source": source,
            "mapped": bool(outline_result.get("mapped")),
            "semi_frozen": bool(outline_result.get("semi_frozen")),
            "prevalidated": True,
        }

    @staticmethod
    def _try_balanced_provider_shortcut(
        analysis: Dict,
        page_count: int,
    ) -> Optional[Dict]:
        """Run v4.2 providers and adapt a trusted skeleton to legacy result shape."""
        from pageindex.balanced_orchestrator import ProviderRegistry, build_balanced_state
        from pageindex.page_mapping_service import map_skeleton_pages
        from pageindex.providers.code_toc_provider import CodeTocProvider
        from pageindex.providers.deterministic_outline_provider import (
            default_agenda_outline_provider,
            default_slide_outline_provider,
        )
        from pageindex.providers.toc_page_provider import TocPageTextProvider

        registry = ProviderRegistry([
            CodeTocProvider(),
            TocPageTextProvider(),
            default_slide_outline_provider(),
            default_agenda_outline_provider(),
        ])
        state = build_balanced_state(analysis, registry)
        PageIndexService._sync_build_state_to_analysis(analysis, state)
        skeleton = state.get("skeleton")
        if not skeleton or not skeleton.get("skeleton_valid"):
            candidates = state.get("candidates") or []
            if not candidates:
                return None
            candidate = candidates[0]
            items = candidate.get("items") or []
            if not items:
                return None
            source = candidate.get("source") or "outline_candidate"
            analysis["toc_frozen"] = bool(candidate.get("top_level_frozen", candidate.get("semi_frozen", True)))
            analysis["toc_frozen_source"] = source
            analysis["top_level_frozen"] = analysis["toc_frozen"]
            analysis["allow_child_expansion"] = bool(candidate.get("allow_child_expansion", True))
            return {
                "items": items,
                "source": source,
                "mapped": candidate.get("mapping_strategy") == "existing",
                "semi_frozen": bool(candidate.get("semi_frozen", True)),
                "prevalidated": True,
                "balanced_state": state,
            }

        source = skeleton.get("source") or "toc_skeleton"
        mapping_strategy = "existing"
        mapped = None
        if skeleton.get("page_mapping_valid"):
            items = skeleton.get("items") or []
        else:
            mapped = map_skeleton_pages(
                skeleton,
                analysis.get("page_texts", []),
                page_count,
            )
            items = mapped.get("items") or []
            mapping_strategy = mapped.get("mapping_strategy") or "unknown"

        if not items:
            return None

        analysis["toc_frozen"] = True
        analysis["toc_frozen_source"] = source
        analysis["top_level_frozen"] = True
        analysis["allow_child_expansion"] = True
        return {
            "items": items,
            "source": source,
            "mapped": True,
            "mapping_strategy": mapping_strategy,
            "mapping_quality": mapped.get("mapping_quality") if mapped else 1.0,
            "prevalidated": True,
            "balanced_state": state,
        }

    @staticmethod
    def _sync_build_state_to_analysis(analysis: Dict, state: Dict) -> None:
        """Expose canonical build state while keeping legacy analysis aliases."""
        analysis["build_state"] = state
        analysis["top_level_frozen"] = bool(state.get("top_level_frozen"))
        analysis["allow_child_expansion"] = bool(state.get("allow_child_expansion", True))
        analysis["range_locked"] = bool(state.get("range_locked"))
        analysis["children_locked"] = bool(state.get("children_locked"))
        analysis["tree_complete"] = bool(state.get("tree_complete"))
        analysis["needs_repair"] = bool(state.get("needs_repair"))

    @staticmethod
    def _apply_balanced_result_state(analysis: Dict, balanced_result: Optional[Dict]) -> None:
        """Propagate trusted balanced extraction state to legacy post-processing."""
        if not balanced_result:
            return

        source = balanced_result.get("source") or "balanced"
        top_level_frozen = bool(
            balanced_result.get(
                "top_level_frozen",
                balanced_result.get("mapped")
                or balanced_result.get("semi_frozen")
                or source in {"text_heading", "slide_outline", "agenda_outline", "vlm_toc_skeleton"},
            )
        )
        allow_child_expansion = bool(
            balanced_result.get(
                "allow_child_expansion",
                balanced_result.get("semi_frozen", False),
            )
        )
        if not top_level_frozen:
            return

        build_state = dict(analysis.get("build_state") or {})
        build_state.update({
            "top_level_frozen": True,
            "allow_child_expansion": allow_child_expansion,
            "children_locked": bool(build_state.get("children_locked", False)),
            "top_level_source": source,
            "tree_complete": bool(build_state.get("tree_complete", False)),
        })
        analysis["build_state"] = build_state
        analysis["top_level_frozen"] = True
        analysis["allow_child_expansion"] = allow_child_expansion
        analysis["toc_frozen_source"] = source
        if allow_child_expansion:
            analysis["toc_frozen"] = False
            analysis["toc_semi_frozen"] = True
        else:
            analysis["toc_frozen"] = True
            analysis["toc_semi_frozen"] = False

    @staticmethod
    def _is_prevalidated_outline_result(result: Optional[Dict]) -> bool:
        return bool(
            result
            and result.get("source") in {
                "text_heading",
                "slide_outline",
                "agenda_outline",
                "toc_page_text",
                "bookmarks",
                "links",
                "regex",
                "vlm_toc_skeleton",
            }
            and result.get("prevalidated")
            and result.get("items")
        )

    @staticmethod
    def _should_skip_legacy_toc_detection(
        analysis: Dict,
        new_architecture_result: Optional[Dict],
    ) -> bool:
        """Avoid repeating TOC detection when canonical/anchored result already succeeded."""
        return bool(
            new_architecture_result
            and new_architecture_result.get("items")
            and new_architecture_result.get("prevalidated")
            and (
                analysis.get("toc_pages")
                or (analysis.get("toc_page") or {}).get("pages")
            )
        )

    @staticmethod
    def _try_text_heading_shortcut_legacy(
        analysis: Dict,
        balanced_result: Optional[Dict],
    ) -> Optional[Dict]:
        """Deprecated compatibility shim."""
        if not balanced_result or balanced_result.get("source") != "text_heading":
            return None
        items = balanced_result.get("toc_items") or []
        if not items:
            return None

        analysis["toc_frozen"] = True
        analysis["toc_frozen_source"] = "text_heading"
        return {
            "items": items,
            "source": "text_heading",
            "mapped": bool(balanced_result.get("mapped")),
            "semi_frozen": bool(balanced_result.get("semi_frozen")),
            "prevalidated": True,
        }

    @staticmethod
    def _is_prevalidated_text_heading_result(result: Optional[Dict]) -> bool:
        return PageIndexService._is_prevalidated_outline_result(result)

    @staticmethod
    def _prevalidated_skip_validation_message(result: Dict) -> str:
        source = result.get("source") or "outline"
        return f"[INDEX-V3-NEW] {source} shortcut prevalidated, skipping generic validation"

    @staticmethod
    def _is_effectively_image_doc(analysis: Dict) -> bool:
        text_coverage = float(analysis.get("text_coverage") or 0.0)
        image_coverage = float(analysis.get("image_coverage") or 0.0)
        return bool(analysis.get("is_image_only_pdf", False)) or (
            text_coverage < 0.3 and image_coverage >= 0.3
        )

    @staticmethod
    def _is_weak_slide_bookmark_toc(analysis: Dict, items: List[Dict]) -> bool:
        if not items:
            return False
        titles = [str(item.get("title", "")).strip() for item in items]
        weak_count = 0
        for title in titles:
            if not title:
                weak_count += 1
            elif re.match(r"^(?:幻灯片|Slide)\s*\d+(?:\s*[:：].*)?$", title, re.IGNORECASE):
                weak_count += 1
            elif title in {"默认节", "Default Section"}:
                weak_count += 1
            elif re.match(r"^第[一二三四五六七八九十]+章$", title):
                weak_count += 1
            elif re.match(r"^Chapter\s*\d+$", title, re.IGNORECASE):
                weak_count += 1

        weak_ratio = weak_count / len(titles)
        text_coverage = float(analysis.get("text_coverage") or 0.0)
        image_coverage = float(analysis.get("image_coverage") or 0.0)
        page_count = int(analysis.get("page_count") or 0)
        garbled_ratio = (
            len(analysis.get("garbled_pages") or []) / page_count
            if page_count > 0 else 0.0
        )
        low_text_quality = (
            text_coverage <= 0.35
            or garbled_ratio >= 0.3
            or image_coverage >= 0.8
        )
        return weak_ratio >= 0.3 and low_text_quality

    @staticmethod
    def _has_reliable_code_toc(analysis: Dict) -> bool:
        code_toc = analysis.get("code_toc") or {}
        items = code_toc.get("items") or []
        source = code_toc.get("source")
        if not items:
            return False
        if source in {"bookmarks", "links"}:
            if source == "bookmarks" and PageIndexService._is_weak_slide_bookmark_toc(analysis, items):
                print("[CODE-TOC] Ignoring weak slide-export bookmarks")
                analysis["code_toc_reject_reason"] = "weak_slide_bookmarks"
                return False
            return True
        if source != "regex":
            return False
        if analysis.get("agenda_outline_candidate"):
            print("[CODE-TOC] Ignoring weak regex TOC: agenda_outline_candidate=True")
            return False

        page_count = int(analysis.get("page_count") or 0)
        if page_count <= 0:
            return False

        physical_pages = [
            item.get("physical_index")
            for item in items
            if isinstance(item.get("physical_index"), int)
        ]
        if len(physical_pages) < 3:
            return False

        out_of_range_ratio = sum(1 for page in physical_pages if page > page_count) / len(physical_pages)
        year_like_ratio = sum(1 for page in physical_pages if 1900 <= page <= 2100) / len(physical_pages)
        if out_of_range_ratio >= 0.3 or year_like_ratio >= 0.3:
            print(
                f"[CODE-TOC] Ignoring weak regex TOC: "
                f"out_of_range={out_of_range_ratio:.0%}, years={year_like_ratio:.0%}"
            )
            return False

        compressed_ratio = max(physical_pages) / page_count if physical_pages else 1.0
        figure_title_ratio = sum(
            1
            for item in items
            if str(item.get("title", "")).strip().startswith(("图：", "表：", "图:", "表:"))
        ) / len(items)
        if page_count > 15 and compressed_ratio <= 0.35:
            print(
                f"[CODE-TOC] Ignoring weak regex TOC: "
                f"compressed_pages={compressed_ratio:.0%}"
            )
            return False
        if figure_title_ratio >= 0.2:
            print(
                f"[CODE-TOC] Ignoring weak regex TOC: "
                f"figure_titles={figure_title_ratio:.0%}"
            )
            return False

        in_range_pages = [page for page in physical_pages if 1 <= page <= page_count]
        unique_ratio = len(set(in_range_pages)) / len(in_range_pages) if in_range_pages else 0.0
        return len(in_range_pages) >= 3 and unique_ratio >= 0.6

    @staticmethod
    def _select_initial_execution_mode(requested_mode: str, analysis: Dict) -> str:
        if requested_mode != "smart":
            return requested_mode
        return "fast" if PageIndexService._has_reliable_code_toc(analysis) else "balanced"

    @staticmethod
    def _log_index_stage(stage_no: int, name: str, status: str, **details: Any) -> None:
        detail_text = " ".join(
            f"{key}={value}" for key, value in details.items()
            if value is not None
        )
        suffix = f" {detail_text}" if detail_text else ""
        print(f"[INDEX] Stage {stage_no}/7 {name}: {status}{suffix}")

    @staticmethod
    def _content_ocr_stage_name() -> str:
        return "content_ocr"

    @staticmethod
    def _build_toc_extract_stage_details(
        toc_items: List[Dict],
        page_count: int,
        frozen: bool,
    ) -> Dict[str, Any]:
        physical_pages = [
            item.get("physical_index")
            for item in toc_items
            if isinstance(item.get("physical_index"), int)
        ]
        start_pages = (
            f"{min(physical_pages)}-{max(physical_pages)}"
            if physical_pages else None
        )
        return {
            "start_pages": start_pages,
            "coverage": "100%" if physical_pages and page_count > 0 else None,
            "final_end": page_count if physical_pages else None,
            "frozen": frozen,
        }

    @staticmethod
    def _build_auxiliary_catalog_nodes(analysis: Dict) -> List[Dict]:
        code_toc = analysis.get("code_toc") or {}
        if code_toc.get("source") != "regex":
            return []
        items = code_toc.get("items") or []
        groups = {
            "figure": {"title": "图目录", "prefix": "图", "items": []},
            "table": {"title": "表目录", "prefix": "表", "items": []},
        }
        for item in items:
            title = str(item.get("title", "")).strip()
            if re.match(r"^图\s*\d+[.、：:\s]", title):
                groups["figure"]["items"].append(item)
            elif re.match(r"^表\s*\d+[.、：:\s]", title):
                groups["table"]["items"].append(item)

        catalogs: List[Dict[str, Any]] = []
        for catalog_type in ("figure", "table"):
            group = groups[catalog_type]
            if not group["items"]:
                continue
            children = []
            for idx, item in enumerate(group["items"], start=1):
                children.append(
                    {
                        "structure": f"{catalog_type}.{idx}",
                        "title": str(item.get("title", "")).strip(),
                        "physical_index": item.get("physical_index"),
                        "start_index": item.get("physical_index"),
                        "end_index": item.get("physical_index"),
                        "node_type": "auxiliary_catalog_item",
                        "catalog_type": catalog_type,
                        "exclude_from_coverage": True,
                        "exclude_from_llm_qc": True,
                        "exclude_from_text": True,
                        "source_anchor": {
                            "start_page": item.get("physical_index"),
                            "end_page": item.get("physical_index"),
                        },
                    }
                )
            catalogs.append(
                {
                    "structure": catalog_type,
                    "title": group["title"],
                    "physical_index": None,
                    "node_type": "auxiliary_catalog",
                    "catalog_type": catalog_type,
                    "exclude_from_coverage": True,
                    "exclude_from_llm_qc": True,
                    "exclude_from_text": True,
                    "nodes": children,
                }
            )
        return catalogs

    @staticmethod
    def _merge_auxiliary_catalog_nodes(
        tree: List[Dict],
        catalogs: List[Dict],
    ) -> List[Dict]:
        if not catalogs:
            return tree
        def _catalog_key(node: Dict) -> tuple[Any, Any]:
            return (
                node.get("node_type"),
                node.get("catalog_type") or node.get("title"),
            )

        existing = {
            _catalog_key(node)
            for node in tree
        }
        merged = list(tree)
        for catalog in catalogs:
            key = _catalog_key(catalog)
            if key not in existing:
                merged.append(catalog)
                existing.add(key)
        return merged

    @staticmethod
    def _normalize_auxiliary_catalog_nodes(tree: List[Dict]) -> List[Dict]:
        def normalize_item_title(title: str) -> str:
            text = re.sub(r"\s+", "", str(title or "").strip().lower())
            return re.sub(r"[：:，,、。.·\-\s]+", "", text)

        def range_quality(node: Dict) -> int:
            start = node.get("start_index") or node.get("physical_index")
            end = node.get("end_index") or start
            if not isinstance(start, int) or start <= 0:
                return 0
            if not isinstance(end, int) or end <= 0:
                return 1
            if start == 1 and end == 1:
                return 1
            return 3 if end >= start else 2

        def choose_better_item(existing: Dict, candidate: Dict) -> Dict:
            if range_quality(candidate) > range_quality(existing):
                merged = dict(existing)
                merged.update(candidate)
                return merged
            merged = dict(candidate)
            merged.update(existing)
            return merged

        def merge_auxiliary_catalog_roots(nodes: List[Dict]) -> List[Dict]:
            regular_nodes: List[Dict] = []
            catalog_by_type: Dict[str, Dict] = {}
            child_keys_by_type: Dict[str, Dict[str, int]] = {}

            for node in nodes:
                if (
                    node.get("node_type") != "auxiliary_catalog"
                    or node.get("catalog_type") not in {"figure", "table"}
                ):
                    regular_nodes.append(node)
                    continue

                catalog_type = str(node.get("catalog_type"))
                if catalog_type not in catalog_by_type:
                    catalog_by_type[catalog_type] = dict(node)
                    catalog_by_type[catalog_type]["nodes"] = []
                    child_keys_by_type[catalog_type] = {}

                target = catalog_by_type[catalog_type]
                target["exclude_from_coverage"] = True
                target["exclude_from_llm_qc"] = True
                target["exclude_from_text"] = True
                target["is_auxiliary"] = True

                for child in node.get("nodes") or []:
                    key = normalize_item_title(child.get("title", ""))
                    if not key:
                        continue
                    children = target["nodes"]
                    existing_index = child_keys_by_type[catalog_type].get(key)
                    if existing_index is None:
                        child_keys_by_type[catalog_type][key] = len(children)
                        children.append(child)
                    else:
                        children[existing_index] = choose_better_item(
                            children[existing_index],
                            child,
                        )

            merged = list(regular_nodes)
            for catalog_type in ("figure", "table"):
                catalog = catalog_by_type.get(catalog_type)
                if catalog:
                    merged.append(catalog)
            return merged

        def detect_catalog_type(node: Dict) -> Optional[str]:
            catalog_type = node.get("catalog_type")
            if catalog_type in {"figure", "table"}:
                return str(catalog_type)
            page_type = str(node.get("page_type") or "").lower()
            if page_type == "figure_catalog":
                return "figure"
            if page_type == "table_catalog":
                return "table"
            title = str(node.get("title") or "").strip().lower()
            figure_markers = {
                "figure catalog",
                "list of figures",
                "\u56fe\u76ee\u5f55",
                "\u63d2\u56fe\u76ee\u5f55",
            }
            table_markers = {
                "table catalog",
                "list of tables",
                "\u8868\u76ee\u5f55",
                "\u8868\u683c\u76ee\u5f55",
            }
            if any(marker in title for marker in figure_markers):
                return "figure"
            if any(marker in title for marker in table_markers):
                return "table"
            if node.get("node_type") == "auxiliary_catalog":
                return str(node.get("catalog_type") or "")
            return None

        def mark_auxiliary_item(node: Dict, catalog_type: str) -> Dict:
            item = dict(node)
            item["node_type"] = "auxiliary_catalog_item"
            item["catalog_type"] = catalog_type
            item["is_auxiliary"] = True
            item["exclude_from_coverage"] = True
            item["exclude_from_llm_qc"] = True
            item["exclude_from_text"] = True
            item.pop("text", None)
            item.pop("summary", None)
            children = item.get("nodes") or []
            item["nodes"] = [mark_auxiliary_item(child, catalog_type) for child in children]
            if "source_anchor" not in item:
                start = item.get("start_index") or item.get("physical_index")
                end = item.get("end_index") or start
                item["source_anchor"] = {"start_page": start, "end_page": end}
            return item

        normalized: List[Dict] = []
        for node in tree or []:
            catalog_type = detect_catalog_type(node)
            if catalog_type in {"figure", "table"}:
                catalog = dict(node)
                catalog["node_type"] = "auxiliary_catalog"
                catalog["catalog_type"] = catalog_type
                catalog["is_auxiliary"] = True
                catalog["exclude_from_coverage"] = True
                catalog["exclude_from_llm_qc"] = True
                catalog["exclude_from_text"] = True
                catalog.pop("text", None)
                catalog.pop("summary", None)
                catalog["nodes"] = [
                    mark_auxiliary_item(child, catalog_type)
                    for child in (node.get("nodes") or [])
                ]
                normalized.append(catalog)
                continue

            regular = dict(node)
            if regular.get("page_type") == "catalog_group":
                regular.pop("page_type", None)
            if regular.get("node_type") == "catalog_group":
                regular.pop("node_type", None)
            children = regular.get("nodes")
            if isinstance(children, list):
                regular["nodes"] = PageIndexService._normalize_auxiliary_catalog_nodes(children)
            normalized.append(regular)
        return merge_auxiliary_catalog_roots(normalized)

    @staticmethod
    def _normalize_final_tree_schema(
        tree: List[Dict],
        *,
        doc_id: str,
        page_count: int,
    ) -> List[Dict]:
        """Normalize the final saved tree to the canonical balanced schema."""
        from pageindex.tree_schema import normalize_tree_node

        return [
            normalize_tree_node(node, doc_id=doc_id, page_count=page_count)
            for node in (tree or [])
            if isinstance(node, dict)
        ]

    @staticmethod
    def _allows_child_outline_expansion(analysis: Dict) -> bool:
        build_state = analysis.get("build_state") or {}
        top_level_frozen = bool(
            analysis.get("top_level_frozen")
            or build_state.get("top_level_frozen")
            or analysis.get("toc_semi_frozen")
        )
        allow_child_expansion = bool(
            analysis.get(
                "allow_child_expansion",
                build_state.get("allow_child_expansion", analysis.get("toc_semi_frozen", False)),
            )
        )
        return top_level_frozen and allow_child_expansion

    @staticmethod
    def _expand_visual_page_outline_if_needed(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
    ) -> int:
        """Expand a top-level-frozen TOC skeleton with child page titles."""
        if not PageIndexService._allows_child_outline_expansion(analysis):
            return 0
        from pageindex.visual_page_outline_extractor import (
            expand_flat_toc_with_page_titles,
            expand_toc_with_page_evidence,
        )

        page_evidence = analysis.get("page_evidence") or analysis.get("page_evidences") or []
        if PageIndexService._requires_visual_outline_provider(analysis) and not page_evidence:
            reason = PageIndexService._flat_text_outline_skip_reason(analysis)
            analysis["outline_expansion"] = {
                "source": "none",
                "reason": reason,
                "added_children": 0,
                "quality": "bad",
                "expected_children": 0,
                "actual_children": 0,
                "needs_repair": True,
            }
            print(f"[OUTLINE-EXPAND] skipped provider=flat_text_fallback reason={reason}")
            return 0

        if page_evidence:
            print(f"[OUTLINE-EXPAND] provider=page_evidence chapters={len(toc_tree)}")
            expansion = expand_toc_with_page_evidence(toc_tree, page_evidence, page_count)
            expansion["source"] = "page_evidence"
        else:
            print(f"[OUTLINE-EXPAND] provider=flat_text_fallback chapters={len(toc_tree)}")
            page_texts = [
                str(page[0] or "")
                for page in (page_list or [])
                if isinstance(page, (list, tuple)) and len(page) >= 1
            ]
            if not page_texts:
                print("[OUTLINE-EXPAND] skipped reason=no_page_texts")
                return 0
            expansion = expand_flat_toc_with_page_titles(toc_tree, page_texts, page_count)
            expansion["source"] = "flat_text_fallback"

        added = int(expansion.get("added_children") or 0)
        analysis["outline_expansion"] = expansion
        if added:
            print(
                f"[OUTLINE-EXPAND] done added_children={added} "
                f"quality={expansion.get('quality')} "
                f"source_distribution={expansion.get('source_distribution')} "
                f"avg_confidence={expansion.get('avg_title_confidence')} "
                f"low_confidence_ratio={expansion.get('low_confidence_ratio')}"
            )
        else:
            print(
                f"[OUTLINE-EXPAND] skipped reason=no_visual_titles "
                f"quality={expansion.get('quality')} "
                f"expected_children={expansion.get('expected_children')} "
                f"actual_children={expansion.get('actual_children')}"
            )
        return added

    @staticmethod
    def _should_skip_flat_text_outline_expansion(analysis: Dict) -> bool:
        """Return true when extracted page text is not trustworthy for structure."""
        if PageIndexService._requires_visual_outline_provider(analysis):
            return True

        text_quality = analysis.get("text_quality") or {}
        if bool(text_quality.get("is_low_quality")):
            return True
        if bool(analysis.get("is_garbled_pdf")):
            return True

        try:
            text_coverage = float(analysis.get("text_coverage") or 0.0)
        except Exception:
            text_coverage = 0.0
        try:
            duplicate_ratio = float(text_quality.get("duplicate_ratio") or 0.0)
        except Exception:
            duplicate_ratio = 0.0
        try:
            meaningful_ratio = float(text_quality.get("meaningful_ratio") or 1.0)
        except Exception:
            meaningful_ratio = 1.0

        return text_coverage <= 0.35 and (
            duplicate_ratio >= 0.65
            or meaningful_ratio <= 0.35
            or bool(analysis.get("garbled_pages"))
        )

    @staticmethod
    def _requires_visual_outline_provider(analysis: Dict) -> bool:
        """Return true when structure must come from visual evidence, not OCR text."""
        if str(analysis.get("structure_policy") or "").lower() == "visual_required":
            return True
        if str(analysis.get("layout_type") or "").lower() in {
            "scanned_image_pdf",
            "mixed_visual_report",
            "slide_like_report",
        }:
            return True
        return False

    @staticmethod
    def _flat_text_outline_skip_reason(analysis: Dict) -> str:
        if PageIndexService._requires_visual_outline_provider(analysis):
            return "visual_required"
        return "low_quality_text"

    @staticmethod
    async def _expand_visual_page_outline_with_vlm_fallback(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
        model: Optional[str] = None,
    ) -> int:
        """Run deterministic expansion, then bounded VLM fallback if quality is bad."""
        if not PageIndexService._allows_child_outline_expansion(analysis):
            return 0
        if (
            PageIndexService._should_skip_flat_text_outline_expansion(analysis)
            and analysis.get("document_path")
        ):
            skip_reason = PageIndexService._flat_text_outline_skip_reason(analysis)
            print(f"[OUTLINE-EXPAND] skip flat_text_fallback reason={skip_reason}")
            visual_expansion = await PageIndexService._extract_visual_child_titles_for_flat_skeleton(
                file_path=str(analysis["document_path"]),
                tree=toc_tree,
                page_count=page_count,
                model=model,
            )
            visual_expansion["source"] = "vlm_page_titles"
            visual_expansion["reason"] = skip_reason
            analysis["outline_expansion"] = visual_expansion
            visual_added = int(visual_expansion.get("added_children") or 0)
            print(
                f"[OUTLINE-EXPAND] vlm_page_titles added_children={visual_added} "
                f"quality={visual_expansion.get('quality')}"
            )
            return visual_added

        added = PageIndexService._expand_visual_page_outline_if_needed(
            toc_tree=toc_tree,
            analysis=analysis,
            page_count=page_count,
            toc_source=toc_source,
            page_list=page_list,
        )
        expansion = analysis.get("outline_expansion") or {}
        if not expansion.get("needs_repair") or not analysis.get("document_path"):
            return added

        visual_expansion = await PageIndexService._extract_visual_child_titles_for_flat_skeleton(
            file_path=str(analysis["document_path"]),
            tree=toc_tree,
            page_count=page_count,
            model=model,
        )
        visual_added = int(visual_expansion.get("added_children") or 0)
        if visual_added > added:
            visual_expansion["source"] = "vlm_page_titles"
            analysis["outline_expansion"] = visual_expansion
            print(
                f"[OUTLINE-EXPAND] vlm fallback added_children={visual_added} "
                f"quality={visual_expansion.get('quality')}"
            )
            return visual_added
        return added

    @staticmethod
    async def _extract_visual_child_titles_for_flat_skeleton(
        *,
        file_path: str,
        tree: List[Dict],
        page_count: int,
        model: Optional[str] = None,
    ) -> Dict:
        """Use VLM page images to extract child titles for long flat visual chapters."""
        from pageindex.visual_page_outline_extractor import expand_toc_with_page_evidence

        evidence = await PageIndexService._build_visual_page_title_evidence(
            file_path=file_path,
            tree=tree,
            page_count=page_count,
            model=model,
        )
        if not evidence:
            return {
                "added_children": 0,
                "quality": "bad",
                "expected_children": 0,
                "actual_children": 0,
                "needs_repair": True,
            }
        result = expand_toc_with_page_evidence(tree, evidence, page_count)
        result["evidence_pages"] = [item.get("page") for item in evidence]
        return result

    @staticmethod
    async def _build_visual_page_title_evidence(
        *,
        file_path: str,
        tree: List[Dict],
        page_count: int,
        model: Optional[str] = None,
    ) -> List[Dict]:
        """Render bounded chapter pages and ask VLM for visible slide/page titles."""
        from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

        def safe_confidence(value: Any, default: float = 0.75) -> float:
            try:
                return float(value)
            except Exception:
                text = str(value or "").strip().lower()
                if text in {"high", "yes", "true"}:
                    return 0.85
                if text in {"medium", "mid"}:
                    return 0.65
                if text in {"low", "weak"}:
                    return 0.45
                return default

        pages: List[int] = []
        for node in tree or []:
            if node.get("nodes"):
                continue
            title = str(node.get("title") or "").lower()
            if str(node.get("structure") or "") == "0" or "preface" in title:
                continue
            start = node.get("start_index") or node.get("physical_index")
            end = node.get("end_index") or page_count
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if end - start + 1 < 6:
                continue
            pages.extend(range(max(1, start), min(page_count, end) + 1))

        page_indices = sorted({p - 1 for p in pages})
        if not page_indices:
            return []

        evidence: List[Dict] = []
        batch_size = 6
        for offset in range(0, len(page_indices), batch_size):
            batch = page_indices[offset : offset + batch_size]
            images = render_pages_to_images(file_path, batch, dpi=120)
            if not images:
                continue
            labels = "\n".join(f"- image {idx + 1}: PDF page {img['page_index'] + 1}" for idx, img in enumerate(images))
            prompt = f"""You are extracting visible page/slide titles from a PDF report.

For each image, read only the main visible title of that page. Ignore footers, page numbers, website URLs, chart axis labels, body paragraphs, and decorative text.
If a page is a chapter cover whose title duplicates the parent chapter, still return it; downstream logic will filter duplicates.
If no reliable page title exists, return an empty title.

Images:
{labels}

Return strict JSON only:
{{
  "pages": [
    {{"page": 11, "title": "visible title", "confidence": 0.0}}
  ]
}}
"""
            try:
                raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=2000, timeout=45)
                parsed = parse_vlm_json(raw)
            except Exception as exc:
                print(f"[OUTLINE-EXPAND] VLM page title batch failed: {exc}")
                continue
            for item in (parsed.get("pages") if isinstance(parsed, dict) else []) or []:
                try:
                    page = int(item.get("page") or 0)
                except Exception:
                    continue
                title = str(item.get("title") or "").strip()
                if not page or not title:
                    continue
                confidence = safe_confidence(item.get("confidence"))
                evidence.append(
                    {
                        "page": page,
                        "primary_role": "content_slide",
                        "source": "vlm_page_titles",
                        "confidence": confidence,
                        "evidence_spans": [
                            {
                                "role": "page_title",
                                "text": title,
                                "confidence": confidence,
                            }
                        ],
                    }
                )
        return evidence

    @staticmethod
    def _apply_balanced_quality_gate(
        toc_tree: List[Dict],
        analysis: Dict,
        completeness: Dict,
        page_count: int,
    ) -> tuple[List[Dict], Dict]:
        """Run deterministic balanced quality checks before LLM QC/enrichment."""
        from pageindex.balanced_quality_gate import run_balanced_quality_gate

        state = analysis.get("build_state") or {
            "top_level_frozen": bool(analysis.get("top_level_frozen") or analysis.get("toc_frozen")),
            "allow_child_expansion": bool(analysis.get("allow_child_expansion", True)),
        }
        skeleton = analysis.get("toc_skeleton") or (state.get("skeleton") if isinstance(state, dict) else None)
        fixed_tree, gate = run_balanced_quality_gate(toc_tree, state, skeleton, page_count)
        updated = dict(completeness or {})
        updated["balanced_quality_gate"] = gate
        if gate.get("needs_repair"):
            updated["needs_repair"] = True
            updated["quality"] = "bad"
        analysis["balanced_quality_gate"] = gate
        return fixed_tree, updated

    @staticmethod
    def _save_index_payload(doc_id: str, payload: Dict[str, Any]) -> Path:
        INDEXES_DIR.mkdir(parents=True, exist_ok=True)
        index_path = INDEXES_DIR / f"{doc_id}.json"
        PageIndexService._attach_index_quality_report(payload)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return index_path

    @staticmethod
    def _attach_index_quality_report(
        payload: Dict[str, Any],
        page_count: Optional[int] = None,
        *,
        force_pdf: bool = False,
    ) -> None:
        if not isinstance(payload, dict) or payload.get("quality_report") is not None:
            return

        doc_name = str(
            payload.get("doc_name") or payload.get("document_name") or ""
        ).lower()
        is_pdf_payload = (
            force_pdf
            or str(payload.get("format") or "").lower() == "pdf"
            or doc_name.endswith(".pdf")
        )
        if not is_pdf_payload:
            return

        payload["quality_report"] = build_index_quality_report(
            payload,
            page_count=page_count or payload.get("page_count"),
        )

    async def _generate_index_v2(
        self, file_path: Path, doc_id: str, mode_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """v3 閲嶆瀯鐗堬細pdf_analyzer 鈫?fast/balanced(text|visual) 鈫?post_processing 鈫?node_filler"""
        from pageindex.pdf_analyzer import analyze_pdf_structure
        from pageindex.fast_toc import try_fast_toc
        from pageindex.balanced_toc import (
            decide_balanced_path,
            build_balanced_toc_visual,
            build_balanced_toc_text,
            _try_extract_text_heading_toc,
            _vlm_detect_anchors,
        )
        from pageindex.slide_outline_extractor import (
            is_slide_like_document,
        )
        from pageindex.agenda_outline_extractor import (
            is_agenda_outline_document,
        )
        from pageindex.post_processing import post_process_toc
        from pageindex.node_filler import (
            fill_node_text,
            ocr_image_pages,
            generate_summaries,
            generate_doc_description,
            write_node_ids,
        )

        model = getattr(self.opt, "model", "qwen3.6-flash")
        requested_mode = mode_override or "smart"

        # 鍒涘缓 enhancement hooks锛堝湪 balanced 妯″紡涓嬩娇鐢級
        from pageindex.enhancement_hooks import MultimodalEnhancementHooks
        hooks = MultimodalEnhancementHooks(
            enable_hooks=[]
        )

        # 鈹€鈹€鈹€ Phase 0: 鏂囨。棰勫垎鏋?鈹€鈹€鈹€
        self._log_index_stage(1, "analyze", "started")
        print(f"[INDEX-V3] Phase 0: analyzing {file_path.name}")
        analysis = analyze_pdf_structure(str(file_path))
        analysis["document_path"] = str(file_path)
        page_count = analysis["page_count"]
        page_list = list(analysis["page_list"])
        analysis["slide_outline_candidate"] = is_slide_like_document(analysis)
        analysis["agenda_outline_candidate"] = is_agenda_outline_document(analysis)
        self._log_index_stage(
            1,
            "analyze",
            "done",
            pages=page_count,
            text_coverage=f"{analysis['text_coverage']:.0%}",
        )
        print(
            "[INDEX-V3] Profile: "
            f"layout_type={analysis.get('layout_type', 'unknown')}, "
            f"text_layer_quality={analysis.get('text_layer_quality', 'unknown')}, "
            f"structure_policy={analysis.get('structure_policy', 'unknown')}, "
            f"ocr_policy={analysis.get('ocr_policy', 'unknown')}, "
            f"visual_dependency_score={analysis.get('visual_dependency_score', 0)}"
        )

        # 璺敱鍐崇瓥
        execution_mode = self._select_initial_execution_mode(requested_mode, analysis)
        initial_execution_mode = execution_mode

        balanced_path = None
        if execution_mode == "balanced":
            balanced_path = decide_balanced_path(analysis)
            analysis["balanced_path"] = balanced_path

        print(
            f"[INDEX-V3] Route: requested={requested_mode}, execution={execution_mode}, "
            f"balanced_path={balanced_path}, code_toc={analysis['code_toc']['source']}, "
            f"pages={page_count}, text_coverage={analysis['text_coverage']:.0%}"
        )

        # 鈹€鈹€鈹€ Phase 0.5: 閿氱偣妫€娴嬶紙鎵€鏈?balanced 鏂囨。锛夆攢鈹€鈹€
        # P2-fix: 鎵€鏈?balanced 鏂囨。閮藉厛璺戦敋鐐规娴嬶紝鑾峰彇 dividers 淇℃伅
        anchors = None
        ocr_text_map = None
        dividers = []  # Initialize for all execution modes
        if execution_mode == "balanced":
            self._log_index_stage(2, "anchors", "started")
            print("[INDEX-V3] Phase 0.5: anchor detection for all balanced documents")
            anchors = await _vlm_detect_anchors(str(file_path), model)
            dividers = anchors.get("chapter_dividers", [])
            self._sync_toc_context(
                analysis,
                anchors.get("toc_pages", []),
                confidence="anchor",
            )
            print(f"[INDEX-V3] Phase 0.5: detected {len(dividers)} dividers")
            self._log_index_stage(
                2,
                "anchors",
                "done",
                toc_pages=anchors.get("toc_pages", []),
                dividers=len(dividers),
            )
            
            # 鍥剧墖鍨嬫枃妗ｉ澶栧仛 OCR
            if balanced_path == "visual" and (analysis.get("is_image_only_pdf") or analysis["text_coverage"] < 0.3):
                print("[INDEX-V3] Phase 0.5: pre-TOC OCR for image-only PDF")
                toc_pages = anchors.get("toc_pages", [])
                if toc_pages:
                    pages_to_ocr = sorted(
                        set([p - 1 for p in toc_pages])
                        | set(range(max(toc_pages), min(max(toc_pages) + 6, page_count)))
                    )
                    print(
                        f"[INDEX-V3] Phase 0.5 structure_ocr: {len(pages_to_ocr)} pages "
                        f"(toc_pages={toc_pages})"
                    )
                    analysis["structure_ocr_pages"] = pages_to_ocr
                    ocr_text_map = await self._ocr_pages_for_toc_validation(
                        file_path, pages_to_ocr
                    )
                    print(
                        f"[INDEX-V3] Phase 0.5 structure_ocr done, "
                        f"{len(ocr_text_map)} pages with text"
                    )

        # 鈹€鈹€鈹€ Phase 0.8: 鏂版灦鏋勬櫤鑳借矾鐢憋紙瀹為獙鎬э紝鍚戝悗鍏煎锛夆攢鈹€鈹€
        # 濡傛灉鍚敤浜嗘柊鏋舵瀯锛屽皾璇曚娇鐢?-path璺敱
        new_architecture_result = None
        try:
            from pageindex.router import decide_extraction_path, get_path_description
            from pageindex.toc_page_extractor import extract_toc_from_analysis
            from pageindex.hierarchical_extractor import extract_hierarchical_toc
            from pageindex.batch_extractor import extract_batch_toc
            from pageindex.fast_text_extractor import extract_fast_text_toc
            from pageindex.visual_extractor import extract_visual_toc
            from pageindex.quality_validator import validate_toc, repair_toc

            route_decision = decide_extraction_path(analysis, requested_mode)
            chosen_path = route_decision["path"]
            print(f"[INDEX-V3-NEW] Smart router chose: {chosen_path} ({get_path_description(chosen_path)})")
            print(f"[INDEX-V3-NEW] Reasons: {route_decision['reasons']}")

            if not new_architecture_result and execution_mode == "balanced" and balanced_path == "text":
                text_heading_result = _try_extract_text_heading_toc(analysis)
                new_architecture_result = self._try_text_heading_shortcut(
                    analysis,
                    text_heading_result,
                )
                if new_architecture_result:
                    print(
                        f"[INDEX-V3-NEW] Using text heading shortcut: "
                        f"{len(new_architecture_result['items'])} items"
                    )

            if not new_architecture_result and execution_mode == "balanced":
                new_architecture_result = self._try_balanced_provider_shortcut(
                    analysis,
                    page_count,
                )
                if new_architecture_result:
                    print(
                        f"[INDEX-V3-NEW] Using balanced provider shortcut: "
                        f"source={new_architecture_result['source']} "
                        f"items={len(new_architecture_result['items'])} "
                        f"mapping={new_architecture_result.get('mapping_strategy')}"
                    )

            if new_architecture_result:
                pass
            elif chosen_path == "toc_page":
                new_architecture_result = extract_toc_from_analysis(analysis, doc_path=str(file_path))
            elif chosen_path == "hierarchical":
                new_architecture_result = await extract_hierarchical_toc(
                    analysis.get("page_texts", []), model
                )
            elif chosen_path == "batch":
                new_architecture_result = await extract_batch_toc(
                    analysis.get("page_texts", []), model
                )
            elif chosen_path == "fast_text":
                new_architecture_result = extract_fast_text_toc(
                    analysis.get("page_texts", []), model
                )
            elif chosen_path == "visual":
                # 瑙嗚璺緞浣跨敤鍘熸湁鐨?balanced_toc_visual
                new_architecture_result = await extract_visual_toc(
                    str(file_path), analysis, model,
                    anchors=anchors,
                    ocr_text_map=ocr_text_map,
                )

            # 璐ㄩ噺楠岃瘉
            if new_architecture_result and new_architecture_result.get("items"):
                if self._is_prevalidated_text_heading_result(new_architecture_result):
                    print(self._prevalidated_skip_validation_message(new_architecture_result))
                else:
                    validation = validate_toc(
                        new_architecture_result["items"],
                        page_count,
                        analysis.get("page_texts", []),
                        source=new_architecture_result.get("source", "unknown"),
                    )
                    print(f"[INDEX-V3-NEW] Validation: score={validation['score']:.2f}, valid={validation['is_valid']}")

                    if not validation["is_valid"]:
                        # 灏濊瘯淇
                        repaired = await repair_toc(
                            new_architecture_result["items"],
                            validation["issues"],
                            analysis.get("page_texts", []),
                            model,
                        )
                        new_architecture_result["items"] = repaired
                        new_architecture_result["repaired"] = True

                    if validation["score"] >= 0.7:
                        print(f"[INDEX-V3-NEW] Using new architecture result (score={validation['score']:.2f})")
                    else:
                        print(f"[INDEX-V3-NEW] Score too low ({validation['score']:.2f}), falling back to legacy")
                        new_architecture_result = None

        except Exception as e:
            print(f"[INDEX-V3-NEW] New architecture failed: {e}, falling back to legacy")
            new_architecture_result = None

        # 鈹€鈹€鈹€ Phase 1: TOC 鏋勫缓 鈹€鈹€鈹€
        toc_items = None
        toc_source = None

        # 濡傛灉浣跨敤鏂版灦鏋勬垚鍔燂紝杞崲鏍煎紡骞惰烦杩囧悗缁?legacy 鎻愬彇
        new_architecture_used = False
        if new_architecture_result:
            toc_items = new_architecture_result["items"]
            toc_source = new_architecture_result.get("source", "new_architecture")
            top_level_frozen = bool(
                new_architecture_result.get(
                    "top_level_frozen",
                    new_architecture_result.get("mapped") or new_architecture_result.get("semi_frozen"),
                )
            )
            allow_child_expansion = bool(
                new_architecture_result.get(
                    "allow_child_expansion",
                    new_architecture_result.get("semi_frozen", False),
                )
            )
            analysis["top_level_frozen"] = top_level_frozen
            analysis["allow_child_expansion"] = allow_child_expansion
            if allow_child_expansion:
                analysis["toc_frozen"] = False
                analysis["toc_frozen_source"] = toc_source
                analysis["toc_semi_frozen"] = True
            elif top_level_frozen:
                analysis["toc_frozen"] = True
                analysis["toc_frozen_source"] = toc_source
            new_architecture_used = True
            stage_details = self._build_toc_extract_stage_details(
                toc_items,
                page_count=page_count,
                frozen=analysis.get("toc_frozen", False),
            )
            self._log_index_stage(
                3,
                "toc_extract",
                "done",
                source=toc_source,
                items=len(toc_items),
                **stage_details,
            )
            print(f"[INDEX-V3-NEW] Converted {len(toc_items)} items to legacy format")

        if execution_mode == "fast" and not new_architecture_used:
            print("[INDEX-V3] Phase 1: trying fast TOC")
            fast_result = await try_fast_toc(analysis, model)
            if fast_result and not fast_result.get("quality_check_failed"):
                toc_items = fast_result["toc_items"]
                toc_source = fast_result["source"]
            elif fast_result and fast_result.get("quality_check_failed"):
                # P1-fix: Fast TOC quality check failed, but we have items - escalate to balanced
                print("[INDEX-V3] Fast TOC quality check failed, escalating to balanced")
                execution_mode = "balanced"
                balanced_path = "visual"  # Force visual for better accuracy
            elif requested_mode == "fast":
                raise ValueError(
                    "FAST_TOC_INCOMPLETE: code extraction + validation failed"
                )
            else:
                print("[INDEX-V3] Fast failed, escalating to balanced")
                execution_mode = "balanced"
                balanced_path = decide_balanced_path(analysis)

        skip_legacy_toc_detection = self._should_skip_legacy_toc_detection(
            analysis,
            new_architecture_result,
        )
        if execution_mode == "balanced" and not new_architecture_used and not skip_legacy_toc_detection:
            # 鈹€鈹€鈹€ Step 1: 鏌ユ壘鐩綍椤?鈹€鈹€鈹€
            from pageindex.toc_detector import find_toc_pages

            anchor_toc_pages = list((anchors or {}).get("toc_pages") or analysis.get("toc_pages") or [])
            if anchor_toc_pages:
                toc_pages = anchor_toc_pages
                print(f"[INDEX-V3] Phase 1: using anchor toc_pages={toc_pages}")
            else:
                print("[INDEX-V3] Phase 1: searching for toc pages")
                toc_pages = await find_toc_pages(analysis, str(file_path), model)
                self._sync_toc_context(analysis, toc_pages, confidence="detected")

            visual_required = self._requires_visual_outline_provider(analysis)

            if toc_pages:
                print(f"[INDEX-V3] Found toc pages: {toc_pages}")
                from pageindex.toc_page_extractor import extract_toc_from_pages
                from pageindex.quality_validator import validate_toc
                
                toc_result = None
                if visual_required:
                    print(
                        "[TOC-PAGE] Skip text/regex extraction: "
                        f"structure_policy={analysis.get('structure_policy')}"
                    )
                else:
                    toc_result = extract_toc_from_pages(
                        doc_path=str(file_path),
                        toc_page_indices=[p - 1 for p in toc_pages],
                        doc_page_count=page_count,
                        model=model,
                        page_texts=analysis.get("page_texts", []),
                    )
                
                if toc_result and toc_result.get("items"):
                    # 璐ㄩ噺楠岃瘉
                    validation = validate_toc(
                        toc_result["items"],
                        page_count,
                        analysis.get("page_texts", []),
                        source="toc_page",
                    )
                    
                    if validation["score"] >= 0.7:
                        print(f"[INDEX-V3] v4 extraction success (score={validation['score']:.2f})")
                        toc_items = toc_result["items"]
                        toc_source = "toc_page"
                    else:
                        print(f"[INDEX-V3] v4 quality low ({validation['score']:.2f}), falling back")
                        toc_items = None
                else:
                    if visual_required:
                        print("[TOC-PAGE] Text/regex extraction skipped; using balanced visual path")
                    else:
                        print("[INDEX-V3] v4 extraction failed, falling back")
                    toc_items = None
                
                if toc_items is None:
                    is_image_doc = self._is_effectively_image_doc(analysis)
                    
                    if visual_required:
                        print("[INDEX-V3] Skip legacy TOC fallback: structure_policy=visual_required")
                    elif is_image_doc:
                        # 鍥剧墖鍨?鈫?VLM瑙嗚鎻愬彇
                        print("[INDEX-V3] Fallback: VLM visual extraction for image doc")
                        
                        fallback_result = await self._extract_toc_visual(
                            str(file_path), toc_pages, page_count, model
                        )
                        fallback_result = self._normalize_and_map_fallback_toc(
                            fallback_result,
                            page_count=page_count,
                            toc_pages=toc_pages,
                            ocr_text_map=ocr_text_map,
                            dividers=dividers,
                        )
                        if fallback_result and fallback_result.get("toc_items"):
                            checker = TocQualityChecker()
                            toc_check = checker.check(fallback_result["toc_items"], toc_pages)
                            if toc_check["is_valid"]:
                                if toc_check["has_hierarchy"]:
                                    # 鏈夊眰绾?鈫?鐩存帴浣跨敤
                                    toc_items = fallback_result["toc_items"]
                                    toc_source = "vlm_visual"
                                    print(f"[INDEX-V3] VLM visual extraction success: {len(toc_items)} items with hierarchy")
                                else:
                                    # 鍙湁涓€绾?鈫?闇€瑕佸垎鏀疊鍒嗘鎻愬彇
                                    print(f"[INDEX-V3] TOC has {toc_check['top_level_count']} top-level items only, need Branch B")
                                    # 娓呯┖toc_items锛岃瀹冭繘鍏uild_balanced_toc_visual杩涜璺緞鍐崇瓥鍜屽垎鏀疊
                                    toc_items = None
                    else:
                        # 鏂囨湰鍨?鈫?LLM鏂囨湰鎻愬彇
                        print("[INDEX-V3] Fallback: LLM text extraction for text doc")
                        fallback_result = await self._extract_toc_text(
                            analysis, toc_pages, page_count, model
                        )
                        fallback_result = self._normalize_and_map_fallback_toc(
                            fallback_result,
                            page_count=page_count,
                            toc_pages=toc_pages,
                            ocr_text_map=ocr_text_map,
                            dividers=dividers,
                        )
                        if fallback_result and fallback_result.get("toc_items"):
                            checker = TocQualityChecker()
                            toc_check = checker.check(fallback_result["toc_items"], toc_pages)
                            if toc_check["is_valid"]:
                                if toc_check["has_hierarchy"]:
                                    toc_items = fallback_result["toc_items"]
                                    toc_source = "llm_text"
                                    print(f"[INDEX-V3] LLM text extraction success: {len(toc_items)} items with hierarchy")
                                else:
                                    print(f"[INDEX-V3] TOC has {toc_check['top_level_count']} top-level items only, need Branch B")
                                    toc_items = None
                
                # 濡傛灉闄嶇骇涔熷け璐ユ垨鍙湁涓€绾ч渶瑕佸垎鏀疊锛岀户缁蛋鍘熸湁balanced閫昏緫
                if toc_items is None:
                    if visual_required:
                        print("[INDEX-V3] Visual skeleton extraction delegated to balanced visual path")
                    else:
                        print("[INDEX-V3] Fallback incomplete, continuing with balanced path for sub-chapter extraction")
            else:
                print("[INDEX-V3] No toc pages found, continuing with traditional balanced path")
                toc_items = None
            
            # 濡傛灉娌℃湁閫氳繃v4鑾峰彇鍒皌oc锛岃蛋鍘熸湁balanced璺緞
            if toc_items is None:
                if balanced_path == "text":
                    print("[INDEX-V3] Phase 1: balanced TEXT (LLM)")
                    # P2-fix: 浼犲叆 dividers 淇 Text 璺緞缁撴灉
                    text_dividers = anchors.get("chapter_dividers", []) if anchors else []
                    balanced_result = await build_balanced_toc_text(
                        analysis, model, dividers=text_dividers, hooks=hooks
                    )
                    
                    # P5-fix: Check text path quality, fallback to visual if poor
                    toc_items = balanced_result["toc_items"]
                    if (
                        balanced_result.get("mapped")
                        or balanced_result.get("semi_frozen")
                        or balanced_result.get("source") == "text_heading"
                    ):
                        analysis["toc_frozen"] = True
                        analysis["toc_frozen_source"] = balanced_result.get("source")
                    self._apply_balanced_result_state(analysis, balanced_result)
                    top_level = [it for it in toc_items if "." not in str(it.get("structure", ""))]
                    has_large_nodes = any(
                        (toc_items[i+1].get("physical_index", page_count+1) - it.get("physical_index", 0)) > 15
                        for i, it in enumerate(toc_items[:-1])
                    ) if len(toc_items) > 1 else False
                    
                    if (
                        not analysis.get("toc_frozen")
                        and len(top_level) < 3
                        and len(toc_items) > 10
                        and has_large_nodes
                    ):
                        print(f"[INDEX-V3] Text path quality poor: {len(top_level)} top-level, {len(toc_items)} items, large nodes detected")
                        print("[INDEX-V3] Falling back to VISUAL path")
                        balanced_path = "visual"
                        balanced_result = await build_balanced_toc_visual(
                            str(file_path), analysis, model,
                            anchors=anchors,
                            ocr_text_map=ocr_text_map,
                            hooks=hooks,
                        )
                        toc_items = balanced_result["toc_items"]
                        toc_source = balanced_result["source"]
                        self._apply_balanced_result_state(analysis, balanced_result)
                    else:
                        toc_source = balanced_result["source"]
                else:
                    print("[INDEX-V3] Phase 1: balanced VISUAL (VLM)")
                    balanced_result = await build_balanced_toc_visual(
                        str(file_path), analysis, model,
                        anchors=anchors,
                        ocr_text_map=ocr_text_map,
                        hooks=hooks,
                    )
                    toc_items = balanced_result["toc_items"]
                    toc_source = balanced_result["source"]
                    self._apply_balanced_result_state(analysis, balanced_result)

        # 鈹€鈹€鈹€ Phase 1.5: OCR 鍥剧墖椤?鈹€鈹€鈹€
        needs_ocr = (
            len(analysis.get("image_only_pages", [])) > 0
            or len(analysis.get("garbled_pages", [])) > 0
        )
        if needs_ocr:
            analysis["ocr_role"] = "content_fill"
            content_ocr_stage = self._content_ocr_stage_name()
            self._log_index_stage(
                4,
                content_ocr_stage,
                "started",
                role="content_fill",
                pages=len(analysis.get("image_only_pages", []))
                + len(analysis.get("garbled_pages", [])),
            )
            print(
                f"[INDEX-V3] Content OCR: {len(analysis.get('image_only_pages', []))} image "
                f"+ {len(analysis.get('garbled_pages', []))} garbled pages"
            )
            if self._requires_visual_outline_provider(analysis):
                print("[INDEX-V3] OCR role=content_fill; structure providers remain visual-only")
            page_list = await ocr_image_pages(
                analysis,
                page_list,
                ocr_service_fn=self._run_full_pdf_ocr_by_images,
            )
            analysis["page_list"] = page_list
            self._log_index_stage(
                4,
                content_ocr_stage,
                "done",
                role="content_fill",
                coverage=f"{len(page_list)}/{page_count}",
            )

        # 鈹€鈹€鈹€ Phase 2: 鍚庡鐞?(post_processing.py v3) 鈹€鈹€鈹€
        # Check whether extraction already returned a nested tree.
        has_prebuilt_tree = any(
            isinstance(item.get("nodes"), list) and bool(item.get("nodes"))
            for item in toc_items
        )
        
        if has_prebuilt_tree:
            print(f"[INDEX-V3] Phase 2: prebuilt tree detected, assigning page ranges to {len(toc_items)} roots")
            toc_tree = []
            for item in toc_items:
                if "start_index" not in item:
                    item["start_index"] = item.get("physical_index") or 1
                if "end_index" not in item:
                    item["end_index"] = page_count
                
                # 涓哄瓙鑺傜偣璁剧疆鑼冨洿
                children = item.get("nodes", [])
                for i, child in enumerate(children):
                    if "start_index" not in child:
                        child["start_index"] = child.get("physical_index") or 1
                    if "end_index" not in child:
                        # 涓嬩竴涓厔寮熻妭鐐圭殑椤电爜 - 1锛屾垨鏂囨。鏈熬
                        if i < len(children) - 1:
                            next_page = children[i + 1].get("physical_index")
                            if next_page:
                                child["end_index"] = max(next_page - 1, child["start_index"])
                            else:
                                child["end_index"] = page_count
                        else:
                            child["end_index"] = page_count
                    
                    grandchildren = child.get("nodes", [])
                    for j, gc in enumerate(grandchildren):
                        if "start_index" not in gc:
                            gc["start_index"] = gc.get("physical_index") or 1
                        if "end_index" not in gc:
                            if j < len(grandchildren) - 1:
                                next_page = grandchildren[j + 1].get("physical_index")
                                if next_page:
                                    gc["end_index"] = max(next_page - 1, gc["start_index"])
                                else:
                                    gc["end_index"] = page_count
                            else:
                                # 浣跨敤鐖惰妭鐐圭殑缁撴潫椤电爜
                                gc["end_index"] = child.get("end_index", page_count)
                
                toc_tree.append(item)
            
            completeness = {
                "quality": "good",
                "coverage": 1.0,
                "gaps": [],
                "reaches_end": True,
                "ok": True,
                "needs_repair": False,
            }
            print(f"[INDEX-V3] Prebuilt tree preserved with {sum(len(item.get('nodes', [])) for item in toc_tree)} total entries")
        else:
            print(f"[INDEX-V3] Phase 2: post-processing {len(toc_items)} items")
            self._log_index_stage(5, "post_process", "started", input_items=len(toc_items))
            if execution_mode == "fast":
                toc_tree, completeness = post_process_toc(
                    toc_items,
                    page_count,
                    dividers=dividers,
                )
            else:
                toc_tree, completeness = post_process_toc(
                    toc_items,
                    page_count,
                    dividers=dividers,
                    analysis=analysis,
                    use_llm_grouping=True,
                    model=model,
                )
            self._log_index_stage(
                5,
                "post_process",
                "done",
                coverage=f"{completeness.get('coverage', 0):.0%}",
                needs_repair=completeness.get("needs_repair", False),
            )

        if completeness.get("needs_repair"):
            print(f"[INDEX-V3] Coverage needs repair: {completeness}")
            # TODO: gap 淇锛堝 gaps 鍖哄煙琛ュ厖鍒嗘瀽")

        # 鈹€鈹€鈹€ Phase 2.5: LLM 璐ㄩ噺妫€鏌?鈹€鈹€鈹€
        # 鍒濆鍖?result 鐢ㄤ簬瀛樺偍璐ㄦ缁撴灉
        await self._expand_visual_page_outline_with_vlm_fallback(
            toc_tree=toc_tree,
            analysis=analysis,
            page_count=page_count,
            toc_source=toc_source,
            page_list=page_list,
            model=model,
        )
        toc_tree, completeness = self._apply_balanced_quality_gate(
            toc_tree=toc_tree,
            analysis=analysis,
            completeness=completeness,
            page_count=page_count,
        )
        gate = completeness.get("balanced_quality_gate") or {}
        print(
            f"[BALANCED-QC] top_level_frozen_check: "
            f"ok={gate.get('top_level_exact_match')} "
            f"needs_repair={gate.get('needs_repair')}"
        )

        result = {"llm_quality_check": None}
        try:
            from pageindex.post_processing import llm_quality_check
            quality_result = await llm_quality_check(
                tree=toc_tree,
                toc_items=toc_items,
                page_count=page_count,
                source=toc_source or "unknown",
                has_dividers=bool(anchors and anchors.get("chapter_dividers")),
                divider_count=len(anchors.get("chapter_dividers", [])) if anchors else 0,
                model=model,
            )
            result["llm_quality_check"] = quality_result
            
            # 鏍规嵁璐ㄦ缁撴灉淇
            if quality_result.get("needs_repair"):
                print("[INDEX-V3] LLM-QC advisory suggestions detected")
                for suggestion in quality_result.get("suggestions", []):
                    if any(token in suggestion for token in ("子章节", "拆分", "sub-chapter", "split")):
                        print("[INDEX-V3] LLM-QC advisory: large-node detail can be improved")
                        # 鏍囪闇€瑕佸瓙绔犺妭鎻愬彇
                        break
        except Exception as e:
            print(f"[INDEX-V3] LLM quality check skipped: {e}")

        if execution_mode == "balanced":
            import asyncio as _aio
            from pageindex.page_index import process_large_node_recursively, JsonLogger

            logger = JsonLogger(str(file_path))
            tasks = [
                process_large_node_recursively(node, page_list, self.opt, logger=logger)
                for node in toc_tree
            ]
            await _aio.gather(*tasks)

        auxiliary_catalogs = self._build_auxiliary_catalog_nodes(analysis)
        if auxiliary_catalogs:
            toc_tree = self._merge_auxiliary_catalog_nodes(toc_tree, auxiliary_catalogs)
            print(
                f"[INDEX-V3] Added auxiliary catalogs: "
                f"{', '.join(node.get('title', '') for node in auxiliary_catalogs)}"
            )

        # 鈹€鈹€鈹€ Phase 3: 鑺傜偣濉厖 + 鎽樿 鈹€鈹€鈹€
        toc_tree = self._normalize_auxiliary_catalog_nodes(toc_tree)
        toc_tree = self._normalize_final_tree_schema(
            toc_tree,
            doc_id=doc_id,
            page_count=page_count,
        )
        print(f"[INDEX-V3] Phase 3: filling nodes + summaries (mode={execution_mode})")
        self._log_index_stage(6, "enrich", "started", mode=execution_mode)
        fill_node_text(toc_tree, page_list)
        write_node_ids(toc_tree)
        # 鈹€鈹€鈹€ 鏋勫缓杈撳嚭 鈹€鈹€鈹€
        # 淇濈暀涔嬪墠鐨勮川妫€缁撴灉
        llm_quality_check_result = result.get("llm_quality_check")
        result = {
            "doc_name": file_path.name,
            "doc_description": "",
            "page_count": page_count,
            "structure": toc_tree,
            "route_decision": {
                "requested_mode": requested_mode,
                "execution_mode": execution_mode,
                "initial_execution_mode": initial_execution_mode,
                "final_execution_mode": execution_mode,
                "balanced_path": balanced_path,
                "toc_source": toc_source,
                "text_coverage": analysis["text_coverage"],
                "is_image_only_pdf": analysis.get("is_image_only_pdf", False),
                "fallback_reason": analysis.get("code_toc_reject_reason"),
            },
            "completeness": completeness,
            "ocr_used": needs_ocr,
            "llm_quality_check": llm_quality_check_result,
            "enrichment_status": "pending",
        }

        # Save a usable base index before slower enrichment calls.
        index_path = self._save_index_payload(doc_id, result)
        print(f"[INDEX-V2] Saved base index before enrichment: {index_path}")

        await generate_summaries(toc_tree, model=model, mode=execution_mode)
        doc_description = await generate_doc_description(
            toc_tree, model=model, file_name=file_path.name
        )
        result["doc_description"] = doc_description
        result["enrichment_status"] = "done"
        self._log_index_stage(6, "enrich", "done")

        index_path = self._save_index_payload(doc_id, result)
        print(f"[INDEX-V2] Saved index: {index_path}")
        self._log_index_stage(7, "save", "done", index=index_path.name)

        return {"index_path": str(index_path), "structure": result}

    async def generate_index(
        self, file_path: str, doc_id: str, mode_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a PageIndex tree index for a document."""
        file_path = Path(file_path)

        if file_path.suffix.lower() == ".pdf":
            return await self._generate_index_v2(file_path, doc_id, mode_override)

        # 闈?PDF 鏂囦欢璧版棫娴佺▼
        self.opt = self._build_opt(mode_override=mode_override)

        visual_coverage = None
        if file_path.suffix.lower() == ".pdf":
            pre_analysis = self._pre_analyze_pdf(file_path)
            route = self._decide_pdf_route(
                getattr(self.opt, "index_mode", "balanced"),
                pre_analysis,
            )

            page_count = int(pre_analysis.get("page_count") or 0)
            has_images = int(pre_analysis.get("image_pages") or 0) > 0
            ocr_used = False
            ocr_pages: List[Dict[str, Any]] = []
            ocr_coverage = 0.0
            ocr_missing_pages: List[int] = []
            ocr_page_list: Optional[List[Any]] = None

            if has_images and page_count > 0:
                print(f"[OCR] start image-block OCR doc={doc_id} pages={page_count}")
                ocr_result = await self._run_full_pdf_ocr_by_images(
                    file_path, page_count
                )
                ocr_pages = list(ocr_result.get("ocr_pages") or [])
                ocr_coverage = float(ocr_result.get("ocr_coverage") or 0.0)
                ocr_missing_pages = [
                    int(p) for p in (ocr_result.get("ocr_missing_pages") or [])
                ]
                ocr_used = True
                base_page_list = get_page_tokens(
                    str(file_path),
                    model=getattr(self.opt, "model", None),
                    pdf_parser=pre_analysis.get("preferred_parser", "PyPDF2"),
                )
                ocr_page_list = self._build_page_list_with_ocr_overlay(
                    base_page_list=base_page_list,
                    ocr_pages=ocr_pages,
                    model=getattr(self.opt, "model", "qwen3.6-flash"),
                )
                print(
                    f"[OCR] done doc={doc_id} coverage={round(ocr_coverage, 4)} missing={len(ocr_missing_pages)}"
                )

            execution_mode = route["execution_mode"]
            self.opt = self._build_opt(mode_override=execution_mode)
            setattr(
                self.opt,
                "pdf_parser",
                pre_analysis.get("preferred_parser", "PyPDF2"),
            )
            setattr(self.opt, "file_path", str(file_path))

            # 鈹€鈹€鈹€ 涓よ疆 Fast TOC 鎻愬彇锛圤CR 鍓?+ OCR 鍚庯級鈹€鈹€鈹€
            fast_toc_result = None
            if execution_mode in ("fast", "smart"):
                import pageindex.page_index as _pi_mod

                extract_toc_code_only = _pi_mod.extract_toc_code_only
                validate_and_finalize_toc = _pi_mod.validate_and_finalize_toc
                _extract_toc_by_regex = _pi_mod._extract_toc_by_regex

                raw_page_list = None
                try:
                    raw_page_list = get_page_tokens(
                        str(file_path),
                        model=getattr(self.opt, "model", None),
                        pdf_parser=pre_analysis.get("preferred_parser", "PyPDF2"),
                    )
                    toc_items, source = extract_toc_code_only(
                        str(file_path), raw_page_list
                    )
                except Exception as e:
                    print(f"[FAST-TOC] Round 1 error: {e}")
                    toc_items, source = None, None

                # 绗簩杞細濡傛灉绗竴杞病鎴愬姛涓旀湁 OCR 鏂囨湰锛岀敤 OCR 鏂囨湰鍐嶈窇 Level 3
                if not toc_items and ocr_page_list:
                    try:
                        toc_items = _extract_toc_by_regex(ocr_page_list)
                        if toc_items:
                            source = "regex_ocr"
                            print(
                                f"[FAST-TOC] Level 3 OCR round: {len(toc_items)} items"
                            )
                    except Exception as e:
                        print(f"[FAST-TOC] Round 2 error: {e}")

                # 鏍￠獙
                if toc_items:
                    try:
                        # 浣跨敤 OCR page_list锛堝鏋滄湁锛夋垨鍘熷 page_list 杩涜 offset 鏍℃
                        correction_page_list = ocr_page_list or raw_page_list
                        fast_toc_result = await validate_and_finalize_toc(
                            toc_items,
                            source,
                            page_count,
                            model=getattr(self.opt, "model", None),
                            page_list=correction_page_list,
                        )
                    except Exception as e:
                        print(f"[FAST-TOC] Validation error: {e}")

                if not fast_toc_result:
                    requested = route.get("requested_mode", execution_mode)
                    if requested == "fast":
                        raise ValueError(
                            "FAST_TOC_INCOMPLETE: code extraction + validation failed"
                        )
                    # smart 妯″紡锛氬崌绾у埌 balanced
                    print(
                        "[FAST-TOC] Smart mode: fast extraction failed, escalating to balanced"
                    )
                    execution_mode = "balanced"
                    route["execution_mode"] = "balanced"
                    route["escalated_from_fast_quality"] = True
                    self.opt = self._build_opt(mode_override="balanced")
                    setattr(
                        self.opt,
                        "pdf_parser",
                        pre_analysis.get("preferred_parser", "PyPDF2"),
                    )
                    setattr(self.opt, "file_path", str(file_path))
                    fast_toc_result = None  # balanced 涓嶇敤 fast result

            def run_pageindex(opt_obj):
                # 浣跨敤澶栧眰宸插垱寤虹殑 hooks
                if ocr_page_list is None:
                    return page_index_main(
                        str(file_path), opt_obj, fast_toc_result=fast_toc_result, hooks=hooks
                    )
                return page_index_main_with_page_list(
                    doc_name=file_path.name,
                    page_list=ocr_page_list,
                    opt=opt_obj,
                    fast_toc_result=fast_toc_result,
                    hooks=hooks,
                )

            def run_balanced_once(reason: str) -> Dict[str, Any]:
                nonlocal execution_mode
                balanced_opt = self._build_opt(mode_override="balanced")
                setattr(
                    balanced_opt,
                    "pdf_parser",
                    pre_analysis.get("preferred_parser", "PyPDF2"),
                )
                execution_mode = "balanced"
                route["execution_mode"] = "balanced"
                route["escalated_from_fast_quality"] = True
                route["reasons"].append(reason)
                self.opt = balanced_opt
                return run_pageindex(balanced_opt)

            try:
                result = run_pageindex(self.opt)
            except ValueError as e:
                msg = str(e)
                if (
                    execution_mode == "fast"
                    and route.get("requested_mode") == "smart"
                    and msg.startswith("FAST_TOC_INCOMPLETE")
                ):
                    result = run_balanced_once(f"smart_fast_unavailable:{msg}")
                else:
                    raise

            if execution_mode == "fast":
                fast_gate = self._evaluate_fast_toc_readiness(result)
                route["fast_gate"] = fast_gate
                if not fast_gate.get("ok", False):
                    reason = str(fast_gate.get("reason") or "unknown")
                    if route.get("requested_mode") == "fast":
                        raise ValueError(f"FAST_TOC_INCOMPLETE: {reason}")
                    result = run_balanced_once(f"smart_fast_unavailable:{reason}")
            result["pre_analysis"] = pre_analysis
            result["route_decision"] = route
            result["ocr_used"] = ocr_used
            result["ocr_coverage"] = ocr_coverage
            result["ocr_missing_pages"] = ocr_missing_pages

            # 涓绘祦绋嬭川閲忛棬鎺э細浠?balanced 妯″紡鎵ц
            if execution_mode == "fast":
                structure_data = result.get("structure", result)
                # Fast mode skips LLM-based node summaries, fill from title/text
                self._ensure_structure_node_summaries(structure_data)
                quality = self._compute_structure_quality(structure_data)
                result["toc_quality"] = {
                    "before": quality,
                    "after": quality,
                    "text_health": self._compute_pdf_text_health(
                        file_path, pre_analysis
                    ),
                    "repaired": False,
                }
            else:
                structure_data = result.get("structure", result)
                quality_before = self._compute_structure_quality(structure_data)
                text_health = self._compute_pdf_text_health(file_path, pre_analysis)
                result["toc_quality"] = {
                    "before": quality_before,
                    "after": quality_before,
                    "text_health": text_health,
                    "repaired": False,
                }

            if execution_mode == "fast":
                # Fast mode: no visual processing, skip expensive computation
                result["visual_coverage"] = {
                    "visual_required_pages": 0,
                    "visual_success_pages": 0,
                    "visual_coverage": 1.0,
                    "downgraded": False,
                    "downgraded_pages": 0,
                    "daily_downgrade_rate": 0.0,
                    "downgrade_reasons": [],
                }
            else:
                page_results = result.get("visual_page_results", [])
                if not isinstance(page_results, list):
                    page_results = []
                visual_coverage = self.calculate_visual_coverage(page_results)
                if visual_coverage.get("visual_required_pages", 0) == 0:
                    visual_summaries = result.get("visual_page_summaries")
                    if isinstance(visual_summaries, list) and visual_summaries:
                        required = len(pre_analysis.get("vlm_needed_pages") or [])
                        success = len(visual_summaries)
                        visual_coverage = {
                            "visual_required_pages": required,
                            "visual_success_pages": success,
                            "visual_coverage": (success / required)
                            if required
                            else 1.0,
                            "downgraded": success < required,
                            "downgraded_pages": max(0, required - success),
                            "daily_downgrade_rate": ((required - success) / required)
                            if required
                            else 0.0,
                            "downgrade_reasons": [],
                        }
                result["visual_coverage"] = visual_coverage
        elif file_path.suffix.lower() in [".md", ".markdown"]:
            adapted = generate_multi_format_index(file_path)
            if adapted is not None:
                result = adapted
            else:
                # 鍏滃簳鍏煎锛氫繚鐣欏師鏈?md_to_tree 璺緞
                result = await md_to_tree(
                    md_path=str(file_path),
                    if_thinning=False,
                    min_token_threshold=None,
                    if_add_node_summary=self.opt.if_add_node_summary,
                    summary_token_threshold=200,
                    if_add_doc_description=self.opt.if_add_doc_description,
                    if_add_node_text=self.opt.if_add_node_text,
                    if_add_node_id="yes",
                    model=self.opt.model,
                )
        else:
            adapted = generate_multi_format_index(file_path)
            if adapted is None:
                raise ValueError(f"Unsupported file type: {file_path.suffix}")
            result = adapted

        index_path = INDEXES_DIR / f"{doc_id}.json"

        doc_description = ""
        page_count = None
        if isinstance(result, dict):
            doc_description = result.get("doc_description", "") or ""
            if "page_count" in result:
                page_count = result.get("page_count")
            elif file_path.suffix.lower() == ".pdf":
                # 浠?PDF 鏂囦欢鑾峰彇瀹為檯椤垫暟
                try:
                    with open(file_path, "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        page_count = len(pdf_reader.pages)
                except Exception as e:
                    print(f"[WARN] Failed to get PDF page count from {file_path}: {e}")
                    page_count = None

            # Fast mode generates a lightweight document summary in-flow.
            if (
                not doc_description
                and getattr(self.opt, "index_mode", "balanced") == "fast"
            ):
                structure_data = result.get("structure", result)
                doc_description = await self._generate_fast_light_doc_summary(
                    structure_data, file_path
                )
                if doc_description:
                    result["doc_description"] = doc_description
                else:
                    print(
                        f"[FAST_SUMMARY] final=empty doc={file_path.name} doc_id={doc_id}"
                    )

        self._attach_index_quality_report(
            result,
            page_count=page_count,
            force_pdf=file_path.suffix.lower() == ".pdf",
        )

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return {
            "index_path": str(index_path),
            "structure": result,
            "doc_description": doc_description,
            "page_count": page_count,
            "visual_coverage": visual_coverage,
            "index_mode": getattr(self.opt, "index_mode", "balanced"),
        }

    async def load_index(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Load a document index."""
        index_path = INDEXES_DIR / f"{doc_id}.json"
        if not index_path.exists():
            return None

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[PageIndexService] Warning: Index file corrupted for doc {doc_id}: {e}")
            return None

    @staticmethod
    def _build_search_structure_summary(
        nodes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        summary_rows: List[Dict[str, Any]] = []
        for node in nodes:
            summary = (node.get("summary") or "").strip()
            if not summary and node.get("text"):
                summary = str(node.get("text") or "")[:160]
            if not summary:
                summary = str(node.get("title") or "")[:160]

            start = node.get("start_index")
            end = node.get("end_index")
            pages = ""
            if start is not None and end is not None:
                pages = f"{start}-{end}"

            summary_rows.append(
                {
                    "node_id": node.get("node_id"),
                    "title": node.get("title"),
                    "summary": summary[:160] if summary else "",
                    "pages": pages,
                }
            )
        return summary_rows

    @staticmethod
    def _page_source_anchor(
        doc_name: str, start_index: Any, end_index: Any
    ) -> Optional[Dict[str, Any]]:
        if start_index is None:
            return None
        suffix = Path(doc_name).suffix.lstrip(".").lower() or "pdf"
        return {
            "format": suffix,
            "unit_type": "page",
            "start_page": start_index,
            "end_page": end_index if end_index is not None else start_index,
        }

    @classmethod
    def _retrieval_trace_fields(
        cls,
        doc_name: str,
        start_index: Any,
        end_index: Any,
        relevance: float,
        retrieval_source: str,
        why_selected: str,
    ) -> Dict[str, Any]:
        anchor = cls._page_source_anchor(doc_name, start_index, end_index)
        return {
            "retrieval_source": retrieval_source,
            "confidence": relevance,
            "why_selected": why_selected,
            "source_anchor": anchor,
            "display_label": (
                build_source_display_label(doc_name, anchor) if anchor else None
            ),
        }

    @staticmethod
    def _visual_summary_keyword_search(
        query: str,
        visual_summaries: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        doc_id: str,
        doc_name: str,
    ) -> List[Dict[str, Any]]:
        import re as _re

        q = (query or "").lower().replace(" ", "")
        if not q or not visual_summaries:
            return []

        raw_tokens = _re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", q)
        stopwords = set("搜索一下帮找一下请什么是的有吗呢了啊关于介绍下帮我")
        kws = [t for t in raw_tokens if len(t) > 1 or t not in stopwords]
        if not kws:
            kws = [q]

        node_ranges: List[Dict[str, Any]] = []
        for n in nodes:
            try:
                s = int(n.get("start_index") or 0)
                e = int(n.get("end_index") or 0)
            except Exception:
                continue
            if s > 0 and e >= s:
                node_ranges.append(n)

        candidates: List[Dict[str, Any]] = []
        for item in visual_summaries:
            page = int(item.get("page_num") or 0)
            summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if page <= 0 or not summary:
                continue
            hay = summary.lower().replace(" ", "")
            hit_count = sum(1 for kw in kws if kw and kw in hay)
            if q in hay:
                hit_count += 2
            if hit_count <= 0:
                continue

            target = None
            for n in node_ranges:
                s = int(n.get("start_index") or 0)
                e = int(n.get("end_index") or 0)
                if s <= page <= e:
                    target = n
                    break
            if target is None:
                continue

            score = min(0.92, 0.45 + 0.08 * hit_count)
            relevance = round(score, 3)
            candidates.append(
                {
                    "document_id": doc_id,
                    "document_name": doc_name,
                    "node_id": target.get("node_id"),
                    "node_title": target.get("title"),
                    "start_index": target.get("start_index"),
                    "end_index": target.get("end_index"),
                    "summary": summary[:300],
                    "full_text": summary,
                    "reasoning": f"visual_summary_hit:p.{page}",
                    "relevance": relevance,
                    "source": "visual_summary",
                    **PageIndexService._retrieval_trace_fields(
                        doc_name,
                        target.get("start_index"),
                        target.get("end_index"),
                        relevance,
                        "visual_summary",
                        "Matched visual page summary.",
                    ),
                }
            )

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in sorted(
            candidates, key=lambda x: x.get("relevance", 0), reverse=True
        ):
            nid = str(item.get("node_id") or "")
            if not nid:
                continue
            if nid not in dedup:
                dedup[nid] = item
        return list(dedup.values())[:3]

    async def search_in_structure_async(
        self,
        structure: Dict[str, Any],
        query: str,
        doc_id: str,
        doc_name: str,
        user_id: str = "legacy",
    ) -> List[Dict[str, Any]]:
        """Use LLM reasoning to search the tree structure."""
        from app.core.llm import async_chat_completion
        from app.services.cache_service import cache_service

        cached_result = cache_service.get_search_result(user_id, query, [doc_id])
        if cached_result is not None:
            print(f"[CACHE] Search cache hit for query: {query[:30]}...")
            return cached_result

        if "structure" in structure:
            structure_data = structure["structure"]
        else:
            structure_data = structure
        visual_summaries = (
            structure.get("visual_page_summaries", [])
            if isinstance(structure, dict)
            else []
        )

        nodes = structure_to_list(structure_data)
        structure_summary = self._build_search_structure_summary(nodes)

        prompt = f"""Analyze the document TOC structure and find the chapters most relevant to the user query.

TOC structure:
{json.dumps(structure_summary, ensure_ascii=False, indent=2)}

User query: {query}

Return the most relevant 2-3 chapters as JSON:
[{{"node_id": "node id", "reasoning": "why relevant", "relevance_score": 0.0}}]

Return JSON only."""

        try:
            response = await async_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                model="qwen3.6-flash",
            )
            content = response.choices[0].message.content

            # 瑙ｆ瀽 JSON
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                llm_results = json.loads(json_match.group())
            else:
                llm_results = []

            results = []
            node_dict = {n.get("node_id"): n for n in nodes}

            for item in llm_results:
                node_id = item.get("node_id")
                if node_id in node_dict:
                    node = node_dict[node_id]
                    # 鑾峰彇鏂囨湰鍐呭
                    text = node.get("text", "")
                    relevance = item.get("relevance_score", 0.5)
                    reasoning = item.get("reasoning", "")

                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node_id,
                            "node_title": node.get("title"),
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": text[:300] if text else "",  # 鎽樿鐢ㄤ簬灞曠ず
                            "full_text": text,  # 瀹屾暣鍘熸枃鐢ㄤ簬鎺ㄧ悊
                            "reasoning": reasoning,
                            "relevance": relevance,
                            **self._retrieval_trace_fields(
                                doc_name,
                                node.get("start_index"),
                                node.get("end_index"),
                                relevance,
                                "tree_reasoning",
                                reasoning or "Selected by tree reasoning.",
                            ),
                        }
                    )

            if results:
                verified_results = await verify_candidate_nodes(
                    candidates=results,
                    query=query,
                    nodes=nodes,
                    model="qwen3.6-flash",
                )
                results = verified_results

                filtered_results = [
                    r
                    for r in results
                    if not (
                        r.get("verification_passed") == False
                        and r.get("verification_confidence", 0) > 0.7
                    )
                ]

                if not filtered_results and results:
                    filtered_results = [results[0]]

                results = filtered_results

            visual_candidates = self._visual_summary_keyword_search(
                query=query,
                visual_summaries=(
                    visual_summaries if isinstance(visual_summaries, list) else []
                ),
                nodes=nodes,
                doc_id=doc_id,
                doc_name=doc_name,
            )
            if visual_candidates:
                existing_ids = {str(x.get("node_id") or "") for x in results}
                for vc in visual_candidates:
                    nid = str(vc.get("node_id") or "")
                    if nid and nid not in existing_ids:
                        results.append(vc)
                        existing_ids.add(nid)

            # 鎸夌浉鍏冲害鍜岄獙璇佺疆淇″害缁煎悎鎺掑簭
            results.sort(
                key=lambda x: (
                    x.get("relevance", 0)
                    * max(x.get("verification_confidence", 0.5), 0.1)
                ),
                reverse=True,
            )

            final_results = results[:3]

            # 缂撳瓨缁撴灉
            cache_service.set_search_result(user_id, query, [doc_id], final_results)

            return final_results

        except Exception as e:
            print(f"LLM search error: {e}")
            return self._simple_search(structure_data, query, doc_id, doc_name)

    def _simple_search(
        self, structure_data: Dict[str, Any], query: str, doc_id: str, doc_name: str
    ) -> List[Dict[str, Any]]:
        """Simple keyword search fallback."""


        import re as _re

        nodes = structure_to_list(structure_data)
        results = []

        # 娓呯悊鏌ヨ
        query_clean = query.lower().replace(" ", "")

        # 鎻愬彇鍏抽敭璇嶏細鑻辨枃璇?+ 涓枃2瀛楄瘝 + 涓枃鍗曞瓧
        stopwords = set("搜索一下帮找一下请什么是的有吗呢了啊关于介绍下帮我")
        raw_tokens = _re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query_clean)
        # 淇濈暀鑻辨枃璇嶅拰涓嶅湪鍋滅敤璇嶈〃涓殑涓枃瀛楃
        keywords = [t for t in raw_tokens if len(t) > 1 or t not in stopwords]
        # 鍚屾椂鐢熸垚鐩搁偦涓ゅ瓧缁勫悎锛堟ā鎷熶腑鏂囧垎璇嶏級
        bigrams = []
        cn_chars = [t for t in raw_tokens if len(t) == 1 and t not in stopwords]
        for i in range(len(cn_chars) - 1):
            bigrams.append(cn_chars[i] + cn_chars[i + 1])
        all_keywords = keywords + bigrams

        for node in nodes:
            title = node.get("title", "")
            text = node.get("text", "")
            summary = (node.get("summary") or "")[:100]
            title_lower = title.lower().replace(" ", "")
            text_lower = text.lower().replace(" ", "")
            search_content = f"{title} {text} {summary}".lower().replace(" ", "")

            # 绗竴绾э細鍏ㄤ覆鍖归厤
            if query_clean in search_content:
                relevance = 0.9
                results.append(
                    {
                        "document_id": doc_id,
                        "document_name": doc_name,
                        "node_id": node.get("node_id"),
                        "node_title": title,
                        "start_index": node.get("start_index"),
                        "end_index": node.get("end_index"),
                        "summary": text[:200] if text else "",
                        "relevance": relevance,
                        **self._retrieval_trace_fields(
                            doc_name,
                            node.get("start_index"),
                            node.get("end_index"),
                            relevance,
                            "keyword_fallback",
                            "Matched fallback keyword search.",
                        ),
                    }
                )
                continue

            # 绗簩绾э細鍏抽敭璇?鎷嗗瓧鍖归厤
            if all_keywords:
                hit_count = sum(1 for kw in all_keywords if kw in search_content)
                title_hits = sum(1 for kw in all_keywords if kw in title_lower)
                text_hits = sum(1 for kw in all_keywords if kw in text_lower)
                min_hits = min(2, len(all_keywords)) if len(all_keywords) >= 2 else 1
                if hit_count >= min_hits:
                    base = 0.3 + hit_count * 0.05
                    title_bonus = title_hits * 0.15
                    text_density = min(text_hits * 0.02, 0.2)
                    relevance = round(
                        min(base + title_bonus + text_density, 0.89), 2
                    )
                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node.get("node_id"),
                            "node_title": title,
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": text[:200] if text else "",
                            "relevance": relevance,
                            **self._retrieval_trace_fields(
                                doc_name,
                                node.get("start_index"),
                                node.get("end_index"),
                                relevance,
                                "keyword_fallback",
                                "Matched fallback keyword search.",
                            ),
                        }
                    )

        # 鎸夌浉鍏冲害鎺掑簭
        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return results[:3]

    def search_in_structure(
        self, structure: Dict[str, Any], query: str, doc_id: str, doc_name: str
    ) -> List[Dict[str, Any]]:
        """Synchronous search compatibility wrapper."""

        # Normalize index payload format.
        if "structure" in structure:
            structure_data = structure["structure"]
        else:
            structure_data = structure

        return self._simple_search(structure_data, query, doc_id, doc_name)

    async def reasoning_search(
        self,
        structure: Dict[str, Any],
        query: str,
        doc_id: str,
        doc_name: str,
        pdf_text: str = None,
    ) -> List[Dict[str, Any]]:
        """Use LLM reasoning to search the document tree."""
        from app.core.llm import async_chat_completion

        nodes = structure_to_list(structure)
        structure_summary = self._build_search_structure_summary(nodes)

        prompt = f"""You are a document retrieval expert. Given the document TOC and user query, find the most relevant chapters.

TOC structure:
{json.dumps(structure_summary, ensure_ascii=False, indent=2)}

User query: {query}

Return JSON only:
[
  {{
    "node_id": "node id",
    "title": "chapter title",
    "reasoning": "why this chapter is relevant",
    "relevance_score": 0.0
  }}
]"""

        try:
            response = await async_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a document retrieval expert.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )
            content = response.choices[0].message.content

            # 瑙ｆ瀽 JSON
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                llm_results = json.loads(json_match.group())
            else:
                llm_results = []

            results = []
            node_dict = {n.get("node_id"): n for n in nodes}

            for item in llm_results:
                node_id = item.get("node_id")
                if node_id in node_dict:
                    node = node_dict[node_id]
                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node_id,
                            "node_title": node.get("title"),
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": node.get("summary", ""),
                            "reasoning": item.get("reasoning", ""),
                            "relevance": item.get("relevance_score", 0.5),
                        }
                    )

            # 鎸夌浉鍏冲害鎺掑簭
            results.sort(key=lambda x: x["relevance"], reverse=True)
            return results[:5]

        except Exception as e:
            print(f"Reasoning search error: {e}")
            return self.search_in_structure(structure, query, doc_id, doc_name)
