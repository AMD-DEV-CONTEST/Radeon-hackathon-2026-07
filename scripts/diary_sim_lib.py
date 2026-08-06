#!/usr/bin/env python
"""
Shared library for the diary adversarial / batch simulation.

This consolidates the reusable pieces (LLM user-simulator, TTS+ASR, single-turn
runner, reliable day-reader, eval/coverage helpers, hermetic key minting) so that
both the single-run regression test (`adversarial_diary_test.py`) and the scaled
batch harness (`batch_diary_sim.py`) share one implementation.

Key design notes (see plan / commit 5c6b1ad):
  * Bionic-Graph's `out` query UNDER-RETURNS (rank-index cap), so we never try to
    enumerate a day's entries via day->out. We read each Entry node directly by
    its stable_key (the same lookup `_upsert` uses).
  * Entry stable_keys are NOT date-scoped and `_upsert` never overwrites, so every
    simulated run MUST use unique turn_ids (see `mint_run_keys`). A fresh *date*
    alone is not enough.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI

from diary import config, runtime
from diary.agent import DiaryAgent, FACET_LABELS
from diary import schema as S
from diary.tools import DiaryContext, call_tool
from database.bionic_graph_client import BionicGraphClient
from tts.kokoro_tts import synthesize

FACETS = ["Food", "Person", "Place", "Mood", "Activity", "Transport"]


# ─── LLM (local, OpenAI-compatible) ──────────────────────────────────────────

class LLM:
    def __init__(self, base_url: str | None = None):
        self.client = OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=base_url or config.LLM_BASE_URL,
        )

    def chat(self, system: str, user: str, max_tokens: int = 600,
             temperature: float = 0.7) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("extra_body", None)
            resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        return json.loads(text[s : e + 1])
    except json.JSONDecodeError:
        return {}


def _shift(date_iso: str, days: int) -> str:
    return (_date.fromisoformat(date_iso) + __import__("datetime").timedelta(days=days)).isoformat()


# ─── Hermetic run keys ───────────────────────────────────────────────────────

def mint_run_keys(run_idx: int, base_date: str = "2099-08-05") -> tuple[str, str]:
    """Return (date, nonce) that make a run hermetic.

    * `date` is a unique far-future day so the day-node and its todo edges don't
      collide with other runs.
    * `nonce` scopes every turn_id/id, because Entry stable_keys are global
      (not date-scoped) and `_upsert` never overwrites.
    """
    import time as _time
    base = _date(2099, 1, 1)
    offset = (int(_time.time()) // 7 + run_idx * 31) % 20000
    date = (base + __import__("datetime").timedelta(days=offset)).isoformat()
    nonce = f"r{run_idx}_{int(_time.time() * 1000) % 100000}_"
    return date, nonce


# ─── User simulator ──────────────────────────────────────────────────────────

def simulate_day(llm: LLM, date: str, n: int) -> list[dict]:
    """LLM narrates a day; returns turns with the LLM's own intended facts."""
    system = (
        f"You are a person narrating their day into a voice diary. Produce {n} short, "
        "natural spoken turns in Chinese (1-3 sentences each, as if talking aloud). "
        "Across the day cover: what you ate (Food), a person you met (Person), a place "
        "you went (Place), your mood (Mood), an activity (Activity), how you got around "
        "(Transport). Include at least ONE explicit future plan with a relative date "
        "(e.g. '明天我要...' / '下周一...') and at least ONE todo. Also include ONE very "
        "short/vague turn (e.g. '嗯，今天还行'). "
        "Return ONLY JSON: {\"turns\":[{\"text\":\"...\","
        "\"mentions\":[\"Person:alice\",\"Food:火锅\"],\"todos\":[\"...\"]}]}. "
        "Each mention is \"Label:Key\" with a lowercase key. List only clearly stated facts."
    )
    user = f"Today is {date}. Narrate your day."
    data = {}
    for attempt in range(3):
        data = _parse_json(llm.chat(system, user, max_tokens=1500, temperature=0))
        if data.get("turns"):
            break
    turns = []
    for i, t in enumerate(data.get("turns") or []):
        turns.append({
            "id": f"sim{i}",
            "text": t.get("text", "").strip(),
            "turn_id": None,
            "source": "llm",
            "expect": {
                "mentions": t.get("mentions", []),
                "todos": t.get("todos", []),
            },
        })
    if not turns:
        print("[sim] LLM day-sim failed to parse; using deterministic fallback day")
        return _fallback_day(date)
    return turns


def _fallback_day(date: str) -> list[dict]:
    """Deterministic scripted day, used only if the LLM simulator can't parse.
    Ensures the pipeline always exercises a non-trivial narrated day."""
    return [
        {"id": "sim0", "text": "早上我喝了咖啡，然后去公园散步。", "turn_id": None,
         "source": "llm", "expect": {"mentions": ["Food:咖啡", "Activity:散步"], "todos": []}},
        {"id": "sim1", "text": "中午和Alice一起吃了火锅。", "turn_id": None,
         "source": "llm", "expect": {"mentions": ["Food:火锅", "Person:alice"], "todos": []}},
        {"id": "sim2", "text": "下午坐地铁去了公司开会。", "turn_id": None,
         "source": "llm", "expect": {"mentions": ["Place:公司", "Transport:地铁"], "todos": []}},
        {"id": "sim3", "text": "心情挺轻松的，工作还算顺利。", "turn_id": None,
         "source": "llm", "expect": {"mentions": ["Mood:轻松"], "todos": []}},
        {"id": "sim4", "text": "对了，明天我得交报告。", "turn_id": None,
         "source": "llm", "expect": {"todos": ["交报告"], "for_date": _shift(date, 1)}},
        {"id": "sim5", "text": "嗯，今天还行。", "turn_id": None,
         "source": "llm", "expect": {}},
    ]


def corner_cases(date: str) -> list[dict]:
    """Deterministic, hard-asserted adversarial inputs."""
    tomorrow = _shift(date, 1)
    far = _shift(date, 30)
    return [
        # 1. empty / whitespace → no entry, no crash
        {"id": "c_empty", "text": "    ", "turn_id": None, "source": "corner",
         "expect": {"empty": True}},
        # 2+3. duplicate turn (same turn_id) → only one entry
        {"id": "c_dup1", "text": "我中午吃了拉面。", "turn_id": "dup1", "source": "corner",
         "expect": {"mentions": ["Food:拉面"]}},
        {"id": "c_dup2", "text": "我中午吃了拉面。", "turn_id": "dup1", "source": "corner",
         "expect": {"dedup": True}},
        # 4. plan for tomorrow → todo + highlighted later
        {"id": "c_plan_tomorrow", "text": "明天我要去健身房。", "turn_id": None, "source": "corner",
         "expect": {"todos": ["健身房"], "for_date": tomorrow}},
        # 5. plan for a far-future absolute date → todo attached to that target day
        {"id": "c_plan_far", "text": f"{far} 我要交季度报告。", "turn_id": None, "source": "corner",
         "expect": {"todos": ["季度报告"], "for_date": far}},
        # 6. very long monologue
        {"id": "c_long", "text": ("今天发生了好多事。" * 25), "turn_id": None, "source": "corner",
         "expect": {}},
        # 7. mixed Chinese/English → recorded; lang=en for storage
        {"id": "c_mix", "text": "I had coffee with Bob 然后去了公园散步。", "turn_id": None,
         "source": "corner", "expect": {"mentions": ["Person:bob"], "lang": "en"}},
        # 8. garbage / no content
        {"id": "c_garbage", "text": "。。。嗯。", "turn_id": None, "source": "corner",
         "expect": {}},
        # 9. activity with a time → recorded as Activity mention
        {"id": "c_time", "text": "我早上7点起床，然后去跑步了。", "turn_id": None, "source": "corner",
         "expect": {"mentions": ["Activity:跑步"]}},
        # 10+11. NUDGE scenario: plan, then a later turn that ignores it → agent highlights it
        {"id": "c_nudge_plan", "text": "明天下午我要提交报告。", "turn_id": None, "source": "corner",
         "expect": {"todos": ["提交报告"], "for_date": tomorrow}},
        {"id": "c_nudge_later", "text": "今天工作有点忙，不过还行。", "turn_id": None,
         "source": "corner", "expect": {"nudge": ["提交报告"]}},
    ]


# ─── TTS + ASR ───────────────────────────────────────────────────────────────

def tts(text: str, stem: str):
    if not text or not text.strip():
        return None
    # synthesize() returns the full "<stem>.wav" path (or None on failure).
    return synthesize(text, stem, lang="zh")


def asr(mode: str, wav_path, source_text: str, noise_rate: float = 0.15, seed: int = 0) -> str:
    if mode == "echo" or not source_text:
        return source_text
    if mode == "noise":
        rnd = random.Random(seed)
        out = []
        for ch in source_text:
            if ch.strip() and rnd.random() < noise_rate:
                if rnd.random() < 0.5:
                    continue  # drop
                out.append(rnd.choice("的了他了吗呢啊吧和跟在和跟对吧哦呀"))
            else:
                out.append(ch)
        return "".join(out)
    if mode == "whisper":
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            print(f"[ASR] faster_whisper unavailable ({e}); falling back to echo")
            return source_text
        model = WhisperModel("tiny", device="cpu")
        segs, _ = model.transcribe(wav_path, language="zh")
        return "".join(s.text for s in segs)
    return source_text


# ─── Run one turn through the pipeline ───────────────────────────────────────

def run_turn(agent: DiaryAgent, ctx: DiaryContext, date: str, turn: dict,
             asr_mode: str, outdir: str, noise_rate: float, seed: int,
             no_tts: bool = False) -> dict:
    # Give every turn a stable id so its Entry node is discoverable later by
    # stable_key (Bionic-Graph's `out` query under-returns, so day->entries
    # traversal cannot enumerate them reliably).
    turn_id = turn.get("turn_id") or turn["id"]
    wav = None if no_tts else tts(turn["text"], os.path.join(outdir, "turn_" + turn_id))
    recognized = asr(asr_mode, wav, turn["text"], noise_rate, seed)
    lang = turn.get("expect", {}).get("lang", "zh")
    reply = agent.process_turn(ctx, date, recognized, lang=lang, turn_id=turn_id)
    return {
        "id": turn["id"],
        "turn_id": turn_id,
        "source": turn["text"],
        "wav": wav,
        "recognized": recognized,
        "reply": reply,
        "expect": turn.get("expect", {}),
        "source_tag": turn.get("source"),
    }


# ─── Read the day back from the graph ────────────────────────────────────────

def read_day_full(client: BionicGraphClient, ctx: DiaryContext, date: str, turns: list[dict]) -> dict:
    """Reliable per-turn read.

    Bionic-Graph's ``out`` query UNDER-RETURNS (rank-index cap), so we cannot
    enumerate a day's entries via day -> out(has_entry). Instead we look each
    turn's Entry node up directly by its stable_key (the same lookup ``_upsert``
    uses, which is reliable), then read its mentions via per-entry ``out``.
    """
    S.ensure_day(client, date)
    entries_by_turn: dict[str, str] = {}
    mentions_by_turn: dict[str, list] = {}

    for t in turns:
        tid = t.get("turn_id") or t.get("id")
        if not tid:
            continue
        name = S._stable_name(S.L_ENTRY, tid)
        hits = client.gremlin(
            [{"step": "V"}, {"step": "has", "key": S.STABLE_KEY_PROP, "value": name},
             {"step": "limit", "count": 1}]
        ) or []
        node = None
        for h in hits:
            if h.get("type") == "vertex" and h.get("name") == name:
                node = h
                break
        if not node:
            continue
        entries_by_turn[tid] = (node.get("properties") or {}).get("text", "")
        ms = client.gremlin(
            [{"step": "V", "ids": [node["id"]]}, {"step": "out", "name": S.E_MENTIONS, "depth": 1}]
        ) or []
        mlist = []
        for m in ms:
            labels = m.get("labels") or []
            if not (set(labels) & FACET_LABELS):
                continue
            mname = m.get("name", "")
            key = mname.split(":", 1)[1] if ":" in mname else mname
            mlist.append((labels[0], key.lower()))
        mentions_by_turn[tid] = mlist

    todo_nodes = call_tool("get_todos", ctx, date=date)
    todo_texts = [(t.get("properties") or {}).get("text", "") for t in todo_nodes]
    return {"entries_by_turn": entries_by_turn, "mentions_by_turn": mentions_by_turn, "todos": todo_texts}


# ─── Evaluate: script (ground truth) vs database ─────────────────────────────

def evaluate(results: list[dict], db: dict, ctx: DiaryContext, date: str) -> list[tuple]:
    checks = []  # (label, hard:bool, passed:bool)

    def add(label, passed, hard=True):
        checks.append((label, hard, bool(passed)))

    ebt = db["entries_by_turn"]
    mbt = db["mentions_by_turn"]
    todos = db["todos"]

    for r in results:
        exp = r["expect"]
        rec = r["recognized"]
        tid = r.get("turn_id") or r["id"]
        # entry presence
        if exp.get("empty"):
            add(f"empty_no_entry:{r['id']}", tid not in ebt)
            continue
        add(f"entry_present:{r['id']}", ebt.get(tid) == rec)
        # todos
        for td in exp.get("todos", []):
            add(f"todo_present:{r['id']}:{td}", any(td in t for t in todos))
        # nudge / highlight
        for nk in exp.get("nudge", []):
            add(f"nudge:{r['id']}:{nk}", nk in (r["reply"] or ""))
        # dedup (same turn_id -> one entry, equal text)
        if exp.get("dedup"):
            add(f"dedup:{r['id']}", ebt.get(tid) == rec)
        # future plan attached to its TARGET day (not just planning day)
        fd = exp.get("for_date")
        if fd:
            target_todos = [
                (t.get("properties") or {}).get("text", "")
                for t in call_tool("get_todos", ctx, date=fd)
            ]
            for td in exp.get("todos", []):
                add(f"target_day_todo:{r['id']}:{td}@{fd}", any(td in t for t in target_todos))
        # mentions (SOFT — LLM extraction may legitimately differ)
        for m in exp.get("mentions", []):
            lab, key = (m.split(":", 1) + ["", ""])[:2]
            found = any(
                ml.lower() == lab.lower() and mk.lower() == key.lower()
                for ml, mk in mbt.get(tid, [])
            )
            add(f"mention:{r['id']}:{m}", found, hard=False)

    return checks


def facet_coverage(db: dict):
    all_mentions = [m for ms in db["mentions_by_turn"].values() for m in ms]
    present = {lab for lab, _ in all_mentions}
    covered = [f for f in FACETS if f in present]
    missing = [f for f in FACETS if f not in present]
    return covered, missing


# ─── Coverage loop: ask valuable questions until confident ───────────────────

def coverage_loop(llm: LLM, agent: DiaryAgent, ctx: DiaryContext, date: str,
                  db: dict, outdir: str, asr_mode: str, max_rounds: int) -> list[dict]:
    log = []
    for rd in range(max_rounds):
        covered, missing = facet_coverage(db)
        if not missing:
            break
        q = llm.chat(
            "You are a warm voice-diary assistant. The user's day so far is missing these "
            f"aspects: {', '.join(missing)}. Ask ONE short follow-up question (Chinese) to learn "
            "about ONE missing aspect. Return ONLY the question, no quotes.",
            "Ask a follow-up.",
        ).strip().strip('"')
        ans = llm.chat(
            f"The assistant asked: '{q}'. Reply briefly AS THE USER, naturally mentioning the "
            f"missing aspect ({missing[0]}). Return ONLY the answer.",
            "Answer as the user.",
        ).strip()
        wav = tts(ans, os.path.join(outdir, f"cov{rd}"))
        recognized = asr(asr_mode, wav, ans)
        reply = agent.process_turn(ctx, date, recognized, lang="zh")
        db = read_day_full(runtime.get_client(), ctx, date, [])  # refresh handled by caller
        log.append({"question": q, "answer": ans, "reply": reply, "missing": missing})
    return log
