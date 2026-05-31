from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.table_analysis_service import TableAnalysisService


def test_groupby_sum_on_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "city,amount\nbeijing,10\nbeijing,20\nshanghai,5\n",
        encoding="utf-8",
    )

    doc = type(
        "Doc",
        (),
        {
            "id": "doc-1",
            "original_name": "sales.csv",
            "file_type": ".csv",
            "file_path": str(csv_path),
        },
    )()

    service = TableAnalysisService()
    loaded = service.load_table_documents([doc])
    result = service.aggregate(
        loaded["datasets"],
        {
            "operation": "groupby",
            "group_by": "city",
            "target_column": "amount",
            "metric": "sum",
        },
    )

    table = result["result_table"]
    assert table[0]["city"] == "beijing"
    assert table[0]["sum_amount"] == 30
    assert any(c["doc_id"] == "doc-1" for c in result["citations"])
