import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_engines.paddleocr_job_adapter import PaddleOCRJobAdapter  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, *, text="", status_code=200) -> None:
        self._payload = payload or {}
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


class FakeSession:
    def __init__(self, *, job_states, jsonl_lines) -> None:
        self.job_states = list(job_states)
        self.jsonl_text = "\n".join(json.dumps(line) for line in jsonl_lines)
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"data": {"jobId": "job-123"}})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url.endswith("/job-123"):
            state = self.job_states.pop(0)
            if state == "done":
                return FakeResponse(
                    {
                        "data": {
                            "state": "done",
                            "extractProgress": {"extractedPages": 1},
                            "resultUrl": {"jsonUrl": "https://example.test/result.jsonl"},
                        }
                    }
                )
            return FakeResponse(
                {
                    "data": {
                        "state": state,
                        "extractProgress": {"totalPages": 2, "extractedPages": 0},
                    }
                }
            )
        return FakeResponse(text=self.jsonl_text)


def test_url_mode_submits_json_and_parses_ppocr_line_boxes() -> None:
    session = FakeSession(
        job_states=["pending", "running", "done"],
        jsonl_lines=[
            {
                "result": {
                    "ocrResults": [
                        {
                            "prunedResult": {
                                "width": 1200,
                                "height": 1600,
                                "rec_texts": ["1. Intro", "2. Details"],
                                "rec_scores": [0.99, 0.95],
                                "rec_boxes": [[100, 200, 400, 236], [100, 260, 460, 296]],
                            }
                        }
                    ]
                }
            }
        ],
    )
    adapter = PaddleOCRJobAdapter(
        token="secret-token",
        model="PP-OCRv6",
        session=session,
        poll_interval_seconds=0,
    )

    result = adapter.recognize("https://example.test/doc.pdf", task="toc_page")

    post_url, post_kwargs = session.posts[0]
    assert post_url == "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    assert post_kwargs["json"]["fileUrl"] == "https://example.test/doc.pdf"
    assert post_kwargs["json"]["model"] == "PP-OCRv6"
    assert post_kwargs["headers"]["Content-Type"] == "application/json"
    assert result.pages[0].evidence_level == "line_box"
    assert result.pages[0].plain_text == "1. Intro\n2. Details"
    assert result.pages[0].lines[0].box == [100.0, 200.0, 400.0, 236.0]


def test_local_file_mode_submits_multipart_payload(tmp_path: Path) -> None:
    file_path = tmp_path / "page.png"
    file_path.write_bytes(b"image")
    session = FakeSession(
        job_states=["done"],
        jsonl_lines=[{"result": {"ocrResults": []}}],
    )
    adapter = PaddleOCRJobAdapter(
        token="secret-token",
        model="PP-OCRv6",
        session=session,
        poll_interval_seconds=0,
    )

    adapter.recognize(str(file_path), task="page_text", options={"useTextlineOrientation": False})

    _, post_kwargs = session.posts[0]
    assert post_kwargs["data"]["model"] == "PP-OCRv6"
    assert json.loads(post_kwargs["data"]["optionalPayload"])["useTextlineOrientation"] is False
    assert "files" in post_kwargs
    assert "Content-Type" not in post_kwargs["headers"]


def test_structure_models_parse_markdown_results_as_model_inferred() -> None:
    session = FakeSession(
        job_states=["done"],
        jsonl_lines=[
            {
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {
                                "text": "# Contents\n\n- Intro 1",
                                "images": {"a.png": "https://example.test/a.png"},
                            },
                            "outputImages": {"layout": "https://example.test/layout.jpg"},
                        }
                    ]
                }
            }
        ],
    )
    adapter = PaddleOCRJobAdapter(
        token="secret-token",
        model="PP-StructureV3",
        session=session,
        poll_interval_seconds=0,
    )

    result = adapter.recognize("https://example.test/doc.pdf", task="toc_page")

    assert result.pages[0].evidence_level == "model_inferred"
    assert result.pages[0].markdown == "# Contents\n\n- Intro 1"
    assert result.pages[0].raw["markdown_images"] == {"a.png": "https://example.test/a.png"}
    assert result.pages[0].raw["output_images"] == {"layout": "https://example.test/layout.jpg"}


def test_failed_job_redacts_token_from_errors() -> None:
    class FailedSession(FakeSession):
        def post(self, url, **kwargs):
            return FakeResponse(text="bad secret-token", status_code=401)

    adapter = PaddleOCRJobAdapter(
        token="secret-token",
        model="PP-OCRv6",
        session=FailedSession(job_states=[], jsonl_lines=[]),
        poll_interval_seconds=0,
    )

    try:
        adapter.recognize("https://example.test/doc.pdf", task="toc_page")
        assert False, "Expected submit failure"
    except RuntimeError as exc:
        assert "secret-token" not in str(exc)
        assert "[redacted-token]" in str(exc)
