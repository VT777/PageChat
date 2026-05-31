import json
import threading
from pathlib import Path

from app.core.config import DATA_DIR, PAGEINDEX_MODE


class RuntimeSettingsService:
    def __init__(self, file_path: Path | None = None):
        self.file_path = file_path or (DATA_DIR / "runtime_settings.json")
        self._lock = threading.Lock()

    def _defaults(self) -> dict:
        mode = (
            PAGEINDEX_MODE
            if PAGEINDEX_MODE in {"smart", "balanced", "fast"}
            else "balanced"
        )
        return {"pageindex_mode": mode}

    def get_settings(self) -> dict:
        defaults = self._defaults()
        if not self.file_path.exists():
            return defaults

        with self._lock:
            try:
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return defaults
            except Exception:
                return defaults

        mode = (
            str(data.get("pageindex_mode", defaults["pageindex_mode"])).strip().lower()
        )
        if mode not in {"smart", "balanced", "fast"}:
            mode = defaults["pageindex_mode"]
        return {"pageindex_mode": mode}

    def update_pageindex_mode(self, mode: str) -> dict:
        normalized = str(mode or "").strip().lower()
        if normalized not in {"smart", "balanced", "fast"}:
            raise ValueError("pageindex_mode must be 'smart', 'balanced' or 'fast'")

        data = self.get_settings()
        data["pageindex_mode"] = normalized

        with self._lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        return data


runtime_settings_service = RuntimeSettingsService()
