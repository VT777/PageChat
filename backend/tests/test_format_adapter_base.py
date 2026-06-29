from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.format_adapters import (
    ContentBlock,
    DocumentContent,
    FormatCapabilities,
    IndexNode,
    SourceAnchor,
    document_content_to_index,
)


def test_document_content_converts_to_current_index_shape() -> None:
    anchor = SourceAnchor(
        format="markdown",
        unit_type="line",
        values={"start_line": 2, "end_line": 8},
    ).to_dict()
    node = IndexNode(
        node_id="node_1",
        title="Intro",
        summary="Short summary",
        text="Full text",
        start_index=1,
        end_index=1,
        source_anchor=anchor,
        level=1,
    )
    content = DocumentContent(
        format="markdown",
        title="notes.md",
        doc_description="Document summary",
        unit_type="line",
        unit_count=12,
        nodes=[node],
        blocks=[
            ContentBlock(
                id="line_2",
                type="text",
                content="Full text",
                source_anchor=anchor,
            )
        ],
        metadata={"encoding": "utf-8"},
    )

    result = document_content_to_index(content)

    assert result["format"] == "markdown"
    assert result["doc_description"] == "Document summary"
    assert result["page_count"] == 12
    assert result["unit_type"] == "line"
    assert result["unit_count"] == 12
    assert result["metadata"] == {"encoding": "utf-8"}
    assert result["structure"][0]["source_anchor"]["unit_type"] == "line"
    assert result["structure"][0]["nodes"] == []


def test_format_capabilities_serializes_supported_features() -> None:
    capabilities = FormatCapabilities(
        format="xlsx",
        unit_type="row_range",
        supports_tables=True,
        supports_images=False,
        supports_hierarchy=True,
    )

    assert capabilities.to_dict() == {
        "format": "xlsx",
        "unit_type": "row_range",
        "supports_tables": True,
        "supports_images": False,
        "supports_hierarchy": True,
    }
