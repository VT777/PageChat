from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.utils import post_processing


def _flatten(nodes):
    out = []
    for node in nodes:
        out.append(node)
        children = node.get("nodes") or []
        out.extend(_flatten(children))
    return out


def test_post_processing_never_generates_negative_range_when_same_page_starts() -> None:
    flat = [
        {
            "structure": "4",
            "title": "第四章",
            "physical_index": 46,
            "appear_start": "yes",
        },
        {
            "structure": "4.1",
            "title": "引言",
            "physical_index": 46,
            "appear_start": "yes",
        },
        {
            "structure": "4.2",
            "title": "行业场景",
            "physical_index": 47,
            "appear_start": "yes",
        },
    ]

    tree = post_processing(flat, end_physical_index=50)
    all_nodes = _flatten(tree)

    assert all(
        node["end_index"] >= node["start_index"]
        for node in all_nodes
        if isinstance(node.get("start_index"), int)
        and isinstance(node.get("end_index"), int)
    )
