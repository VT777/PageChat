import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_MD = ROOT / "docs" / "architecture" / "ai_knowledge_expected_toc_reference.md"
FIXTURE_PATH = ROOT / "backend" / "tests" / "fixtures" / "toc" / "ai_knowledge_expected_toc_reference.json"


def _load_fixture() -> dict:
    assert FIXTURE_PATH.exists(), "expected TOC reference fixture is missing"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_expected_toc_reference_fixture_covers_all_ai_knowledge_documents() -> None:
    fixture = _load_fixture()
    documents = fixture.get("documents")

    assert fixture["source_markdown"] == str(REFERENCE_MD)
    assert isinstance(documents, list)
    assert [doc["id"] for doc in documents] == [f"T{idx:02d}" for idx in range(1, 14)]

    for doc in documents:
        assert doc["file"].endswith(".pdf")
        assert doc["page_count"] > 0
        assert doc["expected_path"]
        assert doc.get("reference_status") in {"locked", "needs_child_expansion", "reject_current"}
        assert doc.get("expected_route", {}).get("selected_path")
        assert doc.get("required_checks"), f"{doc['id']} must define concrete checks"


def test_expected_toc_reference_fixture_has_route_specific_assertions() -> None:
    fixture = _load_fixture()
    by_id = {doc["id"]: doc for doc in fixture["documents"]}

    assert by_id["T03"]["forbidden_patterns"]["max_nodes_on_same_non_toc_page"] == 3
    assert by_id["T04"]["required_checks"]["requires_child_expansion"] is True
    assert by_id["T05"]["must_have_nodes"][0]["start_index"] == 3
    assert by_id["T08"]["must_have_sections"] == ["main_toc", "figure_toc", "table_toc"]
    assert by_id["T09"]["must_have_nodes"][2]["title"].startswith("1.3")
    assert by_id["T13"]["forbidden_title_patterns"] == ["pure_digit", "date_only", "table_cell_org_name"]


def test_expected_toc_reference_markdown_contains_all_fixture_documents() -> None:
    fixture = _load_fixture()
    markdown = REFERENCE_MD.read_text(encoding="utf-8")

    for doc in fixture["documents"]:
        assert f"## {doc['id']} " in markdown
        assert doc["file"] in markdown
