import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_turn import ModelToolCall
from app.agent.nodes import compact_tool_result
from app.agent.tool_messages import build_tool_result_message


def test_browse_documents_tool_result_is_compact_model_json():
    call = ModelToolCall(
        id="call_1",
        name="browse_documents",
        arguments={"folder_id": "root"},
    )
    result = {
        "success": True,
        "documents": [
            {
                "id": "doc-a",
                "name": "Report.pdf",
                "page_count": 12,
                "description": "A report",
                "file_path": "C:/secret/Report.pdf",
            }
        ],
        "next_steps": "Use document structure or page tools for content questions.",
    }

    message, ui_result = build_tool_result_message(call, result)

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_1"
    assert message["name"] == "browse_documents"
    assert message["content"]
    assert "file_path" not in message["content"]
    assert "C:/secret" not in message["content"]
    assert "Report.pdf" in message["content"]
    assert ui_result["result_label"] == "1 document"


def test_model_tool_message_strips_large_payloads_but_keeps_page_evidence():
    call = ModelToolCall(id="call_2", name="get_page_content", arguments={"pages": "2"})
    result = {
        "success": True,
        "data": {
            "doc_id": "doc-a",
            "doc_name": "alpha.pdf",
            "returned_pages": "2",
            "content": [
                {
                    "page": 2,
                    "text": "Relevant evidence.",
                    "ocr_text": "raw ocr text should not be copied wholesale",
                    "page_image_base64": "base64-payload",
                    "embedding": [0.1, 0.2],
                }
            ],
        },
    }

    message, ui_result = build_tool_result_message(call, result)
    content = json.loads(message["content"])

    assert content["doc_id"] == "doc-a"
    assert content["items"][0]["page"] == 2
    assert content["items"][0]["text"] == "Relevant evidence."
    assert "base64-payload" not in message["content"]
    assert "raw ocr text" not in message["content"]
    assert "embedding" not in message["content"]
    assert ui_result["result_label"] == "1 page"


def test_model_tool_message_exposes_readable_citation_markers_not_internal_keys():
    call = ModelToolCall(
        id="call_3",
        name="search_within_document",
        arguments={"doc_id": "doc-cq", "query": "Chongqing Normal University"},
    )
    result = {
        "success": True,
        "matches": [
            {
                "doc_id": "doc-cq",
                "doc_name": "Chongqing cases.pdf",
                "page": 43,
                "snippet": "Chongqing Normal University case appears here.",
                "citation_key": "c0c48156",
                "display_label": "Chongqing cases.pdf p.43",
                "source_anchor": {
                    "format": "pdf",
                    "unit_type": "page",
                    "start_page": 43,
                    "end_page": 43,
                },
            }
        ],
    }

    message, ui_result = build_tool_result_message(call, result)
    content = json.loads(message["content"])

    assert content["items"][0]["citation_marker"] == "[[Chongqing cases.pdf p.43]]"
    assert content["citation_markers"] == ["[[Chongqing cases.pdf p.43]]"]
    assert "c0c48156" not in message["content"]
    assert "citation_key" not in message["content"]
    assert ui_result["citations"][0]["display_label"] == "Chongqing cases.pdf p.43"


def test_web_tool_message_does_not_emit_document_style_citation_marker():
    call = ModelToolCall(
        id="call_web",
        name="web_search",
        arguments={"query": "PageChat"},
    )
    result = {
        "success": True,
        "results": [
            {
                "title": "PageChat docs",
                "url": "https://example.test/pagechat",
                "snippet": "PageChat web result.",
                "source": "anysearch",
            }
        ],
    }

    message, _ui_result = build_tool_result_message(call, result)

    assert "citation_marker" not in message["content"]
    assert "[[PageChat docs]]" not in message["content"]
    assert "https://example.test/pagechat" in message["content"]


def test_view_folder_structure_has_display_metadata():
    result = compact_tool_result(
        {
            "success": True,
            "tree": {"id": "root", "name": "root", "children": []},
            "total_folders": 2,
        },
        tool_name="view_folder_structure",
    )

    assert result["result_count"] == 2
    assert result["result_label"] == "2 folders"


def test_folder_tool_message_keeps_names_but_strips_local_paths():
    call = ModelToolCall(
        id="call_folders",
        name="view_folder_structure",
        arguments={},
    )
    result = {
        "success": True,
        "tree": {
            "id": "root",
            "name": "root",
            "path": "root",
            "path_on_disk": "C:/secret/root",
            "children": [
                {
                    "id": "folder-sales",
                    "name": "Sales",
                    "path": "root/Sales",
                    "path_on_disk": "C:/secret/root/Sales",
                    "children": [],
                }
            ],
        },
        "total_folders": 2,
    }

    message, ui_result = build_tool_result_message(call, result)
    content = json.loads(message["content"])

    assert content["tree"]["children"][0]["name"] == "Sales"
    assert "C:/secret" not in message["content"]
    assert "path_on_disk" not in message["content"]
    assert ui_result["result_label"] == "2 folders"
