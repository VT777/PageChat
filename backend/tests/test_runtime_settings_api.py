from pathlib import Path
import sys
import asyncio

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402
from test_model_settings_api import _create_bootstrap_schema  # noqa: E402


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    db_path = tmp_path / "runtime-settings.db"

    async def init() -> None:
        async with aiosqlite.connect(db_path) as db:
            await _create_bootstrap_schema(db)
            await run_migrations(db)

    asyncio.run(init())

    app = FastAPI()
    app.include_router(settings.router)

    async def override_auth() -> dict:
        return {"id": "user-a", "email": "user-a@example.test"}

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
