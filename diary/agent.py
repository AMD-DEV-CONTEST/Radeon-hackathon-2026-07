"""Diary interviewer agent — talks to the local LLM and records to the graph.

This is a NEW agent for the diary app. It is intentionally separate from the legacy
`agents.graph_agent.GraphVoiceAgent` (which is a Cypher/Neo4j movie chatbot bound to a
cloud LLM). The diary agent:

- calls the LOCAL LLM (OpenAI-compatible, see diary.config) — no cloud keys;
- returns a structured turn: a spoken reply + extracted facets (people/places/things…)
  + any todos/plans the user mentioned;
- writes everything through the RBAC-guarded diary tool layer (diary.tools);
- proactively nudges about futures todos the user planned but hasn't discussed.

The LLM is asked for JSON so we can route facts to the graph without a separate
entity-extraction model.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from diary import config
from diary import schema as S
from diary import tools as T
from diary.tools import DiaryContext

# Valid facet labels the LLM may emit for a mention.
FACET_LABELS = {
    S.L_PERSON, S.L_PLACE, S.L_EVENT, S.L_ORG, S.L_THING, S.L_ACTIVITY,
    S.L_MOOD, S.L_HEALTH, S.L_WORK, S.L_FINANCE,
    S.L_FOOD, S.L_MEAL, S.L_CLOTHING, S.L_SHELTER, S.L_TRANSPORT,
}

INTERVIEWER_SYSTEM = """你是一位温暖、好奇的朋友，帮助用户写语音日记。
你必须只用中文回复，绝不使用英文、阿拉伯语或其他语言。回复要像真实对话一样简短（1-3 句），不要写成报告。

你如何帮助：
- 倾听用户分享的当天经历（衣食住行：穿了什么、吃了什么、待在哪里、怎么出行），以及提到的人、地点和事件。
- 如果用户说得很少，问一个温和的追问来了解更多信息。
- CRITICAL：提取每一个明确说出的计划、意图或任务作为 'todo'——包括以"我要 / 打算 / 准备 / 开始做 X"表述的内容。若有提到绝对日期/时间，请记下。不要提取纯粹对已完成的过去动作的叙述（如"我吃了 / 我去了 / 我做完了"）。
- 只提取对象明确的具体计划（如“交报告”“去健身房”）。绝不虚构用户没说过的事项，绝不把“稍后 / 今天做 / 收到 / 好 / do it”等时间片段或应答当作 todo。
- CRITICAL：提取所有提到的人、地点、事物、食物、心情、活动作为 'mentions'。
- ENTITY RULE：实体必须使用用户原话的措辞，不要翻译、概括或改名。
- 自然地回引之前的对话。
- 只询问用户提到过或下面日记条目中出现的话题，不要提出用户从未提到的新话题（如无关的地点、活动、人物）。
- STRICT：下面这些日记条目是用户生活的唯一记录。绝不虚构或假设用户没说过的事实（不要编造旅行、餐食、任务、人物）。如果没有相关信息，就简单说“我没有这条记录”。
- DIRECT ANSWER：当用户询问某天发生了什么（例如“昨天吃了什么”/“前天见了谁”/“某日做了什么”）时，直接根据下面提供的日记条目回答，列出相关事实；不要反问“你指的是哪一天”或表示不确定。条目已按日期标注。

你会看到今天到目前为止的日记内容。
"""

INTERVIEWER_SYSTEM_EN = """You are a warm, curious friend who helps the user keep a voice diary.
You MUST reply in ENGLISH only. Never use Chinese, Arabic, or any other language.
Keep spoken replies short (1-3 sentences), like a real conversation — never a report.

How you help:
- Listen to what the user shares about their day (what they wore, ate, where they stayed,
  how they got around) and the people, places, and events they mention.
- If the user gives little detail, ask ONE gentle follow-up question to learn more.
- CRITICAL: Extract EVERY clearly stated plan, intention, or task as a 'todo' — including
  things phrased as "I will / I'm going to / I plan to / I'm about to / I started doing X".
  Capture the absolute date/time if mentioned. Do NOT extract pure recollections of
  already-finished past actions (e.g. "I ate / I went / I finished").
- Extract ONLY concrete plans with a clear object (e.g. "submit the report", "go to the
  gym"). NEVER invent a todo the user did not state, and NEVER turn bare acknowledgments
  or time fragments ("later today", "do it", "sure", "ok") into todos.
- CRITICAL: Extract ALL mentioned entities (People, Places, Things, Food, Moods, Activities)
  into 'mentions'.
- ENTITY RULE: Use the EXACT wording the user used for entities. Do NOT translate,
  summarize, or rename them.
- Reference earlier moments naturally.
- Only ask about things the user mentioned or that appear in the provided diary
  entries — never bring up topics the user hasn't mentioned (unrelated places,
  activities, or people).
- STRICT: the diary entries below are the ONLY record of the user's life. Never
  invent or assume facts the user hasn't stated (no imaginary trips, meals, tasks,
  or people). If you don't have the information, simply say you don't have that
  record.
- DIRECT ANSWER: when the user asks what happened on a specific day (e.g. "what did
  I eat yesterday?", "who did I see the day before yesterday?", "what did I do on
  Aug 5?"), answer DIRECTLY from the diary entries provided below — list the
  relevant facts. Do not ask which day they mean or express uncertainty; the
  entries are labelled with their dates.

You will be given the day's entries so far.
"""

# Language-specific system prompts. Only English and Chinese are supported; any other
# script (e.g. Arabic) is treated as English and forced to English output.
LANG_SYSTEM = {"zh": INTERVIEWER_SYSTEM, "en": INTERVIEWER_SYSTEM_EN}

STRUCTURE_INSTRUCTION = (
    "只返回一个 JSON 对象，不要包含任何其他内容，格式如下：\n"
    '{\n'
    '  "reply": "<简短的口语回复，使用中文>",\n'
    '  "mentions": [{"label": "Person|Place|Event|Food|Clothing|Shelter|Transport|Organization|Thing|Activity|Mood|Health|Work|Finance", "key": "<简短稳定 id，小写，例如 alice 或 pasta>"}],\n'
    '  "todos": [{"text": "<计划内容>", "for_date": "<绝对日期 YYYY-MM-DD 或 null>"}]\n'
    "}\n"
    '当用户说"明天" / "下周一" / "三天后"要做某事时，请根据给定的今天日期算出绝对日期，填入 for_date。\n'
    "只提取明确说出的 mentions/todos，没有就返回空列表。"
)

STRUCTURE_INSTRUCTION_EN = (
    "Respond with ONLY a JSON object and nothing else, of this shape:\n"
    '{\n'
    '  "reply": "<your short spoken reply, in ENGLISH>",\n'
    '  "mentions": [{"label": "Person|Place|Event|Food|Clothing|Shelter|Transport|Organization|Thing|Activity|Mood|Health|Work|Finance", "key": "<short stable id, lowercase, e.g. alice or pasta>"}],\n'
    '  "todos": [{"text": "<what was planned>", "for_date": "<absolute YYYY-MM-DD or null>"}]\n'
    "}\n"
    'When the user says they will do something "tomorrow" / "next Monday" / "in 3 days", '
    "compute the ABSOLUTE date (you are given today's date) and put it in for_date.\n"
    "Only include mentions/todos that are clearly stated. Empty lists are fine."
)

LANG_STRUCTURE = {"zh": STRUCTURE_INSTRUCTION, "en": STRUCTURE_INSTRUCTION_EN}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (text or ""))


def detect_lang(text: str) -> str:
    """Only English and Chinese are supported. CJK -> zh, everything else -> en
    (so Arabic / other scripts are forced to English, never echoed back)."""
    return "zh" if _has_cjk(text) else "en"


def _parse_json(raw: str) -> dict:
    """Defensive JSON parse: strip code fences + thinking blocks, then outermost {...}."""
    if raw is None:
        return {}
    text = raw.strip()
    # drop ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # drop Qwen <think>...</think> reasoning blocks (possible when thinking is on)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _format_day(day: dict) -> str:
    entries = [e for e in day.get("entries", []) if e]
    if not entries:
        return "(nothing recorded yet today)"
    return "\n".join(f"- {e}" for e in entries)


def _referenced_dates(query: str, today: str) -> list[str]:
    """Resolve the days a query references (yesterday / 前天 / tomorrow / 明天 /
    explicit YYYY-MM-DD) so the agent can answer questions about *other* days,
    not just the currently selected one. The selected day is always included by
    the caller; this returns the additional days worth loading.
    """
    dates: list[str] = []
    q = (query or "").lower()
    if "day before yesterday" in q or "前天" in q:
        dates.append(_shift_date(today, -2))
    if "yesterday" in q or "昨天" in q:
        dates.append(_shift_date(today, -1))
    if "tomorrow" in q or "明天" in q:
        dates.append(_shift_date(today, 1))
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", query or ""):
        dates.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return dates


def _format_days(ctx: T.DiaryContext, today: str, dates: list[str]) -> str:
    """Read several days and format them, each labelled with its date, so the
    LLM can tell which day each entry belongs to."""
    parts: list[str] = []
    for d in dict.fromkeys(dates):  # de-dup, keep order
        try:
            day = T.call_tool("read_day", ctx, date=d)
        except Exception:
            continue
        entries = [e for e in day.get("entries", []) if e]
        if not entries:
            continue
        label = "Today" if d == today else d
        parts.append(f"{label} ({d}):\n" + "\n".join(f"- {e}" for e in entries))
    if not parts:
        return "(nothing recorded for these days)"
    return "\n\n".join(parts)


@dataclass
class DiaryAgent:
    client: Any = None
    history: list[dict] = field(default_factory=list)
    enable_thinking: bool = False
    system_prompt: str | None = None  # override for prompt-mining / replay
    # Todos already nudged this session ("text|for_date") — we ask once, then let
    # the user answer without nagging about the same plan on every turn.
    _nudged: set[str] = field(default_factory=set)

    def __post_init__(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        # Pinned temperature for reproducible prompt-mining replays; 0.4 in normal
        # operation keeps the interviewer warm but reduces fabricated facts.
        self.temperature = float(os.getenv("DIARY_AGENT_TEMP", "0.4"))

    # -- LLM call (thinking toggle with fallback) --------------------
    def _llm(self, messages: list[dict], max_tokens: int = 400) -> str:
        kwargs: dict[str, Any] = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if not self.enable_thinking:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception:
            # Some builds reject the thinking toggle; retry plainly.
            kwargs.pop("extra_body", None)
            resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    # -- main entry ----------------------------------------------------
    def process_turn(
        self,
        ctx: DiaryContext,
        date: str,
        text: str,
        ts=None,
        lang: str = "zh",
        turn_id=None,
    ) -> str:
        if not text or not text.strip():
            return ""

        # Only English and Chinese are supported. Decide the reply language from the
        # user's own text (CJK -> zh, anything else -> en) so a non-CJK script such as
        # Arabic is forced to English and never echoed back. This also overrides any
        # misdetected `lang` passed in.
        eff_lang = detect_lang(text)
        if lang not in ("zh", "en"):
            lang = eff_lang

        # A null timestamp collapses every entry of a day onto the SAME upsert key
        # ("entry:<day>:None"), so all turns would overwrite one node and lose data.
        # Default to a high-resolution now() so each turn is its own entry (callers
        # may still pass an explicit ts/turn_id for retransmit de-duplication).
        if ts is None:
            ts = datetime.datetime.now().isoformat()

        # Load the selected day plus any days the query references (e.g. "what
        # did I eat yesterday?") so the agent can answer about other days' graphs.
        dates_to_read = [date] + _referenced_dates(text, date)
        memory = _format_days(ctx, date, dates_to_read)

        # NOTE: Qwen's chat template requires exactly ONE system message at the
        # start; the JSON-format instruction must live there, not as a trailing
        # system turn. History (user/assistant) follows, then the user utterance.
        # Use the language-specific system + structure prompt (unless a prompt-mining
        # override was supplied). The prompt hard-constrains the reply language so the
        # multilingual model cannot drift into Arabic / other scripts.
        if self.system_prompt:
            system_prompt = self.system_prompt
            structure = STRUCTURE_INSTRUCTION if eff_lang == "zh" else STRUCTURE_INSTRUCTION_EN
        else:
            system_prompt = LANG_SYSTEM[eff_lang]
            structure = LANG_STRUCTURE[eff_lang]
        messages = [
            {
                "role": "system",
                "content": (
                    system_prompt
                    + f"\n\nToday's date is {date}. Use it to resolve relative dates."
                    + "\n\n"
                    + structure
                    + f"\n\nDiary entries you can see (each labelled with its date):\n{memory}"
                ),
            },
            *self.history[-6:],
            {"role": "user", "content": text},
        ]

        data = _parse_json(self._llm(messages))
        reply = (data.get("reply") or "").strip()
        mentions = data.get("mentions") or []
        todos = data.get("todos") or []

        # Record the spoken turn + extracted facts through the RBAC tool layer.
        T.call_tool(
            "record_entry",
            ctx,
            date=date,
            text=text,
            ts=ts,
            lang=eff_lang,
            turn_id=turn_id,
            mentions=[self._norm_mention(m) for m in mentions if self._norm_mention(m)],
        )
        for t in todos:
            # Skip echo-todos like "later today" / "do it" that the LLM extracts
            # from the user's acknowledgment — they are not real plans.
            if not _is_real_todo(t.get("text") or ""):
                continue
            # Don't create a duplicate when the user is confirming an existing plan.
            if _todo_already_planned(ctx, date, t.get("text", ""), t.get("for_date")):
                continue
            fd = t.get("for_date")
            if fd:
                T.call_tool("add_todo", ctx, date=date, text=t["text"], for_date=fd)
            else:
                T.call_tool("add_todo", ctx, date=date, text=t["text"])

        # Proactively check futures todos the user planned but hasn't discussed.
        nudge = self._future_todo_nudge(ctx, date, text, lang=eff_lang)
        if nudge and reply:
            reply = reply + " " + nudge
        elif nudge:
            reply = nudge

        self.history.append({"role": "user", "content": text})
        if reply:
            self.history.append({"role": "assistant", "content": reply})
        return reply

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _norm_mention(m: dict):
        label = (m.get("label") or "").strip().title()
        key = (m.get("key") or "").strip()
        if not key:
            return None
        if label not in FACET_LABELS:
            # Map a few common synonyms; default to Thing.
            syn = {
                "Person": S.L_PERSON, "People": S.L_PERSON,
                "Place": S.L_PLACE, "Location": S.L_PLACE,
                "Event": S.L_EVENT, "Organization": S.L_ORG, "Org": S.L_ORG,
                "Food": S.L_FOOD, "Meal": S.L_MEAL, "Clothing": S.L_CLOTHING,
                "Shelter": S.L_SHELTER, "Transport": S.L_TRANSPORT,
                "Activity": S.L_ACTIVITY, "Mood": S.L_MOOD, "Health": S.L_HEALTH,
                "Work": S.L_WORK, "Finance": S.L_FINANCE, "Money": S.L_FINANCE,
                "Thing": S.L_THING,
            }
            label = syn.get(label, S.L_THING)
        return {"label": label, "key": key.lower(), "properties": m.get("properties")}

    # Phrases that mean the user is already handling a planned todo — don't nag.
    _ACKNOWLEDGE = (
        "will do", "do it", "do that", "on it", "got it", "good catch",
        "i will", "i'll", "i’ll", "later today", "tonight", "this evening",
        "稍后", "待会", "会做", "去做", "去办", "我来做", "我安排", "收到",
    )

    def _future_todo_nudge(self, ctx: DiaryContext, date: str, text: str, lang: str = "en") -> str:
        """If the user planned a future todo but hasn't acknowledged it, ask.
        Each todo is nudged at most ONCE per session, and an acknowledgment in the
        user's current message suppresses the nudge. Reply is in the user's
        language (zh / en)."""
        text_l = text.lower()
        if any(a in text_l for a in self._ACKNOWLEDGE):
            return ""  # the user already said they're on it
        tomorrow = _shift_date(date, 1)
        for d in (date, tomorrow):
            try:
                todos = T.call_tool("get_todos", ctx, date=d)
            except Exception:
                continue
            for t in todos:
                props = t.get("properties") or {}
                if props.get("for_date") not in (date, tomorrow):
                    continue  # not a today/tomorrow plan (e.g. planned here for later)
                ttext = (props.get("text") or "").lower()
                key = f"{props.get('for_date')}|{ttext}"
                if key in self._nudged:
                    continue  # already asked about this one this session
                if ttext and ttext not in text_l:
                    self._nudged.add(key)
                    todo_text = props.get("text", "")
                    if lang == "zh":
                        when = "明天" if props.get("for_date") == tomorrow else "今天"
                        return (
                            f"顺便问一句，你之前计划{when}做「{todo_text}」，"
                            f"有进展吗？"
                        )
                    when = "tomorrow" if props.get("for_date") == tomorrow else "today"
                    return (
                        f"By the way, you mentioned you planned to {todo_text} {when}"
                        f" — how's that going?"
                    )
        return ""


# Bare acknowledgments / time fragments that are NOT real new plans — the LLM
# sometimes echoes them back as a todo when the user just says "I will do it
# later today" or "sure, tomorrow".
_TODO_FRAGMENTS = {
    "later today", "today", "tonight", "tomorrow", "later", "do it", "do that",
    "on it", "ok", "okay", "yes", "sure", "will do", "got it", "good catch",
    "收到", "稍后", "待会", "今天", "明天", "好", "嗯", "行", "去做", "会做", "我",
}


def _is_real_todo(text: str) -> bool:
    t = (text or "").strip().lower()
    if len(t) < 3 or t in _TODO_FRAGMENTS:
        return False
    # Strip acknowledgment / time filler; if nothing concrete remains it's just a
    # fragment, not a plan (e.g. "do a later today" -> "", "submit the report" ->
    # "submit report").
    core = re.sub(
        r"\b(do|doing|i'll|i will|i am|i'm|a|an|the|my|this|that|it|them|for|to|later|"
        r"today|tonight|tomorrow|now|sure|yes|ok|okay|on|with|please)\b",
        " ", t,
    )
    core = re.sub(r"[\s\[\]()]+", " ", core).strip()
    return len(core) >= 3


def _norm_todo(text: str) -> str:
    """Normalize a todo's core intent (drop action verbs + filler) so "Submit AMD
    AI hackathon contest project" and "Do AMD AI hackathon contest project" match."""
    core = re.sub(
        r"\b(do|doing|submit|send|finish|complete|start|begin|go|make|get|plan|schedule|"
        r"i'll|i will|i am|i'm|a|an|the|my|this|that|for|to|later|today|tonight|tomorrow|"
        r"now|please)\b",
        " ", (text or "").lower(),
    )
    return re.sub(r"[\s\[\]()]+", " ", core).strip()


def _todo_already_planned(ctx: T.DiaryContext, date: str, text: str, for_date: str | None) -> bool:
    """True if a todo with the same core intent already exists on the target day
    (so confirming/restating a plan doesn't create a duplicate node)."""
    new_core = _norm_todo(text)
    if not new_core:
        return True
    for d in {for_date, date}:
        if not d:
            continue
        try:
            existing = T.call_tool("get_todos", ctx, date=d)
        except Exception:
            continue
        for t in existing:
            props = t.get("properties") or {}
            if _norm_todo(props.get("text", "")) == new_core:
                return True
    return False


def _shift_date(date_iso: str, days: int) -> str:
    """Shift a YYYY-MM-DD string by `days` (no external deps)."""
    import datetime

    try:
        d = datetime.date.fromisoformat(date_iso)
        return (d + datetime.timedelta(days=days)).isoformat()
    except Exception:
        return date_iso
