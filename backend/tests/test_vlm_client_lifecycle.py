from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import vlm_utils
from pageindex import utils as pageindex_utils


def test_vlm_client_cache_is_scoped_to_event_loop(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr(vlm_utils, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(vlm_utils, "_vlm_clients_by_loop", {})

    async def get_client_id():
        return id(vlm_utils._get_vlm_client())

    first = asyncio.run(get_client_id())
    second = asyncio.run(get_client_id())

    assert first != second
    assert len(created) == 2


def test_pageindex_async_llm_client_cache_is_scoped_to_event_loop(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(self)

    monkeypatch.setattr(pageindex_utils, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(pageindex_utils, "_async_clients_by_loop", {})

    async def get_client_id():
        return id(pageindex_utils._get_async_client())

    first = asyncio.run(get_client_id())
    second = asyncio.run(get_client_id())

    assert first != second
    assert len(created) == 2
