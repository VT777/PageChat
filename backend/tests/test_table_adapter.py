from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.format_adapters.table_adapter import parse_table
from app.services.multi_format_adapter import generate_multi_format_index


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_csv_table_adapter_emits_dataset_and_row_anchors(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.csv"
    file_path.write_text("city,amount\nbeijing,10\nshanghai,20\n", encoding="utf-8")

    content = parse_table(file_path)

    assert content.format == "csv"
    assert content.nodes[0].source_anchor["unit_type"] == "row_range"
    assert content.tables[0]["headers"] == ["city", "amount"]
    assert content.tables[0]["rows"][0]["amount"] == "10"
    assert content.tables[0]["schema"]["amount"] == "number"
    assert content.blocks[0].source_anchor["start_row"] == 1


def test_tsv_table_adapter_uses_tab_delimiter(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.tsv"
    file_path.write_text("city\tamount\nbeijing\t10\n", encoding="utf-8")

    content = parse_table(file_path)

    assert content.format == "tsv"
    assert content.tables[0]["rows"][0]["city"] == "beijing"


def test_xlsx_table_adapter_handles_sheets_and_limits(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.xlsx"
    rows = "\n".join(
        f"<row r='{i}'><c r='A{i}' t='inlineStr'><is><t>city{i}</t></is></c><c r='B{i}'><v>{i}</v></c></row>"
        for i in range(1, 123)
    )
    _write_zip(
        file_path,
        {
            "xl/workbook.xml": "<workbook><sheets><sheet name='Sales' sheetId='1'/></sheets></workbook>",
            "xl/worksheets/sheet1.xml": f"<worksheet><sheetData>{rows}</sheetData></worksheet>",
        },
    )

    content = parse_table(file_path)

    assert content.format == "xlsx"
    assert content.tables[0]["sheet"] == "Sales"
    assert content.nodes[0].source_anchor["sheet"] == "Sales"
    assert content.nodes[0].source_anchor["end_row"] <= 100
    assert content.metadata["row_count"] == 122


def test_xlsx_table_adapter_handles_multiple_sheets_and_empty_rows(tmp_path: Path) -> None:
    file_path = tmp_path / "multi.xlsx"
    _write_zip(
        file_path,
        {
            "xl/workbook.xml": """
            <workbook>
              <sheets>
                <sheet name='North' sheetId='1'/>
                <sheet name='South' sheetId='2'/>
              </sheets>
            </workbook>
            """,
            "xl/worksheets/sheet1.xml": """
            <worksheet><sheetData>
              <row r='1'><c r='A1' t='inlineStr'><is><t>city</t></is></c><c r='B1' t='inlineStr'><is><t>amount</t></is></c></row>
              <row r='2'></row>
              <row r='3'><c r='A3' t='inlineStr'><is><t>beijing</t></is></c><c r='B3'><v>10</v></c></row>
            </sheetData></worksheet>
            """,
            "xl/worksheets/sheet2.xml": """
            <worksheet><sheetData>
              <row r='1'><c r='A1' t='inlineStr'><is><t>city</t></is></c><c r='B1' t='inlineStr'><is><t>amount</t></is></c></row>
              <row r='2'><c r='A2' t='inlineStr'><is><t>shanghai</t></is></c><c r='B2'><v>20</v></c></row>
            </sheetData></worksheet>
            """,
        },
    )

    content = parse_table(file_path)

    assert [table["sheet"] for table in content.tables] == ["North", "South"]
    assert content.tables[0]["rows"] == [{"city": "beijing", "amount": "10"}]
    assert content.tables[0]["schema"]["amount"] == "number"


def test_corrupt_xlsx_returns_controlled_error(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.xlsx"
    file_path.write_text("not a zip", encoding="utf-8")

    content = parse_table(file_path)

    assert content.nodes == []
    assert content.metadata["parse_status"] == "error"
    assert "error" in content.metadata


def test_facade_delegates_tables_to_canonical_adapter(tmp_path: Path) -> None:
    file_path = tmp_path / "sales.csv"
    file_path.write_text("city,amount\nbeijing,10\n", encoding="utf-8")

    result = generate_multi_format_index(file_path)

    assert result["metadata"]["adapter"] == "canonical_table"
    assert result["unit_type"] == "row_range"
