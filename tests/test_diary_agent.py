"""Unit tests for the diary interviewer agent (offline, mocked LLM + graph)."""

import unittest
from unittest.mock import MagicMock

from database.bionic_graph_client import BionicGraphClient
from diary import agent as A
from diary import schema as S
from diary.agent import DiaryAgent, _parse_json, _shift_date
from diary.tools import DiaryContext


# -- fake OpenAI client ------------------------------------------------------
class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResp:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    """Returns a fixed JSON reply; records the last call kwargs."""

    def __init__(self, content):
        self._content = content
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeResp(self._content)


class FakeClient:
    def __init__(self, content):
        self.chat = MagicMock()
        self.chat.completions = FakeCompletions(content)


def make_ctx():
    c = MagicMock(spec=BionicGraphClient)
    c.search.return_value = []
    c.gremlin.return_value = []
    c.create_vertex.return_value = 1
    return DiaryContext(client=c)


# -- tests -------------------------------------------------------------------
class TestJsonParse(unittest.TestCase):
    def test_strips_fences(self):
        self.assertEqual(_parse_json('```json\n{"reply":"hi"}\n```'), {"reply": "hi"})

    def test_outermost_braces(self):
        self.assertEqual(_parse_json('noise {"a":1} more'), {"a": 1})

    def test_invalid_returns_empty(self):
        self.assertEqual(_parse_json("not json at all"), {})
        self.assertEqual(_parse_json(None), {})


class TestShiftDate(unittest.TestCase):
    def test_forward(self):
        self.assertEqual(_shift_date("2026-08-05", 1), "2026-08-06")

    def test_backward(self):
        self.assertEqual(_shift_date("2026-03-01", -1), "2026-02-28")

    def test_bad_input_passthrough(self):
        self.assertEqual(_shift_date("nonsense", 3), "nonsense")


class TestProcessTurn(unittest.TestCase):
    def test_empty_text_returns_empty(self):
        agent = DiaryAgent(client=FakeClient("{}"))
        self.assertEqual(agent.process_turn(make_ctx(), "2026-08-05", "   "), "")

    def test_records_entry_and_returns_reply(self):
        llm = FakeClient('{"reply":"今天听起来不错！","mentions":[],"todos":[]}')
        agent = DiaryAgent(client=llm)
        ctx = make_ctx()
        out = agent.process_turn(ctx, "2026-08-05", "我今天去了公园")
        self.assertEqual(out, "今天听起来不错！")
        # record_entry -> create_vertex was exercised
        self.assertTrue(ctx.client.create_vertex.called)

    def test_mentions_normalized_through_schema(self):
        llm = FakeClient(
            '{"reply":"ok","mentions":[{"label":"People","key":"Alice"}],"todos":[]}'
        )
        agent = DiaryAgent(client=llm)
        ctx = make_ctx()
        with unittest.mock.patch("diary.schema.mention") as m:
            agent.process_turn(ctx, "2026-08-05", "我和 Alice 见面了")
            m.assert_called_once()
            label, key = m.call_args.args[2], m.call_args.args[3]
            self.assertEqual(label, S.L_PERSON)
            self.assertEqual(key, "alice")

    def test_todos_with_future_date(self):
        llm = FakeClient(
            '{"reply":"记下了","mentions":[],'
            '"todos":[{"text":"看医生","for_date":"2026-08-10"}]}'
        )
        agent = DiaryAgent(client=llm)
        ctx = make_ctx()
        out = agent.process_turn(ctx, "2026-08-05", "我计划 8 月 10 日看医生")
        self.assertEqual(out, "记下了")
        # ensure_day + todo vertex created
        self.assertTrue(ctx.client.create_vertex.called)

    def test_thinking_toggled_off_by_default(self):
        llm = FakeClient('{"reply":"hi","mentions":[],"todos":[]}')
        agent = DiaryAgent(client=llm, enable_thinking=False)
        agent.process_turn(make_ctx(), "2026-08-05", "hello")
        self.assertIn("extra_body", llm.chat.completions.last_kwargs)
        self.assertEqual(
            llm.chat.completions.last_kwargs["extra_body"],
            {"chat_template_kwargs": {"enable_thinking": False}},
        )


class TestFutureTodoNudge(unittest.TestCase):
    def test_nudges_when_future_todo_unmentioned(self):
        # get_todos for tomorrow returns a plan; user's text doesn't mention it.
        llm = FakeClient('{"reply":"今天开心吗？","mentions":[],"todos":[]}')
        agent = DiaryAgent(client=llm)
        ctx = make_ctx()
        # todos_for_day -> gremlin returns a tomorrow todo vertex
        ctx.client.gremlin.return_value = [
            {
                "id": 9,
                "labels": [S.L_TODO],
                "properties": {"text": "还书", "for_date": "2026-08-06"},
            }
        ]
        out = agent.process_turn(ctx, "2026-08-05", "今天天气真好")
        self.assertIn("还书", out)

    def test_no_nudge_when_already_mentioned(self):
        llm = FakeClient('{"reply":"好的，那个已经办了","mentions":[],"todos":[]}')
        agent = DiaryAgent(client=llm)
        ctx = make_ctx()
        ctx.client.gremlin.return_value = [
            {"id": 9, "labels": [S.L_TODO], "properties": {"text": "还书"}}
        ]
        out = agent.process_turn(ctx, "2026-08-05", "我今天已经还书了")
        # planned todo already mentioned -> no nudge appended
        self.assertEqual(out, "好的，那个已经办了")


if __name__ == "__main__":
    unittest.main()
