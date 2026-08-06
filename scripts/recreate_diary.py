"""Clean the diary graph and recreate 08-04 + 08-05 by feeding the story to the
LLM one segment at a time, printing what the pipeline extracts each turn.

This walks the real path:  DiaryAgent.process_turn  →  LLM structured JSON  →
  RBAC tools  →  graph writes (Entry / mentions / Todo). Run it to SEE the
  pipeline work, then browse the day views at :8080.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diary import runtime, config
from diary import schema as S
from diary import tools as T
from diary.agent import DiaryAgent
from diary.image_agent import MEDIA_ROOT, read_day_rich
from diary.day_view import get_day_view

GRAPH = config.GRAPH_NAME

print("=== 1. wipe diary graph ===")
client = runtime.get_client()
client.delete_graph(GRAPH)
client.create_graph(GRAPH, time_travel=False)
print("recreated graph:", GRAPH)

print("=== 2. clear generated media ===")
n = 0
for d in sorted(os.listdir(MEDIA_ROOT)):
    p = os.path.join(MEDIA_ROOT, d)
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        n += 1
print("removed", n, "media day dirs")

print("=== 3. feed the story to the LLM, one segment at a time ===\n")
ctx = T.DiaryContext(client=client)


def feed_day(date, turns):
    agent = DiaryAgent()
    day_id = S.ensure_day(client, date)
    for i, (text, ts) in enumerate(turns, 1):
        reply = agent.process_turn(ctx, date, text, ts=ts, lang="en")

        # What the pipeline just wrote to the graph for THIS turn.
        rich = read_day_rich(ctx, date)
        this = next((e for e in rich if e["text"] == text), None)
        mentions = [m["key"] for m in (this["mentions"] if this else [])]
        todos = [
            f"{t.get('properties', {}).get('text')}"
            + (f" → {t['properties'].get('for_date')}" if t.get("properties", {}).get("for_date") else "")
            for t in S.todos_for_day(client, day_id)
        ]

        print(f"--- {date} · turn {i} ({ts[11:16]}) ---")
        print(f"  input   : {text}")
        print(f"  reply   : {reply}")
        print(f"  mentions: {mentions}")
        print(f"  todos   : {todos}")
        print()


feed_day(
    "2026-08-05",
    [
        ("I got up late since I can work remote today.", "2026-08-05T09:30:00"),
        ("I was on AMD AI hackathon contest and the deadline of submission was the midnight next day (20260806 11:59PM).", "2026-08-05T10:00:00"),
        ("I cooked three meals today. Boiled egg and milk for breakfast, pumpkin pie for lunch, and wonton soup for dinner.", "2026-08-05T10:40:00"),
        ("I worked on the company's project for most of the day.", "2026-08-05T14:00:00"),
        ("After 5PM I got time to develop the remaining part of the AMD hackathon.", "2026-08-05T17:30:00"),
    ],
)

feed_day(
    "2026-08-04",
    [
        ("I got up early to go to work. It's a long drive.", "2026-08-04T07:30:00"),
        ("I had bao for breakfast.", "2026-08-04T08:20:00"),
        ("At lunch I got a chance to dine with some colleagues. One of the colleagues just got promoted.", "2026-08-04T12:40:00"),
        ("When I got home, it was already 7PM. What a long day.", "2026-08-04T19:30:00"),
    ],
)

print("=== 4. summary ===")
for date in ("2026-08-05", "2026-08-04"):
    v = get_day_view(date)
    print(f"{date}: {len(v['nodes'])} nodes, {len(v['edges'])} edges, "
          f"{len(v['entries'])} entries, {len(v['todos'])} todos")
