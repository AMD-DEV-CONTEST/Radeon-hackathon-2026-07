from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from app.main import get_skill


class SkillApiTests(TestCase):
    def test_get_skill_returns_decoded_review_sessions(self) -> None:
        # Given: SQLite session rows contain JSON-encoded persistence fields.
        stored_session = {
            "id": 7,
            "skill_id": 1,
            "status": "进行中",
            "card_ids": "[1]",
            "transcript": '[{"role":"ai","content":"review prompt"}]',
            "state_json": "{}",
            "user_override": 0,
            "created_at": "t",
            "completed_at": None,
        }
        decoded_session = {
            "id": 7,
            "skill_id": 1,
            "status": "进行中",
            "card_ids": [1],
            "transcript": [{"role": "ai", "content": "review prompt"}],
            "state_json": {},
            "user_override": 0,
            "created_at": "t",
            "completed_at": None,
        }

        # When: the skill detail API response is assembled (typed contract).
        with (
            patch("app.main.db.get_skill", return_value={
                "id": 1, "name": "Raft", "description": "", "growth_value": 0.0,
                "decay_rate": 3.0, "status": "萌芽", "last_reviewed_at": None,
                "last_decay_at": None, "created_at": "t", "updated_at": "t"}),
            patch("app.main.db.list_cards", return_value=[]),
            patch("app.main.db.list_sessions", return_value=[stored_session]),
            patch("app.main.db.get_session", return_value=decoded_session),
        ):
            response = get_skill(1)

        # Then: browser consumers receive decoded arrays, not serialized JSON text.
        self.assertEqual(response.sessions[0].transcript, decoded_session["transcript"])
        self.assertEqual(response.sessions[0].status, "进行中")
