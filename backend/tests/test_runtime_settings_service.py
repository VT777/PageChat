from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.runtime_settings_service import RuntimeSettingsService


def test_runtime_settings_defaults_without_file(tmp_path: Path) -> None:
    service = RuntimeSettingsService(file_path=tmp_path / "runtime_settings.json")
    settings = service.get_settings()
    assert settings["pageindex_mode"] in {"smart", "balanced", "fast"}
    assert settings["qa_thinking_mode"] == "off"


def test_runtime_settings_update_and_reload(tmp_path: Path) -> None:
    file_path = tmp_path / "runtime_settings.json"
    service = RuntimeSettingsService(file_path=file_path)

    updated = service.update_pageindex_mode("smart")
    assert updated["pageindex_mode"] == "smart"
    updated = service.update_qa_thinking_mode("auto")
    assert updated["qa_thinking_mode"] == "auto"

    reloaded = RuntimeSettingsService(file_path=file_path).get_settings()
    assert reloaded["pageindex_mode"] == "smart"
    assert reloaded["qa_thinking_mode"] == "auto"


def test_runtime_settings_rejects_invalid_mode(tmp_path: Path) -> None:
    service = RuntimeSettingsService(file_path=tmp_path / "runtime_settings.json")
    try:
        service.update_pageindex_mode("invalid")
        assert False, "Expected ValueError"
    except ValueError:
        assert True


def test_runtime_settings_rejects_invalid_qa_thinking_mode(tmp_path: Path) -> None:
    service = RuntimeSettingsService(file_path=tmp_path / "runtime_settings.json")
    try:
        service.update_qa_thinking_mode("verbose")
        assert False, "Expected ValueError"
    except ValueError:
        assert True
