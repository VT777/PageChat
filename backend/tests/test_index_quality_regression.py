import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.multi_format_adapter import generate_multi_format_index


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "evaluation"


def _load_queries() -> list[dict]:
    return json.loads((FIXTURE_DIR / "queries.json").read_text(encoding="utf-8"))


def test_evaluation_manifest_has_required_fields() -> None:
    queries = _load_queries()

    assert queries
    for item in queries:
        assert item["id"]
        assert item["query"]
        assert item["expected_title_contains"]
        assert item["expected_unit_type"]
        assert item["allow_fallback"] is False


def test_markdown_fixture_preserves_expected_node_and_line_anchor(tmp_path) -> None:
    markdown = tmp_path / "deployment-notes.md"
    markdown.write_text(
        "# Release Notes\n\n"
        "Introductory text.\n\n"
        "## Deployment Checklist\n\n"
        "- Confirm environment variables.\n"
        "- Run smoke tests.\n"
        "- Notify support.\n",
        encoding="utf-8",
    )

    index_payload = generate_multi_format_index(markdown)
    flat_nodes = []

    def walk(nodes):
        for node in nodes:
            flat_nodes.append(node)
            walk(node.get("nodes") or [])

    walk(index_payload["structure"])

    expected = _load_queries()[0]
    matched = [
        node
        for node in flat_nodes
        if expected["expected_title_contains"] in str(node.get("title") or "")
    ]

    assert matched
    assert matched[0]["source_anchor"]["unit_type"] == expected["expected_unit_type"]
    assert matched[0]["source_anchor"]["start_line"] <= matched[0]["source_anchor"]["end_line"]
