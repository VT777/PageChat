import sys
import json
import asyncio
import inspect
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

# 婵烇綀婵?pageindex 闁?Python 閻犱警鍨扮欢?
sys.path.insert(0, str(Path(__file__).parent.parent))

from pageindex.utils import config, get_nodes, get_page_tokens, structure_to_list
from pageindex.page_index_md import md_to_tree
from pageindex.index_quality import TocQualityChecker, build_index_quality_report
from app.models.retrieval import build_source_display_label
from app.core.config import (
    DATA_DIR,
    INDEXES_DIR,
    build_effective_pageindex_config,
    PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED,
    PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES,
    PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS,
    PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD,
    PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD,
    PAGEINDEX_TOC_LLM_MAX_TOKENS,
    PAGEINDEX_TOC_LLM_TIMEOUT_SECONDS,
    OCR_MAX_CONCURRENCY,
)
from app.prompts.pageindex_prompts import (
    QUERY_VERIFICATION_PROMPT,
    FAST_DOC_LIGHT_SUMMARY_PROMPT,
    TOC_DETECTOR_SINGLE_PROMPT,
)
from app.services.multi_format_adapter import generate_multi_format_index
from app.services.model_gateway import ModelGateway
from app.services.ocr_service import OCRService
from app.services.runtime_settings_service import runtime_settings_service


TREE_HIGH_CONFIDENCE_THRESHOLD = 0.65
TREE_FALLBACK_CONFIDENCE_THRESHOLD = 0.35


class _ModelSettingsResolverProxy:
    async def resolve_route(self, user_id: str | None, route_slot: str) -> Dict[str, Any]:
        import aiosqlite

        from app.models.database import DB_PATH
        from app.services.model_settings_service import ModelSettingsService

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            return await ModelSettingsService(db).resolve_route(user_id, route_slot)


async def check_query_appearance(
    query: str,
    node_text: str,
    model: str = "qwen3.6-flash",
    provider_config: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    濡ょ姴鐭侀惁澶愭偨閵婏箑鐓曢柡灞诲劥椤曟寮伴姘剨闁告垼娅ｉ獮鍥捶閵娿劌螡闁绘劘閺嬪啴寮甸鑳幀

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
            provider_config=provider_config,
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
    provider_config: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    """
    濡ょ姴鐭侀惁?LLM 闂佺€氥劑鎯冮崟鍋撳▎鎾亾婢跺骸螡闁绘劘濡叉悂宕ラ敂鐐焸闁汇劌瀚€垫﹢宕ラ锝囧弨閻犲洢鍨归崬瀵糕偓?
    Args:
        candidates: LLM 閺夆晜鏌ㄥú鏍儍閸曞亾濞嗘挴鍋撴径濠傜仚閻?        query: 闁诲妽閸╂盯寮婚妷鍤?
        nodes: 闁圭鍋撻柡鍫濇俊鎮欓崷鐣遍悗鐟版湰閺嗭絾绌遍埄鍐х礀 (from structure_to_list)
        model: 濡ょ姴鐭侀惁澶愭偨閵娧勭暠婵♀偓宕団偓?

    Returns:
        閻㈢畵閻涙瑧鎷犳担绋跨€婚柡浣瑰濞堟垿宕愬▎鎾亾婢跺﹤鐏欓悶?    """
    node_dict = {n.get("node_id"): n for n in nodes}
    verified_results = []

    async def verify_one(candidate):
        node_id = candidate.get("node_id")
        if node_id in node_dict:
            node = node_dict[node_id]
            text = node.get("text", "") or ""
            return await check_query_appearance(
                query, text, model, provider_config=provider_config
            )
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

    def __init__(self, user_id: str | None = None):
        self.user_id = user_id
        self._model_route_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self.opt = self._build_opt()

    async def _resolve_model_route(self, route_slot: str) -> Optional[Dict[str, Any]]:
        if not self.user_id:
            return None
        if route_slot in self._model_route_cache:
            return self._model_route_cache[route_slot]
        try:
            import aiosqlite

            from app.models.database import DB_PATH
            from app.services.model_settings_service import ModelSettingsService

            async with aiosqlite.connect(str(DB_PATH)) as db:
                db.row_factory = aiosqlite.Row
                route = await ModelSettingsService(db).resolve_route(
                    self.user_id, route_slot
                )
                if route.get("source") != "user":
                    route = None
        except Exception as exc:
            print(
                f"[TOC-MODEL] fallback route_slot={route_slot} user_id={self.user_id} error_type={type(exc).__name__}"
            )
            route = None
        self._model_route_cache[route_slot] = route
        return route

    async def _indexing_completion(
        self,
        *,
        messages: list[dict],
        model: str | None = None,
        **kwargs,
    ):
        from app.core.llm import async_chat_completion

        route = await self._resolve_model_route("indexing")
        if route:
            return await async_chat_completion(
                messages=messages,
                model=route.get("model") or model,
                provider_config=route,
                **kwargs,
            )
        return await async_chat_completion(messages=messages, model=model, **kwargs)

    async def _build_model_gateway(self):
        route = await self._resolve_model_route("vision")
        if not route:
            return ModelGateway()
        return ModelGateway(
            model_settings_service=_ModelSettingsResolverProxy(),
            user_id=self.user_id,
        )

    @staticmethod
    def _sanitize_model_route_metadata(route: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(route, dict):
            return {}
        metadata = {}
        for key in ("route_slot", "source", "model", "route_version"):
            value = route.get(key)
            if value is not None:
                metadata[key] = value
        return metadata

    async def _model_route_metadata(self) -> Dict[str, Dict[str, Any]]:
        metadata: Dict[str, Dict[str, Any]] = {}
        for slot in ("indexing",):
            route = await self._resolve_model_route(slot)
            clean = self._sanitize_model_route_metadata(route)
            if clean:
                metadata[slot] = clean
        return metadata

    @staticmethod
    def _persist_failure_diagnostics(doc_id: str, payload: Dict[str, Any]) -> None:
        try:
            INDEXES_DIR.mkdir(parents=True, exist_ok=True)
            index_path = INDEXES_DIR / f"{doc_id}.json"
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[TOC-DIAG] failed to persist diagnostics doc={doc_id}: {e}")

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
        raw = str(text or "").strip()
        if not raw:
            return ""

        stripped = PageIndexService._strip_ocr_code_fences(raw)
        json_text = PageIndexService._extract_reading_order_text_from_json(stripped)
        if json_text:
            return json_text
        html_text = PageIndexService._extract_reading_order_text_from_html(stripped)
        if html_text:
            return html_text
        return PageIndexService._normalize_reading_order_text(stripped)

    @staticmethod
    def _strip_ocr_code_fences(text: str) -> str:
        lines = str(text or "").strip().splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_reading_order_text(text: str) -> str:
        output: List[str] = []
        for line in str(text or "").splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("```"):
                continue
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                output.append(cleaned)
        if output:
            joined = "\n".join(output)
            if PageIndexService._looks_like_coordinate_dump(joined):
                return ""
            return joined
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _looks_like_coordinate_dump(text: str) -> bool:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            return False

        coord_like = 0
        for line in lines:
            if re.fullmatch(r"[\d,\s.-]{8,}", line) and len(re.findall(r"\d", line)) >= 5:
                coord_like += 1
                continue
            if re.fullmatch(r"\d{1,4}(?:\s*,\s*\d{1,4}){2,}", line):
                coord_like += 1
        return coord_like >= max(2, len(lines) - 1)

    @staticmethod
    def _extract_reading_order_text_from_json(text: str) -> str:
        value = str(text or "").strip()
        if not value or value[0] not in "[{":
            return ""
        try:
            payload = json.loads(value)
        except Exception:
            return ""

        preferred_keys = ("text", "title", "content", "markdown", "plain_text", "block_content")
        child_keys = ("children", "nodes", "items", "data", "result", "results", "pages")
        skip_keys = {
            "level", "page", "page_num", "pos_list", "bbox", "box", "score",
            "width", "height", "model", "label", "type", "role", "id",
        }
        lines: List[str] = []

        def add_text(value: Any) -> None:
            normalized = PageIndexService._normalize_reading_order_text(str(value or ""))
            for line in normalized.splitlines():
                if line:
                    lines.append(line)

        def walk(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if isinstance(value, dict):
                consumed = set()
                for key in preferred_keys:
                    field = value.get(key)
                    if isinstance(field, str) and field.strip():
                        add_text(field)
                        consumed.add(key)
                for key in child_keys:
                    if key in value:
                        walk(value.get(key))
                        consumed.add(key)
                for key, field in value.items():
                    if key in consumed or key in skip_keys:
                        continue
                    if isinstance(field, (dict, list)):
                        walk(field)
                return
            if isinstance(value, str) and value.strip():
                add_text(value)

        walk(payload)
        seen: set[str] = set()
        deduped: List[str] = []
        for line in lines:
            key = line.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return "\n".join(deduped)

    @staticmethod
    def _extract_reading_order_text_from_html(text: str) -> str:
        value = str(text or "").strip()
        if not re.search(r"<\s*[A-Za-z][^>]*>", value):
            return ""
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            block_tags = {"br", "p", "div", "section", "article", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}

            def __init__(self) -> None:
                super().__init__()
                self.parts: List[str] = []

            def _break(self) -> None:
                if self.parts and self.parts[-1] != "\n":
                    self.parts.append("\n")

            def handle_starttag(self, tag: str, attrs) -> None:
                if tag.lower() in self.block_tags:
                    self._break()

            def handle_endtag(self, tag: str) -> None:
                if tag.lower() in self.block_tags:
                    self._break()

            def handle_data(self, data: str) -> None:
                cleaned = re.sub(r"\s+", " ", data).strip()
                if cleaned:
                    self.parts.append(cleaned)

        parser = TextExtractor()
        try:
            parser.feed(value)
        except Exception:
            return ""
        return PageIndexService._normalize_reading_order_text("".join(parser.parts))

    async def _resolve_ocr_engine(self, task: str):
        import aiosqlite

        from app.models.database import DB_PATH
        from app.services.ocr_engines.resolver import OCREngineResolver
        from app.services.ocr_settings_service import OCRSettingsService

        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row
            return await OCREngineResolver(
                settings_service=OCRSettingsService(db)
            ).resolve(self.user_id, task)

    @staticmethod
    def _ocr_call_diagnostics(resolved, response, task: str) -> Dict[str, Any]:
        route = dict(getattr(resolved, "route", {}) or {})
        diagnostics = dict(getattr(response, "diagnostics", {}) or {})
        raw = getattr(response, "raw", {}) or {}
        if isinstance(raw.get("diagnostics"), dict):
            diagnostics = {**raw["diagnostics"], **diagnostics}
        pages = list(getattr(response, "pages", []) or [])
        evidence_levels = sorted(
            {
                str(getattr(page, "evidence_level", "") or "")
                for page in pages
                if getattr(page, "evidence_level", "")
            }
        )
        merged = {
            "task": task,
            "source": route.get("source"),
            "engine_type": route.get("engine_type"),
            "model": route.get("model"),
            "profile_version": route.get("profile_version"),
        }
        for key in (
            "profile_id",
            "prompt_name",
            "prompt_version",
            "prompt_text",
            "prompt_sha256",
            "prompt_chars",
            "input_type",
            "elapsed_ms",
            "result_pages",
            "job_id",
            "requested_pages",
            "rendered_pages",
            "rendered_page_inputs",
            "fallback_reason",
            "fallback_error_type",
        ):
            if diagnostics.get(key) is not None:
                merged[key] = diagnostics[key]
        if diagnostics.get("evidence_level"):
            merged["evidence_level"] = diagnostics["evidence_level"]
        elif evidence_levels:
            merged["evidence_level"] = evidence_levels[0] if len(evidence_levels) == 1 else ",".join(evidence_levels)
        if "result_pages" not in merged:
            merged["result_pages"] = len(pages)
        return {key: value for key, value in merged.items() if value is not None}

    @staticmethod
    def _record_ocr_call(
        analysis: Optional[Dict[str, Any]],
        call_diagnostics: Dict[str, Any],
        *,
        page_num: Optional[int] = None,
        status: Optional[str] = None,
    ) -> None:
        if analysis is None:
            return
        record = dict(call_diagnostics or {})
        if page_num is not None:
            record["page_num"] = page_num
        if status:
            record["status"] = status
        analysis.setdefault("ocr_calls", []).append(record)
        analysis["ocr_route"] = dict(call_diagnostics or {})

        task = str(record.get("task") or "")
        if not task:
            return
        summaries = analysis.setdefault("ocr_calls_summary", {})
        summary = summaries.setdefault(task, {})
        if task == "page_text":
            summary["calls"] = int(summary.get("calls") or 0) + 1
            if page_num is not None:
                seen = list(summary.get("page_nums") or [])
                if page_num not in seen:
                    seen.append(page_num)
                summary["page_nums"] = sorted(seen)
                summary["pages"] = len(seen)
            if not summary.get("primary_engine"):
                summary["primary_engine"] = record.get("engine_type")
            if not summary.get("primary_model"):
                summary["primary_model"] = record.get("model")
            if status == "ok":
                summary["success"] = int(summary.get("success") or 0) + 1
            elif status == "missing":
                summary["missing"] = int(summary.get("missing") or 0) + 1
            if record.get("fallback_reason") or str(record.get("engine_type") or "").startswith("legacy"):
                summary["fallback"] = int(summary.get("fallback") or 0) + 1
            return

        summary["engine"] = record.get("engine_type")
        summary["model"] = record.get("model")
        summary["pages"] = record.get("result_pages")
        summary["status"] = status or "done"

    @staticmethod
    def _update_content_ocr_summary(
        analysis: Optional[Dict[str, Any]],
        *,
        page_count: int,
        success: int,
        missing: List[int],
    ) -> Dict[str, Any]:
        if analysis is None:
            return {}
        summaries = analysis.setdefault("ocr_calls_summary", {})
        summary = summaries.setdefault("page_text", {})
        summary["pages"] = page_count
        summary["success"] = success
        summary["missing"] = len(missing)
        summary["missing_pages"] = list(missing[:10])
        summary.setdefault("fallback", 0)
        return summary

    @staticmethod
    async def _close_ocr_adapter(adapter: Any) -> None:
        close = getattr(adapter, "aclose", None) or getattr(adapter, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _ocr_image_with_resolver(
        self,
        image_base64: str,
        page_num: int,
        analysis: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None,
    ):
        from app.services.ocr_service import OCRPageResult

        resolved = await self._resolve_ocr_engine("page_text")
        try:
            image_url = f"data:image/png;base64,{image_base64}"
            route_options = dict((resolved.route or {}).get("options") or {})
            if prompt:
                route_options["prompt"] = prompt
                route_options.setdefault("prompt_name", "page_text_reading_order_v1")
            response = resolved.adapter.recognize(
                image_url,
                task="page_text",
                options=route_options,
            )
            if hasattr(response, "__await__"):
                response = await response
            call_diagnostics = self._ocr_call_diagnostics(resolved, response, "page_text")
            text = ""
            for page in getattr(response, "pages", []) or []:
                if int(getattr(page, "page_num", page_num) or page_num) == page_num:
                    text = getattr(page, "plain_text", "") or getattr(page, "markdown", "") or ""
                    break
            if not text and getattr(response, "pages", None):
                first_page = response.pages[0]
                text = getattr(first_page, "plain_text", "") or getattr(first_page, "markdown", "") or ""
            self._record_ocr_call(
                analysis,
                call_diagnostics,
                page_num=page_num,
                status="ok" if text.strip() else "missing",
            )
            return OCRPageResult(page_num=page_num, text=text.strip(), ok=bool(text.strip()))
        finally:
            await self._close_ocr_adapter(getattr(resolved, "adapter", None))

    async def _build_layout_with_resolver(
        self,
        file_path: Path,
        page_count: int,
        analysis: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ):
        from pageindex.layout.ocr_normalizer import normalize_ocr_document

        resolved = await self._resolve_ocr_engine("toc_page")
        try:
            route = resolved.route or {}
            engine_type = str(route.get("engine_type") or "")
            model_name = str(route.get("model") or "")
            if engine_type == "openai_compatible_ocr" or "vl" in model_name.lower():
                response = await self._recognize_toc_pages_with_vl(
                    resolved,
                    file_path=file_path,
                    page_count=page_count,
                    analysis=analysis,
                )
            else:
                response = resolved.adapter.recognize(
                    str(file_path),
                    task="toc_page",
                    options=route.get("options") or {},
                )
            if hasattr(response, "__await__"):
                response = await response
            call_diagnostics = self._ocr_call_diagnostics(resolved, response, "toc_page")
            if doc_id:
                diag_path = self._persist_ocr_diagnostics(
                    doc_id,
                    task="toc_page",
                    response=response,
                    call_diagnostics=call_diagnostics,
                )
                if diag_path is not None and analysis is not None:
                    call_diagnostics = {
                        **call_diagnostics,
                        "diagnostics_path": str(diag_path),
                    }
            if analysis is not None:
                analysis["ocr_route"] = call_diagnostics
                analysis.setdefault("ocr_calls", []).append(call_diagnostics)
                analysis.setdefault("ocr_calls_summary", {})["toc_page"] = {
                    "engine": call_diagnostics.get("engine_type"),
                    "model": call_diagnostics.get("model"),
                    "pages": call_diagnostics.get("result_pages"),
                    "status": "done",
                }
                if call_diagnostics.get("diagnostics_path"):
                    analysis["ocr_calls_summary"]["toc_page"]["diagnostics_path"] = call_diagnostics.get("diagnostics_path")
            diag_suffix = ""
            if call_diagnostics.get("diagnostics_path"):
                diag_suffix = f" diagnostics={call_diagnostics.get('diagnostics_path')}"
            print(
                f"[TOC-OCR] task=toc_page status=done engine={call_diagnostics.get('engine_type')} "
                f"model={call_diagnostics.get('model')} pages={call_diagnostics.get('result_pages', 0)}"
                f"{diag_suffix}"
            )
            return normalize_ocr_document(
                response,
                doc_id=str(file_path),
                page_count=page_count,
            )
        finally:
            await self._close_ocr_adapter(getattr(resolved, "adapter", None))

    async def _recognize_toc_pages_with_vl(
        self,
        resolved,
        *,
        file_path: Path,
        page_count: int,
        analysis: Optional[Dict[str, Any]] = None,
    ):
        from app.services.ocr_engines.contracts import OCRDocumentResult
        from pageindex.layout.page_renderer import render_pages_to_images

        route_options = dict((resolved.route or {}).get("options") or {})
        batch_size = self._toc_detector_batch_size(analysis)
        scan_limit = self._toc_detector_scan_limit(analysis, page_count)
        model = getattr(self.opt, "model", "qwen3.6-flash")

        confirmed_pages = self._confirmed_toc_pages_from_analysis(analysis, page_count)
        explicit_page_indices = [page - 1 for page in confirmed_pages]
        scan_mode = not explicit_page_indices and page_count > batch_size

        pages = []
        diagnostics = None
        raw_results = []
        rendered_inputs = []
        rendered_page_numbers: List[int] = []
        detection_candidates: List[Dict[str, Any]] = []
        detected_pages: List[int] = []
        seen_toc = False
        stop_reason = "scan_exhausted"
        batch_count = 0
        classified_count = 0
        ocr_sem = asyncio.Semaphore(min(batch_size, max(1, int(OCR_MAX_CONCURRENCY))))

        async def recognize_image(image: Dict[str, Any]) -> Dict[str, Any]:
            physical_page = int(image.get("page_index") or 0) + 1
            image_mime_type = str(image.get("image_mime_type") or "image/jpeg")
            rendered_input = {
                "page_num": physical_page,
                "page_index": int(image.get("page_index") or 0),
                "dpi": image.get("dpi") or 150,
                "image_format": image.get("image_format") or "jpeg",
                "image_mime_type": image_mime_type,
                "image_sha256": image.get("image_sha256"),
                "width": image.get("width"),
                "height": image.get("height"),
            }
            rendered_input = {key: value for key, value in rendered_input.items() if value is not None}
            image_url = f"data:{image_mime_type};base64,{image.get('image_base64') or ''}"
            async with ocr_sem:
                response = resolved.adapter.recognize(
                    image_url,
                    task="toc_page",
                    options=route_options,
                )
                if hasattr(response, "__await__"):
                    response = await response
            raw_result = dict(getattr(response, "raw", {}) or {})
            raw_result["rendered_input"] = rendered_input
            page_results = []
            for page in getattr(response, "pages", []) or []:
                page.page_num = physical_page
                if not getattr(page, "width", 0):
                    page.width = int(image.get("width") or 0)
                if not getattr(page, "height", 0):
                    page.height = int(image.get("height") or 0)
                page_results.append(page)
            return {
                "physical_page": physical_page,
                "rendered_input": rendered_input,
                "raw_result": raw_result,
                "diagnostics": dict(getattr(response, "diagnostics", {}) or {}),
                "pages": page_results,
            }

        async def recognize_batch(page_indices: List[int]) -> List[Any]:
            nonlocal diagnostics
            images = render_pages_to_images(str(file_path), page_indices, dpi=150)
            results = await asyncio.gather(*(recognize_image(image) for image in images))
            batch_pages = []
            for result in sorted(results, key=lambda item: int(item.get("physical_page") or 0)):
                rendered_inputs.append(result["rendered_input"])
                raw_results.append(result["raw_result"])
                rendered_page_numbers.append(int(result["physical_page"]))
                if result.get("diagnostics"):
                    diagnostics = dict(result.get("diagnostics") or diagnostics or {})
                for page in result.get("pages") or []:
                    pages.append(page)
                    batch_pages.append(page)
            return batch_pages

        if not scan_mode:
            page_indices = explicit_page_indices or self._toc_probe_page_indices(analysis or {}, page_count)
            for offset in range(0, len(page_indices), batch_size):
                batch_count += 1
                await recognize_batch(page_indices[offset : offset + batch_size])
        else:
            cursor = 0
            scanned_count = 0
            while cursor < page_count:
                if not seen_toc and scanned_count >= scan_limit:
                    stop_reason = "scan_limit_reached"
                    break
                if seen_toc:
                    take = min(batch_size, page_count - cursor)
                else:
                    take = min(batch_size, page_count - cursor, scan_limit - scanned_count)
                if take <= 0:
                    stop_reason = "scan_limit_reached"
                    break
                page_indices = list(range(cursor, cursor + take))
                batch_count += 1
                batch_pages = await recognize_batch(page_indices)
                scanned_count += len(page_indices)
                cursor += len(page_indices)
                batch_candidates = await self._classify_toc_pages_with_llm(
                    batch_pages,
                    model=model,
                    batch_index=batch_count,
                )
                classified_count += len(batch_candidates)
                seen_toc, should_stop, stop_reason = self._consume_toc_detection_candidates(
                    batch_candidates,
                    detected_pages=detected_pages,
                    candidates=detection_candidates,
                    seen_toc=seen_toc,
                )
                if should_stop:
                    break
                if seen_toc:
                    last_batch_page = page_indices[-1] + 1
                    if last_batch_page in detected_pages:
                        stop_reason = "scan_exhausted"
                        continue
                    stop_reason = "contiguous_toc_run_ended"
                    break

            status = "detected" if detected_pages else "not_found"
            report = {
                "source": "llm_classifier",
                "status": status,
                "pages": detected_pages,
                "candidates": detection_candidates,
                "reason": "confirmed_by_llm_classifier" if detected_pages else stop_reason,
                "scan_limit": scan_limit,
                "batch_size": batch_size,
                "batch_count": batch_count,
                "classified_pages": classified_count,
                "classification_complete": True,
            }
            self._sync_llm_toc_detection_report(analysis, report, page_count=page_count)

        merged_diagnostics = {
            **(diagnostics or {}),
            "input_type": "rendered_pdf_page_data_url",
            "result_pages": len(pages),
            "rendered_pages": rendered_page_numbers,
            "rendered_page_inputs": rendered_inputs,
            "ocr_batch_size": batch_size,
            "ocr_batch_count": batch_count,
        }
        return OCRDocumentResult(
            task="toc_page",
            engine_type=str((resolved.route or {}).get("engine_type") or "openai_compatible_ocr"),
            model=str((resolved.route or {}).get("model") or ""),
            pages=pages,
            profile_id=(resolved.route or {}).get("profile_id"),
            profile_version=(resolved.route or {}).get("profile_version"),
            diagnostics=merged_diagnostics,
            raw={"diagnostics": merged_diagnostics, "page_results": raw_results},
        )

    @staticmethod
    def _persist_ocr_diagnostics(
        doc_id: str,
        *,
        task: str,
        response: Any,
        call_diagnostics: Dict[str, Any],
    ) -> Optional[Path]:
        try:
            diagnostics_dir = DATA_DIR / "ocr_diagnostics"
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            path = diagnostics_dir / f"{doc_id}.json"
            existing: Dict[str, Any] = {}
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
            calls = list(existing.get("calls") or [])
            calls.append(
                {
                    "task": task,
                    "diagnostics": PageIndexService._sanitize_ocr_artifact(call_diagnostics),
                    "pages": [
                        PageIndexService._ocr_page_diagnostic(page)
                        for page in list(getattr(response, "pages", []) or [])
                    ],
                    "raw_preview": PageIndexService._raw_ocr_preview(
                        getattr(response, "raw", {}) or {}
                    ),
                }
            )
            payload = {
                "doc_id": doc_id,
                "calls": calls,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        except Exception as exc:
            print(f"[TOC-DIAG] failed to persist OCR diagnostics doc={doc_id}: {type(exc).__name__}")
            return None

    @staticmethod
    def _ocr_page_diagnostic(page: Any) -> Dict[str, Any]:
        markdown = str(getattr(page, "markdown", "") or getattr(page, "plain_text", "") or "")
        structured_items = list(getattr(page, "structured_items", []) or [])
        return PageIndexService._sanitize_ocr_artifact(
            {
                "page_num": getattr(page, "page_num", None),
                "evidence_level": getattr(page, "evidence_level", None),
                "width": getattr(page, "width", None),
                "height": getattr(page, "height", None),
                "markdown_chars": len(markdown),
                "markdown_preview": markdown[:2000],
                "content_head": markdown[:200],
                "content_type_guess": PageIndexService._guess_ocr_content_type(markdown),
                "structured_item_count": len(structured_items),
                "structured_items_preview": structured_items[:20],
                "raw": getattr(page, "raw", {}) or {},
            }
        )

    @staticmethod
    def _raw_ocr_preview(raw: Dict[str, Any]) -> Dict[str, Any]:
        raw = dict(raw or {})
        preview: Dict[str, Any] = {}
        content = raw.get("content")
        if isinstance(content, str):
            preview["content_chars"] = len(content)
            preview["content_head"] = content[:200]
            preview["content_preview"] = content[:2000]
            preview["content_type_guess"] = PageIndexService._guess_ocr_content_type(content)
        rendered_input = raw.get("rendered_input")
        if isinstance(rendered_input, dict):
            preview["rendered_input"] = rendered_input
        page_results = raw.get("page_results")
        if isinstance(page_results, list):
            preview["page_results"] = [
                PageIndexService._raw_ocr_preview(item)
                for item in page_results[:20]
                if isinstance(item, dict)
            ]
        diagnostics = raw.get("diagnostics")
        if isinstance(diagnostics, dict):
            preview["diagnostics"] = diagnostics
        return PageIndexService._sanitize_ocr_artifact(preview)

    @staticmethod
    def _guess_ocr_content_type(text: str) -> str:
        value = str(text or "").strip()
        lower = value.lower()
        if lower.startswith("```json"):
            return "json"
        if lower.startswith("```markdown") or lower.startswith("```md"):
            return "markdown"
        if lower.startswith("```"):
            value = re.sub(r"^```\w*\s*", "", value).strip()
            lower = value.lower()
        if lower.startswith(("{", "[")):
            return "json"
        if lower.startswith("<") or "<table" in lower:
            return "html"
        if lower.startswith(("#", "|", "- ", "* ")):
            return "markdown"
        return "text"

    @staticmethod
    def _sanitize_ocr_artifact(value: Any) -> Any:
        secret_keys = {
            "api_key",
            "token",
            "api_key_ciphertext",
            "authorization",
            "password",
            "secret",
        }
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                key_str = str(key)
                if key_str.lower() in secret_keys:
                    continue
                sanitized[key_str] = PageIndexService._sanitize_ocr_artifact(item)
            return sanitized
        if isinstance(value, list):
            return [PageIndexService._sanitize_ocr_artifact(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _toc_probe_page_indices(analysis: Dict[str, Any], page_count: int) -> List[int]:
        pages = []
        toc_page = analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}
        sources = (
            (analysis.get("toc_pages"), False),
            (toc_page.get("pages"), False),
            (toc_page.get("page_indices"), True),
        )
        for source, zero_based in sources:
            if not isinstance(source, list):
                continue
            for item in source:
                if isinstance(item, bool):
                    continue
                try:
                    page = int(item)
                except (TypeError, ValueError):
                    continue
                if zero_based:
                    if 0 <= page < page_count:
                        pages.append(page)
                elif 1 <= page <= page_count:
                    pages.append(page - 1)
        if not pages:
            pages = list(range(min(max(1, page_count), 5)))
        return sorted(set(pages))

    @staticmethod
    def _detect_toc_pages_from_layout(
        layout: Any,
        *,
        page_count: int,
        analysis: Optional[Dict[str, Any]] = None,
        log: bool = False,
    ) -> Dict[str, Any]:
        if not layout or not getattr(layout, "pages", None):
            report = {
                "source": "layout",
                "status": "not_found",
                "pages": [],
                "candidates": [],
                "reason": "empty_layout",
            }
            if analysis is not None:
                analysis["toc_page_detection"] = report
            if log:
                print("[TOC-PAGE] source=layout status=not_found pages=[] candidates=0 reason=empty_layout")
            return report

        from pageindex.pipeline.toc_page_detector import detect_toc_pages_from_layout

        report = detect_toc_pages_from_layout(layout, page_count=page_count)
        pages = list(report.get("pages") or [])
        status = str(report.get("status") or ("detected" if pages else "not_found"))
        reason = str(report.get("reason") or ("confirmed_by_layout_signals" if pages else "no_confirmed_toc_pages"))
        if analysis is not None:
            analysis["toc_page_detection"] = report
            if pages:
                analysis["toc_pages"] = pages
                analysis["toc_page"] = {
                    **(analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}),
                    "has_toc_page": True,
                    "pages": pages,
                    "source": "layout_detection",
                }
        if log:
            print(
                f"[TOC-PAGE] source=layout status={status} "
                f"pages={PageIndexService._format_compact_pages(pages)} "
                f"candidates={len(report.get('candidates') or [])} reason={reason}"
            )
        return report

    @staticmethod
    def _confirmed_toc_pages_from_analysis(
        analysis: Optional[Dict[str, Any]],
        page_count: int,
    ) -> List[int]:
        if not isinstance(analysis, dict):
            return []
        sources: List[Any] = []
        detection = analysis.get("toc_page_detection")
        if isinstance(detection, dict) and str(detection.get("status") or "") == "detected":
            sources.append(detection.get("pages"))
        sources.append(analysis.get("toc_pages"))
        toc_page = analysis.get("toc_page")
        if isinstance(toc_page, dict):
            sources.append(toc_page.get("pages"))
        pages: List[int] = []
        for source in sources:
            if not isinstance(source, list):
                continue
            for value in source:
                if isinstance(value, bool):
                    continue
                try:
                    page = int(value)
                except (TypeError, ValueError):
                    continue
                if 1 <= page <= int(page_count or 0) and page not in pages:
                    pages.append(page)
        return pages

    @staticmethod
    def _toc_detector_scan_limit(analysis: Optional[Dict[str, Any]], page_count: int) -> int:
        if isinstance(analysis, dict):
            value = analysis.get("toc_check_page_num")
            if not value:
                value = (analysis.get("pageindex_config") or {}).get("toc_check_page_num") if isinstance(analysis.get("pageindex_config"), dict) else None
        else:
            value = None
        if not value:
            value = 15
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = 15
        return max(1, min(int(page_count or 0) or limit, limit))

    @staticmethod
    def _toc_detector_batch_size(analysis: Optional[Dict[str, Any]]) -> int:
        value = None
        if isinstance(analysis, dict):
            value = analysis.get("toc_detector_batch_size")
            if not value and isinstance(analysis.get("pageindex_config"), dict):
                value = analysis["pageindex_config"].get("toc_detector_batch_size")
        if not value:
            value = 5
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = 5
        return max(1, min(5, size))

    @staticmethod
    def _toc_detector_page_number(page: Any) -> int:
        return int(getattr(page, "page", 0) or getattr(page, "page_num", 0) or 0)

    @staticmethod
    def _toc_detector_page_text(page: Any) -> str:
        return str(getattr(page, "markdown", "") or getattr(page, "plain_text", "") or "").strip()

    @staticmethod
    def _sync_llm_toc_detection_report(
        analysis: Optional[Dict[str, Any]],
        report: Dict[str, Any],
        *,
        page_count: int,
    ) -> None:
        if analysis is None:
            return
        detected_pages = [
            int(page)
            for page in report.get("pages") or []
            if isinstance(page, int) and 1 <= int(page) <= int(page_count or 0)
        ]
        analysis["toc_page_detection"] = report
        if detected_pages:
            analysis["toc_pages"] = detected_pages
            existing_toc_page = analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}
            analysis["toc_page"] = {
                **existing_toc_page,
                "has_toc_page": True,
                "pages": detected_pages,
                "source": "llm_classifier",
            }
        else:
            analysis.pop("toc_pages", None)

    async def _classify_toc_pages_with_llm(
        self,
        pages: List[Any],
        *,
        model: str,
        batch_index: int,
    ) -> List[Dict[str, Any]]:
        async def classify_one(page: Any) -> Dict[str, Any]:
            page_num = self._toc_detector_page_number(page)
            text = self._toc_detector_page_text(page)
            candidate: Dict[str, Any] = {
                "page": page_num,
                "source": "llm_classifier",
                "is_toc": False,
                "score": 0.0,
                "decision": "no",
                "batch_index": batch_index,
                "batch_size": len(pages),
            }
            if page_num <= 0 or not text:
                candidate["decision"] = "empty"
                return candidate
            try:
                prompt = TOC_DETECTOR_SINGLE_PROMPT.format(content=text[:3500])
                response = await self._indexing_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    timeout=min(PAGEINDEX_TOC_LLM_TIMEOUT_SECONDS, 30),
                    max_tokens=64,
                    model=model,
                )
                content = self._extract_llm_text_content(response)
                payload = self._parse_json_payload(content)
                raw_decision = payload.get("toc_detected")
                if raw_decision is None:
                    raw_decision = payload.get("toc")
                if raw_decision is None:
                    raw_decision = payload.get("is_toc")
                decision = str(raw_decision or "").strip().lower()
                is_toc = decision in {"yes", "true", "1"}
                candidate.update(
                    {
                        "is_toc": is_toc,
                        "score": 1.0 if is_toc else 0.0,
                        "decision": "yes" if is_toc else "no",
                    }
                )
            except Exception as exc:
                candidate.update(
                    {
                        "is_toc": False,
                        "score": 0.0,
                        "decision": "error",
                        "error_type": type(exc).__name__,
                    }
                )
            return candidate

        return list(await asyncio.gather(*(classify_one(page) for page in pages)))

    @staticmethod
    def _consume_toc_detection_candidates(
        batch_candidates: List[Dict[str, Any]],
        *,
        detected_pages: List[int],
        candidates: List[Dict[str, Any]],
        seen_toc: bool,
    ) -> tuple[bool, bool, str]:
        stop_reason = "scan_exhausted"
        for candidate in batch_candidates:
            candidates.append(candidate)
            page_num = int(candidate.get("page") or 0)
            if candidate.get("is_toc"):
                if not seen_toc or not detected_pages or page_num == detected_pages[-1] + 1:
                    if page_num not in detected_pages:
                        detected_pages.append(page_num)
                    seen_toc = True
                    continue
                return seen_toc, True, "contiguous_toc_run_ended"
            if seen_toc:
                return seen_toc, True, "contiguous_toc_run_ended"
        return seen_toc, False, stop_reason

    async def _detect_toc_pages_with_llm_from_layout(
        self,
        layout: Any,
        *,
        page_count: int,
        model: str,
        analysis: Optional[Dict[str, Any]] = None,
        log: bool = False,
    ) -> Dict[str, Any]:
        existing = analysis.get("toc_page_detection") if isinstance(analysis, dict) else None
        if isinstance(existing, dict) and existing.get("source") == "llm_classifier" and existing.get("classification_complete"):
            return existing

        if not layout or not getattr(layout, "pages", None):
            report = {
                "source": "llm_classifier",
                "status": "not_found",
                "pages": [],
                "candidates": [],
                "reason": "empty_layout",
                "classification_complete": True,
            }
            self._sync_llm_toc_detection_report(analysis, report, page_count=page_count)
            if log:
                print("[TOC-PAGE] source=llm_classifier status=not_found pages=[] candidates=0 reason=empty_layout")
            return report

        scan_limit = self._toc_detector_scan_limit(analysis, page_count)
        batch_size = self._toc_detector_batch_size(analysis)
        pages = [
            page
            for page in sorted(list(getattr(layout, "pages", []) or []), key=lambda item: self._toc_detector_page_number(item))
            if self._toc_detector_page_number(page) > 0
        ]
        candidates: List[Dict[str, Any]] = []
        detected_pages: List[int] = []
        seen_toc = False
        classified_count = 0
        stop_reason = "scan_exhausted"
        cursor = 0
        batch_count = 0

        while cursor < len(pages):
            if not seen_toc and classified_count >= scan_limit:
                stop_reason = "scan_limit_reached"
                break
            remaining = len(pages) - cursor
            if seen_toc:
                take = min(batch_size, remaining)
            else:
                take = min(batch_size, remaining, scan_limit - classified_count)
            if take <= 0:
                stop_reason = "scan_limit_reached"
                break

            batch_pages = pages[cursor : cursor + take]
            batch_count += 1
            batch_candidates = await self._classify_toc_pages_with_llm(
                batch_pages,
                model=model,
                batch_index=batch_count,
            )
            classified_count += len(batch_pages)
            cursor += len(batch_pages)
            seen_toc, should_stop, stop_reason = self._consume_toc_detection_candidates(
                batch_candidates,
                detected_pages=detected_pages,
                candidates=candidates,
                seen_toc=seen_toc,
            )
            if should_stop:
                break
            if seen_toc:
                last_batch_page = self._toc_detector_page_number(batch_pages[-1])
                if last_batch_page in detected_pages:
                    stop_reason = "scan_exhausted"
                    continue
                stop_reason = "contiguous_toc_run_ended"
                break

        status = "detected" if detected_pages else "not_found"
        reason = "confirmed_by_llm_classifier" if detected_pages else stop_reason
        report = {
            "source": "llm_classifier",
            "status": status,
            "pages": detected_pages,
            "candidates": candidates,
            "reason": reason,
            "scan_limit": scan_limit,
            "batch_size": batch_size,
            "batch_count": batch_count,
            "classified_pages": classified_count,
            "classification_complete": True,
        }
        self._sync_llm_toc_detection_report(analysis, report, page_count=page_count)
        if log:
            print(
                f"[TOC-PAGE] source=llm_classifier status={status} "
                f"pages={PageIndexService._format_compact_pages(detected_pages)} "
                f"candidates={len(candidates)} batches={batch_count} reason={reason}"
            )
        return report
    @staticmethod
    def _layout_with_pages(layout: Any, pages: List[int]) -> Any:
        from pageindex.layout.document_layout import DocumentLayout

        selected = set(int(page) for page in pages if int(page) > 0)
        return DocumentLayout(
            doc_id=str(getattr(layout, "doc_id", "") or ""),
            page_count=int(getattr(layout, "page_count", 0) or 0),
            source_type=str(getattr(layout, "source_type", "ocr") or "ocr"),
            pages=[
                page
                for page in list(getattr(layout, "pages", []) or [])
                if int(getattr(page, "page", 0) or 0) in selected
            ],
        )

    @staticmethod
    def _select_detected_toc_page_run(candidates: List[Dict[str, Any]]) -> List[int]:
        detected = [
            candidate
            for candidate in sorted(candidates, key=lambda item: int(item.get("page") or 0))
            if candidate.get("is_toc") and int(candidate.get("page") or 0) > 0
        ]
        if not detected:
            return []
        runs: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for candidate in detected:
            page = int(candidate.get("page") or 0)
            if current and page != int(current[-1].get("page") or 0) + 1:
                runs.append(current)
                current = []
            current.append(candidate)
        if current:
            runs.append(current)
        best = max(
            runs,
            key=lambda run: (
                len(run),
                sum(float(candidate.get("score") or 0.0) for candidate in run),
            ),
        )
        return [int(candidate.get("page") or 0) for candidate in best]

    @staticmethod
    def _strip_ocr_markdown_fences(text: str) -> str:
        value = str(text or "").strip()
        if not value.startswith("```"):
            return value
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _has_toc_page_heading(text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "").lower())
        return any(
            marker in normalized
            for marker in (
                "\u76ee\u5f55",
                "contents",
                "tableofcontents",
                "\u9432\ue1c6\u7dbd",
                "\u9429\uff46\u5f55",
            )
        )

    @staticmethod
    def _count_catalog_like_lines(text: str) -> int:
        lines = [
            re.sub(r"^#{1,6}\s+", "", line).strip()
            for line in PageIndexService._strip_ocr_markdown_fences(text).splitlines()
        ]
        lines = [line for line in lines if line]
        count = 0
        for index, line in enumerate(lines):
            compact = re.sub(r"\s+", " ", line)
            if re.search(r"(?:\.{2,}|_{2,}|\u2026{1,})\s*\d{1,4}\s*$", compact):
                count += 1
                continue
            if compact.startswith("|") and "|" in compact[1:] and len(re.findall(r"\b\d{1,4}\b", compact)) >= 2:
                count += 1
                continue
            if (
                len(compact) <= 150
                and re.match(r"^(?:[-*+]\s*)?(?:\d{1,3}[\s.)\u3001\uff0e-]+)?\S.{2,}", compact)
                and re.search(r"\s+\d{1,4}\s*$", compact)
            ):
                count += 1
                continue
            if index + 1 < len(lines) and re.fullmatch(r"\d{1,4}", lines[index + 1].strip()) and 4 <= len(compact) <= 150:
                count += 1
        return count

    @staticmethod
    def _body_page_signal(text: str) -> float:
        lines = [line.strip() for line in PageIndexService._strip_ocr_markdown_fences(text).splitlines() if line.strip()]
        if not lines:
            return 0.0
        long_lines = sum(1 for line in lines if len(line) >= 90)
        paragraph_lines = sum(1 for line in lines if len(line) >= 45 and not re.search(r"(?:\.{2,}|_{2,}|\u2026{1,})\s*\d{1,4}\s*$", line))
        image_lines = sum(1 for line in lines if "<img" in line.lower() or line.lower().startswith("<div"))
        signal = 0.0
        if long_lines >= 2:
            signal += 0.16
        if paragraph_lines / max(1, len(lines)) >= 0.35:
            signal += 0.14
        if image_lines:
            signal += 0.04
        return min(0.36, signal)

    @staticmethod
    def _format_compact_pages(pages: List[int]) -> str:
        if not pages:
            return "[]"
        sorted_pages = sorted(set(int(page) for page in pages))
        ranges: List[str] = []
        start = sorted_pages[0]
        prev = sorted_pages[0]
        for page in sorted_pages[1:]:
            if page == prev + 1:
                prev = page
                continue
            ranges.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = page
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        return "[" + ",".join(ranges) + "]"

    async def _ocr_pages_for_toc_validation(
        self, file_path: Path, page_indices: List[int]
    ) -> Dict[int, str]:
        """Run lightweight OCR for selected pages.

        Returns: {physical_page_number(1-indexed): OCR text}
        """
        if not page_indices:
            return {}

        from pageindex.layout.page_renderer import render_pages_to_images

        images = render_pages_to_images(str(file_path), page_indices, dpi=150)
        if not images:
            return {}

        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))

        async def ocr_single(img_info):
            page_num = img_info["page_index"] + 1  # 0-indexed 闁?1-indexed
            async with sem:
                try:
                    result = await self._ocr_image_with_resolver(
                        img_info["image_base64"], page_num=page_num
                    )
                except Exception as exc:
                    fallback_service = OCRService()
                    try:
                        result = await fallback_service.ocr_image_base64(
                            img_info["image_base64"], page_num=page_num
                        )
                    finally:
                        await fallback_service.aclose()
            return page_num, result.text if result.ok else ""

        results = await asyncio.gather(*[ocr_single(img) for img in images])
        return {
            page_num: text for page_num, text in results if text
        }

    async def _run_pdf_ocr_pages_by_images(
        self,
        file_path: Path,
        page_indices: List[int],
        analysis: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        page_indices = sorted({int(idx) for idx in page_indices if int(idx) >= 0})
        if not page_indices:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": [],
                "overlay_all_pages": False,
            }

        try:
            from pageindex.layout.page_renderer import render_pages_to_images
        except Exception:
            requested = [idx + 1 for idx in page_indices]
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": requested,
                "overlay_all_pages": False,
            }

        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))
        render_batch_size = max(1, min(int(OCR_MAX_CONCURRENCY), 20))

        async def parse_page(image_input: Dict[str, Any]) -> Dict[str, Any]:
            page_num = int(image_input.get("page_index") or 0) + 1
            image_b64 = str(image_input.get("image_base64") or "")
            if not image_b64:
                return {
                    "page_num": page_num,
                    "text": "",
                    "ok": False,
                    "ocr_image_targets": 1,
                    "ocr_image_hits": 0,
                    "error": "empty_rendered_page_image",
                }

            async with sem:
                try:
                    r = await self._ocr_image_with_resolver(
                        image_b64,
                        page_num,
                        analysis=analysis,
                        prompt=prompt,
                    )
                except Exception as exc:
                    self._record_ocr_call(
                        analysis,
                        {
                            "task": "page_text",
                            "engine_type": "legacy_openai_ocr",
                            "model": "legacy",
                            "fallback_reason": "resolver_failed",
                            "fallback_error_type": type(exc).__name__,
                        },
                        page_num=page_num,
                        status="fallback",
                    )
                    fallback_service = OCRService(log_model_identity=False)
                    try:
                        r = await fallback_service.ocr_image_base64(image_b64, page_num)
                    finally:
                        await fallback_service.aclose()

            text = self._normalize_page_text_for_ocr(r.text if getattr(r, "ok", False) else "")
            return {
                "page_num": page_num,
                "text": text,
                "ok": bool(text),
                "ocr_image_targets": 1,
                "ocr_image_hits": 1 if text else 0,
                "error": "" if text else "no_page_ocr_text",
            }

        rows: List[Dict[str, Any]] = []
        for offset in range(0, len(page_indices), render_batch_size):
            batch_indices = page_indices[offset : offset + render_batch_size]
            images = render_pages_to_images(str(file_path), batch_indices, dpi=150)
            batch_rows = await asyncio.gather(*(parse_page(image) for image in images))
            rows.extend(batch_rows)
        rows = sorted(rows, key=lambda x: int(x.get("page_num") or 0))

        requested_pages = [idx + 1 for idx in page_indices]
        returned_pages = {int(row.get("page_num") or 0) for row in rows}
        success = sum(1 for x in rows if x.get("text"))
        missing = [
            page_num
            for page_num in requested_pages
            if page_num not in returned_pages
        ] + [int(x["page_num"]) for x in rows if not x.get("text")]
        summary = self._update_content_ocr_summary(
            analysis,
            page_count=len(requested_pages),
            success=success,
            missing=missing,
        )
        if analysis is not None:
            print(
                "[TOC-OCR] task=page_text status=done "
                f"primary_engine={summary.get('primary_engine')} "
                f"primary_model={summary.get('primary_model')} "
                f"pages={summary.get('pages', len(requested_pages))} "
                f"success={summary.get('success', success)} "
                f"missing={summary.get('missing', len(missing))} "
                f"fallback={summary.get('fallback', 0)}"
            )
        return {
            "ocr_pages": rows,
            "overlay_all_pages": False,
            "ocr_coverage": (success / len(requested_pages)) if requested_pages else 0.0,
            "ocr_missing_pages": missing,
        }

    async def _run_full_pdf_ocr_by_images(
        self,
        file_path: Path,
        page_count: int,
        analysis: Optional[Dict[str, Any]] = None,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page_count <= 0:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": [],
                "overlay_all_pages": True,
            }
        result = await self._run_pdf_ocr_pages_by_images(
            file_path,
            list(range(page_count)),
            analysis=analysis,
            prompt=prompt,
        )
        result["overlay_all_pages"] = True
        return result

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
                f"[TOC-SUMMARY] skipped disabled doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')}"
            )
            return ""

        toc_outline = self._build_toc_outline_text(structure_data)
        if not toc_outline:
            print(f"[TOC-SUMMARY] skipped empty_toc doc={file_path.name}")
            return ""

        prompt = FAST_DOC_LIGHT_SUMMARY_PROMPT.format(
            doc_name=file_path.name,
            file_type=file_path.suffix.lower(),
            toc_outline=toc_outline,
        )
        start_time = time.perf_counter()
        deadline = start_time + PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS
        attempt = 0

        while True:
            attempt += 1
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[TOC-SUMMARY] status=timeout doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt - 1} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                )
                return ""

            try:
                response = await asyncio.wait_for(
                    self._indexing_completion(
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
                        f"[TOC-SUMMARY] status=ok doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                    )
                    return summary

                print(
                    f"[TOC-SUMMARY] status=empty_output doc={file_path.name} attempt={attempt} remaining_s={round(max(0.0, deadline - time.perf_counter()), 2)}"
                )
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[TOC-SUMMARY] status=retry_error doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} attempt={attempt} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms} error_type={type(e).__name__} error={e}"
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
            "disclaimer",
            "www.iyiou.com",
            "iyiou",
            "www.iyiou.com",
        ]
        for fragment in watermark_fragments:
            t = t.replace(fragment, " ")

        t = re.sub(r"^[鈼嗏€⑩棌\-*\s]+", "", t)
        t = re.sub(r"(?i)^chapter\s*\d+[a-zA-Z]*[\s:锛?\-]*", "", t)
        t = re.sub(r"^绗琝s*\d+\s*[绔犺妭閮ㄥ垎鍗风瘒]\s*", "", t)
        t = re.sub(r"^\d+(?:\.\d+)*[\s:锛?\-]*", "", t)
        t = re.sub(r"\s+", " ", t).strip(" -:锛殀路")
        return t

    @staticmethod
    def _is_common_readable_char(ch: str) -> bool:
        if "\u4e00" <= ch <= "\u9fff":
            return True
        if ch.isascii() and (
            ch.isalnum() or ch in " \n\t.,:;!?()[]{}<>-_/\\'\"%&+*#@$"
        ):
            return True
        if ch in "\u00b7\u2014\uff1a\uff0c\u3002\u3001\uff1b\uff08\uff09\u3010\u3011\u201c\u201d\u2018\u2019":
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
        if re.fullmatch(r"\d{4}骞碶d{1,2}鏈?\d{1,2}鏃??", t):
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

        noise_keywords = ["risk", "disclaimer", "email", "phone", "copyright", "www.", "@", "notice", "warning", "contact"]
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
        choices = getattr(content, "choices", None)
        if choices:
            try:
                message = choices[0].message
                text = getattr(message, "content", None)
                if isinstance(text, str):
                    return text.strip()
            except Exception:
                pass
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts).strip()
        return ""

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
            r"^(璇ユ枃妗ｆ湰椤祙鏈渚媩璇ユ渚媩璇ユ姤鍛妡妗堜緥灞曠ず|鏂囨。鏄剧ず|鍐呭灞曠ず)[锛?锛?\s]*",
            "",
            text,
        )
        first_clause = re.split(r"[閵嗗偊绱?]", text, maxsplit=1)[0]
        first_clause = first_clause.strip("锛?:锛氥€傦紱; ")
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

    async def _extract_toc_text(
        self,
        analysis: Dict,
        toc_pages: List[int],
        page_count: int,
        model: str,
    ) -> Optional[Dict]:
        """Extract TOC from TOC page text using LLM."""
        try:
            page_texts = analysis.get("page_texts", [])
            toc_text = "\n".join([page_texts[p - 1] for p in toc_pages if p - 1 < len(page_texts)])

            prompt = f"""Extract catalog entries from the following TOC page text.

TOC text:
{toc_text[:12000]}

Requirements:
1. Keep original titles.
2. Return visible printed catalog page numbers as page and hierarchy as level.
3. Do not infer missing page numbers or page offsets.
4. Return JSON only.

Example:
{{
  "toc_items": [
    {{"title": "Chapter 1", "level": 1, "page": 5}},
    {{"title": "1.1 Introduction", "level": 2, "page": 6}}
  ]
}}"""

            response = await self._indexing_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                timeout=PAGEINDEX_TOC_LLM_TIMEOUT_SECONDS,
                max_tokens=PAGEINDEX_TOC_LLM_MAX_TOKENS,
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
            print(f"[TOC-TEXT] Failed: {e}")
            return None

    @staticmethod
    def _try_text_heading_toc(analysis: Dict) -> Optional[Dict]:
        """Build a deterministic text-heading TOC candidate for the new pipeline."""
        if analysis.get("text_coverage", 0) < 0.8:
            return None

        page_texts = analysis.get("page_texts") or []
        toc_pages = analysis.get("toc_pages") or analysis.get("toc_page", {}).get("pages") or []
        if not page_texts or not toc_pages:
            return None

        try:
            from pageindex.text_heading_extractor import (
                extract_text_headings,
                is_chapter_skeleton_toc,
                merge_chapter_skeleton_with_headings,
            )
        except Exception:
            return None

        toc_text = "\n".join(
            page_texts[p - 1]
            for p in toc_pages
            if isinstance(p, int) and 0 <= p - 1 < len(page_texts)
        )
        skeleton = is_chapter_skeleton_toc(toc_text)
        if not skeleton.get("is_skeleton"):
            return None

        headings = extract_text_headings(page_texts, start_page=1)
        body_headings = [
            item for item in headings
            if item.get("physical_index") not in toc_pages
        ]
        if len(body_headings) < 5:
            return None

        merged = merge_chapter_skeleton_with_headings(skeleton, body_headings)
        if len(merged) < 5:
            return None

        return {
            "toc_items": merged,
            "source": "text_heading",
            "mapped": True,
            "semi_frozen": True,
            "prevalidated": True,
        }

    async def _build_text_toc_candidate(
        self,
        analysis: Dict,
        *,
        toc_pages: Optional[List[int]],
        page_count: int,
        model: str,
        ocr_text_map: Optional[Dict[int, str]] = None,
        dividers: Optional[List[int]] = None,
    ) -> Dict:
        """Build a text/layout TOC candidate without invoking image-model TOC extraction."""
        heading_result = self._try_text_heading_toc(analysis)
        if heading_result:
            return heading_result

        if toc_pages:
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
                toc_items = fallback_result["toc_items"]
                has_printed_page_numbers = any(
                    PageIndexService._coerce_positive_int(
                        item.get("page") or item.get("logical_page")
                    )
                    is not None
                    for item in toc_items
                    if isinstance(item, dict)
                )
                analysis["llm_toc_page"] = {
                    "status": "ok",
                    "source": "llm_toc_page",
                    "toc_pages": list(toc_pages or []),
                    "item_count": len(toc_items),
                    "has_printed_page_numbers": has_printed_page_numbers,
                }
                return {
                    "toc_items": toc_items,
                    "source": fallback_result.get("source", "llm_toc_page"),
                }

        return {
            "toc_items": self._build_segment_fallback_toc(page_count),
            "source": "segment_fallback",
        }

    @staticmethod
    def _normalize_and_map_fallback_toc(
        fallback_result: Optional[Dict],
        page_count: int,
        toc_pages: List[int],
        ocr_text_map: Optional[Dict[int, str]] = None,
        dividers: Optional[List[int]] = None,
    ) -> Optional[Dict]:
        """Normalize degraded TOC candidate output before post-processing.

        Older text fallback prompts may put TOC logical page numbers in
        physical_index. The page-mapping verifier detects and maps that shape
        before the candidate is accepted.
        """
        if not fallback_result or not fallback_result.get("toc_items"):
            return fallback_result

        from pageindex.judge.page_mapping_verifier import map_toc_physical_pages

        last_toc_page = max(toc_pages) if toc_pages else 0
        first_content_page = last_toc_page + 1 if last_toc_page else 1

        map_toc_physical_pages(
            fallback_result["toc_items"],
            page_count=page_count,
            first_content_page=first_content_page,
            last_toc_page=last_toc_page,
            ocr_text_map=ocr_text_map,
            dividers=dividers or [],
        )
        fallback_result.setdefault("source", "llm_toc_page")
        fallback_result["mapped"] = True
        fallback_result["mapping_source"] = "page_mapping_verifier"
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

    async def _resolve_balanced_toc_pages(
        self,
        *,
        analysis: Dict[str, Any],
        file_path: Path,
        page_count: int,
        model: str,
    ) -> List[int]:
        """Resolve TOC pages for balanced mode and sync shared analysis fields."""
        from pageindex.toc_detector import find_toc_pages

        pages = await find_toc_pages(analysis, str(file_path), model)
        normalized: List[int] = []
        for page in pages or []:
            if isinstance(page, bool):
                continue
            try:
                value = int(page)
            except (TypeError, ValueError):
                continue
            if 1 <= value <= page_count:
                normalized.append(value)
        resolved = sorted(set(normalized))
        analysis["toc_page_detection"] = {
            "source": "text_detector",
            "status": "detected" if resolved else "not_found",
            "pages": resolved,
            "candidates": [
                {
                    "page": page,
                    "source": "text_detector",
                    "is_toc": True,
                    "score": 1.0,
                }
                for page in resolved
            ],
            "reason": "detected_by_text_toc_detector" if resolved else "no_text_toc_pages",
            "classification_complete": True,
        }
        self._sync_toc_context(analysis, resolved, confidence="detected")
        return resolved

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
        """Run deterministic providers and adapt a trusted skeleton to candidate shape."""
        from pageindex.balanced_orchestrator import ProviderRegistry, build_balanced_state
        from pageindex.page_mapping_service import map_skeleton_pages
        from pageindex.providers.code_toc_provider import CodeTocProvider
        from pageindex.providers.deterministic_outline_provider import (
            default_agenda_outline_provider,
            default_slide_outline_provider,
        )
        from pageindex.providers.toc_page_provider import TocPageTextProvider

        providers = []
        if not analysis.get("disable_code_toc_fast_path"):
            providers.append(CodeTocProvider())
        providers.extend([
            TocPageTextProvider(),
            default_slide_outline_provider(),
            default_agenda_outline_provider(),
        ])
        registry = ProviderRegistry(providers)
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
        """Expose canonical build state to downstream post-processing."""
        analysis["build_state"] = state
        analysis["top_level_frozen"] = bool(state.get("top_level_frozen"))
        analysis["allow_child_expansion"] = bool(state.get("allow_child_expansion", True))
        analysis["range_locked"] = bool(state.get("range_locked"))
        analysis["children_locked"] = bool(state.get("children_locked"))
        analysis["tree_complete"] = bool(state.get("tree_complete"))
        analysis["needs_repair"] = bool(state.get("needs_repair"))

    @staticmethod
    def _apply_balanced_result_state(analysis: Dict, balanced_result: Optional[Dict]) -> None:
        """Propagate trusted candidate state to downstream post-processing."""
        if not balanced_result:
            return

        source = balanced_result.get("source") or "balanced"
        top_level_frozen = bool(
            balanced_result.get(
                "top_level_frozen",
                balanced_result.get("mapped")
                or balanced_result.get("semi_frozen")
                or source in {"text_heading", "slide_outline", "agenda_outline", "ocr_toc_page", "llm_toc_page", "ppocr_layout"},
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
                "ocr_toc_page",
                "llm_toc_page",
                "ppocr_layout",
            }
            and result.get("prevalidated")
            and result.get("items")
        )

    @staticmethod
    def _should_skip_redundant_toc_detection(
        analysis: Optional[Dict],
        result: Optional[Dict],
    ) -> bool:
        if not isinstance(analysis, dict):
            return False
        if not PageIndexService._is_prevalidated_outline_result(result):
            return False
        source = str((result or {}).get("source") or "")
        if source not in {"toc_page_text", "toc_page", "ocr_toc_page"}:
            return False
        toc_meta = analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}
        toc_pages = analysis.get("toc_pages") or toc_meta.get("pages") or []
        return bool(toc_pages or toc_meta.get("has_toc_page"))

    @staticmethod
    def _toc_result_to_candidate(
        result: Optional[Dict[str, Any]],
        *,
        candidate_id: str,
        source: Optional[str] = None,
        cost_level: str = "medium",
        confidence: Optional[float] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not result:
            return None
        items = result.get("items") or result.get("toc_items") or result.get("structure") or []
        if not isinstance(items, list) or not items:
            return None
        candidate_source = source or result.get("source") or candidate_id
        try:
            raw_confidence = float(
                confidence if confidence is not None else result.get("confidence", 0.68)
            )
        except (TypeError, ValueError):
            raw_confidence = 0.68
        return {
            "candidate_id": candidate_id,
            "source": candidate_source,
            "cost_level": cost_level,
            "items": items,
            "raw_confidence": max(0.0, min(1.0, raw_confidence)),
            "evidence": {
                "provider_source": result.get("source") or candidate_source,
                "prevalidated": bool(result.get("prevalidated")),
                "mapped": bool(result.get("mapped")),
                "semi_frozen": bool(result.get("semi_frozen")),
                "top_level_frozen": bool(
                    result.get("top_level_frozen")
                    or result.get("mapped")
                    or result.get("prevalidated")
                ),
                **(evidence or {}),
            },
            "reasons": list(result.get("reasons") or []),
            "result_meta": {
                key: value
                for key, value in result.items()
                if key not in {"items", "toc_items", "structure"}
            },
        }

    async def _build_llm_toc_page_candidate(
        self,
        *,
        layout: Any,
        page_count: int,
        model: str,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        from pageindex.candidates.llm_toc_page_extractor import (
            build_llm_toc_candidate,
            build_llm_toc_prompt,
            normalize_llm_toc_payload,
        )

        if not layout or not getattr(layout, "pages", None):
            return None
        detected_pages = self._confirmed_toc_pages_from_analysis(analysis, page_count)
        if not detected_pages:
            detection = await self._detect_toc_pages_with_llm_from_layout(
                layout,
                page_count=page_count,
                model=model,
                analysis=analysis,
            )
            detected_pages = list(detection.get("pages") or [])
        if not detected_pages:
            if analysis is not None:
                analysis["llm_toc_page"] = {
                    "status": "skipped",
                    "reason": "no_confirmed_toc_pages",
                    "source": "llm_toc_page",
                }
            print("[TOC-LLM] provider=toc_page action=skip reason=no_confirmed_toc_pages")
            return None
        selected_pages = set(int(page) for page in detected_pages)
        blocks: List[Dict[str, Any]] = []
        toc_pages: List[int] = []
        for page in list(getattr(layout, "pages", []) or []):
            page_num = int(getattr(page, "page", 0) or 0)
            if page_num not in selected_pages:
                continue
            text = str(
                getattr(page, "markdown", "")
                or getattr(page, "plain_text", "")
                or ""
            ).strip()
            if not text:
                continue
            toc_pages.append(page_num)
            blocks.append({"page": page_num, "text": text})
        if not blocks:
            return None

        prompt = build_llm_toc_prompt(blocks)

        try:
            response = await self._indexing_completion(
                messages=[{"role": "user", "content": prompt}],
                timeout=PAGEINDEX_TOC_LLM_TIMEOUT_SECONDS,
                max_tokens=PAGEINDEX_TOC_LLM_MAX_TOKENS,
                temperature=0,
                model=model,
            )
            content = self._extract_llm_text_content(response)
            payload = self._parse_json_payload(content)
        except Exception as exc:
            error_type = type(exc).__name__
            if analysis is not None:
                status = "timeout" if "timeout" in error_type.lower() else "error"
                analysis["llm_toc_page"] = {
                    "status": status,
                    "error_type": error_type,
                    "source": "llm_toc_page",
                }
            print(f"[TOC-LLM] provider=toc_page action=skip error_type={error_type}")
            return None

        extraction = normalize_llm_toc_payload(payload)
        if not extraction.items:
            if analysis is not None:
                analysis["llm_toc_page"] = {
                    "status": "empty",
                    "source": "llm_toc_page",
                    "toc_pages": toc_pages,
                }
            return None
        candidate = build_llm_toc_candidate(extraction, toc_pages=toc_pages)
        if analysis is not None:
            analysis["llm_toc_page"] = {
                "status": "ok",
                "source": "llm_toc_page",
                "toc_pages": toc_pages,
                "item_count": len(extraction.items),
                "has_printed_page_numbers": extraction.has_printed_page_numbers,
                "raw_numeric_labels": list(extraction.raw_numeric_labels),
                "extracted_numeric_labels": list(extraction.raw_numeric_labels),
                "missing_numeric_labels": list(extraction.missing_numeric_labels),
                "numeric_label_gap_count": extraction.numeric_label_gap_count,
                "max_level": extraction.diagnostics.get("max_level"),
                "level_distribution": extraction.diagnostics.get("level_distribution"),
                "timeout_seconds": PAGEINDEX_TOC_LLM_TIMEOUT_SECONDS,
                "max_tokens": PAGEINDEX_TOC_LLM_MAX_TOKENS,
            }
        print(
            f"[TOC-LLM] provider=toc_page status=ok model={model} "
            f"toc_pages={PageIndexService._format_compact_pages(toc_pages)} "
            f"items={len(extraction.items)}"
        )
        return candidate

    @staticmethod
    def _parse_json_payload(content: str) -> Dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise
            payload = json.loads(match.group())
        if not isinstance(payload, dict):
            raise ValueError("LLM TOC payload must be a JSON object")
        return payload

    @staticmethod
    def _normalize_llm_ocr_toc_items(items: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(items, list):
            return normalized
        for item in items:
            if not isinstance(item, dict):
                continue
            title = re.sub(r"\s+", " ", str(item.get("title") or "").strip())
            if not title or len(title) > 140:
                continue
            page = PageIndexService._coerce_positive_int(item.get("page"))
            physical_index = PageIndexService._coerce_positive_int(item.get("physical_index"))
            if page is None and physical_index is None:
                continue
            normalized.append(
                {
                    "title": title,
                    "level": PageIndexService._coerce_positive_int(item.get("level")) or 1,
                    "page": page,
                    "physical_index": physical_index,
                    "confidence": PageIndexService._coerce_float(item.get("confidence"), default=0.58),
                    "nodes": [],
                }
            )
        return normalized

    @staticmethod
    def _coerce_positive_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _coerce_float(value: Any, *, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, parsed))

    async def _collect_text_toc_candidates(
        self,
        *,
        analysis: Dict,
        route_decision: Dict[str, Any],
        file_path: Path,
        page_count: int,
        model: str,
        anchors: Dict[str, Any],
        ocr_text_map: Optional[Dict[int, str]],
        dividers: List[int],
    ) -> List[Dict[str, Any]]:
        from pageindex.hierarchical_extractor import extract_hierarchical_toc
        from pageindex.batch_extractor import extract_batch_toc
        from pageindex.fast_text_extractor import extract_fast_text_toc
        from pageindex.baseline.official_baseline_runner import OfficialBaselineRunner

        candidates: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def add_candidate(
            result: Optional[Dict[str, Any]],
            candidate_id: str,
            source: str,
            confidence: float,
            cost_level: str = "medium",
        ) -> None:
            candidate = self._toc_result_to_candidate(
                result,
                candidate_id=candidate_id,
                source=source,
                confidence=confidence,
                cost_level=cost_level,
                evidence={"route_path": route_decision.get("path")},
            )
            if not candidate:
                return
            fingerprint = f"{source}:{len(candidate.get('items') or [])}:{candidate.get('candidate_id')}"
            if fingerprint in seen:
                return
            seen.add(fingerprint)
            candidates.append(candidate)

        official = self._try_balanced_provider_shortcut(analysis, page_count)
        official_candidate_result = OfficialBaselineRunner().run_result(
            {
                "structure": official.get("items", []),
                "confidence": official.get("confidence", 0.78),
                "page_count": page_count,
            }
        ) if official else None
        if official_candidate_result:
            official_candidate_result["items"] = official_candidate_result.get("items") or []
            official_candidate_result["source"] = "official_baseline"
            official_candidate_result.update(
                {
                    k: v
                    for k, v in (official or {}).items()
                    if k not in {"items", "source"}
                }
            )
            add_candidate(
                official_candidate_result,
                "official_baseline_001",
                "official_baseline",
                float(official_candidate_result.get("raw_confidence") or official_candidate_result.get("confidence") or 0.78),
                "medium",
            )

        text_heading = self._try_text_heading_toc(analysis)
        if text_heading:
            add_candidate(text_heading, "text_heading_001", "text_heading", 0.82, "low")

        toc_pages = list(
            anchors.get("toc_pages")
            or analysis.get("toc_pages")
            or (analysis.get("toc_page") or {}).get("pages")
            or []
        )
        llm_toc_candidate_added = False
        if toc_pages and not self._requires_layout_outline_provider(analysis):
            llm_toc_result = await self._extract_toc_text(analysis, toc_pages, page_count, model)
            llm_toc_result = self._normalize_and_map_fallback_toc(
                llm_toc_result,
                page_count=page_count,
                toc_pages=toc_pages,
                ocr_text_map=ocr_text_map,
                dividers=dividers,
            )
            if llm_toc_result:
                llm_toc_result.setdefault("source", "llm_toc_page")
                toc_items_for_state = [
                    item
                    for item in (llm_toc_result.get("toc_items") or [])
                    if isinstance(item, dict)
                ]
                analysis["llm_toc_page"] = {
                    "status": "ok",
                    "source": "llm_toc_page",
                    "toc_pages": list(toc_pages or []),
                    "item_count": len(toc_items_for_state),
                    "has_printed_page_numbers": any(
                        PageIndexService._coerce_positive_int(
                            item.get("page") or item.get("logical_page")
                        )
                        is not None
                        for item in toc_items_for_state
                    ),
                }
                before_count = len(candidates)
                add_candidate(llm_toc_result, "llm_toc_page_001", "llm_toc_page", 0.72, "high")
                llm_toc_candidate_added = len(candidates) > before_count

        chosen_path = route_decision.get("path")
        if chosen_path == "hierarchical":
            try:
                hierarchical_result = await extract_hierarchical_toc(analysis.get("page_texts", []), model)
            except Exception as exc:
                print(
                    f"[TOC-CANDIDATE] provider=hierarchical stage=merge status=error action=skip error_type={type(exc).__name__}"
                )
                hierarchical_result = None
            add_candidate(
                hierarchical_result,
                "hierarchical_001",
                "hierarchical",
                0.65,
                "high",
            )
        elif chosen_path == "batch":
            add_candidate(
                await extract_batch_toc(analysis.get("page_texts", []), model),
                "batch_001",
                "batch",
                0.64,
                "high",
            )
        elif chosen_path == "fast_text":
            add_candidate(
                extract_fast_text_toc(analysis.get("page_texts", []), model),
                "fast_text_001",
                "fast_text",
                0.58,
                "low",
            )

        if not llm_toc_candidate_added:
            text_candidate = await self._build_text_toc_candidate(
                analysis,
                toc_pages=toc_pages,
                page_count=page_count,
                model=model,
                ocr_text_map=ocr_text_map,
                dividers=dividers,
            )
            if text_candidate:
                source = str(text_candidate.get("source") or "text_tree")
                add_candidate(
                    text_candidate,
                    f"{source}_candidate",
                    source,
                    0.38 if source == "segment_fallback" else 0.60,
                    "medium",
                )

        if not candidates:
            add_candidate(
                {
                    "toc_items": self._build_segment_fallback_toc(page_count),
                    "source": "segment_fallback",
                },
                "segment_fallback_001",
                "segment_fallback",
                0.28,
                "low",
            )
        return candidates

    async def _run_unified_toc_controller(
        self,
        *,
        file_path: Path,
        requested_mode: str,
        analysis: Dict,
        route_decision: Dict[str, Any],
        page_count: int,
        model: str,
        anchors: Dict[str, Any],
        ocr_text_map: Optional[Dict[int, str]],
        dividers: List[int],
    ) -> Optional[Dict[str, Any]]:
        from pageindex.layout.document_layout import DocumentLayoutBuilder
        from pageindex.layout.ppocr_client import PPOCRClient
        from pageindex.pipeline.toc_pipeline_controller import TOCPipelineController

        controller = TOCPipelineController()
        controller_budget = {"allow_vlm": False, "allow_code_toc": not analysis.get("disable_code_toc_fast_path")}
        early_judged = controller.generate(
            pdf_path=str(file_path),
            mode=requested_mode,
            analysis=analysis,
            page_count=page_count,
            budget=controller_budget,
        )
        if (
            early_judged.get("source") == "code_toc"
            and (early_judged.get("evidence") or {}).get("early_return_allowed")
            and early_judged.get("items")
        ):
            return {
                "items": early_judged["items"],
                "source": "code_toc",
                "candidate_source": "code_toc",
                "confidence": early_judged.get("confidence", 0.0),
                "prevalidated": bool(early_judged.get("status") == "ok"),
                "diagnostics": early_judged.get("diagnostics", {}),
                "evidence": early_judged.get("evidence", {}),
                "rejected_candidates": early_judged.get("rejected_candidates", []),
                "mapped": True,
                "top_level_frozen": True,
                "allow_child_expansion": False,
            }

        candidates = await self._collect_text_toc_candidates(
            analysis=analysis,
            route_decision=route_decision,
            file_path=file_path,
            page_count=page_count,
            model=model,
            anchors=anchors,
            ocr_text_map=ocr_text_map,
            dividers=dividers,
        )

        layout = None
        toc_layout = None
        if route_decision.get("path") == "ppocr_layout" or self._requires_layout_outline_provider(analysis):
            try:
                layout = await self._build_layout_with_resolver(
                    file_path,
                    page_count,
                    analysis=analysis,
                    doc_id=analysis.get("doc_id"),
                )
            except Exception as exc:
                print("[TOC-PIPELINE] OCR resolver layout candidate failed; falling back to legacy PP-OCR")
                try:
                    legacy_client = PPOCRClient()
                    legacy_pages = self._toc_probe_pages_1_based(analysis, page_count)
                    ppocr_pages = await asyncio.to_thread(
                        legacy_client.recognize_pages,
                        str(file_path),
                        legacy_pages,
                    )
                    legacy_diagnostics = self._legacy_ppocr_diagnostics(
                        legacy_client,
                        pages=ppocr_pages,
                        requested_pages=legacy_pages,
                        fallback_error=exc,
                    )
                    analysis["fallback_reason"] = "ocr_resolver_failed"
                    analysis["ocr_route"] = legacy_diagnostics
                    analysis.setdefault("ocr_calls", []).append(legacy_diagnostics)
                    layout = DocumentLayoutBuilder().build(
                        doc_id=str(file_path),
                        page_count=page_count,
                        ppocr_pages=ppocr_pages,
                    )
                except Exception as legacy_exc:
                    print(f"[TOC-PIPELINE] PP-OCR layout candidate failed: {type(legacy_exc).__name__}: {legacy_exc}")

        judged = None
        if layout is not None:
            page_detection = await self._detect_toc_pages_with_llm_from_layout(
                layout,
                page_count=page_count,
                model=model,
                analysis=analysis,
                log=True,
            )
            detected_pages = list(page_detection.get("pages") or [])
            toc_layout = self._layout_with_pages(layout, detected_pages) if detected_pages else self._layout_with_pages(layout, [])
            if detected_pages:
                llm_toc_candidate = await self._build_llm_toc_page_candidate(
                    layout=toc_layout,
                    page_count=page_count,
                    model=model,
                    analysis=analysis,
                )
                if llm_toc_candidate:
                    candidates.append(llm_toc_candidate)
                    judged = controller.generate(
                        pdf_path=str(file_path),
                        mode=requested_mode,
                        analysis=analysis,
                        layout=None,
                        candidates=candidates,
                        page_count=page_count,
                        budget=controller_budget,
                    )
                elif self._confirmed_toc_pages_require_llm(analysis):
                    analysis["toc_llm_required"] = True
                    return None

        if judged is None:
            judged = controller.generate(
                pdf_path=str(file_path),
                mode=requested_mode,
                analysis=analysis,
                layout=toc_layout if toc_layout is not None else layout,
                candidates=candidates,
                page_count=page_count,
                budget=controller_budget,
            )
        if not judged.get("items"):
            return None

        analysis["toc_candidates_summary"] = self._summarize_toc_candidates(candidates, judged)
        winner_source = str(judged.get("source") or "")
        matched = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("source") == winner_source
                and candidate.get("items") == judged.get("items")
            ),
            None,
        )
        result_meta = dict((matched or {}).get("result_meta") or {})
        evidence = dict(judged.get("evidence") or {})
        output_source = str(evidence.get("provider_source") or result_meta.get("source") or winner_source or "toc_candidate")
        result = {
            "items": judged["items"],
            "source": output_source,
            "candidate_source": winner_source,
            "confidence": judged.get("confidence", 0.0),
            "prevalidated": bool(judged.get("status") == "ok"),
            "diagnostics": judged.get("diagnostics", {}),
            "evidence": evidence,
            "rejected_candidates": judged.get("rejected_candidates", []),
        }
        for key in (
            "mapped",
            "semi_frozen",
            "top_level_frozen",
            "allow_child_expansion",
            "mapping_strategy",
            "mapping_quality",
            "balanced_state",
        ):
            if key in result_meta:
                result[key] = result_meta[key]
        self._apply_balanced_result_state(analysis, result)
        return result

    @staticmethod
    def _is_segment_fallback_judgment(judged: Dict[str, Any]) -> bool:
        return str(judged.get("source") or "") == "segment_fallback"

    @staticmethod
    def _confirmed_toc_pages_require_llm(analysis: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(analysis, dict):
            return False
        detection = analysis.get("toc_page_detection")
        if not isinstance(detection, dict):
            return False
        if str(detection.get("status") or "") != "detected":
            return False
        if not detection.get("pages"):
            return False
        try:
            text_coverage = float(analysis.get("text_coverage") or 0.0)
        except (TypeError, ValueError):
            text_coverage = 0.0
        return bool(
            analysis.get("pipeline_path") == "ppocr_layout"
            or analysis.get("is_image_only_pdf")
            or analysis.get("is_garbled_pdf")
            or text_coverage < 0.3
        )

    @staticmethod
    def _legacy_ppocr_diagnostics(
        legacy_client: Any,
        *,
        pages: List[Any],
        requested_pages: List[int],
        fallback_error: Exception,
    ) -> Dict[str, Any]:
        return {
            "task": "toc_page",
            "source": "legacy_fallback",
            "engine_type": "ppocr_legacy",
            "model": getattr(legacy_client, "model", "PP-OCRv6"),
            "backend": getattr(legacy_client, "backend", None),
            "evidence_level": "line_box",
            "result_pages": len(pages),
            "requested_pages": list(requested_pages),
            "fallback_reason": "ocr_resolver_failed",
            "fallback_error_type": type(fallback_error).__name__,
        }

    @staticmethod
    def _toc_probe_pages_1_based(analysis: Dict[str, Any], page_count: int) -> List[int]:
        return [index + 1 for index in PageIndexService._toc_probe_page_indices(analysis, page_count)]

    @staticmethod
    def _is_weak_slide_bookmark_toc(analysis: Dict, items: List[Dict]) -> bool:
        if not items:
            return False
        titles = [str(item.get("title", "")).strip() for item in items]
        weak_count = 0
        for title in titles:
            if PageIndexService._is_slide_export_bookmark_title(title):
                weak_count += 1
            elif re.match(r"^绗琜涓€浜屼笁鍥涗簲鍏竷鍏節鍗乚+绔?", title):
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
    def _is_slide_export_bookmark_title(title: str) -> bool:
        value = str(title or "").strip()
        if not value:
            return True
        lower = value.lower()
        if lower == "default section" or value.startswith("榛樿鑺"):
            return True
        slide_prefixes = ("slide", "幻灯片", "骞荤伅鐗")
        if lower.startswith("page "):
            return True
        return any(lower.startswith(prefix.lower()) for prefix in slide_prefixes)

    @staticmethod
    def _has_reliable_code_toc(analysis: Dict) -> bool:
        code_toc = analysis.get("code_toc") or {}
        items = code_toc.get("items") or []
        source = code_toc.get("source")
        if not items:
            return False
        if source in {"bookmarks", "links"}:
            if source == "bookmarks" and PageIndexService._is_weak_slide_bookmark_toc(analysis, items):
                print("[TOC-CODE] Ignoring weak slide-export bookmarks")
                analysis["code_toc_reject_reason"] = "weak_slide_bookmarks"
                return False
            return True
        if source != "regex":
            return False
        if analysis.get("agenda_outline_candidate"):
            print("[TOC-CODE] Ignoring weak regex TOC: agenda_outline_candidate=True")
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
                f"[TOC-CODE] Ignoring weak regex TOC: "
                f"out_of_range={out_of_range_ratio:.0%}, years={year_like_ratio:.0%}"
            )
            return False

        compressed_ratio = max(physical_pages) / page_count if physical_pages else 1.0
        figure_title_ratio = sum(
            1
            for item in items
            if str(item.get("title", "")).strip().startswith(("\u56fe\uff1a", "\u8868\uff1a", "Figure", "Table"))
        ) / len(items)
        if page_count > 15 and compressed_ratio <= 0.35:
            print(
                f"[TOC-CODE] Ignoring weak regex TOC: "
                f"compressed_pages={compressed_ratio:.0%}"
            )
            return False
        if figure_title_ratio >= 0.2:
            print(
                f"[TOC-CODE] Ignoring weak regex TOC: "
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
        print(f"[TOC-PIPELINE] stage={stage_no}/7 name={name} status={status}{suffix}")

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
        from pageindex.catalog_classifier import (
            CATALOG_FIGURE,
            CATALOG_TABLE,
            catalog_group_title,
            detect_catalog_type,
        )

        code_toc = analysis.get("code_toc") or {}
        if not PageIndexService._should_add_auxiliary_catalog_nodes(analysis):
            return []
        groups = {
            CATALOG_FIGURE: {"title": catalog_group_title(CATALOG_FIGURE), "items": []},
            CATALOG_TABLE: {"title": catalog_group_title(CATALOG_TABLE), "items": []},
        }
        pure_catalog_headings = {
            "figurecatalog",
            "figurescatalog",
            "listoffigures",
            "tablecatalog",
            "tablescatalog",
            "listoftables",
            "\u56fe\u76ee\u5f55",
            "\u63d2\u56fe\u76ee\u5f55",
            "\u8868\u76ee\u5f55",
            "\u8868\u683c\u76ee\u5f55",
        }
        for item in code_toc.get("items") or []:
            if not isinstance(item, dict):
                continue
            catalog_type = detect_catalog_type(item)
            if catalog_type not in groups:
                continue
            compact_title = re.sub(r"\s+", "", str(item.get("title", "")).strip().lower())
            if compact_title in pure_catalog_headings:
                continue
            groups[catalog_type]["items"].append(item)

        catalogs: List[Dict[str, Any]] = []
        for catalog_type in (CATALOG_FIGURE, CATALOG_TABLE):
            group = groups[catalog_type]
            if not group["items"]:
                continue
            children = []
            for idx, item in enumerate(group["items"], start=1):
                page = (
                    item.get("physical_index")
                    or item.get("start_index")
                    or item.get("page")
                )
                children.append(
                    {
                        "structure": f"{catalog_type}.{idx}",
                        "title": str(item.get("title", "")).strip(),
                        "physical_index": page,
                        "start_index": page,
                        "end_index": page,
                        "node_type": "auxiliary_catalog_item",
                        "catalog_type": catalog_type,
                        "exclude_from_coverage": True,
                        "exclude_from_llm_qc": True,
                        "exclude_from_text": True,
                        "source_anchor": {
                            "start_page": page,
                            "end_page": page,
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
    def _should_add_auxiliary_catalog_nodes(analysis: Dict) -> bool:
        if not isinstance(analysis, dict):
            return False
        source = str(analysis.get("toc_source") or "").strip()
        if source in {"ocr_toc_page", "llm_toc_page", "toc_page_layout", "toc_page_text"}:
            return False
        code_toc = analysis.get("code_toc") if isinstance(analysis.get("code_toc"), dict) else {}
        return code_toc.get("source") == "regex"

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
            from pageindex.tree_schema import normalize_title

            return normalize_title(title)

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
    def _enable_child_outline_expansion_for_shallow_toc(
        analysis: Dict,
        toc_items: List[Dict[str, Any]],
        *,
        page_count: int,
        toc_source: Optional[str],
    ) -> bool:
        """Unlock child expansion when a confirmed TOC page only provides a shallow skeleton."""
        if not PageIndexService._is_shallow_toc_requiring_child_expansion(
            toc_items,
            page_count=page_count,
            toc_source=toc_source,
        ):
            return False

        build_state = dict(analysis.get("build_state") or {})
        build_state.update(
            {
                "top_level_frozen": True,
                "allow_child_expansion": True,
                "children_locked": False,
                "top_level_source": toc_source or analysis.get("toc_source") or "toc_page",
                "tree_complete": False,
            }
        )
        analysis["build_state"] = build_state
        analysis["top_level_frozen"] = True
        analysis["allow_child_expansion"] = True
        analysis["toc_frozen"] = False
        analysis["toc_semi_frozen"] = True
        if toc_source:
            analysis["toc_frozen_source"] = toc_source
        analysis["shallow_toc_expansion"] = {
            "status": "enabled",
            "source": toc_source,
            "reason": "long_leaf_ranges",
        }
        return True

    @staticmethod
    def _is_shallow_toc_requiring_child_expansion(
        toc_items: List[Dict[str, Any]],
        *,
        page_count: int,
        toc_source: Optional[str],
    ) -> bool:
        source = str(toc_source or "")
        if source not in {"llm_toc_page", "ocr_toc_page", "toc_page_text", "toc_page_layout"}:
            return False
        if not isinstance(toc_items, list) or len(toc_items) < 2 or page_count <= 0:
            return False
        if any(isinstance(item, dict) and item.get("nodes") for item in toc_items):
            return False
        levels = [
            PageIndexService._coerce_positive_int(item.get("level"))
            for item in toc_items
            if isinstance(item, dict)
        ]
        if any(level is not None and level > 1 for level in levels):
            return False

        from pageindex.catalog_classifier import CATALOG_MAIN, detect_catalog_type

        body_pages: List[int] = []
        for item in toc_items:
            if not isinstance(item, dict):
                continue
            catalog_type = str(item.get("catalog_type") or detect_catalog_type(item))
            if catalog_type != CATALOG_MAIN:
                continue
            page = (
                PageIndexService._coerce_positive_int(item.get("physical_index"))
                or PageIndexService._coerce_positive_int(item.get("start_index"))
            )
            if page is not None:
                body_pages.append(page)
        if len(body_pages) < 2:
            return False
        dense_limit = max(8, page_count // 6)
        if len(body_pages) > dense_limit:
            return False
        if any(left > right for left, right in zip(body_pages, body_pages[1:])):
            return False
        spans = [
            max(1, next_page - page)
            for page, next_page in zip(body_pages, body_pages[1:] + [page_count + 1])
        ]
        return bool(spans and max(spans) >= 6)

    @staticmethod
    def _has_sufficient_content_ocr_text(analysis: Dict) -> bool:
        summary = ((analysis.get("ocr_calls_summary") or {}).get("page_text") or {})
        pages = PageIndexService._coerce_positive_int(summary.get("pages"))
        success = PageIndexService._coerce_positive_int(summary.get("success")) or 0
        if pages:
            return success / pages >= 0.8
        try:
            coverage = float(summary.get("ocr_coverage") or analysis.get("ocr_coverage") or 0.0)
        except (TypeError, ValueError):
            coverage = 0.0
        return coverage >= 0.8

    @staticmethod
    def _expand_page_outline_if_needed(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
    ) -> int:
        """Expand a top-level-frozen TOC skeleton with child page titles."""
        if not PageIndexService._allows_child_outline_expansion(analysis):
            return 0
        from pageindex.page_outline_extractor import (
            expand_flat_toc_with_page_titles,
            expand_toc_with_page_evidence,
        )

        page_evidence = analysis.get("page_evidence") or analysis.get("page_evidences") or []
        if (
            PageIndexService._requires_layout_outline_provider(analysis)
            and not page_evidence
            and not PageIndexService._has_sufficient_content_ocr_text(analysis)
        ):
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
            print(f"[TOC-OUTLINE] skipped provider=flat_text_fallback reason={reason}")
            return 0

        if page_evidence:
            print(f"[TOC-OUTLINE] provider=page_evidence chapters={len(toc_tree)}")
            expansion = expand_toc_with_page_evidence(toc_tree, page_evidence, page_count)
            expansion["source"] = "page_evidence"
        else:
            print(f"[TOC-OUTLINE] provider=flat_text_fallback chapters={len(toc_tree)}")
            page_texts = [
                str(page[0] or "")
                for page in (page_list or [])
                if isinstance(page, (list, tuple)) and len(page) >= 1
            ]
            if not page_texts:
                print("[TOC-OUTLINE] skipped reason=no_page_texts")
                return 0
            expansion = expand_flat_toc_with_page_titles(toc_tree, page_texts, page_count)
            expansion["source"] = "flat_text_fallback"

        added = int(expansion.get("added_children") or 0)
        analysis["outline_expansion"] = expansion
        if added:
            print(
                f"[TOC-OUTLINE] done added_children={added} "
                f"quality={expansion.get('quality')} "
                f"source_distribution={expansion.get('source_distribution')} "
                f"avg_confidence={expansion.get('avg_title_confidence')} "
                f"low_confidence_ratio={expansion.get('low_confidence_ratio')}"
            )
        else:
            print(
                f"[TOC-OUTLINE] skipped reason=no_page_titles "
                f"quality={expansion.get('quality')} "
                f"expected_children={expansion.get('expected_children')} "
                f"actual_children={expansion.get('actual_children')}"
            )
        return added

    @staticmethod
    def _should_skip_flat_text_outline_expansion(analysis: Dict) -> bool:
        """Return true when extracted page text is not trustworthy for structure."""
        if PageIndexService._requires_layout_outline_provider(analysis):
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
    def _requires_layout_outline_provider(analysis: Dict) -> bool:
        """Return true when structure must come from layout/OCR evidence, not native text."""
        if str(analysis.get("structure_policy") or "").lower() == "layout_required":
            return True
        if str(analysis.get("layout_type") or "").lower() in {
            "scanned_image_pdf",
            "mixed_layout_report",
            "slide_like_report",
        }:
            return True
        return False

    @staticmethod
    def _flat_text_outline_skip_reason(analysis: Dict) -> str:
        if PageIndexService._requires_layout_outline_provider(analysis):
            return "layout_required"
        return "low_quality_text"

    @staticmethod
    async def _expand_page_outline(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
        model: Optional[str] = None,
    ) -> int:
        """Run deterministic child expansion from page evidence or native text."""
        return PageIndexService._expand_page_outline_if_needed(
            toc_tree=toc_tree,
            analysis=analysis,
            page_count=page_count,
            toc_source=toc_source,
            page_list=page_list,
        )

    @staticmethod
    def _expand_visual_page_outline_if_needed(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
    ) -> int:
        """Backward-compatible alias for the renamed deterministic outline expander."""
        return PageIndexService._expand_page_outline_if_needed(
            toc_tree=toc_tree,
            analysis=analysis,
            page_count=page_count,
            toc_source=toc_source,
            page_list=page_list,
        )

    @staticmethod
    async def _extract_visual_child_titles_for_flat_skeleton(
        *,
        file_path: str,
        tree: List[Dict],
        page_count: int,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deprecated targeted-VLM hook retained for old monkeypatch-based tests.

        The new default architecture does not invoke VLM from this helper. A real
        implementation can be wired behind an explicit budgeted fallback later.
        """
        return {
            "added_children": 0,
            "quality": "warning",
            "expected_children": 0,
            "actual_children": 0,
            "needs_repair": False,
            "source": "none",
            "reason": "targeted_vlm_disabled",
        }

    @staticmethod
    async def _expand_visual_page_outline_with_vlm_fallback(
        toc_tree: List[Dict],
        analysis: Dict,
        page_count: int,
        toc_source: Optional[str],
        page_list: Optional[List[Any]] = None,
        model: Optional[str] = None,
    ) -> int:
        """Compatibility wrapper around deterministic expansion plus disabled VLM hook."""
        added = PageIndexService._expand_page_outline_if_needed(
            toc_tree=toc_tree,
            analysis=analysis,
            page_count=page_count,
            toc_source=toc_source,
            page_list=page_list,
        )
        expansion = analysis.get("outline_expansion") or {}
        if added or not PageIndexService._allows_child_outline_expansion(analysis):
            return added

        if not PageIndexService._should_skip_flat_text_outline_expansion(analysis):
            if not expansion.get("needs_repair"):
                return added

        document_path = analysis.get("document_path")
        if not document_path:
            return added

        fallback = await PageIndexService._extract_visual_child_titles_for_flat_skeleton(
            file_path=str(document_path),
            tree=toc_tree,
            page_count=page_count,
            model=model,
        )
        fallback_added = int(fallback.get("added_children") or 0)
        if fallback_added > 0:
            analysis["outline_expansion"] = {
                **fallback,
                "source": "vlm_page_titles",
                "reason": PageIndexService._flat_text_outline_skip_reason(analysis),
            }
            return fallback_added
        return added

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
    def _existing_physical_mapping_report(
        toc_items: List[Dict[str, Any]],
        *,
        page_count: int,
        toc_pages: Optional[List[int]],
    ) -> Dict[str, Any]:
        pages = [
            PageIndexService._coerce_positive_int(item.get("physical_index"))
            for item in toc_items or []
            if isinstance(item, dict)
        ]
        pages = [page for page in pages if page is not None]
        item_count = len([item for item in toc_items or [] if isinstance(item, dict)])
        toc_page_set = {
            int(page)
            for page in (toc_pages or [])
            if isinstance(page, int) and not isinstance(page, bool) and page > 0
        }
        mapped_ratio = len(pages) / item_count if item_count else 0.0
        monotonic = all(left <= right for left, right in zip(pages, pages[1:]))
        in_range = all(1 <= page <= page_count for page in pages) if page_count else False
        toc_page_leakage_count = sum(1 for page in pages if page in toc_page_set)
        leakage_ratio = toc_page_leakage_count / item_count if item_count else 0.0
        reasons: List[str] = []
        if item_count == 0:
            reasons.append("empty_items")
        if mapped_ratio < 1.0:
            reasons.append("incomplete_existing_mapping")
        if not monotonic:
            reasons.append("mapping_non_monotonic")
        if not in_range:
            reasons.append("mapping_out_of_range")
        if toc_page_leakage_count >= 2 and leakage_ratio >= 0.3:
            reasons.append("toc_page_leakage")
        status = "ok" if not reasons else "failed"
        return {
            "status": status,
            "strategy": "existing_physical_mapping",
            "excluded_pages": sorted(toc_page_set),
            "strong_anchor_count": len(pages),
            "item_count": item_count,
            "title_match_rate": 1.0 if status == "ok" else 0.0,
            "sample_match_rate": 1.0 if status == "ok" else 0.0,
            "mapping_monotonic": monotonic,
            "estimated_ratio": 0.0,
            "tail_collapse": False,
            "front_collapse": False,
            "toc_page_leakage_count": toc_page_leakage_count,
            "page_mapping_score": 1.0 if status == "ok" else 0.0,
            "reasons": sorted(set(reasons)),
        }

    @staticmethod
    def _page_list_has_text_evidence(page_list: Optional[List[Any]]) -> bool:
        for page in page_list or []:
            text = ""
            if isinstance(page, (list, tuple)) and page:
                text = str(page[0] or "")
            elif isinstance(page, dict):
                text = str(page.get("text") or page.get("plain_text") or page.get("markdown") or "")
            elif isinstance(page, str):
                text = page
            if text.strip():
                return True
        return False

    @staticmethod
    def _resolved_toc_pages(
        toc_pages: Optional[List[int]],
        analysis: Optional[Dict[str, Any]],
    ) -> List[int]:
        def collect(sources: List[Any]) -> List[int]:
            pages: List[int] = []
            for source in sources:
                if not isinstance(source, list):
                    continue
                for value in source:
                    parsed = PageIndexService._coerce_positive_int(value)
                    if parsed is not None and parsed not in pages:
                        pages.append(parsed)
            return pages

        if isinstance(analysis, dict):
            toc_page = analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}
            detection = analysis.get("toc_page_detection") if isinstance(analysis.get("toc_page_detection"), dict) else {}
            analysis_pages = collect([
                analysis.get("toc_pages"),
                toc_page.get("pages"),
                detection.get("pages"),
            ])
            if analysis_pages:
                return analysis_pages
        return collect([toc_pages])

    @staticmethod
    def _should_run_final_content_mapping(
        *,
        toc_source: str,
        toc_items: List[Dict[str, Any]],
        page_list: List[Any],
        page_count: int,
        toc_pages: Optional[List[int]],
        analysis: Dict[str, Any],
        needs_ocr: bool,
    ) -> bool:
        """Return whether selected TOC items need final physical page mapping.

        TOC-page extraction produces a skeleton from catalog pages. Its page
        values may be printed/logical pages, so final saved output must be
        anchored against body content whenever body text evidence is available.
        """
        if not toc_items or page_count <= 0:
            return False
        if not PageIndexService._page_list_has_text_evidence(page_list):
            return False

        source = str(toc_source or "").strip()
        detected_toc_pages = PageIndexService._resolved_toc_pages(toc_pages, analysis)
        has_source_page_hint = any(
            isinstance(item, dict)
            and PageIndexService._coerce_positive_int(item.get("source_page")) is not None
            for item in toc_items
        )
        has_toc_page_context = bool(detected_toc_pages or has_source_page_hint)

        toc_page_sources = {
            "ocr_toc_page",
            "llm_toc_page",
            "toc_page_layout",
            "toc_page_text",
        }
        if source in toc_page_sources:
            return has_toc_page_context

        if source == "official_baseline":
            judge = analysis.get("toc_judge") if isinstance(analysis, dict) else {}
            evidence = judge.get("evidence") if isinstance(judge, dict) else {}
            provider_source = str((evidence or {}).get("provider_source") or "").strip()
            return has_toc_page_context and provider_source in toc_page_sources

        return bool(needs_ocr and source in toc_page_sources)

    @staticmethod
    def _should_reverify_existing_toc_mapping(analysis: Dict[str, Any]) -> bool:
        if not isinstance(analysis, dict):
            return False
        source = str(analysis.get("toc_source") or "").strip()
        toc_page_sources = {
            "ocr_toc_page",
            "llm_toc_page",
            "toc_page_layout",
            "toc_page_text",
        }
        if source in toc_page_sources:
            return True
        if source != "official_baseline":
            return False
        judge = analysis.get("toc_judge") if isinstance(analysis.get("toc_judge"), dict) else {}
        evidence = judge.get("evidence") if isinstance(judge.get("evidence"), dict) else {}
        provider_source = str(evidence.get("provider_source") or "").strip()
        return provider_source in toc_page_sources

    @staticmethod
    def _map_toc_items_after_content_ocr(
        toc_items: List[Dict[str, Any]],
        *,
        page_list: List[Any],
        page_count: int,
        toc_pages: Optional[List[int]],
        analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

        resolved_toc_pages = PageIndexService._resolved_toc_pages(toc_pages, analysis)
        if resolved_toc_pages:
            toc_pages = resolved_toc_pages

        page_texts = [page[0] if isinstance(page, (list, tuple)) and page else "" for page in (page_list or [])]
        existing_report = PageIndexService._existing_physical_mapping_report(
            toc_items,
            page_count=page_count,
            toc_pages=toc_pages or [],
        )
        if (
            existing_report["status"] == "ok"
            and not PageIndexService._should_reverify_existing_toc_mapping(analysis)
        ):
            mapped_items = [dict(item) for item in toc_items]
            report = existing_report
        else:
            prefer_printed_page_numbers = False
            llm_toc_page = analysis.get("llm_toc_page") if isinstance(analysis, dict) else None
            if isinstance(llm_toc_page, dict):
                prefer_printed_page_numbers = bool(llm_toc_page.get("has_printed_page_numbers"))
            mapped_items, report = map_toc_items_to_physical_pages(
                toc_items,
                page_texts=page_texts,
                page_count=page_count,
                toc_pages=toc_pages or [],
                prefer_printed_page_numbers=prefer_printed_page_numbers,
            )
        analysis["ocr_text_map"] = {
            index: str(page[0] or "")
            for index, page in enumerate(page_list or [], start=1)
            if isinstance(page, (list, tuple)) and len(page) >= 1
        }
        analysis["toc_content_mapping"] = report
        analysis.setdefault("toc_judge", {})
        analysis["toc_judge"]["content_mapping"] = report
        print(
            "[TOC-MAPPING] "
            f"strategy={report.get('strategy')} "
            f"status={report.get('status')} "
            f"anchors={report.get('strong_anchor_count')}/{report.get('item_count')} "
            f"title_match={report.get('title_match_rate', 0):.0%} "
            f"estimated={report.get('estimated_ratio', 0):.0%}"
        )
        return mapped_items

    @staticmethod
    def _build_page_heading_outline_candidate_from_page_list(
        page_list: List[Any],
        *,
        page_count: int,
        toc_pages: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        from pageindex.page_outline_extractor import extract_page_title_candidates
        from pageindex.pipeline.toc_page_detector import has_toc_page_heading

        if not page_list or page_count <= 0:
            return None

        skipped_pages = {
            int(page)
            for page in (toc_pages or [])
            if isinstance(page, int) and not isinstance(page, bool) and page > 0
        }
        page_texts: List[str] = []
        for index in range(1, page_count + 1):
            value = page_list[index - 1] if index - 1 < len(page_list) else ""
            if isinstance(value, (list, tuple)) and value:
                text = str(value[0] or "")
            elif isinstance(value, dict):
                text = str(value.get("text") or value.get("plain_text") or value.get("markdown") or "")
            else:
                text = str(value or "")
            if index in skipped_pages or has_toc_page_heading(text):
                text = ""
            page_texts.append(text)

        candidates = extract_page_title_candidates(page_texts, 1, page_count)
        strong = [
            candidate
            for candidate in candidates
            if str(candidate.get("reason") or "").startswith("explicit_section_marker")
            or float(candidate.get("confidence") or 0.0) >= 0.7
        ]
        if len(strong) < 3:
            return None

        items: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in sorted(strong, key=lambda item: int(item.get("physical_index") or item.get("page") or 0)):
            title = re.sub(r"\s+", " ", str(candidate.get("title") or "").strip())
            page = PageIndexService._coerce_positive_int(candidate.get("physical_index") or candidate.get("page"))
            if not title or page is None or page in skipped_pages:
                continue
            key = re.sub(r"[\s\W_]+", "", title.lower(), flags=re.UNICODE)
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "structure": str(len(items) + 1),
                    "title": title,
                    "level": 1,
                    "physical_index": page,
                    "source": "page_heading_outline",
                    "mapping_confidence": float(candidate.get("confidence") or 0.0),
                    "title_confidence": float(candidate.get("confidence") or 0.0),
                    "nodes": [],
                }
            )

        if len(items) < 3:
            return None

        return {
            "items": items,
            "source": "page_heading_outline",
            "mapped": True,
            "prevalidated": True,
            "top_level_frozen": True,
            "allow_child_expansion": False,
        }

    @staticmethod
    def _collect_toc_quality_failure_reasons(
        *,
        analysis: Dict[str, Any],
        completeness: Dict[str, Any],
        llm_quality_check: Optional[Dict[str, Any]],
        quality_report: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        reasons: List[str] = []

        mapping = analysis.get("toc_content_mapping") if isinstance(analysis, dict) else None
        if isinstance(mapping, dict) and str(mapping.get("status") or "").lower() == "failed":
            mapping_reasons = mapping.get("reasons") or []
            if isinstance(mapping_reasons, list) and mapping_reasons:
                reasons.extend(f"content_mapping:{reason}" for reason in mapping_reasons[:5])
            else:
                reasons.append("content_mapping:failed")

        if isinstance(completeness, dict):
            gate = completeness.get("balanced_quality_gate") or {}
            if isinstance(gate, dict) and gate.get("needs_repair"):
                reasons.append("balanced_quality_gate:needs_repair")
            elif completeness.get("needs_repair"):
                reasons.append("completeness:needs_repair")

        llm_failure_reason = PageIndexService._llm_quality_failure_reason(llm_quality_check)
        if llm_failure_reason:
            reasons.append(llm_failure_reason)

        if isinstance(quality_report, dict):
            status = str(quality_report.get("status") or "")
            if status.startswith("failed:"):
                reasons.append(f"quality_report:{status}")

        return sorted(set(str(reason) for reason in reasons if reason))

    @staticmethod
    def _normalized_llm_quality_score(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))

    @staticmethod
    def _llm_quality_failure_reason(llm_quality_check: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(llm_quality_check, dict):
            return None

        verdict = str(llm_quality_check.get("verdict") or "").strip().lower()
        score_value = llm_quality_check.get("overall_score")
        normalized_score = PageIndexService._normalized_llm_quality_score(score_value)
        hard_fail_reasons = llm_quality_check.get("hard_fail_reasons") or []
        has_hard_fail_reasons = isinstance(hard_fail_reasons, list) and any(
            str(reason).strip() for reason in hard_fail_reasons
        )

        if verdict == "fail":
            return f"llm_quality_check:fail:{score_value}"
        if has_hard_fail_reasons:
            return f"llm_quality_check:hard_fail:{score_value}"
        if llm_quality_check.get("needs_repair") and normalized_score is not None and normalized_score <= 0.5:
            return f"llm_quality_check:low_score:{score_value}"
        return None

    @staticmethod
    def _should_retry_toc_with_balanced(result: Dict[str, Any], reasons: List[str]) -> bool:
        if not reasons:
            return False
        route = result.get("route_decision") if isinstance(result, dict) else None
        if not isinstance(route, dict):
            return False
        requested = str(route.get("requested_mode") or "")
        initial = str(route.get("initial_execution_mode") or "")
        final = str(route.get("final_execution_mode") or route.get("execution_mode") or "")
        if requested not in {"smart", "fast"}:
            return False
        if initial != "fast" or final != "fast":
            return False
        return True

    @staticmethod
    def _raise_for_toc_quality_failure(
        *,
        analysis: Dict[str, Any],
        completeness: Dict[str, Any],
        llm_quality_check: Optional[Dict[str, Any]],
        quality_report: Optional[Dict[str, Any]] = None,
    ) -> None:
        unique_reasons = PageIndexService._collect_toc_quality_failure_reasons(
            analysis=analysis,
            completeness=completeness,
            llm_quality_check=llm_quality_check,
            quality_report=quality_report,
        )
        if unique_reasons:
            raise RuntimeError(
                "TOC quality gate failed: " + ", ".join(unique_reasons)
            )

    @staticmethod
    def _summarize_toc_candidates(
        candidates: List[Dict[str, Any]],
        judged: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        judged = judged or {}
        selected_source = str(judged.get("source") or "")
        selected_score = judged.get("confidence")
        rejected_by_id: Dict[str, Dict[str, Any]] = {}
        rejected_by_source: Dict[str, Dict[str, Any]] = {}
        for rejected in judged.get("rejected_candidates") or []:
            if not isinstance(rejected, dict):
                continue
            candidate_id = str(rejected.get("candidate_id") or "")
            source = str(rejected.get("source") or "")
            if candidate_id:
                rejected_by_id[candidate_id] = rejected
            if source and source not in rejected_by_source:
                rejected_by_source[source] = rejected

        summary: List[Dict[str, Any]] = []
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            source = str(candidate.get("source") or "")
            items = candidate.get("items") or []
            item_count = len(items) if isinstance(items, list) else 0
            rejected = rejected_by_id.get(candidate_id) or rejected_by_source.get(source)
            if source and source == selected_source:
                status = "selected"
                score = selected_score
                reasons = list(candidate.get("reasons") or [])
            elif rejected:
                status = "rejected"
                score = rejected.get("score")
                reasons = list(rejected.get("reasons") or [])
            else:
                status = "considered"
                score = candidate.get("final_score", candidate.get("raw_confidence"))
                reasons = list(candidate.get("reasons") or [])
            try:
                score_value = round(max(0.0, min(1.0, float(score))), 4)
            except (TypeError, ValueError):
                score_value = 0.0
            summary.append(
                {
                    "candidate_id": candidate_id,
                    "source": source,
                    "item_count": item_count,
                    "score": score_value,
                    "status": status,
                    "reasons": [str(reason) for reason in reasons[:5]],
                }
            )
        return summary

    @staticmethod
    def _index_diagnostics_from_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {}
        if not isinstance(analysis, dict):
            return diagnostics

        def keep_jsonish(value: Any) -> Any:
            blocked_keys = {
                "api_key",
                "token",
                "api_key_ciphertext",
                "content",
                "content_preview",
                "content_head",
                "prompt_text",
                "markdown",
                "markdown_preview",
                "plain_text",
                "raw",
                "raw_preview",
                "page_results",
                "items",
                "toc_items",
                "structure",
            }
            if isinstance(value, dict):
                return {
                    str(key): keep_jsonish(item)
                    for key, item in value.items()
                    if str(key) not in blocked_keys
                }
            if isinstance(value, list):
                return [keep_jsonish(item) for item in value]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)

        for key in (
            "page_text_map_diagnostics",
            "ocr_route",
            "ocr_calls",
            "ocr_calls_summary",
            "toc_page_detection",
            "toc_judge",
            "toc_content_mapping",
            "toc_candidates_summary",
            "llm_toc_page",
        ):
            value = analysis.get(key)
            if value:
                diagnostics[key] = keep_jsonish(value)
        fallback_reason = analysis.get("fallback_reason") or analysis.get("code_toc_reject_reason")
        if fallback_reason:
            diagnostics["fallback_reason"] = keep_jsonish(fallback_reason)
        return diagnostics

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

    @staticmethod
    def _should_generate_node_summaries(opt: Any) -> bool:
        return str(getattr(opt, "if_add_node_summary", "no") or "no").lower() == "yes"

    @staticmethod
    def _should_generate_doc_description(opt: Any) -> bool:
        return str(getattr(opt, "if_add_doc_description", "yes") or "yes").lower() == "yes"

    async def _generate_pdf_index(
        self,
        file_path: Path,
        doc_id: str,
        mode_override: Optional[str] = None,
        *,
        _quality_retry: bool = True,
        _disable_code_toc: bool = False,
        _fallback_from: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a PDF index through the layout-first TOC pipeline."""
        from pageindex.pdf_analyzer import analyze_pdf_structure
        from pageindex.slide_outline_extractor import (
            is_slide_like_document,
        )
        from pageindex.agenda_outline_extractor import (
            is_agenda_outline_document,
        )
        from pageindex.post_processing import post_process_toc
        from pageindex.node_filler import (
            fill_node_text,
            generate_summaries,
            generate_doc_description,
            write_node_ids,
        )
        from pageindex.preprocess_page_text import (
            PAGE_TEXT_OCR_PROMPT,
            preprocess_page_text_map,
        )

        model = getattr(self.opt, "model", "qwen3.6-flash")
        requested_mode = mode_override or "smart"
        from pageindex.router import decide_extraction_path, get_path_description

        self._log_index_stage(1, "analyze", "started")
        print(f"[TOC-PIPELINE] stage=analyze action=start doc={file_path.name}")
        analysis = analyze_pdf_structure(str(file_path))
        analysis["document_path"] = str(file_path)
        analysis["doc_id"] = doc_id
        analysis["file_path"] = str(file_path)
        if _disable_code_toc:
            analysis["disable_code_toc_fast_path"] = True
        if _fallback_from:
            analysis["quality_fallback_from"] = dict(_fallback_from)
        page_count = analysis["page_count"]
        analysis["slide_outline_candidate"] = is_slide_like_document(analysis)
        analysis["agenda_outline_candidate"] = is_agenda_outline_document(analysis)
        page_text_map = await preprocess_page_text_map(
            file_path,
            analysis,
            ocr_pages_fn=lambda fp, pages, prompt, analysis: self._run_pdf_ocr_pages_by_images(
                Path(fp),
                list(pages),
                analysis=analysis,
                prompt=prompt,
            ),
            prompt=PAGE_TEXT_OCR_PROMPT,
        )
        page_list = page_text_map.to_page_list()
        page_text_diagnostics = page_text_map.to_diagnostics()
        print(
            "[TOC-PIPELINE] stage=preprocess "
            f"content_type={analysis.get('content_type')} "
            f"pages={page_text_diagnostics.get('page_count')} "
            f"ocr_pages={page_text_diagnostics.get('ocr_page_count')} "
            f"sources={page_text_diagnostics.get('sources')}"
        )
        self._log_index_stage(
            1,
            "analyze",
            "done",
            pages=page_count,
            text_coverage=f"{analysis['text_coverage']:.0%}",
        )
        print(
            "[TOC-PIPELINE] stage=analyze action=profile "
            f"layout_type={analysis.get('layout_type', 'unknown')}, "
            f"text_layer_quality={analysis.get('text_layer_quality', 'unknown')}, "
            f"structure_policy={analysis.get('structure_policy', 'unknown')}, "
            f"ocr_policy={analysis.get('ocr_policy', 'unknown')}, "
            f"layout_dependency_score={analysis.get('layout_dependency_score', 0)}"
        )

        # 閻犱警鍨抽弫閬嶅礃瀹曞洨鎽?
        execution_mode = self._select_initial_execution_mode(requested_mode, analysis)
        initial_execution_mode = execution_mode
        initial_route_decision = decide_extraction_path(analysis, requested_mode)

        pipeline_path = None
        if execution_mode == "balanced":
            pipeline_path = (
                "ppocr_layout"
                if initial_route_decision.get("path") == "ppocr_layout"
                else "text"
            )
            analysis["pipeline_path"] = pipeline_path

        print(
            f"[TOC-PIPELINE] stage=route requested={requested_mode} execution={execution_mode} "
            f"pipeline_path={pipeline_path} code_toc={analysis['code_toc']['source']} "
            f"pages={page_count} text_coverage={analysis['text_coverage']:.0%}"
        )

        if execution_mode == "balanced":
            await self._resolve_balanced_toc_pages(
                analysis=analysis,
                file_path=file_path,
                page_count=page_count,
                model=model,
            )


        # P2-fix: 闁圭鍋撻柡?balanced 闁哄倸娲﹂妴鍌炴焾閽樺甯ラ悹鐑樺灴閺佸鎮欑憴鍕垫⒕婵炴潙缁辨繈鎳㈠畡鏉跨悼 dividers 濞ｅ洠鍓濇导?
        anchors = {
            "toc_pages": list(
                analysis.get("toc_pages")
                or (analysis.get("toc_page") or {}).get("pages")
                or []
            ),
            "chapter_dividers": list(analysis.get("chapter_dividers") or []),
        }
        ocr_text_map = None
        dividers = list(anchors.get("chapter_dividers") or [])
        if execution_mode == "balanced":
            self._log_index_stage(2, "layout_signals", "started")
            print("[TOC-PIPELINE] stage=probe action=layout_signals source=deterministic")
            self._sync_toc_context(
                analysis,
                anchors.get("toc_pages", []),
                confidence="detected" if anchors.get("toc_pages") else "low",
            )
            print(f"[TOC-PIPELINE] stage=probe action=layout_signals dividers={len(dividers)}")
            self._log_index_stage(
                2,
                "layout_signals",
                "done",
                toc_pages=anchors.get("toc_pages", []),
                dividers=len(dividers),
            )

            # 闁搞儱澧芥晶鏍垂鐎ｇ€俊妤嬬秮椤ゅ倹寰勯弽褌绮?OCR
        # 濠碘€冲€归悘澶愬触椤栨粍鏆忓ù婊冩閺屽﹪寮搁懜鐢碘偓鏁嶇仦鐣屾閻犲洦娲戞繛鍥偨?-path閻犱警鍨抽弫?
        # Unified TOC candidate pipeline.
        route_decision = initial_route_decision
        print(
            f"[TOC-PIPELINE] stage=controller route={route_decision['path']} "
            f"({get_path_description(route_decision['path'])})"
        )
        print(f"[TOC-PIPELINE] stage=controller reasons={route_decision['reasons']}")

        new_architecture_result = await self._run_unified_toc_controller(
            file_path=file_path,
            requested_mode=requested_mode,
            analysis=analysis,
            route_decision=route_decision,
            page_count=page_count,
            model=model,
            anchors=anchors,
            ocr_text_map=ocr_text_map,
            dividers=dividers,
        )
        if not new_architecture_result or not new_architecture_result.get("items"):
            raise ValueError("TOC_PIPELINE_NO_CANDIDATE: unified controller returned no TOC items")

        toc_items = new_architecture_result["items"]
        toc_source = new_architecture_result.get("source", "toc_candidate")
        analysis["toc_source"] = toc_source
        analysis["toc_judge"] = {
            "source": toc_source,
            "candidate_source": new_architecture_result.get("candidate_source"),
            "confidence": new_architecture_result.get("confidence"),
            "evidence": new_architecture_result.get("evidence", {}),
            "rejected_candidates": new_architecture_result.get("rejected_candidates", []),
        }
        top_level_frozen = bool(
            new_architecture_result.get(
                "top_level_frozen",
                new_architecture_result.get("mapped")
                or new_architecture_result.get("semi_frozen")
                or toc_source in {"official_baseline", "text_heading", "slide_outline", "agenda_outline", "ocr_toc_page", "llm_toc_page", "ppocr_layout"},
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
        print(
            f"[TOC-JUDGE] decision=accept items={len(toc_items)} "
            f"source={toc_source} confidence={new_architecture_result.get('confidence')}"
        )
        document_needs_ocr = (
            len(analysis.get("image_only_pages", [])) > 0
            or len(analysis.get("garbled_pages", [])) > 0
        )
        content_ocr_ran = False
        if document_needs_ocr and not analysis.get("page_text_map_ocr_completed"):
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
            if self._requires_layout_outline_provider(analysis):
                print("[TOC-PIPELINE] stage=content_ocr structure_source=layout_first")
            ocr_result = await self._run_pdf_ocr_pages_by_images(
                Path(analysis["file_path"]),
                sorted(set(analysis.get("image_only_pages", []) + analysis.get("garbled_pages", []))),
                analysis=analysis,
                prompt=PAGE_TEXT_OCR_PROMPT,
            )
            page_text_map = await preprocess_page_text_map(
                file_path,
                analysis,
                ocr_pages_fn=lambda *_args, **_kwargs: ocr_result,
                prompt=PAGE_TEXT_OCR_PROMPT,
            )
            page_list = page_text_map.to_page_list()
            analysis["page_list"] = page_list
            content_ocr_ran = True
            self._log_index_stage(
                4,
                content_ocr_stage,
                "done",
                role="content_fill",
                coverage=f"{len(page_list)}/{page_count}",
            )

        if toc_source == "segment_fallback":
            detected_toc_pages = list(
                anchors.get("toc_pages")
                or analysis.get("toc_pages")
                or (analysis.get("toc_page") or {}).get("pages")
                or []
            )
            page_heading_outline = self._build_page_heading_outline_candidate_from_page_list(
                page_list,
                page_count=page_count,
                toc_pages=detected_toc_pages,
            )
            if page_heading_outline:
                toc_items = page_heading_outline["items"]
                toc_source = "page_heading_outline"
                analysis["toc_source"] = toc_source
                analysis["toc_judge"] = {
                    **analysis.get("toc_judge", {}),
                    "source": toc_source,
                    "candidate_source": toc_source,
                    "confidence": 0.62,
                    "evidence": {
                        "provider_source": toc_source,
                        "prevalidated": True,
                        "mapped": True,
                        "page_mapping_score": 1.0,
                    },
                }
                build_state = dict(analysis.get("build_state") or {})
                build_state.update(
                    {
                        "top_level_frozen": True,
                        "allow_child_expansion": False,
                        "children_locked": True,
                        "top_level_source": toc_source,
                        "tree_complete": True,
                    }
                )
                analysis["build_state"] = build_state
                analysis["top_level_frozen"] = True
                analysis["allow_child_expansion"] = False
                analysis["toc_frozen"] = True
                analysis["toc_semi_frozen"] = False
                analysis["toc_frozen_source"] = toc_source
                analysis["page_heading_outline"] = {
                    "status": "ok",
                    "item_count": len(toc_items),
                }
                print(
                    f"[TOC-CANDIDATE] provider=page_heading_outline "
                    f"action=accepted items={len(toc_items)}"
                )
            else:
                analysis["page_heading_outline"] = {
                    "status": "skipped",
                    "reason": "insufficient_page_titles",
                }

        if self._should_run_final_content_mapping(
            toc_source=toc_source,
            toc_items=toc_items,
            page_list=page_list,
            page_count=page_count,
            toc_pages=anchors.get("toc_pages", []),
            analysis=analysis,
            needs_ocr=document_needs_ocr,
        ):
            toc_items = self._map_toc_items_after_content_ocr(
                toc_items,
                page_list=page_list,
                page_count=page_count,
                toc_pages=anchors.get("toc_pages", []),
                analysis=analysis,
            )

        self._enable_child_outline_expansion_for_shallow_toc(
            analysis,
            toc_items,
            page_count=page_count,
            toc_source=toc_source,
        )

        # Check whether extraction already returned a nested tree.
        has_prebuilt_tree = any(
            isinstance(item.get("nodes"), list) and bool(item.get("nodes"))
            for item in toc_items
        )

        if has_prebuilt_tree:
            print(f"[TOC-POST] action=assign_page_ranges prebuilt_tree=true roots={len(toc_items)}")
            toc_tree = []
            for item in toc_items:
                if "start_index" not in item:
                    item["start_index"] = item.get("physical_index") or 1
                if "end_index" not in item:
                    item["end_index"] = page_count

                # 濞戞挸鎼悺娆撴嚍閸屾粌浠悹浣稿⒔閻ゅ棝鎳犻崘銊︾函
                children = item.get("nodes", [])
                for i, child in enumerate(children):
                    if "start_index" not in child:
                        child["start_index"] = child.get("physical_index") or 1
                    if "end_index" not in child:
                        # 濞戞挸缁斿瓨绋夐鍕笧鐎靛枙婵℃倷閸︾暠濡炪倗鏁搁悥?- 1闁挎稑鏈崹銊╁棘閸ャ劊鈧倿寮甸銏㈠暡
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
                                # 濞达綀娉曢弫銈夋偉閹澘螡闁绘劕婀卞▓鎴犵磼閹惧瓨灏嗗銈囨暩閻?
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
            print(f"[TOC-POST] action=preserve_prebuilt_tree entries={sum(len(item.get('nodes', [])) for item in toc_tree)}")
        else:
            print(f"[TOC-POST] action=post_process input_items={len(toc_items)}")
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
            print(f"[TOC-QUALITY] action=coverage_repair_required details={completeness}")
            # TODO: gap 濞ｅ浂鍠栭ˇ鏌ユ晬閸繍鍤?gaps 闁告牕鎼悡娆戞偘閵夈儱甯犻柛鎺戞閻?)

        # 闁告帗绻傞～鎰板礌?result 闁诲妺缁ㄢ偓娑櫭崑宥囨嫻閵婏富姊剧紓浣规尰閻?
        await self._expand_page_outline(
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
            f"[TOC-QUALITY] top_level_frozen_check: "
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

            # 闁哄秷瀹撲胶鎷归妸锔绘⒕缂備焦鎸婚悘澶嬬┍椤旂⒈妲?
            if quality_result.get("needs_repair"):
                print("[TOC-QUALITY] provider=llm_qc action=advisory suggestions=true")
                for suggestion in quality_result.get("suggestions", []):
                    if any(token in suggestion for token in ("sub-chapter", "split")):
                        print("[TOC-QUALITY] provider=llm_qc action=advisory reason=large_node_detail")
                        # 闁哄秴娲╅鍥閳ф啺娴ｅ摜鎽嶇紒鏃傚Ь婵″箵閹扮悼
                        break
        except Exception as e:
            print(f"[TOC-QUALITY] provider=llm_qc action=skip error={e}")

        auxiliary_catalogs = self._build_auxiliary_catalog_nodes(analysis)
        if auxiliary_catalogs:
            toc_tree = self._merge_auxiliary_catalog_nodes(toc_tree, auxiliary_catalogs)
            print(
                f"[TOC-POST] action=add_auxiliary_catalogs titles="
                f"{', '.join(node.get('title', '') for node in auxiliary_catalogs)}"
            )

        toc_tree = self._normalize_auxiliary_catalog_nodes(toc_tree)
        toc_tree = self._normalize_final_tree_schema(
            toc_tree,
            doc_id=doc_id,
            page_count=page_count,
        )
        print(f"[TOC-PIPELINE] stage=enrich action=fill_nodes_and_doc_summary mode={execution_mode}")
        self._log_index_stage(6, "enrich", "started", mode=execution_mode)
        fill_node_text(toc_tree, page_text_map)
        write_node_ids(toc_tree)
        # 闁冲厜鍋撻柍鍏夊亾闁冲厜鍋?闁哄瀚紓鎾存綇閹惧啿姣?闁冲厜鍋撻柍鍏夊亾闁冲厜鍋?
        # 濞ｅ洦绻勯弳鈧☉鏂挎晶鐘绘儍閸曠獩婵″亾缂備焦鎸婚悘?
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
                "pipeline_path": pipeline_path,
                "toc_source": toc_source,
                "text_coverage": analysis["text_coverage"],
                "is_image_only_pdf": analysis.get("is_image_only_pdf", False),
                "fallback_reason": analysis.get("code_toc_reject_reason"),
                "fallback_from": analysis.get("quality_fallback_from"),
                "code_toc_disabled": bool(analysis.get("disable_code_toc_fast_path")),
            },
            "completeness": completeness,
            "ocr_used": bool(analysis.get("page_text_map_ocr_completed")) or content_ocr_ran,
            "llm_quality_check": llm_quality_check_result,
            "enrichment_status": "pending",
        }
        diagnostics = self._index_diagnostics_from_analysis(analysis)
        if diagnostics:
            result["diagnostics"] = diagnostics

        model_routes = await self._model_route_metadata()
        if model_routes:
            result["model_routes"] = model_routes

        self._attach_index_quality_report(result, page_count=page_count, force_pdf=True)
        quality_failure_reasons = self._collect_toc_quality_failure_reasons(
            analysis=analysis,
            completeness=completeness,
            llm_quality_check=llm_quality_check_result,
            quality_report=result.get("quality_report"),
        )
        if _quality_retry and self._should_retry_toc_with_balanced(result, quality_failure_reasons):
            print(
                "[TOC-PIPELINE] stage=quality action=retry_balanced "
                f"reason={';'.join(quality_failure_reasons)}"
            )
            return await self._generate_pdf_index(
                file_path,
                doc_id,
                "balanced",
                _quality_retry=False,
                _disable_code_toc=True,
                _fallback_from={
                    "requested_mode": requested_mode,
                    "execution_mode": execution_mode,
                    "toc_source": toc_source,
                    "reasons": quality_failure_reasons,
                },
            )
        if quality_failure_reasons:
            raise RuntimeError(
                "TOC quality gate failed: " + ", ".join(quality_failure_reasons)
            )

        # Save a usable base index before slower enrichment calls.
        index_path = self._save_index_payload(doc_id, result)
        print(f"[TOC-PIPELINE] stage=save status=base_index_saved index={index_path}")

        if self._should_generate_node_summaries(self.opt):
            await generate_summaries(toc_tree, model=model, mode=execution_mode)
        doc_description = ""
        if self._should_generate_doc_description(self.opt):
            doc_description = await generate_doc_description(
                toc_tree, model=model, file_name=file_path.name
            )
        result["doc_description"] = doc_description
        result["enrichment_status"] = "done"
        if model_routes:
            result["model_routes"] = model_routes
        self._log_index_stage(6, "enrich", "done")

        index_path = self._save_index_payload(doc_id, result)
        print(f"[TOC-PIPELINE] stage=save status=final_index_saved index={index_path}")
        self._log_index_stage(7, "save", "done", index=index_path.name)

        return {"index_path": str(index_path), "structure": result}

    async def generate_index(
        self, file_path: str, doc_id: str, mode_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a PageIndex tree index for a document."""
        file_path = Path(file_path)

        if file_path.suffix.lower() == ".pdf":
            return await self._generate_pdf_index(file_path, doc_id, mode_override)

        self.opt = self._build_opt(mode_override=mode_override)

        if file_path.suffix.lower() in [".md", ".markdown"]:
            adapted = generate_multi_format_index(file_path)
            if adapted is not None:
                result = adapted
            else:
                # 闁稿繑绮岀花鎶藉礂閻撳寒鍟囬柨娑欑煯缁绘岸鎮惧▎蹇撴枾闁?md_to_tree 閻犱警鍨扮欢?
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
                        f"[TOC-SUMMARY] final=empty doc={file_path.name} doc_id={doc_id}"
                    )

        self._attach_index_quality_report(
            result,
            page_count=page_count,
            force_pdf=file_path.suffix.lower() == ".pdf",
        )
        model_routes = await self._model_route_metadata()
        if model_routes:
            result["model_routes"] = model_routes

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return {
            "index_path": str(index_path),
            "structure": result,
            "doc_description": doc_description,
            "page_count": page_count,
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

    async def search_in_structure_async(
        self,
        structure: Dict[str, Any],
        query: str,
        doc_id: str,
        doc_name: str,
        user_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """Use LLM reasoning to search the tree structure."""
        from app.services.cache_service import cache_service

        route = await self._resolve_model_route("indexing")
        route_version = route.get("route_version") if route else None
        cached_result = cache_service.get_search_result(
            user_id, query, [doc_id], route_version=route_version
        )
        if cached_result is not None:
            print(f"[CACHE] Search cache hit for query: {query[:30]}...")
            return cached_result

        if "structure" in structure:
            structure_data = structure["structure"]
        else:
            structure_data = structure
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
            response = await self._indexing_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                model="qwen3.6-flash",
            )
            content = response.choices[0].message.content

            # 閻熸瑱绲鹃悗?JSON
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
                    # 闁兼儳鍢茶ぐ鍥棘閸ャ劍鎷遍柛鎰噹椤?
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
                            "summary": text[:300] if text else "",  # 闁硅姤椤╋箓鎮介妸銈囪壘閻忕偞娲滈妵?
                            "full_text": text,  # 閻庣懓鏈弳锝夊储閻斿憡鐎柣鍔嬬花骞掗妸褎鍊?
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
                    provider_config=route,
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

            # 闁圭濞村宕楅崘鎻掗柛婊冪焸閻涙瑧鎷犳担铏规瀭濞ｅ洠鈧啿缂備胶鍘ч幃搴ㄥ箳閹烘垹纰?
            results.sort(
                key=lambda x: (
                    x.get("relevance", 0)
                    * max(x.get("verification_confidence", 0.5), 0.1)
                ),
                reverse=True,
            )

            final_results = results[:3]

            # 缂傚倹鎸搁悺銊х磼閹惧浜?
            cache_service.set_search_result(
                user_id, query, [doc_id], final_results, route_version=route_version
            )

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

        # 婵炴挸鎳愰幃濠囧蓟閵夊殑
        query_clean = query.lower().replace(" ", "")

        # 闁圭粯鍔曡ぐ鍥礂閹惰姤鏆涢悹鍥х▌缁变即鎳熸潏銊︾€悹?+ 濞戞搩鍘介弸?閻庢稒閻?+ 濞戞搩鍘介弸鍐础閺囩偟鎽?
        stopwords = set("theaantoofinfor")
        raw_tokens = _re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query_clean)
        # 濞ｅ洦绻勯弳鈧柤鏄忛哺閺嬪啰鎷犲鍛濞戞挸绉村﹢宕戝鍛殢閻犲洤绉烽妴鍐╃▔椤撶姵鐣卞☉鎿冨幗閺嬪啰鈧稒椤?
        keywords = [t for t in raw_tokens if len(t) > 1 or t not in stopwords]
        # 闁告艾鏈鍌炴偨閻旂鐏囬柣鈺傛倐閸嬶附绋夐妶鍛憻缂備礁瀚幃搴ㄦ晬閸唽渚€骞忛悢鎯板幀闁哄倸娲ら崹搴ｆ嫚瀹ュ繒绀?
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

            # 缂佹鍏涚粩瀵哥棯瑜濈槐浼村礂閵娿倛闁告牕缍婇崢?
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

            # 缂佹鍏涚花鈺冪棯瑜濈槐浼村礂閹惰姤鏆涢悹?闁瑰嘲妫楅悺褔宕犺ぐ鎺戝赋
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

        # 闁圭濞村宕楅崘鎻掗柟鐑樺笒缁?
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
            response = await self._indexing_completion(
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

            # 閻熸瑱绲鹃悗?JSON
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

            # 闁圭濞村宕楅崘鎻掗柟鐑樺笒缁?
            results.sort(key=lambda x: x["relevance"], reverse=True)
            return results[:5]

        except Exception as e:
            print(f"Reasoning search error: {e}")
            return self.search_in_structure(structure, query, doc_id, doc_name)
