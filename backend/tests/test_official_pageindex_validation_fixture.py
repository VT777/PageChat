import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "backend" / "tests" / "fixtures" / "toc" / "official_pageindex_expected_toc_reference.json"
OFFICIAL_DOCS_DIR = Path(r"D:\projects\PageIndex\examples\documents")
OFFICIAL_RESULTS_DIR = OFFICIAL_DOCS_DIR / "results"


EXPECTED_FILES = [
    "2023-annual-report.pdf",
    "2023-annual-report-truncated.pdf",
    "attention-residuals.pdf",
    "earthmover.pdf",
    "four-lectures.pdf",
    "PRML.pdf",
    "q1-fy25-earnings.pdf",
    "Regulation Best Interest_Interpretive release.pdf",
    "Regulation Best Interest_proposed rule.pdf",
]


def _load_fixture() -> dict:
    assert FIXTURE_PATH.exists(), "official PageIndex validation fixture is missing"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_official_pageindex_fixture_covers_all_sample_documents() -> None:
    fixture = _load_fixture()
    documents = fixture.get("documents")

    assert fixture["input_dir"] == str(OFFICIAL_DOCS_DIR)
    assert fixture["official_results_dir"] == str(OFFICIAL_RESULTS_DIR)
    assert isinstance(documents, list)
    assert [doc["file"] for doc in documents] == EXPECTED_FILES

    for index, doc in enumerate(documents, start=1):
        assert doc["id"] == f"P{index:02d}"
        assert doc["page_count"] > 0
        assert doc["expected_route"]["selected_path"]
        assert doc["acceptance"]["must_succeed"] is True
        assert doc["acceptance"]["min_node_count"] > 0
        assert doc["acceptance"]["min_depth"] >= 1
        assert doc["acceptance"].get("forbidden_patterns", {}).get("no_generic_single_node") is True


def test_official_pageindex_fixture_marks_official_baseline_coverage() -> None:
    fixture = _load_fixture()
    by_file = {doc["file"]: doc for doc in fixture["documents"]}

    assert by_file["attention-residuals.pdf"]["official_baseline"]["available"] is False

    for file_name, doc in by_file.items():
        if file_name == "attention-residuals.pdf":
            continue
        baseline = doc["official_baseline"]
        assert baseline["available"] is True
        assert baseline["result_file"].endswith("_structure.json")
        assert baseline["metrics"]["root_count"] > 0
        assert baseline["metrics"]["node_count"] >= baseline["metrics"]["root_count"]
        assert baseline["metrics"]["max_depth"] >= 1
        assert doc["acceptance"]["min_node_count"] <= baseline["metrics"]["node_count"]
        assert doc["acceptance"]["min_depth"] <= baseline["metrics"]["max_depth"]


def test_official_pageindex_fixture_has_known_regression_assertions() -> None:
    fixture = _load_fixture()
    by_file = {doc["file"]: doc for doc in fixture["documents"]}

    earthmover = by_file["earthmover.pdf"]
    assert earthmover["expected_route"]["selected_path"] == "content_outline"
    assert "INTRODUCTION" in earthmover["acceptance"]["required_root_titles"]
    assert "CONCLUSION" in earthmover["acceptance"]["required_root_titles"]

    four_lectures = by_file["four-lectures.pdf"]
    assert four_lectures["expected_route"]["content_type"] == "ocr"
    assert "Preface" in four_lectures["acceptance"]["required_root_titles"]
    assert "ML at a Glance" in four_lectures["acceptance"]["required_root_titles"]

    annual = by_file["2023-annual-report.pdf"]
    assert annual["expected_route"]["selected_path"] == "embedded_toc"
    assert annual["acceptance"]["forbidden_patterns"]["do_not_replace_good_embedded_toc_with_weaker_fallback"] is True

    proposed = by_file["Regulation Best Interest_proposed rule.pdf"]
    assert proposed["expected_route"]["selected_path"] == "embedded_toc"
    assert proposed["acceptance"]["required_pages"]["IV. Economic Analysis"] == 214


def test_official_pageindex_fixture_references_real_files_when_available() -> None:
    fixture = _load_fixture()
    input_dir = Path(fixture["input_dir"])
    if not input_dir.exists():
        pytest.skip(f"Official PageIndex examples are not available: {input_dir}")

    actual = {path.name for path in input_dir.glob("*.pdf")}
    assert set(EXPECTED_FILES) <= actual

    for doc in fixture["documents"]:
        baseline = doc["official_baseline"]
        if baseline["available"]:
            assert (Path(fixture["official_results_dir"]) / baseline["result_file"]).exists()
