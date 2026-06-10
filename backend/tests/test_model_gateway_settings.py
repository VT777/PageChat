import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.model_gateway import ModelGateway


class FakeSettingsService:
    def __init__(self, routes: dict[str, dict]):
        self.routes = routes

    async def resolve_route(self, user_id: str, route_slot: str) -> dict:
        route = dict(self.routes[route_slot])
        route["route_slot"] = route_slot
        return route


def test_default_route_equals_current_behavior_without_settings() -> None:
    gateway = ModelGateway()

    assert gateway.route_for(
        task="answer",
        input_tokens=100,
        needs_vision=False,
        reasoning_complexity="light",
    ) == "flash"
    assert gateway._model_for("flash").endswith("flash")


def test_general_chat_uses_configured_route() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "general_chat": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "custom-chat",
                        "source": "user",
                        "route_version": "chat-v1",
                        "supports_vision": False,
                    }
                }
            ),
            user_id="user-a",
        )

        await gateway.classify_intent("hello")

        assert calls[0]["model"] == "custom-chat"
        assert calls[0]["provider_config"]["route_version"] == "chat-v1"

    asyncio.run(run())


def test_document_qa_uses_configured_route() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "document_qa": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "custom-qa",
                        "source": "user",
                        "route_version": "qa-v1",
                        "supports_vision": False,
                    }
                }
            ),
            user_id="user-a",
        )

        await gateway.stream_answer([{"role": "user", "content": "question"}])

        assert calls[0]["model"] == "custom-qa"
        assert calls[0]["provider_config"]["route_slot"] == "document_qa"

    asyncio.run(run())


def test_vision_route_rejects_text_only_configured_model() -> None:
    async def run() -> None:
        async def fake_completion(**_kwargs):
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "vision": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "text-only",
                        "source": "user",
                        "route_version": "vision-v1",
                        "supports_vision": False,
                    }
                }
            ),
            user_id="user-a",
        )

        try:
            await gateway.vision_enrich_pdf_page("describe", "data:image/png;base64,abc")
            assert False, "Expected text-only vision route to fail"
        except ValueError as exc:
            assert "vision" in str(exc).lower()

    asyncio.run(run())


def test_route_version_can_be_included_in_cache_keys() -> None:
    from app.services.cache_service import CacheService

    cache = CacheService()
    cache.clear_all()

    cache.set_search_result(
        "user-a", "alpha", ["doc-1"], [{"route": "v1"}], route_version="v1"
    )

    assert cache.get_search_result(
        "user-a", "alpha", ["doc-1"], route_version="v1"
    ) == [{"route": "v1"}]
    assert (
        cache.get_search_result("user-a", "alpha", ["doc-1"], route_version="v2")
        is None
    )
