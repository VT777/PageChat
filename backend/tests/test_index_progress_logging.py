from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import documents as documents_api
from app.services.pageindex_service import PageIndexService


class StopAfterOneTick:
    def __init__(self):
        self.calls = 0

    def wait(self, timeout=None):
        self.calls += 1
        return self.calls > 1

    def is_set(self):
        return True


def test_estimated_progress_thread_does_not_print_fake_page_progress(
    monkeypatch,
    capsys,
):
    updates = []

    def fake_update(_db_path, _doc_id, processed_pages):
        updates.append(processed_pages)

    monkeypatch.setattr(
        documents_api,
        "_update_processed_pages_sync",
        fake_update,
    )

    documents_api._update_progress_sync(
        db_path="dummy.db",
        doc_id="doc123",
        total_pages=44,
        stop_event=StopAfterOneTick(),
    )

    captured = capsys.readouterr()

    assert updates == [1]
    assert "Progress for doc123: 1/44" not in captured.out


def test_toc_extract_stage_log_details_separate_start_pages_from_coverage():
    details = PageIndexService._build_toc_extract_stage_details(
        [
            {"physical_index": 1},
            {"physical_index": 5},
            {"physical_index": 186},
        ],
        page_count=201,
        frozen=True,
    )

    assert details == {
        "start_pages": "1-186",
        "coverage": "100%",
        "final_end": 201,
        "frozen": True,
    }
