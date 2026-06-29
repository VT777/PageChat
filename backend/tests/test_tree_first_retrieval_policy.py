import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prompts import build_agent_system_prompt
from app.services.pageindex_service import (
    TREE_FALLBACK_CONFIDENCE_THRESHOLD,
    TREE_HIGH_CONFIDENCE_THRESHOLD,
)
from app.services.tool_executor import AGENT_TOOLS


def test_tree_first_thresholds_are_conservative() -> None:
    assert TREE_HIGH_CONFIDENCE_THRESHOLD == 0.65
    assert TREE_FALLBACK_CONFIDENCE_THRESHOLD == 0.35
    assert TREE_FALLBACK_CONFIDENCE_THRESHOLD < TREE_HIGH_CONFIDENCE_THRESHOLD


def test_agent_prompt_states_agentic_tool_selection_and_source_boundaries() -> None:
    prompt = build_agent_system_prompt(AGENT_TOOLS)

    assert "Tool Selection Principles" in prompt
    assert "You decide which tool, if any, is useful for the current turn" in prompt
    assert "get_document_structure before get_page_content" not in prompt
    assert "fetch source content before final answer" not in prompt
    assert "Document claims need source evidence from available observations or tools" in prompt


def test_agent_prompt_requires_fallback_disclosure() -> None:
    prompt = build_agent_system_prompt(AGENT_TOOLS)

    assert "keyword_fallback" in prompt
    assert "visual_summary" in prompt
    assert "disclose fallback evidence" in prompt
