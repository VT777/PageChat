from datetime import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.documents import _attach_parse_meta
from app.models.schemas import DocumentResponse


def test_attach_parse_meta_exposes_optional_quality_report(tmp_path) -> None:
    index_path = tmp_path / "doc.json"
    index_path.write_text(
        json.dumps(
            {
                "quality_report": {
                    "status": "needs_review",
                    "score": 0.62,
                    "warnings": ["page range coverage below threshold"],
                    "node_count": 3,
                    "page_range_coverage": 0.5,
                }
            }
        ),
        encoding="utf-8",
    )
    now = datetime.now()
    doc = DocumentResponse(
        id="doc-a",
        name="doc-a.pdf",
        original_name="doc-a.pdf",
        file_path=str(tmp_path / "doc-a.pdf"),
        index_path=str(index_path),
        file_size=10,
        file_type=".pdf",
        status="completed",
        created_at=now,
        updated_at=now,
    )

    enriched = _attach_parse_meta(doc)

    assert enriched.quality_report["status"] == "needs_review"
    assert enriched.quality_report["warnings"] == [
        "page range coverage below threshold"
    ]
