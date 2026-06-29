from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService
from app.services.cache_service import CacheService


def test_structure_cache_is_scoped_by_user() -> None:
    cache = CacheService()
    cache.clear_all()

    cache.set_structure("user-a", "doc-1", {"owner": "a"})

    assert cache.get_structure("user-a", "doc-1") == {"owner": "a"}
    assert cache.get_structure("user-b", "doc-1") is None


def test_page_content_cache_is_scoped_by_user() -> None:
    cache = CacheService()
    cache.clear_all()

    cache.set_page_content("user-a", "doc-1", 2, False, {"owner": "a"})

    assert cache.get_page_content("user-a", "doc-1", 2, False) == {"owner": "a"}
    assert cache.get_page_content("user-b", "doc-1", 2, False) is None


def test_search_result_cache_is_scoped_by_user() -> None:
    cache = CacheService()
    cache.clear_all()

    cache.set_search_result("user-a", "alpha", ["doc-1"], [{"owner": "a"}])

    assert cache.get_search_result("user-a", "alpha", ["doc-1"]) == [
        {"owner": "a"}
    ]
    assert cache.get_search_result("user-b", "alpha", ["doc-1"]) is None


def test_agent_tool_cache_key_differs_by_user_and_scope() -> None:
    args = {"doc_id": "doc-1", "page_nums": [1], "include_image": True}

    user_a_key = AgentService._build_tool_cache_key(
        "get_page_content", args, user_id="user-a", document_ids=["doc-1"]
    )
    user_b_key = AgentService._build_tool_cache_key(
        "get_page_content", args, user_id="user-b", document_ids=["doc-1"]
    )
    other_scope_key = AgentService._build_tool_cache_key(
        "get_page_content", args, user_id="user-a", document_ids=["doc-2"]
    )
    same_page_no_image_key = AgentService._build_tool_cache_key(
        "get_page_content",
        {"doc_id": "doc-1", "page_nums": [1], "include_image": False},
        user_id="user-a",
        document_ids=["doc-1"],
    )

    assert user_a_key != user_b_key
    assert user_a_key != other_scope_key
    assert user_a_key == same_page_no_image_key


def test_agent_conversation_message_key_differs_by_user_and_scope() -> None:
    user_a_key = AgentService._conversation_state_key(
        "conv-1", user_id="user-a", document_ids=["doc-1"]
    )
    user_b_key = AgentService._conversation_state_key(
        "conv-1", user_id="user-b", document_ids=["doc-1"]
    )
    other_scope_key = AgentService._conversation_state_key(
        "conv-1", user_id="user-a", document_ids=["doc-2"]
    )

    assert user_a_key != user_b_key
    assert user_a_key != other_scope_key
