from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService


def test_sanitize_tool_result_removes_nested_base64_fields() -> None:
    raw = {
        "status": "success",
        "data": {
            "doc_id": "x",
            "image_base64": "AAAA",
            "nested": {"page_image_base64": "BBBB", "keep": 1},
        },
        "page_image_base64": "CCCC",
        "ok": True,
    }

    cleaned = AgentService._sanitize_tool_result_for_history(raw)
    assert "page_image_base64" not in cleaned
    assert "image_base64" not in cleaned["data"]
    assert "page_image_base64" not in cleaned["data"]["nested"]
    assert cleaned["data"]["nested"]["keep"] == 1
    assert cleaned["ok"] is True
