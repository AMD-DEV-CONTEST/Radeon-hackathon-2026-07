"""Unit tests for the diary daily-graph schema (offline, mocked client)."""

import unittest
from unittest.mock import MagicMock, call

from database.bionic_graph_client import BionicGraphClient
from diary import schema as S


def make_client():
    c = MagicMock(spec=BionicGraphClient)
    c.gremlin.return_value = []  # no matches -> force the create path in _upsert
    c.create_vertex.return_value = 1
    return c


class TestSchema(unittest.TestCase):
    def test_ensure_owner_creates_me(self):
        c = make_client()
        oid = S.ensure_owner(c)
        self.assertEqual(oid, 1)
        c.create_vertex.assert_called_with(
            "me:me", labels=["Me"], properties={"stable_key": "me:me"}
        )

    def test_ensure_day_links_owner(self):
        c = make_client()
        day_id = S.ensure_day(c, "2024-01-01")
        self.assertEqual(day_id, 1)
        c.create_vertex.assert_any_call(
            "day:2024-01-01",
            labels=["Day"],
            properties={"date": "2024-01-01", "stable_key": "day:2024-01-01"},
        )
        c.create_edge.assert_any_call(1, 1, S.E_LIVES_DAY)

    def test_add_entry_under_day(self):
        c = make_client()
        eid = S.add_entry(c, day_id=5, text="hello", ts=123, turn_id="t1")
        self.assertEqual(eid, 1)
        c.create_vertex.assert_called_with(
            "entry:t1",
            labels=["Entry"],
            properties={
                "text": "hello",
                "ts": 123,
                "lang": "zh",
                "turn_id": "t1",
                "stable_key": "entry:t1",
            },
        )
        c.create_edge.assert_called_with(5, 1, S.E_HAS_ENTRY)

    def test_mention_uses_stable_name_and_labels(self):
        c = make_client()
        fid = S.mention(c, entry_id=9, label=S.L_PERSON, key="Alice")
        c.create_vertex.assert_called_with(
            "person:alice", labels=["Person"], properties={"stable_key": "person:alice"}
        )
        c.create_edge.assert_called_with(9, 1, S.E_MENTIONS)

    def test_add_todo_with_future_date_points_forward(self):
        c = make_client()
        tid = S.add_todo(c, day_id=5, text="run", for_date="2024-01-02")
        self.assertEqual(tid, 1)
        c.create_edge.assert_any_call(5, 1, S.E_HAS_TODO)
        # for_date -> ensure_day(target) -> create_edge(todo, target, for_date)
        c.create_edge.assert_any_call(1, 1, S.E_FOR_DATE)

    def test_upsert_reuses_existing_id(self):
        c = make_client()
        # _upsert now looks up via gremlin `has` on the stable_key property.
        c.gremlin.return_value = [{"id": 42, "type": "vertex", "name": "person:alice"}]
        fid = S.mention(c, entry_id=9, label=S.L_PERSON, key="Alice")
        self.assertEqual(fid, 42)
        c.create_vertex.assert_not_called()  # reused, not created


if __name__ == "__main__":
    unittest.main()
