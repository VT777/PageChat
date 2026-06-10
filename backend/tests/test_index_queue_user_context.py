import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import documents as documents_api


def test_run_index_job_passes_user_id_to_generator(monkeypatch) -> None:
    calls = []

    async def fake_generate(doc_id, file_path, mode_override=None, user_id=None):
        calls.append(
            {
                "doc_id": doc_id,
                "file_path": file_path,
                "mode_override": mode_override,
                "user_id": user_id,
            }
        )

    class FakeLoop:
        def run_until_complete(self, coro):
            asyncio.run(coro)

        def close(self):
            pass

    monkeypatch.setattr(documents_api.asyncio, "new_event_loop", lambda: FakeLoop())
    monkeypatch.setattr(documents_api.asyncio, "set_event_loop", lambda _loop: None)
    monkeypatch.setattr(documents_api, "_generate_index_async", fake_generate)

    documents_api._run_index_job(
        "doc-1", "file.pdf", mode_override="balanced", user_id="user-a"
    )

    assert calls == [
        {
            "doc_id": "doc-1",
            "file_path": "file.pdf",
            "mode_override": "balanced",
            "user_id": "user-a",
        }
    ]


def test_enqueue_index_job_preserves_user_id(monkeypatch) -> None:
    documents_api._reset_index_queue_for_tests()
    monkeypatch.setattr(documents_api, "_update_document_status_sync", lambda *a: None)
    monkeypatch.setattr(documents_api, "_ensure_index_queue_worker_started", lambda: None)

    documents_api._enqueue_index_job(
        "doc-1", "file.pdf", mode_override="fast", user_id="user-a"
    )

    with documents_api._index_queue_condition:
        job = documents_api._index_queue[0]

    assert job.user_id == "user-a"
    assert job.doc_id == "doc-1"
    assert job.mode_override == "fast"


def test_start_index_process_forwards_user_id_to_queue(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(documents_api, "PAGEINDEX_QUEUE_ENABLED", True)
    monkeypatch.setattr(
        documents_api,
        "_enqueue_index_job",
        lambda doc_id, file_path, mode_override=None, user_id=None: calls.append(
            (doc_id, file_path, mode_override, user_id)
        ),
    )

    documents_api.start_index_process(
        "doc-1", "file.pdf", mode_override="smart", user_id="user-a"
    )

    assert calls == [("doc-1", "file.pdf", "smart", "user-a")]
