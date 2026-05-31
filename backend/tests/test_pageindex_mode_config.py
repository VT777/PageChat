from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import build_effective_pageindex_config


def test_build_effective_pageindex_config_balanced() -> None:
    cfg = build_effective_pageindex_config(mode="balanced")
    assert cfg["index_mode"] == "balanced"
    assert cfg["if_add_node_text"] == "yes"


def test_build_effective_pageindex_config_fast() -> None:
    cfg = build_effective_pageindex_config(mode="fast")
    assert cfg["index_mode"] == "fast"
    assert cfg["if_add_node_summary"] == "no"
    assert cfg["if_add_doc_description"] == "no"
    assert cfg["if_add_node_text"] == "yes"


def test_build_effective_pageindex_config_smart() -> None:
    cfg = build_effective_pageindex_config(mode="smart")
    assert cfg["index_mode"] == "smart"
    assert cfg["if_add_node_summary"] == "no"
    assert cfg["if_add_doc_description"] == "no"
