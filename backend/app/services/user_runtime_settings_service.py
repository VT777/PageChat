from __future__ import annotations

from typing import Any

import aiosqlite

from app.services.runtime_settings_service import QA_THINKING_MODES


DEFAULT_USER_RUNTIME_SETTINGS: dict[str, Any] = {
    "qa_thinking_mode": "off",
}


class UserRuntimeSettingsService:
    """Per-user runtime settings that affect chat behavior."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_settings(self, user_id: str) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")

        cursor = await self.db.execute(
            """
            SELECT qa_thinking_mode, updated_at
            FROM user_runtime_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return dict(DEFAULT_USER_RUNTIME_SETTINGS)

        mode = str(row["qa_thinking_mode"] or "off").strip().lower()
        if mode not in QA_THINKING_MODES:
            mode = "off"
        return {
            "qa_thinking_mode": mode,
            "updated_at": row["updated_at"],
        }

    async def update_qa_thinking_mode(self, user_id: str, mode: str) -> dict[str, Any]:
        if not user_id:
            raise ValueError("user_id is required")
        normalized = str(mode or "").strip().lower()
        if normalized not in QA_THINKING_MODES:
            raise ValueError("qa_thinking_mode must be 'off', 'auto' or 'on'")

        await self.db.execute(
            """
            INSERT INTO user_runtime_settings (
                user_id, qa_thinking_mode, updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                qa_thinking_mode = excluded.qa_thinking_mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, normalized),
        )
        await self.db.commit()
        return await self.get_settings(user_id)

