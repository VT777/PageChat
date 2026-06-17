"""PaddleOCR AiStudio job API adapter."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from typing import Any, Dict, List, Optional

from .contracts import OCRDocumentResult, OCRLine, OCRPageResult, OCRTask
from .task_prompts import default_task_prompt


DEFAULT_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
STRUCTURE_MODELS = {"PP-StructureV3", "PaddleOCR-VL-1.6"}
PROMPT_VERSION = "2026-06-15"


class PaddleOCRJobAdapter:
    def __init__(
        self,
        *,
        token: Optional[str] = None,
        job_url: str = DEFAULT_JOB_URL,
        model: str = "PP-OCRv6",
        session: Any = None,
        poll_interval_seconds: float = 5.0,
        optional_payload: Optional[Dict[str, Any]] = None,
        profile_id: Optional[str] = None,
        profile_version: Optional[str] = None,
    ) -> None:
        self.token = token or os.getenv("PADDLEOCR_API_KEY") or os.getenv("PPOCR_AISTUDIO_TOKEN") or ""
        self.job_url = job_url.rstrip("/")
        self.model = model
        self.poll_interval_seconds = poll_interval_seconds
        self.optional_payload = optional_payload or _default_optional_payload(model)
        self.profile_id = profile_id
        self.profile_version = profile_version
        if session is None:
            import requests

            session = requests
        self.session = session

    def recognize(
        self,
        file_path_or_url: str,
        *,
        task: OCRTask,
        options: Optional[Dict[str, Any]] = None,
    ) -> OCRDocumentResult:
        options = options or {}
        prompt, prompt_name = _task_prompt(task, self.model, options)
        started = time.perf_counter()
        base_diagnostics = self._diagnostics(
            task=task,
            prompt=prompt,
            prompt_name=prompt_name,
            input_type=_input_type(file_path_or_url),
        )
        job_id = self._submit_job(file_path_or_url, options, prompt=prompt)
        jsonl_url = self._poll_job(job_id)
        pages = self._download_jsonl(jsonl_url)
        evidence_levels = sorted({page.evidence_level for page in pages})
        diagnostics = {
            **base_diagnostics,
            "job_id": job_id,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "result_pages": len(pages),
            "evidence_level": evidence_levels[0] if len(evidence_levels) == 1 else ",".join(evidence_levels),
        }
        return OCRDocumentResult(
            task=task,
            engine_type="paddleocr_job",
            model=self.model,
            pages=pages,
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            diagnostics=diagnostics,
            raw={"job_id": job_id, "result_url": jsonl_url, "diagnostics": diagnostics},
        )

    def _headers(self, *, json_content: bool = False) -> Dict[str, str]:
        headers = {"Authorization": f"bearer {self.token}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    def _submit_job(self, file_path_or_url: str, options: Dict[str, Any], *, prompt: str = "") -> str:
        if not self.token:
            raise RuntimeError("PaddleOCR job token is required")
        sanitized_options = {
            key: value
            for key, value in options.items()
            if key not in {"prompt", "prompt_name"}
        }
        optional_payload = {**self.optional_payload, **sanitized_options}
        if prompt:
            optional_payload["prompt"] = prompt
        try:
            if file_path_or_url.startswith("http"):
                response = self.session.post(
                    self.job_url,
                    json={
                        "fileUrl": file_path_or_url,
                        "model": self.model,
                        "optionalPayload": optional_payload,
                    },
                    headers=self._headers(json_content=True),
                )
            elif file_path_or_url.startswith("data:"):
                filename, payload = _decode_data_url(file_path_or_url)
                handle = io.BytesIO(payload)
                handle.name = filename
                response = self.session.post(
                    self.job_url,
                    headers=self._headers(),
                    data={
                        "model": self.model,
                        "optionalPayload": json.dumps(optional_payload),
                    },
                    files={"file": handle},
                )
            else:
                if not os.path.exists(file_path_or_url):
                    raise FileNotFoundError(file_path_or_url)
                with open(file_path_or_url, "rb") as handle:
                    response = self.session.post(
                        self.job_url,
                        headers=self._headers(),
                        data={
                            "model": self.model,
                            "optionalPayload": json.dumps(optional_payload),
                        },
                        files={"file": handle},
                    )
            if response.status_code != 200:
                raise RuntimeError(
                    f"PaddleOCR submit failed: status={response.status_code} body={response.text}"
                )
            return str(response.json()["data"]["jobId"])
        except Exception as exc:
            raise RuntimeError(self._redact(str(exc))) from exc

    def _poll_job(self, job_id: str) -> str:
        while True:
            try:
                response = self.session.get(f"{self.job_url}/{job_id}", headers=self._headers())
                if response.status_code != 200:
                    raise RuntimeError(
                        f"PaddleOCR poll failed: status={response.status_code} body={response.text}"
                    )
                data = response.json()["data"]
                state = data.get("state")
                if state == "done":
                    return str(data["resultUrl"]["jsonUrl"])
                if state == "failed":
                    raise RuntimeError(f"PaddleOCR job failed: {data.get('errorMsg') or 'unknown'}")
                time.sleep(self.poll_interval_seconds)
            except Exception as exc:
                raise RuntimeError(self._redact(str(exc))) from exc

    def _download_jsonl(self, jsonl_url: str) -> List[OCRPageResult]:
        try:
            response = self.session.get(jsonl_url)
            response.raise_for_status()
            return _parse_jsonl(response.text, model=self.model)
        except Exception as exc:
            raise RuntimeError(self._redact(str(exc))) from exc

    def _redact(self, message: str) -> str:
        if self.token:
            return message.replace(self.token, "[redacted-token]")
        return message

    def _diagnostics(
        self,
        *,
        task: OCRTask,
        prompt: str,
        prompt_name: str,
        input_type: str,
    ) -> Dict[str, Any]:
        return {
            "task": task,
            "engine_type": "paddleocr_job",
            "model": self.model,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "prompt_name": prompt_name or None,
            "prompt_version": PROMPT_VERSION if prompt else None,
            "prompt_text": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_chars": len(prompt),
            "input_type": input_type,
        }


def _default_optional_payload(model: str) -> Dict[str, Any]:
    if model in STRUCTURE_MODELS:
        return {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
    return {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
    }


def _task_prompt(task: OCRTask, model: str, options: Dict[str, Any]) -> tuple[str, str]:
    configured = str(options.get("prompt") or "").strip()
    if configured:
        return configured, str(options.get("prompt_name") or "custom_prompt")
    if "vl" not in str(model or "").lower():
        return "", ""
    return default_task_prompt(task)

def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    header, sep, encoded = str(data_url).partition(",")
    if not sep:
        raise ValueError("Invalid data URL OCR input")
    if ";base64" not in header.lower():
        raise ValueError("Only base64 data URL OCR input is supported")
    mime_type = header[5:].split(";", 1)[0].lower() or "application/octet-stream"
    extension = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }.get(mime_type, "bin")
    return f"ocr-input.{extension}", base64.b64decode(encoded)

def _input_type(file_path_or_url: str) -> str:
    if str(file_path_or_url).startswith("data:"):
        return "data_url"
    if str(file_path_or_url).startswith(("http://", "https://")):
        return "remote_url"
    return "local_file"


def _parse_jsonl(text: str, *, model: str) -> List[OCRPageResult]:
    pages: List[OCRPageResult] = []
    page_num = 1
    for raw_line in text.strip().splitlines():
        if not raw_line.strip():
            continue
        result = (json.loads(raw_line).get("result") or {})
        for ocr_result in result.get("ocrResults") or []:
            pages.append(_parse_ocr_result(page_num, ocr_result))
            page_num += 1
        for layout_result in result.get("layoutParsingResults") or []:
            pages.append(_parse_layout_result(page_num, layout_result, model=model))
            page_num += 1
    return pages


def _parse_ocr_result(page_num: int, payload: Dict[str, Any]) -> OCRPageResult:
    pruned = payload.get("prunedResult") or payload.get("result") or payload
    texts = pruned.get("rec_texts") or []
    scores = pruned.get("rec_scores") or []
    boxes = pruned.get("rec_boxes") or pruned.get("dt_boxes") or []
    lines: List[OCRLine] = []
    for index, text in enumerate(texts):
        box = _normalize_box(boxes[index] if index < len(boxes) else [])
        lines.append(
            OCRLine(
                text=str(text or "").strip(),
                score=float(scores[index]) if index < len(scores) else 1.0,
                box=box,
                raw={"index": index},
            )
        )
    return OCRPageResult(
        page_num=page_num,
        width=int(pruned.get("width") or payload.get("width") or 0),
        height=int(pruned.get("height") or payload.get("height") or 0),
        evidence_level="line_box",
        lines=lines,
        raw=payload,
    )


def _parse_layout_result(page_num: int, payload: Dict[str, Any], *, model: str) -> OCRPageResult:
    markdown = payload.get("markdown") or {}
    return OCRPageResult(
        page_num=page_num,
        evidence_level="model_inferred",
        markdown=str(markdown.get("text") or "").strip(),
        raw={
            "model": model,
            "markdown_images": dict(markdown.get("images") or {}),
            "output_images": dict(payload.get("outputImages") or {}),
            "source": payload,
        },
    )


def _normalize_box(box: Any) -> List[float]:
    if not isinstance(box, list) or len(box) < 4:
        return []
    if isinstance(box[0], list):
        points = [point for point in box if isinstance(point, list) and len(point) >= 2]
        if not points:
            return []
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return [min(xs), min(ys), max(xs), max(ys)]
    return [float(value) for value in box[:4]]
