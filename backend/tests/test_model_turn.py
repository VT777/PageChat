import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_turn import (
    ModelTextDelta,
    ModelToolCall,
    ModelToolCallDelta,
    ModelTurn,
)


def test_model_turn_collects_tool_calls_without_final_text():
    turn = ModelTurn(
        content="",
        tool_calls=[
            ModelToolCall(
                id="call_1",
                name="browse_documents",
                arguments={"folder_id": "root", "recursive": True},
            )
        ],
    )

    assert turn.has_tool_calls is True
    assert turn.has_final_text is False


def test_model_turn_treats_non_empty_content_as_final_text_only_without_tools():
    turn = ModelTurn(content="There are three documents.")

    assert turn.has_tool_calls is False
    assert turn.has_final_text is True


def test_stream_delta_events_are_plain_provider_neutral_values():
    text_delta = ModelTextDelta(delta="hello")
    tool_delta = ModelToolCallDelta(
        index=0,
        id="call_1",
        name="search_within_document",
        arguments_delta='{"query": "AI"',
    )

    assert text_delta.delta == "hello"
    assert tool_delta.index == 0
    assert tool_delta.arguments_delta.endswith('"AI"')
