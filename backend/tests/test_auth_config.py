from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import auth
from app.core import config


def test_jwt_secret_is_configured_and_stable() -> None:
    assert isinstance(config.JWT_SECRET, str)
    assert len(config.JWT_SECRET) >= 32
    assert auth.JWT_SECRET == config.JWT_SECRET


def test_development_mode_keeps_stable_fallback_secret() -> None:
    secret = config.resolve_jwt_secret(
        {"APP_ENV": "development", "JWT_SECRET": "", "SECRET_KEY": ""}
    )

    assert secret == "dev-only-change-me-page-chat-jwt-secret"


def test_production_mode_without_jwt_secret_fails_validation() -> None:
    try:
        config.resolve_jwt_secret(
            {"APP_ENV": "production", "JWT_SECRET": "", "SECRET_KEY": ""}
        )
        assert False, "Expected production JWT secret validation to fail"
    except RuntimeError as exc:
        assert "JWT_SECRET" in str(exc)
        assert "production" in str(exc).lower()


def test_production_mode_with_jwt_secret_passes_validation() -> None:
    secret = config.resolve_jwt_secret(
        {
            "APP_ENV": "production",
            "JWT_SECRET": "prod-secret-with-at-least-thirty-two-chars",
        }
    )

    assert secret == "prod-secret-with-at-least-thirty-two-chars"


def test_missing_llm_api_key_is_allowed_in_development(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    assert config.validate_required_settings() is None


def test_missing_llm_api_key_is_allowed_in_production(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    assert config.validate_required_settings() is None
