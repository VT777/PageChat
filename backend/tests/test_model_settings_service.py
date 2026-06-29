import asyncio
from pathlib import Path
import sys

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations
from app.services.model_settings_service import (
    ModelProviderInvalidError,
    ModelRouteNotConfiguredError,
    ModelSettingsService,
    _normalize_provider_models,
)


async def _create_bootstrap_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT DEFAULT 'uploaded',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            folder_id TEXT,
            user_id TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            path TEXT NOT NULL,
            user_id TEXT
        )
        """
    )
    await db.commit()


async def _service() -> tuple[aiosqlite.Connection, ModelSettingsService]:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    try:
        await _create_bootstrap_schema(db)
        await run_migrations(db)
    except Exception:
        await db.close()
        raise
    return db, ModelSettingsService(db)


def test_save_and_read_provider_config_masks_api_key() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            configs = await service.list_provider_configs("user-a")

            assert saved["provider_id"]
            assert configs[0]["api_key_mask"] == "sk-...3456"
            assert "api_key" not in configs[0]
            assert "sk-secret-123456" not in str(configs[0])
        finally:
            await db.close()

    asyncio.run(run())


def test_normalize_provider_models_adds_capabilities() -> None:
    models = _normalize_provider_models(
        {
            "data": [
                {
                    "id": "qwen3.7-max-2026-06-08",
                    "owned_by": "dashscope",
                    "context_window": 129024,
                    "max_output_tokens": 8192,
                },
                {
                    "id": "qwen-vl-ocr-2025",
                    "capabilities": ["llm", "vision"],
                    "context_length": 65536,
                },
                {"id": "text-embedding-v3"},
            ]
        }
    )

    assert models[0]["id"] == "qwen3.7-max-2026-06-08"
    assert models[0]["owned_by"] == "dashscope"
    assert models[0]["capabilities"] == ["llm", "tool_calling", "reasoning"]
    assert models[0]["supports_reasoning"] is True
    assert models[0]["supports_tool_calling"] is True
    assert models[0]["context_window"] == 129024
    assert models[0]["max_output_tokens"] == 8192

    assert models[1]["id"] == "qwen-vl-ocr-2025"
    assert models[1]["capabilities"] == ["llm", "vision", "ocr"]
    assert models[1]["supports_vision"] is True
    assert models[1]["supports_ocr"] is True
    assert models[1]["context_window"] == 65536
    assert models[1]["max_output_tokens"] is None

    assert models[2]["id"] == "text-embedding-v3"
    assert models[2]["capabilities"] == ["embedding"]
    assert models[2]["supports_embedding"] is True
    assert models[2]["context_window"] is None


def test_provider_metadata_capabilities_are_marked_as_provider_metadata() -> None:
    models = _normalize_provider_models(
        {"data": [{"id": "model-a", "capabilities": ["vision", "function_calling"]}]}
    )

    assert models[0]["capabilities"] == ["llm", "vision", "tool_calling"]
    assert models[0]["capability_source"] == "provider_metadata"


def test_models_without_metadata_are_conservative_unknown_capabilities() -> None:
    models = _normalize_provider_models({"data": [{"id": "plain-text-model"}]})

    assert models[0]["capabilities"] == ["llm"]
    assert models[0]["capability_source"] == "unknown"
    assert models[0]["supports_vision"] is False
    assert models[0]["supports_tool_calling"] is False


def test_dify_schema_is_primary_for_supported_models() -> None:
    models = _normalize_provider_models({"data": [{"id": "gpt-4o"}]}, provider="openai")

    assert models[0]["capabilities"] == ["llm", "vision", "tool_calling"]
    assert models[0]["capability_source"] == "dify_schema"
    assert models[0]["model_type"] == "llm"
    assert models[0]["model_properties"]["mode"] == "chat"
    assert models[0]["model_properties"]["context_size"] == 128000
    assert models[0]["context_window"] == 128000


def test_dify_schema_is_primary_for_dashscope_and_deepseek_models() -> None:
    dashscope = _normalize_provider_models({"data": [{"id": "qwen-plus"}]}, provider="dashscope")
    deepseek = _normalize_provider_models({"data": [{"id": "deepseek-reasoner"}]}, provider="deepseek")

    assert dashscope[0]["capability_source"] == "dify_schema"
    assert dashscope[0]["capabilities"] == ["llm", "tool_calling"]
    assert dashscope[0]["model_properties"]["context_size"] == 1000000
    assert dashscope[0]["max_output_tokens"] == 32768

    assert deepseek[0]["capability_source"] == "dify_schema"
    assert deepseek[0]["capabilities"] == ["llm", "tool_calling", "reasoning"]
    assert deepseek[0]["supports_tool_calling"] is True
    assert deepseek[0]["model_properties"]["context_size"] == 1000000
    assert deepseek[0]["max_output_tokens"] == 384000


def test_reasoning_model_uses_dify_tool_calling_metadata() -> None:
    models = _normalize_provider_models({"data": [{"id": "deepseek-reasoner"}]}, provider="deepseek")

    assert models[0]["capabilities"] == ["llm", "tool_calling", "reasoning"]
    assert models[0]["capability_source"] == "dify_schema"
    assert models[0]["supports_tool_calling"] is True


def test_dify_schema_fills_litellm_gaps() -> None:
    models = _normalize_provider_models({"data": [{"id": "qwen-vl-max"}]}, provider="dashscope")

    assert models[0]["capability_source"] == "dify_schema"
    assert models[0]["capabilities"] == ["llm", "vision"]
    assert models[0]["supports_vision"] is True


def test_openai_compatible_unknown_vlm_and_ocr_names_are_visual_capable() -> None:
    models = _normalize_provider_models(
        {"data": [{"id": "custom-ocr-proxy"}, {"id": "private-qwen-vl-router"}]},
        provider="openai_compatible",
    )

    assert models[0]["capabilities"] == ["llm", "vision", "ocr"]
    assert models[0]["capability_source"] == "inferred"
    assert models[0]["supports_ocr"] is True
    assert models[0]["supports_vision"] is True
    assert models[1]["capabilities"] == ["llm", "vision"]
    assert models[1]["capability_source"] == "inferred"
    assert models[1]["supports_vision"] is True


def test_provider_metadata_vlm_and_ocr_aliases_expand_to_visual_capabilities() -> None:
    models = _normalize_provider_models(
        {
            "data": [
                {"id": "vendor-vlm-model", "capabilities": ["vlm"]},
                {"id": "vendor-ocr-model", "capabilities": ["ocr"]},
            ]
        }
    )

    assert models[0]["capabilities"] == ["llm", "vision"]
    assert models[0]["capability_source"] == "provider_metadata"
    assert models[0]["supports_vision"] is True
    assert models[1]["capabilities"] == ["llm", "vision", "ocr"]
    assert models[1]["supports_vision"] is True
    assert models[1]["supports_ocr"] is True


def test_openai_compatible_dashscope_base_url_uses_dashscope_capabilities() -> None:
    models = _normalize_provider_models(
        {"data": [{"id": "qwen3-vl-plus"}, {"id": "qwen-vl-max"}]},
        provider="openai_compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    assert models[0]["capability_source"] == "dify_schema"
    assert models[0]["capabilities"] == ["llm", "vision", "reasoning"]
    assert models[0]["supports_vision"] is True
    assert models[1]["capability_source"] == "dify_schema"
    assert models[1]["capabilities"] == ["llm", "vision"]
    assert models[1]["supports_vision"] is True


def test_dify_schema_supplies_capabilities_for_supported_providers() -> None:
    cases = [
        ("openai", None, "gpt-4o", ["llm", "vision", "tool_calling"]),
        ("deepseek", None, "deepseek-chat", ["llm", "tool_calling"]),
        ("anthropic", None, "claude-3-5-sonnet-20241022", ["llm", "vision", "tool_calling"]),
        ("google_gemini", None, "gemini-2.5-pro", ["llm", "vision", "tool_calling", "reasoning"]),
        ("dashscope", None, "qwen3.6-plus", ["llm", "vision", "tool_calling", "reasoning"]),
    ]

    for provider, base_url, model_id, expected_capabilities in cases:
        models = _normalize_provider_models(
            {"data": [{"id": model_id}]},
            provider=provider,
            base_url=base_url,
        )

        assert models[0]["capability_source"] == "dify_schema"
        assert models[0]["capabilities"] == expected_capabilities


def test_dashscope_schema_marks_qwen37_plus_as_vision_model() -> None:
    models = _normalize_provider_models(
        {"data": [{"id": "qwen3.7-plus-2026-06-08"}]},
        provider="openai_compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    assert models[0]["capability_source"] == "dify_schema"
    assert models[0]["capabilities"] == ["llm", "vision", "tool_calling", "reasoning"]
    assert models[0]["supports_vision"] is True
    assert models[0]["context_window"] == 1000000


def test_update_provider_validation_status_persists() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            updated = await service.update_provider_validation_status(
                user_id="user-a",
                provider_id=saved["provider_id"],
                validation_status="valid",
            )

            assert updated["validation_status"] == "valid"
            configs = await service.list_provider_configs("user-a")
            assert configs[0]["validation_status"] == "valid"
        finally:
            await db.close()

    asyncio.run(run())


def test_provider_config_exposes_responses_capabilities_for_known_providers() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            dashscope = await service.save_provider_config(
                user_id="user-a",
                provider="dashscope",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key="sk-secret-123456",
            )
            custom = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-abcdef",
            )

            assert dashscope["supports_responses_api"] is True
            assert dashscope["supports_reasoning_effort"] is True
            assert dashscope["supports_reasoning_summary"] is False
            assert custom["supports_responses_api"] is False

            provider = await service.save_provider_config(
                user_id="user-b",
                provider="openai_compatible",
                base_url="https://api.openai.com/v1",
                api_key="sk-secret-openai",
            )
            route = await service.save_route_mapping(
                user_id="user-b",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="gpt-5-mini",
            )
            resolved = await service.resolve_route("user-b", "document_qa")

            assert route["route_slot"] == "document_qa"
            assert resolved["supports_responses_api"] is True
            assert resolved["supports_reasoning_summary"] is True
        finally:
            await db.close()

    asyncio.run(run())


def test_delete_provider_config_is_user_scoped() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            assert await service.delete_provider_config("user-b", saved["provider_id"]) is False
            assert await service.delete_provider_config("user-a", saved["provider_id"]) is True
            assert await service.list_provider_configs("user-a") == []
        finally:
            await db.close()

    asyncio.run(run())


def test_save_provider_config_cannot_overwrite_another_users_provider_id() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            try:
                await service.save_provider_config(
                    user_id="user-b",
                    provider="openai_compatible",
                    base_url="https://evil.test/v1",
                    api_key="sk-evil-123456",
                    provider_id=saved["provider_id"],
                )
                assert False, "Expected cross-user provider update to fail"
            except ValueError as exc:
                assert "provider" in str(exc).lower()

            configs = await service.list_provider_configs("user-a")
            assert configs[0]["base_url"] == "https://example.test/v1"
        finally:
            await db.close()

    asyncio.run(run())


def test_resolve_route_requires_user_config_by_default(monkeypatch) -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            monkeypatch.setattr(
                "app.services.model_settings_service.config.ALLOW_ENV_MODEL_FALLBACK",
                False,
                raising=False,
            )

            with pytest.raises(ModelRouteNotConfiguredError) as exc_info:
                await service.resolve_route("user-a", "general_chat")

            assert exc_info.value.route_slot == "general_chat"
            assert "general_chat" in str(exc_info.value)
        finally:
            await db.close()

    asyncio.run(run())


def test_resolve_route_uses_environment_fallback_only_when_enabled(monkeypatch) -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            monkeypatch.setattr(
                "app.services.model_settings_service.config.ALLOW_ENV_MODEL_FALLBACK",
                True,
                raising=False,
            )
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_BASE_URL",
                "https://env.example/v1",
            )
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_API_KEY",
                "env-secret",
            )
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_FLASH_MODEL",
                "env-flash",
            )

            resolved = await service.resolve_route("user-a", "general_chat")

            assert resolved["source"] == "environment"
            assert resolved["model"] == "env-flash"
            assert resolved["base_url"] == "https://env.example/v1"
            assert resolved["api_key"] == "env-secret"
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_rejects_missing_provider_or_model() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            try:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="general_chat",
                    provider_id="missing-provider",
                    model="model-a",
                )
                assert False, "Expected missing provider to fail"
            except ValueError as exc:
                assert "provider" in str(exc).lower()

            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            try:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="general_chat",
                    provider_id=provider["provider_id"],
                    model="",
                )
                assert False, "Expected missing model to fail"
            except ValueError as exc:
                assert "model" in str(exc).lower()
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_rejects_cross_user_provider() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            try:
                await service.save_route_mapping(
                    user_id="user-b",
                    route_slot="general_chat",
                    provider_id=provider["provider_id"],
                    model="model-a",
                )
                assert False, "Expected cross-user provider route to fail"
            except ValueError as exc:
                assert "provider" in str(exc).lower()

            assert await service.list_route_mappings("user-b") == []
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_rejects_unknown_model_when_provider_has_known_models() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.save_custom_provider_model(
                user_id="user-a",
                provider_id=provider["provider_id"],
                model="known-model",
                capabilities=["llm"],
            )

            try:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="general_chat",
                    provider_id=provider["provider_id"],
                    model="unknown-model",
                )
                assert False, "Expected unknown model to fail"
            except ValueError as exc:
                assert "model" in str(exc).lower()

            saved = await service.save_route_mapping(
                user_id="user-a",
                route_slot="general_chat",
                provider_id=provider["provider_id"],
                model="known-model",
            )
            assert saved["model"] == "known-model"
        finally:
            await db.close()

    asyncio.run(run())


def test_resolve_route_blocks_invalid_provider_config() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.save_route_mapping(
                user_id="user-a",
                route_slot="general_chat",
                provider_id=provider["provider_id"],
                model="model-a",
            )
            await service.update_provider_validation_status(
                user_id="user-a",
                provider_id=provider["provider_id"],
                validation_status="invalid",
            )

            with pytest.raises(ModelProviderInvalidError) as exc_info:
                await service.resolve_route("user-a", "general_chat")

            assert exc_info.value.provider_id == provider["provider_id"]
            assert exc_info.value.route_slot == "general_chat"
        finally:
            await db.close()

    asyncio.run(run())



def test_save_route_mapping_rejects_invalid_provider_config() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.update_provider_validation_status(
                user_id="user-a",
                provider_id=provider["provider_id"],
                validation_status="invalid",
            )

            with pytest.raises(ModelProviderInvalidError) as exc_info:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="document_qa",
                    provider_id=provider["provider_id"],
                    model="model-a",
                )

            assert exc_info.value.provider_id == provider["provider_id"]
            assert exc_info.value.route_slot == "document_qa"
            assert await service.list_route_mappings("user-a") == []
        finally:
            await db.close()

    asyncio.run(run())
def test_save_route_mapping_persists_provider_capabilities() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            saved = await service.save_route_mapping(
                user_id="user-a",
                route_slot="general_chat",
                provider_id=provider["provider_id"],
                model="custom-chat",
                supports_streaming=True,
                supports_tool_calling=False,
                supports_vision=False,
                supports_structured_output=True,
                supports_responses_api=False,
            )
            listed = await service.list_route_mappings("user-a")
            resolved = await service.resolve_route("user-a", "general_chat")

            for payload in (saved, listed[0], resolved):
                assert payload["supports_streaming"] is True
                assert payload["supports_tool_calling"] is False
                assert payload["supports_vision"] is False
                assert payload["supports_structured_output"] is True
                assert payload["supports_responses_api"] is False
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_derives_vision_from_selected_model() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.save_custom_provider_model(
                user_id="user-a",
                provider_id=provider["provider_id"],
                model="vision-chat",
                model_type="vision",
            )
            await service.save_custom_provider_model(
                user_id="user-a",
                provider_id=provider["provider_id"],
                model="text-chat",
                model_type="llm",
                capabilities=["llm"],
            )

            vision_route = await service.save_route_mapping(
                user_id="user-a",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="vision-chat",
                supports_vision=False,
            )
            text_route = await service.save_route_mapping(
                user_id="user-a",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="text-chat",
                supports_vision=True,
            )

            assert vision_route["supports_vision"] is True
            assert text_route["supports_vision"] is False
            assert text_route["supports_tool_calling"] is True
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_ignores_frontend_vision_override_for_text_model() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.save_custom_provider_model(
                user_id="user-a",
                provider_id=provider["provider_id"],
                model="text-chat",
                model_type="llm",
                capabilities=["llm"],
            )

            saved = await service.save_route_mapping(
                user_id="user-a",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="text-chat",
                supports_vision=True,
            )

            assert saved["supports_vision"] is False
        finally:
            await db.close()

    asyncio.run(run())
