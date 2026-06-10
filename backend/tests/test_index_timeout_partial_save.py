import asyncio
from pathlib import Path
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import documents as documents_api


class FakeDb:
    def __init__(self):
        self.calls = []
        self.committed = False

    async def execute(self, sql, params):
        self.calls.append((sql, params))

    async def commit(self):
        self.committed = True


def test_timeout_with_existing_base_index_marks_completed(monkeypatch) -> None:
    temp_root = Path(__file__).resolve().parents[1] / "tmp_timeout_partial"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    index_path = temp_root / "doc-1.json"
    index_path.write_text(json.dumps({"enrichment_status": "pending"}), encoding="utf-8")

    monkeypatch.setattr(documents_api, "INDEXES_DIR", temp_root)
    monkeypatch.setattr(documents_api, "trigger_search_rebuild_background", lambda: None)
    db = FakeDb()

    try:
        result = asyncio.run(
            documents_api._mark_completed_from_partial_index_if_exists(
                db,
                "doc-1",
                "Indexing exceeded 600s limit",
            )
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    assert result is True
    assert db.committed is True
    assert db.calls
    params = db.calls[0][1]
    assert params[0] == "completed"
    assert params[1] == str(index_path)
    assert "using base index" in params[2]
    assert params[3] == "doc-1"


def test_timeout_without_base_index_keeps_failure_path(monkeypatch) -> None:
    temp_root = Path(__file__).resolve().parents[1] / "tmp_timeout_missing"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(documents_api, "INDEXES_DIR", temp_root)
    db = FakeDb()

    try:
        result = asyncio.run(
            documents_api._mark_completed_from_partial_index_if_exists(
                db,
                "doc-1",
                "Indexing exceeded 600s limit",
            )
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    assert result is False
    assert db.calls == []
    assert db.committed is False
