import asyncio
from pathlib import Path
import sys

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings
from app.models.migrations import run_migrations
from app.services import model_settings_service
from app.services.runtime_settings_service import RuntimeSettingsService


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


def _client(tmp_path: Path, user_id: str = "user-a") -> TestClient:
    db_path = tmp_path / "settings.db"

    async def init() -> None:
        async with aiosqlite.connect(db_path) as db:
            await _create_bootstrap_schema(db)
            await run_migrations(db)

    asyncio.run(init())

    app = FastAPI()
    app.include_router(settings.router)

    async def override_auth() -> dict:
        return {"id": user_id, "email": f"{user_id}@example.test"}

    async def override_db():
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    app.dependency_overrides[settings.require_auth] = override_auth
    app.dependency_overrides[settings.get_db] = override_db
    return TestClient(app)


def test_list_provider_presets(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/settings/model-providers/presets")

    assert response.status_code == 200
    assert response.json()[0]["provider"]


def test_list_provider_presets_includes_common_dify_style_providers(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/settings/model-providers/presets")

    providers = {item["provider"]: item for item in response.json()}
    expected = {
        "openai",
        "openai_compatible",
        "dashscope",
        "deepseek",
        "moonshot",
        "zhipuai",
        "siliconflow",
        "volcengine_ark",
        "openrouter",
        "ollama",
    }
    assert expected.issubset(providers)
    assert providers["dashscope"]["label"] == "Alibaba Cloud Bailian / Tongyi"
    assert providers["dashscope"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert providers["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert providers["siliconflow"]["supports_custom_base_url"] is True


def test_save_read_and_delete_provider_config_masks_api_key(tmp_path: Path) -> None:
    client = _client(tmp_path)

    saved = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    )
    provider_id = saved.json()["provider_id"]

    listed = client.get("/api/settings/model-providers")

    assert saved.status_code == 200
    assert listed.json()[0]["api_key_mask"] == "sk-...3456"
    assert listed.json()[0]["supports_responses_api"] is False
    assert "api_key" not in listed.json()[0]
    assert "sk-secret-123456" not in listed.text

    deleted = client.delete(f"/api/settings/model-providers/{provider_id}")
    assert deleted.status_code == 200
    assert client.get("/api/settings/model-providers").json() == []


def test_list_provider_models_uses_openai_compatible_models_endpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()
    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"id":"qwen-plus"},{"id":"qwen-vl-max"}]}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "qwen-plus"}, {"id": "qwen-vl-max"}]}

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers, timeout))
        return FakeResponse()

    monkeypatch.setattr(model_settings_service.requests, "get", fake_get)

    response = client.get(f"/api/settings/model-providers/{provider['provider_id']}/models")

    assert response.status_code == 200
    models = response.json()["models"]
    assert models[0] == {
        "id": "qwen-plus",
        "capabilities": ["llm", "tool_calling"],
        "features": ["llm", "tool_calling"],
        "supports_vision": False,
        "supports_tool_calling": True,
        "supports_reasoning": False,
        "supports_embedding": False,
        "supports_ocr": False,
        "context_window": None,
        "max_output_tokens": None,
    }
    assert models[1]["id"] == "qwen-vl-max"
    assert models[1]["capabilities"] == ["llm", "vision", "tool_calling"]
    assert models[1]["supports_vision"] is True
    assert calls[0][0] == "https://example.test/v1/models"
    assert calls[0][1]["Authorization"] == "Bearer sk-secret-123456"


def test_list_provider_models_sanitizes_provider_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    def fake_get(url, headers=None, timeout=None):
        raise RuntimeError("bad key sk-secret-123456")

    monkeypatch.setattr(model_settings_service.requests, "get", fake_get)

    response = client.get(f"/api/settings/model-providers/{provider['provider_id']}/models")

    assert response.status_code == 400
    assert "sk-secret-123456" not in response.text
    assert "[redacted-api-key]" in response.text


def test_openai_compatible_provider_can_store_custom_models_when_models_endpoint_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    saved_model = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/models",
        json={
            "model": "custom-vl-model",
            "display_name": "Custom Vision Model",
            "model_type": "vision",
            "endpoint_model_name": "vendor/custom-vl-model",
            "capabilities": ["llm", "vision", "tool_calling"],
            "context_window": 128000,
        },
    )

    def fake_get(url, headers=None, timeout=None):
        raise RuntimeError("models endpoint disabled sk-secret-123456")

    monkeypatch.setattr(model_settings_service.requests, "get", fake_get)

    response = client.get(f"/api/settings/model-providers/{provider['provider_id']}/models")

    assert saved_model.status_code == 200
    assert response.status_code == 200
    assert response.json()["source"] == "custom"
    assert response.json()["models"] == [
        {
            "id": "vendor/custom-vl-model",
            "display_name": "Custom Vision Model",
            "model_type": "vision",
            "capabilities": ["llm", "vision", "tool_calling"],
            "features": ["llm", "vision", "tool_calling"],
            "supports_vision": True,
            "supports_tool_calling": True,
            "supports_reasoning": False,
            "supports_embedding": False,
            "supports_ocr": False,
            "context_window": 128000,
            "max_output_tokens": None,
            "source": "custom",
        }
    ]
    assert "sk-secret-123456" not in response.text


def test_provider_models_merge_remote_and_custom_models(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()
    client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/models",
        json={
            "model": "manual-chat",
            "model_type": "llm",
            "capabilities": ["llm", "tool_calling"],
        },
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "remote-vl", "capabilities": ["llm", "vision"]}]}

    monkeypatch.setattr(model_settings_service.requests, "get", lambda *args, **kwargs: FakeResponse())

    response = client.get(f"/api/settings/model-providers/{provider['provider_id']}/models")

    assert response.status_code == 200
    assert response.json()["source"] == "remote+custom"
    assert [item["id"] for item in response.json()["models"]] == ["remote-vl", "manual-chat"]
    assert response.json()["models"][0]["capabilities"] == ["llm", "vision", "tool_calling"]


def test_update_provider_non_secret_fields_preserves_saved_key(tmp_path: Path) -> None:
    client = _client(tmp_path)

    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.patch(
        f"/api/settings/model-providers/{provider['provider_id']}",
        json={
            "provider": "openai_compatible",
            "base_url": "https://updated.example.test/v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"] == "https://updated.example.test/v1"
    assert payload["api_key_mask"] == "sk-...3456"
    assert "api_key" not in payload
    assert "sk-secret-123456" not in response.text


def test_update_provider_can_replace_saved_key_without_creating_duplicate(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.patch(
        f"/api/settings/model-providers/{provider['provider_id']}",
        json={
            "provider": "openai_compatible",
            "base_url": "https://updated.example.test/v1",
            "api_key": "sk-replaced-987654",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_id"] == provider["provider_id"]
    assert payload["base_url"] == "https://updated.example.test/v1"
    assert payload["api_key_mask"] == "sk-...7654"
    assert "api_key" not in payload
    assert "sk-replaced-987654" not in response.text

    listed = client.get("/api/settings/model-providers")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["provider_id"] == provider["provider_id"]
    assert listed.json()[0]["api_key_mask"] == "sk-...7654"
    assert "sk-replaced-987654" not in listed.text


def test_save_route_mapping(tmp_path: Path) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.put(
        "/api/settings/model-routes",
        json={
            "routes": [
                {
                    "route_slot": "general_chat",
                    "provider_id": provider["provider_id"],
                    "model": "custom-chat",
                    "supports_vision": False,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["route_slot"] == "general_chat"
    assert response.json()[0]["model"] == "custom-chat"


def test_save_route_mapping_accepts_provider_capability_flags(tmp_path: Path) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.put(
        "/api/settings/model-routes",
        json={
            "routes": [
                {
                    "route_slot": "general_chat",
                    "provider_id": provider["provider_id"],
                    "model": "custom-chat",
                    "supports_streaming": True,
                    "supports_tool_calling": False,
                    "supports_vision": False,
                    "supports_structured_output": True,
                    "supports_responses_api": False,
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["supports_streaming"] is True
    assert payload["supports_tool_calling"] is False
    assert payload["supports_vision"] is False
    assert payload["supports_structured_output"] is True
    assert payload["supports_responses_api"] is False


def test_delete_provider_removes_route_mappings_for_fallback(tmp_path: Path) -> None:
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()
    client.put(
        "/api/settings/model-routes",
        json={
            "routes": [
                {
                    "route_slot": "general_chat",
                    "provider_id": provider["provider_id"],
                    "model": "custom-chat",
                    "supports_vision": False,
                }
            ]
        },
    )

    response = client.delete(f"/api/settings/model-providers/{provider['provider_id']}")

    assert response.status_code == 200
    assert client.get("/api/settings/model-routes").json() == []


def test_provider_connection_test_uses_adapter(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(settings, "LiteLLMAdapter", lambda: FakeAdapter())
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/test",
        json={"model": "custom-chat"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls[0]["provider_config"]["model"] == "custom-chat"


def test_provider_connection_test_normalizes_dashscope_model_for_litellm(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(
        "app.services.litellm_adapter.litellm.acompletion",
        fake_acompletion,
    )
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/test",
        json={"model": "qwen3.7-max-2026-06-08"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls[0]["model"] == "dashscope/qwen3.7-max-2026-06-08"


def test_provider_connection_test_can_auto_select_model_and_mark_valid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "qwen-plus"}, {"id": "qwen-vl-max"}]}

    def fake_get(url, headers=None, timeout=None):
        calls.append(("models", url, headers, timeout))
        return FakeResponse()

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(("completion", kwargs))
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(model_settings_service.requests, "get", fake_get)
    monkeypatch.setattr(settings, "LiteLLMAdapter", lambda: FakeAdapter())
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/test",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["tested_model"] == "qwen-plus"
    completion_call = [call for call in calls if call[0] == "completion"][0][1]
    assert completion_call["provider_config"]["model"] == "qwen-plus"
    listed = client.get("/api/settings/model-providers").json()
    assert listed[0]["validation_status"] == "valid"



def test_provider_connection_test_auto_selects_chat_model_before_multimodal_or_audio_models(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"id": "qwen-image-2.0-pro-2026-06-22"},
                    {"id": "fun-asr-flash-2026-06-15"},
                    {"id": "test-sre-gpu-auto-handle"},
                    {"id": "qwen3.7-max-2026-06-08"},
                ]
            }

    def fake_get(url, headers=None, timeout=None):
        calls.append(("models", url, headers, timeout))
        return FakeResponse()

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(("completion", kwargs))
            if kwargs["provider_config"]["model"] != "qwen3.7-max-2026-06-08":
                raise RuntimeError("selected non-chat model")
            return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(model_settings_service.requests, "get", fake_get)
    monkeypatch.setattr(settings, "LiteLLMAdapter", lambda: FakeAdapter())
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/test",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["tested_model"] == "qwen3.7-max-2026-06-08"
    completion_call = [call for call in calls if call[0] == "completion"][0][1]
    assert completion_call["provider_config"]["model"] == "qwen3.7-max-2026-06-08"
    assert client.get("/api/settings/model-providers").json()[0]["validation_status"] == "valid"
def test_provider_connection_test_marks_invalid_and_redacts_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "qwen-plus"}]}

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            raise RuntimeError("bad key sk-secret-123456")

    monkeypatch.setattr(model_settings_service.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(settings, "LiteLLMAdapter", lambda: FakeAdapter())
    client = _client(tmp_path)
    provider = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    ).json()

    response = client.post(
        f"/api/settings/model-providers/{provider['provider_id']}/test",
        json={},
    )

    assert response.status_code == 400
    assert "sk-secret-123456" not in response.text
    assert "[redacted-api-key]" in response.text
    listed = client.get("/api/settings/model-providers").json()
    assert listed[0]["validation_status"] == "invalid"


def test_user_cannot_read_another_users_settings(tmp_path: Path) -> None:
    user_a = _client(tmp_path, user_id="user-a")
    user_a.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    )

    user_b = _client(tmp_path, user_id="user-b")

    assert user_b.get("/api/settings/model-providers").json() == []


def test_qa_settings_are_user_scoped(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        settings,
        "runtime_settings_service",
        RuntimeSettingsService(tmp_path / "runtime-settings.json"),
    )
    user_a = _client(tmp_path, user_id="user-a")
    user_b = _client(tmp_path, user_id="user-b")

    saved = user_a.put("/api/settings/qa", json={"qa_thinking_mode": "on"})

    assert saved.status_code == 200
    assert saved.json()["qa_thinking_mode"] == "on"
    assert user_a.get("/api/settings/qa").json()["qa_thinking_mode"] == "on"
    assert user_b.get("/api/settings/qa").json()["qa_thinking_mode"] == "off"


def test_production_rejects_insecure_key_storage(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MODEL_SETTINGS_SECRET", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr("app.services.model_settings_service.config.IS_PRODUCTION", True)
    client = _client(tmp_path)

    response = client.post(
        "/api/settings/model-providers",
        json={
            "provider": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret-123456",
        },
    )

    assert response.status_code == 400
    assert "MODEL_SETTINGS_SECRET" in response.text
