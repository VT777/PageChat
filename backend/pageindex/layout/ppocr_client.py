"""PP-OCRv6 AiStudio job client."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .document_layout import OCRLayoutLine, PPOCRPageResult


DEFAULT_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"


class PPOCRClient:
    def __init__(
        self,
        *,
        token: Optional[str] = None,
        job_url: str = DEFAULT_JOB_URL,
        model: str = "PP-OCRv6",
        backend: str = "remote_aistudio",
        session: Any = None,
        poll_interval_seconds: float = 5.0,
        optional_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.token = token or os.getenv("PPOCR_AISTUDIO_TOKEN") or os.getenv("OCR_API_KEY") or ""
        self.job_url = job_url
        self.model = model
        self.backend = backend
        self.poll_interval_seconds = poll_interval_seconds
        self.optional_payload = optional_payload or {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useTextlineOrientation": False,
        }
        if session is None:
            import requests

            session = requests
        self.session = session

    def recognize_pages(self, file_path: str, pages: Optional[List[int]] = None, options: Optional[Dict[str, Any]] = None) -> List[PPOCRPageResult]:
        if self.backend != "remote_aistudio":
            raise NotImplementedError(f"unsupported ppocr backend: {self.backend}")
        print(f"[TOC-OCR] task=page_text engine=ppocr_legacy model={self.model}")
        job_id = self._submit_job(file_path, options or {})
        jsonl_url = self._poll_job(job_id)
        results = self._download_jsonl(jsonl_url)
        if pages:
            wanted = set(pages)
            results = [result for result in results if result.page_num in wanted]
        return results

    def _headers(self, json_content: bool = False) -> Dict[str, str]:
        headers = {"Authorization": f"bearer {self.token}"}
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

    def _submit_job(self, file_path: str, options: Dict[str, Any]) -> str:
        if not self.token:
            raise RuntimeError("PPOCR_AISTUDIO_TOKEN or OCR_API_KEY is required for remote_aistudio")
        optional_payload = {**self.optional_payload, **dict(options.get("optional_payload") or {})}
        if file_path.startswith("http"):
            response = self.session.post(
                self.job_url,
                json={
                    "fileUrl": file_path,
                    "model": self.model,
                    "optionalPayload": optional_payload,
                },
                headers=self._headers(json_content=True),
            )
        else:
            if not os.path.exists(file_path):
                raise FileNotFoundError(file_path)
            with open(file_path, "rb") as handle:
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
            raise RuntimeError(f"ppocr submit failed: status={response.status_code} body={response.text}")
        return response.json()["data"]["jobId"]

    def _poll_job(self, job_id: str) -> str:
        while True:
            response = self.session.get(f"{self.job_url}/{job_id}", headers=self._headers())
            if response.status_code != 200:
                raise RuntimeError(f"ppocr poll failed: status={response.status_code} body={response.text}")
            data = response.json()["data"]
            state = data["state"]
            if state == "done":
                return data["resultUrl"]["jsonUrl"]
            if state == "failed":
                raise RuntimeError(f"ppocr job failed: {data.get('errorMsg') or 'unknown'}")
            time.sleep(self.poll_interval_seconds)

    def _download_jsonl(self, jsonl_url: str) -> List[PPOCRPageResult]:
        response = self.session.get(jsonl_url)
        response.raise_for_status()
        pages: List[PPOCRPageResult] = []
        page_num = 1
        for raw_line in response.text.strip().splitlines():
            if not raw_line.strip():
                continue
            payload = json.loads(raw_line)
            result = payload.get("result") or {}
            data_info = result.get("dataInfo") or payload.get("dataInfo")
            for ocr_result in result.get("ocrResults") or []:
                if data_info and "dataInfo" not in ocr_result:
                    ocr_result = {**ocr_result, "dataInfo": data_info}
                pages.append(_parse_ocr_result(page_num, ocr_result))
                page_num += 1
        return pages


def _parse_ocr_result(page_num: int, payload: Dict[str, Any]) -> PPOCRPageResult:
    pruned = payload.get("prunedResult") or payload.get("result") or payload
    texts = pruned.get("rec_texts") or []
    scores = pruned.get("rec_scores") or []
    boxes = pruned.get("rec_boxes") or pruned.get("dt_boxes") or []
    lines: List[OCRLayoutLine] = []
    for index, text in enumerate(texts):
        box = boxes[index] if index < len(boxes) else []
        if box and len(box) == 4 and isinstance(box[0], list):
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            box = [min(xs), min(ys), max(xs), max(ys)]
        lines.append(
            OCRLayoutLine(
                text=str(text or "").strip(),
                score=float(scores[index]) if index < len(scores) else 1.0,
                box=[float(value) for value in box] if len(box) >= 4 else [],
            )
        )
    width, height = _page_size_from_payload(payload, pruned, boxes)
    return PPOCRPageResult(page_num=page_num, width=width, height=height, lines=lines, raw=payload)


def _page_size_from_payload(
    payload: Dict[str, Any],
    pruned: Dict[str, Any],
    boxes: List[Any],
) -> tuple[int, int]:
    width = int(pruned.get("width") or payload.get("width") or 0)
    height = int(pruned.get("height") or payload.get("height") or 0)
    if width and height:
        return width, height

    data_info = payload.get("dataInfo") or {}
    data_pages = data_info.get("pages") or []
    if data_pages and isinstance(data_pages[0], dict):
        page_info = data_pages[0]
        width = width or int(page_info.get("width") or 0)
        height = height or int(page_info.get("height") or 0)
    if width and height:
        return width, height

    normalized_boxes = []
    for box in boxes:
        if box and len(box) == 4 and isinstance(box[0], list):
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            normalized_boxes.append([min(xs), min(ys), max(xs), max(ys)])
        elif isinstance(box, list) and len(box) >= 4:
            normalized_boxes.append(box[:4])
    if normalized_boxes:
        width = width or int(max(float(box[2]) for box in normalized_boxes))
        height = height or int(max(float(box[3]) for box in normalized_boxes))
    return width, height
