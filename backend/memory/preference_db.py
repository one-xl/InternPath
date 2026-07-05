from __future__ import annotations

import logging
from typing import Any

from database import Database

logger = logging.getLogger(__name__)


class PreferenceDB:
    """PostgreSQL-backed storage for Agent resume user preferences."""

    def __init__(self, db: Database | None = None):
        self.db = db or Database()

    def save_preference(
        self,
        user_id: Any,
        section_name: str,
        preference_text: str,
        source_task_id: str | None = None,
        evidence_text: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.db.save_agent_preference(
            user_id=user_id,
            section_name=section_name,
            preference_text=preference_text,
            source_task_id=source_task_id,
            evidence_text=evidence_text,
            tags=tags,
        )
        logger.info("Saved Agent preference: user_id=%s, section=%s", user_id, section_name)

    def get_preferences(self, user_id: Any, section_name: str) -> list[str]:
        return self.db.get_agent_preferences(user_id=user_id, section_name=section_name)
