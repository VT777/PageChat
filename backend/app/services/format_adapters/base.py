from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _anchor_to_dict(anchor: Mapping[str, Any] | "SourceAnchor") -> dict[str, Any]:
    if isinstance(anchor, SourceAnchor):
        return anchor.to_dict()
    return dict(anchor)


@dataclass(frozen=True)
class SourceAnchor:
    format: str
    unit_type: str
    values: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {"format": self.format, "unit_type": self.unit_type}
        data.update(dict(self.values))
        return data


@dataclass
class ContentBlock:
    id: str
    type: str
    content: Any
    source_anchor: Mapping[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "source_anchor": _anchor_to_dict(self.source_anchor),
            "metadata": dict(self.metadata),
        }


@dataclass
class IndexNode:
    node_id: str
    title: str
    summary: str
    text: str
    start_index: int
    end_index: int
    source_anchor: Mapping[str, Any]
    level: int = 1
    nodes: list["IndexNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "summary": self.summary,
            "text": self.text,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "source_anchor": _anchor_to_dict(self.source_anchor),
            "level": self.level,
            "nodes": [node.to_dict() for node in self.nodes],
        }


@dataclass
class DocumentContent:
    format: str
    title: str
    doc_description: str
    unit_type: str
    unit_count: int
    nodes: list[IndexNode]
    blocks: list[ContentBlock] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FormatCapabilities:
    format: str
    unit_type: str
    supports_tables: bool = False
    supports_images: bool = False
    supports_hierarchy: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "unit_type": self.unit_type,
            "supports_tables": self.supports_tables,
            "supports_images": self.supports_images,
            "supports_hierarchy": self.supports_hierarchy,
        }


def document_content_to_index(content: DocumentContent) -> dict[str, Any]:
    return {
        "format": content.format,
        "doc_description": content.doc_description,
        "structure": [node.to_dict() for node in content.nodes],
        "page_count": content.unit_count,
        "unit_type": content.unit_type,
        "unit_count": content.unit_count,
        "metadata": dict(content.metadata),
    }
