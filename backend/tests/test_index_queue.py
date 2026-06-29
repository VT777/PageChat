from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import documents as documents_api


def test_start_index_process_queues_when_worker_busy(monkeypatch) -> None:
    started = []
    statuses = []
    release = threading.Event()
    first_started = threading.Event()

    def fake_run_index_job(doc_id, file_path, mode_override=None, user_id=None):
        started.append(doc_id)
        if doc_id == "doc-1":
            first_started.set()
        if doc_id == "doc-1":
            release.wait(timeout=1)

    monkeypatch.setattr(documents_api, "_run_index_job", fake_run_index_job)
    monkeypatch.setattr(
        documents_api,
        "_update_document_status_sync",
        lambda _db_path, doc_id, status, **_kwargs: statuses.append((doc_id, status)),
    )
    monkeypatch.setattr(documents_api, "PAGEINDEX_QUEUE_ENABLED", True)
    monkeypatch.setattr(documents_api, "PAGEINDEX_MAX_CONCURRENT_JOBS", 1)
    documents_api._reset_index_queue_for_tests()

    try:
        documents_api.start_index_process("doc-1", "one.pdf")
        documents_api.start_index_process("doc-2", "two.pdf")

        assert statuses == [
            ("doc-1", "processing:queued"),
            ("doc-2", "processing:queued"),
        ]

        assert documents_api._wait_for_index_queue_state_for_tests(
            running=1,
            queued=1,
            timeout=1,
        )
        assert first_started.wait(timeout=1)
        assert started == ["doc-1"]

        release.set()

        assert documents_api._wait_for_index_queue_state_for_tests(
            running=0,
            queued=0,
            timeout=2,
        )
        assert started == ["doc-1", "doc-2"]
    finally:
        release.set()
        documents_api._reset_index_queue_for_tests()
