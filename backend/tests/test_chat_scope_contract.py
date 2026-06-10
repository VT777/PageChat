from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import ChatRequest
from app.services.agent_service import AgentService


def test_chat_request_accepts_folder_scope_fields() -> None:
    request = ChatRequest(
        question="Summarize this folder",
        document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=False,
    )

    assert request.folder_id == "folder-a"
    assert request.include_subfolders is True
    assert request.strict_scope is False


def test_agent_injects_folder_scope_into_find_related_documents() -> None:
    patched = AgentService._inject_default_doc_id(
        "find_related_documents",
        {"query": "alpha"},
        document_ids=["doc-a", "doc-b"],
        preferred_document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=True,
    )

    assert patched["document_ids"] == ["doc-a"]
    assert patched["folder_id"] == "folder-a"
    assert patched["include_subfolders"] is True
    assert patched["strict_scope"] is True


def test_agent_scope_cache_key_differs_by_folder_scope() -> None:
    doc_scope = AgentService._conversation_state_key(
        "conv-1", user_id="user-a", document_ids=["doc-a"]
    )
    folder_scope = AgentService._conversation_state_key(
        "conv-1",
        user_id="user-a",
        document_ids=["doc-a"],
        folder_id="folder-a",
        include_subfolders=True,
        strict_scope=True,
    )

    assert doc_scope != folder_scope
