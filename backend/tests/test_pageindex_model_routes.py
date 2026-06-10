import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def _response(text: str = "ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def test_indexing_completion_uses_resolved_user_route(monkeypatch) -> None:
    async def run() -> None:
        service = PageIndexService(user_id="user-a")
        route = {
            "route_slot": "indexing",
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret",
            "model": "custom-index",
            "source": "user",
            "route_version": "index-v1",
            "supports_vision": False,
        }
        calls = []

        async def fake_resolve(route_slot):
            assert route_slot == "indexing"
            return route

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return _response()

        monkeypatch.setattr(service, "_resolve_model_route", fake_resolve)
        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_completion)

        result = await service._indexing_completion(
            messages=[{"role": "user", "content": "summarize"}],
            model="fallback-model",
            temperature=0,
        )

        assert result.choices[0].message.content == "ok"
        assert calls[0]["model"] == "custom-index"
        assert calls[0]["provider_config"]["route_version"] == "index-v1"

    asyncio.run(run())


def test_indexing_completion_falls_back_without_user_route(monkeypatch) -> None:
    async def run() -> None:
        service = PageIndexService()
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return _response()

        monkeypatch.setattr("app.core.llm.async_chat_completion", fake_completion)

        await service._indexing_completion(
            messages=[{"role": "user", "content": "summarize"}],
            model="fallback-model",
            temperature=0,
        )

        assert calls[0]["model"] == "fallback-model"
        assert "provider_config" not in calls[0]

    asyncio.run(run())


def test_build_model_gateway_carries_user_context(monkeypatch) -> None:
    async def run() -> None:
        created = []

        class FakeGateway:
            def __init__(self, **kwargs):
                created.append(kwargs)

        monkeypatch.setattr(
            "app.services.pageindex_service.ModelGateway", FakeGateway, raising=False
        )

        service = PageIndexService(user_id="user-a")
        async def fake_resolve(route_slot):
            return {
                "route_slot": route_slot,
                "source": "user",
                "model": "vision-model",
                "route_version": "vision-v1",
                "supports_vision": True,
            }

        monkeypatch.setattr(service, "_resolve_model_route", fake_resolve)
        gateway = await service._build_model_gateway()

        assert isinstance(gateway, FakeGateway)
        assert created[0]["user_id"] == "user-a"
        assert created[0]["model_settings_service"] is not None

    asyncio.run(run())


def test_build_model_gateway_falls_back_without_user_vision_route(monkeypatch) -> None:
    async def run() -> None:
        created = []

        class FakeGateway:
            def __init__(self, **kwargs):
                created.append(kwargs)

        monkeypatch.setattr(
            "app.services.pageindex_service.ModelGateway", FakeGateway, raising=False
        )

        service = PageIndexService(user_id="user-a")
        async def fake_resolve(_route_slot):
            return None

        monkeypatch.setattr(service, "_resolve_model_route", fake_resolve)

        gateway = await service._build_model_gateway()

        assert isinstance(gateway, FakeGateway)
        assert created == [{}]

    asyncio.run(run())


def test_sanitize_route_metadata_excludes_secrets() -> None:
    service = PageIndexService(user_id="user-a")
    metadata = service._sanitize_model_route_metadata(
        {
            "route_slot": "indexing",
            "source": "user",
            "model": "custom-index",
            "route_version": "index-v1",
            "api_key": "sk-secret",
            "api_key_ciphertext": "encrypted",
        }
    )

    assert metadata == {
        "route_slot": "indexing",
        "source": "user",
        "model": "custom-index",
        "route_version": "index-v1",
    }


def test_fast_light_summary_uses_indexing_route(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        service = PageIndexService(user_id="user-a")
        calls = []

        async def fake_indexing_completion(**kwargs):
            calls.append(kwargs)
            return _response("short summary")

        monkeypatch.setattr(
            "app.services.pageindex_service.PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED", True
        )
        monkeypatch.setattr(service, "_indexing_completion", fake_indexing_completion)

        summary = await service._generate_fast_light_doc_summary(
            [{"title": "Revenue", "node_id": "1"}],
            tmp_path / "report.pdf",
        )

        assert summary == "short summary"
        assert calls[0]["model"] == service.opt.model

    asyncio.run(run())


def test_tree_search_cache_uses_indexing_route_version(monkeypatch) -> None:
    async def run() -> None:
        from app.services.cache_service import cache_service

        cache_service.clear_all()
        service = PageIndexService(user_id="user-a")
        calls = []

        async def fake_resolve(route_slot):
            assert route_slot == "indexing"
            return {"route_version": "index-v1", "model": "custom-index"}

        async def fake_indexing_completion(**kwargs):
            calls.append(kwargs)
            return _response('[{"node_id": "1", "reasoning": "match", "relevance_score": 0.9}]')

        monkeypatch.setattr(service, "_resolve_model_route", fake_resolve)
        monkeypatch.setattr(service, "_indexing_completion", fake_indexing_completion)

        structure = {
            "structure": [
                {
                    "node_id": "1",
                    "title": "Revenue",
                    "text": "Revenue details",
                    "start_index": 1,
                    "end_index": 2,
                }
            ]
        }

        result = await service.search_in_structure_async(
            structure,
            "revenue",
            "doc-1",
            "report.pdf",
            user_id="user-a",
        )

        assert result[0]["node_id"] == "1"
        assert calls
        assert (
            cache_service.get_search_result(
                "user-a", "revenue", ["doc-1"], route_version="index-v1"
            )
            is not None
        )

    asyncio.run(run())
