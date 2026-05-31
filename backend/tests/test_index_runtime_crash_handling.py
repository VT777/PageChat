from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.documents import _extract_failure_status_code, _mark_document_failed_sync


def test_extract_failure_status_code_from_prefixed_error() -> None:
    code = _extract_failure_status_code(
        "VISION_TOC_INSUFFICIENT_STRUCTURE: no visual summaries generated"
    )
    assert code == "vision_toc_insufficient_structure"


def test_extract_failure_status_code_fallback_to_indexing() -> None:
    code = _extract_failure_status_code("random runtime error")
    assert code == "indexing"


def test_mark_document_failed_sync_updates_status(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                status TEXT,
                error_message TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO documents (id, status, error_message, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            ("doc-1", "processing:indexing", None),
        )
        conn.commit()
    finally:
        conn.close()

    _mark_document_failed_sync(
        str(db_path),
        "doc-1",
        "failed:index_runtime_event_loop_crash",
        "INDEX_RUNTIME_EVENT_LOOP_CRASH: test",
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, error_message FROM documents WHERE id = ?", ("doc-1",)
        ).fetchone()
        assert row is not None
        assert row[0] == "failed:index_runtime_event_loop_crash"
        assert "INDEX_RUNTIME_EVENT_LOOP_CRASH" in row[1]
    finally:
        conn.close()
