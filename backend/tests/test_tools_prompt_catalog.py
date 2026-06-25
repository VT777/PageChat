from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prompts import build_agent_system_prompt, build_tool_catalog
from app.services.tool_executor import AGENT_TOOLS


def test_tool_catalog_contains_aggregate_tables() -> None:
    catalog = build_tool_catalog(AGENT_TOOLS)
    assert "aggregate_tables" in catalog


def test_agent_prompt_injects_latest_tool_catalog() -> None:
    prompt = build_agent_system_prompt(AGENT_TOOLS)
    assert "## Tool list" in prompt
    assert "browse_documents" in prompt
    assert "view_folder_structure" in prompt
    assert "aggregate_tables" in prompt


def test_agent_prompt_prefers_navigation_tools_over_raw_retrieval() -> None:
    prompt = build_agent_system_prompt(AGENT_TOOLS)

    assert "browse_documents -> inspect each structure" in prompt
    assert "find_related_documents only to identify candidate documents" not in prompt
    assert "call this first" not in prompt
    assert "not as final evidence" in prompt
    assert "visual pages intentionally omit OCR text" in prompt


def test_agent_prompt_describes_keyword_document_locator_rules() -> None:
    prompt = build_agent_system_prompt(AGENT_TOOLS)

    assert "selected document + locating/keyword question -> search_within_document" in prompt
    assert "deterministic keyword/phrase matching, not BM25/rerank or semantic retrieval" in prompt
    assert "use search matches to choose pages, then fetch source content or page images" in prompt
    assert "OCR/visual search matches must be verified through get_page_image or get_document_image" in prompt
    assert "do not repeat the same tool call with identical arguments" in prompt
