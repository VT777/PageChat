import asyncio
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import DocumentResponse
from app.services.cache_service import cache_service
from app.services.tool_executor import ToolExecutor


def _doc() -> DocumentResponse:
    return DocumentResponse(
        id="doc-a",
        name="a.pdf",
        original_name="a.pdf",
        file_path="/tmp/a.pdf",
        file_size=10,
        file_type=".pdf",
        status="completed",
        page_count=5,
        processed_pages=5,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class FakeDocumentService:
    async def get_document(self, doc_id: str, user_id: str | None = None):
        return _doc() if doc_id == "doc-a" and user_id == "user-a" else None


class FakePageIndexService:
    async def load_index(self, doc_id: str):
        return {
            "quality_report": {
                "status": "completed",
                "score": 0.91,
                "warnings": [],
            },
            "structure": [
                {
                    "node_id": "n1",
                    "title": "Chapter",
                    "start_index": 1,
                    "end_index": 5,
                    "summary": "chapter summary",
                    "text": "full chapter text must not appear",
                    "nodes": [
                        {
                            "node_id": "n1-1",
                            "title": "Section",
                            "start_index": 2,
                            "end_index": 3,
                            "summary": "section summary",
                            "text": "secret section text",
                            "source_anchor": {
                                "format": "pdf",
                                "unit_type": "page",
                                "start_page": 2,
                                "end_page": 3,
                            },
                        }
                    ],
                }
            ]
        }


def test_get_document_structure_can_return_hierarchy_preserving_compact_tree() -> None:
    async def run() -> None:
        cache_service.clear_all()
        executor = ToolExecutor(
            FakePageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute(
            "get_document_structure", {"doc_id": "doc-a", "compact": True}
        )

        tree = result["structure"]
        assert result["structure_format"] == "compact_tree"
        assert result["quality_report"]["status"] == "completed"
        assert result["retrieval_guidance"]["recommended_next_action"] == "use_structure"
        assert tree[0]["node_id"] == "n1"
        assert tree[0]["children"][0]["node_id"] == "n1-1"
        assert tree[0]["children"][0]["source_anchor"]["start_page"] == 2
        assert "text" not in tree[0]
        assert "text" not in tree[0]["children"][0]

    asyncio.run(run())


def test_compact_structure_flags_needs_review_quality_for_agent() -> None:
    class WeakPageIndexService(FakePageIndexService):
        async def load_index(self, doc_id: str):
            payload = await super().load_index(doc_id)
            payload["quality_report"] = {
                "status": "needs_review",
                "score": 0.42,
                "warnings": ["Low page coverage"],
            }
            return payload

    async def run() -> None:
        cache_service.clear_all()
        executor = ToolExecutor(
            WeakPageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute(
            "get_document_structure", {"doc_id": "doc-a", "compact": True}
        )

        assert result["quality_report"]["status"] == "needs_review"
        assert result["retrieval_guidance"] == {
            "recommended_next_action": "verify_with_source_content",
            "fallback_suggested": True,
            "reason": "Index quality needs review; verify compact structure against source content before final claims.",
        }

    asyncio.run(run())


def test_get_document_structure_default_shape_remains_flat_compatible() -> None:
    async def run() -> None:
        cache_service.clear_all()
        executor = ToolExecutor(
            FakePageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute("get_document_structure", {"doc_id": "doc-a"})

        assert result.get("structure_format") != "compact_tree"
        assert [item["node_id"] for item in result["structure"]] == ["n1", "n1-1"]
        assert "children" not in result["structure"][0]

    asyncio.run(run())
