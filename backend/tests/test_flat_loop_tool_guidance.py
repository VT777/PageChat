import asyncio
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_tool_loop import ModelToolLoopRuntime, _DEFAULT_SYSTEM_PROMPT
from app.agent.state import AgentRunState
from app.models.schemas import DocumentResponse
from app.services.tool_executor import AGENT_TOOLS, ToolExecutor
from app.services.web_search_tool import WEB_SEARCH_TOOL


def _doc(
    doc_id: str = "flat-doc",
    name: str = "report.pdf",
    folder_id: str | None = "folder-a",
) -> DocumentResponse:
    return DocumentResponse(
        id=doc_id,
        name=name,
        original_name=name,
        file_path=f"/tmp/{name}",
        file_size=10,
        file_type=".pdf",
        status="completed",
        page_count=3,
        processed_pages=3,
        folder_id=folder_id,
        folder_path="root/reports" if folder_id else "",
        description="A compact report description.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class FakeDocumentService:
    def __init__(self):
        self.docs = [_doc()]

    async def get_document(self, doc_id: str, user_id: str | None = None):
        for doc in self.docs:
            if doc.id == doc_id:
                return doc
        return None

    async def get_indexed_documents(self, user_id: str | None = None):
        return list(self.docs)


class FakePageIndexService:
    async def load_index(self, doc_id: str):
        return {
            "structure": [
                {
                    "node_id": "n1",
                    "title": "Overview",
                    "start_index": 1,
                    "end_index": 3,
                    "summary": "Overview summary",
                }
            ]
        }


class FakeModel:
    async def stream_turn(self, **_kwargs):
        if False:
            yield None


class FakeToolRunner:
    async def execute(self, tool_name, arguments):
        return {"success": True}


def _tool_schema(name: str) -> dict:
    for tool in [*AGENT_TOOLS, WEB_SEARCH_TOOL]:
        if tool["function"]["name"] == name:
            return tool["function"]
    raise AssertionError(f"tool {name} not found")


def test_flat_runtime_prompt_guides_model_without_planner_language() -> None:
    prompt = _DEFAULT_SYSTEM_PROMPT
    lower = prompt.lower()

    assert "return json" not in lower
    assert "planner" not in lower
    assert "action.type" not in lower
    assert "backend checks" not in lower
    assert "decide dynamically" in lower
    assert "information gap" in lower
    assert "answer in the user's language" in lower
    assert "cite" in lower


def test_flat_runtime_prompt_requires_readable_inline_citation_markers() -> None:
    prompt = _DEFAULT_SYSTEM_PROMPT

    assert "[[display_label]]" in prompt
    assert "citation_key" in prompt
    assert "[cite:" in prompt
    assert "immediately after the supported claim" in prompt


def test_initial_messages_do_not_inject_forced_document_route() -> None:
    runtime = ModelToolLoopRuntime(
        model=FakeModel(),
        tool_runner=FakeToolRunner(),
        tools=AGENT_TOOLS,
    )
    state = AgentRunState(
        question="现在有哪些文档",
        conversation_id="c1",
        run_id="r1",
        message_id="m1",
        scope={
            "user_id": "u1",
            "folder_id": "folder-a",
            "include_subfolders": True,
            "selected_scope_summary": {"folder": "AI_Knowledge"},
        },
    )

    text = "\n".join(str(message.get("content", "")) for message in runtime._initial_messages(state))

    assert "view_folder_structure -> browse_documents" not in text
    assert "get_document_structure -> get_page_content" not in text
    assert "before reading pages" not in text


def test_key_tool_descriptions_are_affordances_not_fixed_routes() -> None:
    view_folder_description = _tool_schema("view_folder_structure")["description"]
    browse_description = _tool_schema("browse_documents")["description"]
    structure_description = _tool_schema("get_document_structure")["description"]
    page_description = _tool_schema("get_page_content")["description"]
    web_description = _tool_schema("web_search")["description"]

    assert "before browsing" not in view_folder_description
    assert "use get_document_structure and get_page_content" not in browse_description.lower()
    assert "when section/page-range context is useful" in structure_description
    assert "visual pages return image references only" in page_description
    assert "when the user requested web search" in web_description


def test_document_tool_next_steps_are_concise_model_guidance() -> None:
    async def run() -> None:
        executor = ToolExecutor(
            FakePageIndexService(),
            FakeDocumentService(),
            user_id="flat-guidance-user",
        )

        browse = await executor.execute(
            "browse_documents",
            {"document_ids": ["flat-doc"]},
        )
        structure = await executor.execute(
            "get_document_structure",
            {"doc_id": "flat-doc"},
        )

        assert isinstance(browse["next_steps"], str)
        assert "fixed workflow" not in browse["next_steps"].lower()
        assert "before reading pages" not in browse["next_steps"]
        assert isinstance(structure["next_steps"], str)
        assert "before reading pages" not in structure["next_steps"]

    asyncio.run(run())
