import asyncio
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_engines.resolver import OCREngineResolver  # noqa: E402
from app.services.ocr_engines.openai_compatible_adapter import (  # noqa: E402
    OpenAICompatibleOCRAdapter,
)
from app.services.ocr_engines.paddleocr_job_adapter import PaddleOCRJobAdapter  # noqa: E402


class FakeSettingsService:
    def __init__(self, resolved):
        self.resolved = dict(resolved)
        self.calls = []

    async def resolve_task(self, user_id, task):
        self.calls.append((user_id, task))
        return dict(self.resolved)

    async def _get_profile_with_secret(self, user_id, profile_id):
        return dict(self.resolved) if self.resolved.get("profile_id") == profile_id else None


def _route(**overrides):
    route = {
        "profile_id": "profile-a",
        "source": "default_profile",
        "engine_type": "paddleocr_job",
        "provider": "aistudio",
        "endpoint": "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
        "model": "PP-OCRv6",
        "api_key": "paddle-secret",
        "capabilities": ["toc_page", "page_text"],
        "options": {"useTextlineOrientation": False},
        "profile_version": "v1",
    }
    route.update(overrides)
    return route


def test_explicit_profile_resolution_instantiates_paddleocr_adapter() -> None:
    async def run() -> None:
        service = FakeSettingsService(_route(source="explicit_profile"))
        resolver = OCREngineResolver(settings_service=service)

        resolved = await resolver.resolve("user-a", "toc_page", profile_id="profile-a")

        assert isinstance(resolved.adapter, PaddleOCRJobAdapter)
        assert resolved.route["source"] == "explicit_profile"
        assert resolved.adapter.model == "PP-OCRv6"
        assert resolved.adapter.profile_version == "v1"

    asyncio.run(run())


def test_task_override_resolution_instantiates_openai_adapter() -> None:
    async def run() -> None:
        service = FakeSettingsService(
            _route(
                source="task_override",
                engine_type="openai_compatible_ocr",
                provider="dashscope",
                endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-vl-ocr-2025-11-20",
                api_key="dash-secret",
                capabilities=["toc_page"],
            )
        )
        resolver = OCREngineResolver(settings_service=service)

        resolved = await resolver.resolve("user-a", "toc_page")

        assert isinstance(resolved.adapter, OpenAICompatibleOCRAdapter)
        assert resolved.route["source"] == "task_override"
        assert service.calls == [("user-a", "toc_page")]

    asyncio.run(run())


def test_default_profile_resolution_uses_settings_service() -> None:
    async def run() -> None:
        service = FakeSettingsService(_route(source="default_profile"))
        resolver = OCREngineResolver(settings_service=service)

        resolved = await resolver.resolve("user-a", "page_text")

        assert isinstance(resolved.adapter, PaddleOCRJobAdapter)
        assert resolved.route["source"] == "default_profile"
        assert service.calls == [("user-a", "page_text")]

    asyncio.run(run())


def test_environment_fallback_resolution(monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "app.services.ocr_engines.resolver.config.OCR_DEFAULT_ENGINE_TYPE",
            "openai_compatible_ocr",
            raising=False,
        )
        monkeypatch.setattr(
            "app.services.ocr_engines.resolver.config.OCR_OPENAI_BASE_URL",
            "https://env.example/v1",
            raising=False,
        )
        monkeypatch.setattr(
            "app.services.ocr_engines.resolver.config.OCR_OPENAI_MODEL",
            "env-vision-model",
            raising=False,
        )
        monkeypatch.setattr(
            "app.services.ocr_engines.resolver.config.OCR_OPENAI_API_KEY",
            "env-secret",
            raising=False,
        )
        service = FakeSettingsService(_route(source="task_default", profile_id=None))
        resolver = OCREngineResolver(settings_service=service)

        resolved = await resolver.resolve(None, "page_text")

        assert isinstance(resolved.adapter, OpenAICompatibleOCRAdapter)
        assert resolved.route["source"] == "task_default"
        assert resolved.route["endpoint"] == "https://env.example/v1"
        assert resolved.route["model"] == "env-vision-model"

    asyncio.run(run())


def test_resolution_rejects_engine_without_task_capability() -> None:
    async def run() -> None:
        service = FakeSettingsService(_route(capabilities=["page_text"]))
        resolver = OCREngineResolver(settings_service=service)

        try:
            await resolver.resolve("user-a", "toc_page")
            assert False, "Expected capability check to fail"
        except ValueError as exc:
            assert "capability" in str(exc).lower()

    asyncio.run(run())
