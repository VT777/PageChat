from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import page_index as page_index_module


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


def test_normalize_toc_items_supports_wrapped_dict() -> None:
    payload = {
        "table_of_contents": [
            {"structure": "1", "title": "A", "physical_index": "<physical_index_1>"}
        ]
    }
    items = page_index_module._normalize_toc_items(payload)
    assert isinstance(items, list)
    assert len(items) == 1


def test_process_no_toc_handles_dict_payload_without_extend_crash(monkeypatch) -> None:
    page_list = [("p1", 1), ("p2", 1)]

    monkeypatch.setattr(page_index_module, "count_tokens", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        page_index_module,
        "page_list_to_group_text",
        lambda _contents, _lengths: ["g1", "g2"],
    )
    monkeypatch.setattr(
        page_index_module,
        "generate_toc_init",
        lambda *_args, **_kwargs: {
            "table_of_contents": [
                {
                    "structure": "1",
                    "title": "A",
                    "physical_index": "<physical_index_1>",
                }
            ]
        },
    )
    monkeypatch.setattr(
        page_index_module,
        "generate_toc_continue",
        lambda *_args, **_kwargs: {
            "table_of_contents": [
                {
                    "structure": "2",
                    "title": "B",
                    "physical_index": "<physical_index_2>",
                }
            ]
        },
    )

    result = page_index_module.process_no_toc(
        page_list, start_index=1, model="x", logger=_Logger()
    )
    assert isinstance(result, list)
    assert len(result) == 2


def test_check_toc_transformation_is_complete_tolerates_missing_completed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        page_index_module, "ChatGPT_API", lambda *_args, **_kwargs: "{}"
    )
    monkeypatch.setattr(page_index_module, "extract_json", lambda *_args, **_kwargs: {})

    completed = page_index_module.check_if_toc_transformation_is_complete(
        "raw", "clean", model="x"
    )
    assert completed == "no"
