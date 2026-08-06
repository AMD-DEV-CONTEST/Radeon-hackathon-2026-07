"""Unit tests for the diary RBAC / tool layer (offline, mocked client)."""

import unittest
from unittest.mock import MagicMock, patch

from database.bionic_graph_client import BionicGraphClient
from diary import rbac
from diary import tools as T
from diary.tools import DiaryContext


def make_ctx():
    c = MagicMock(spec=BionicGraphClient)
    c.search.return_value = []
    c.gremlin.return_value = []
    c.create_vertex.return_value = 1
    return DiaryContext(client=c)


class TestRBAC(unittest.TestCase):
    def test_unknown_tool_rejected(self):
        ctx = make_ctx()
        with self.assertRaises(rbac.RBACViolation):
            T.call_tool("delete_everything", ctx)
        with self.assertRaises(rbac.RBACViolation):
            T.call_tool("modify_rbac", ctx)

    def test_registered_tools_match_rbac_allowlist(self):
        self.assertEqual(set(T.TOOLS), rbac.AGENT_TOOLS)

    def test_assert_allowed_raises_for_unlisted(self):
        with self.assertRaises(rbac.RBACViolation):
            rbac.assert_allowed("drop_graph")


class TestTools(unittest.TestCase):
    def test_record_entry_wires_schema(self):
        ctx = make_ctx()
        eid = T.call_tool(
            "record_entry",
            ctx,
            date="2024-01-01",
            text="met Alice",
            mentions=[{"label": "Person", "key": "Alice"}],
        )
        self.assertEqual(eid, 1)
        # schema.add_entry + schema.mention were exercised
        self.assertTrue(ctx.client.create_vertex.called)
        self.assertTrue(ctx.client.create_edge.called)

    def test_get_todos_delegates_to_schema(self):
        ctx = make_ctx()
        with patch("diary.schema.todos_for_day", return_value=[{"id": 7}]) as mocked:
            out = T.call_tool("get_todos", ctx, date="2024-01-01")
        self.assertEqual(out, [{"id": 7}])
        mocked.assert_called_once()

    def test_search_graph_delegates_to_client(self):
        ctx = make_ctx()
        ctx.client.search.return_value = [{"id": 1, "name": "food:pasta"}]
        out = T.call_tool("search_graph", ctx, text="pasta", mode="exact", limit=3)
        ctx.client.search.assert_called_with("pasta", mode="exact", limit=3)
        self.assertEqual(out, [{"id": 1, "name": "food:pasta"}])

    def test_summarize_day_concats_entries(self):
        ctx = make_ctx()
        with patch.object(T, "read_day", return_value={"date": "d", "entries": ["a", "", "b"], "todos": []}):
            summary = T.call_tool("summarize_day", ctx, date="d")
        self.assertEqual(summary, "- a\n- b")


if __name__ == "__main__":
    unittest.main()
