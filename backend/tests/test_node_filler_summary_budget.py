import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import node_filler


def test_balanced_summary_node_timeout_falls_back(monkeypatch) -> None:
    tree = [{"title": "Slow node", "text": "Important text"}]

    async def slow_summary(_node, model=None):
        await asyncio.sleep(0.2)
        return "should not be used"

    async def run_case() -> None:
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS", 1.0)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_MAX_LLM_NODES", 10)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_CONCURRENCY", 1)
        monkeypatch.setattr(
            node_filler,
            "_call_generate_node_summary",
            slow_summary,
        )

        await node_filler.generate_summaries(tree, mode="balanced")

    asyncio.run(run_case())

    assert tree[0]["summary"].startswith("Slow node")
    assert "Important text" in tree[0]["summary"]


def test_balanced_summary_budget_limits_llm_nodes(monkeypatch) -> None:
    tree = [
        {"title": "A", "text": "alpha"},
        {"title": "B", "text": "beta"},
    ]
    calls = []

    async def fast_summary(node, model=None):
        calls.append(node["title"])
        return f"llm {node['title']}"

    async def run_case() -> None:
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_NODE_TIMEOUT_SECONDS", 1.0)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_TOTAL_BUDGET_SECONDS", 1.0)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_MAX_LLM_NODES", 1)
        monkeypatch.setattr(node_filler, "PAGEINDEX_SUMMARY_CONCURRENCY", 1)
        monkeypatch.setattr(
            node_filler,
            "_call_generate_node_summary",
            fast_summary,
        )

        await node_filler.generate_summaries(tree, mode="balanced")

    asyncio.run(run_case())

    assert calls == ["A"]
    assert tree[0]["summary"] == "llm A"
    assert tree[1]["summary"].startswith("B")
    assert "beta" in tree[1]["summary"]
