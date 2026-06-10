from pathlib import Path
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
import app.services.pageindex_service as pageindex_service_module


def test_save_index_payload_writes_json_before_enrichment(monkeypatch) -> None:
    temp_dir = Path(__file__).resolve().parents[1] / "tmp_test_indexes"
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pageindex_service_module, "INDEXES_DIR", temp_dir)

    payload = {
        "doc_name": "demo.pdf",
        "doc_description": "",
        "page_count": 2,
        "structure": [{"title": "A", "start_index": 1, "end_index": 2}],
        "enrichment_status": "pending",
    }

    index_path = PageIndexService._save_index_payload("doc-1", payload)

    try:
        assert index_path == temp_dir / "doc-1.json"
        assert json.loads(index_path.read_text(encoding="utf-8")) == payload
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
