from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings  # noqa: E402
from app.services.runtime_settings_service import RuntimeSettingsService  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(settings.router)
    monkeypatch.setattr(
        settings,
        "runtime_settings_service",
        RuntimeSettingsService(file_path=tmp_path / "runtime_settings.json"),
    )

    async def override_auth() -> dict:
        return {"id": "user-a", "email": "user-a@example.test"}

    app.dependency_overrides[settings.require_auth] = override_auth
    return TestClient(app)


def test_get_qa_settings_defaults_to_thinking_off(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/api/settings/qa")

    assert response.status_code == 200
    assert response.json() == {"qa_thinking_mode": "off"}


def test_update_qa_settings_persists_thinking_mode(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.put("/api/settings/qa", json={"qa_thinking_mode": "auto"})

    assert response.status_code == 200
    assert response.json() == {"qa_thinking_mode": "auto"}
    assert client.get("/api/settings/qa").json() == {"qa_thinking_mode": "auto"}

