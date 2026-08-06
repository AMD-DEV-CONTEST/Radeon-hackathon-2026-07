"""Generate fine-grained world fact graph from LLM training knowledge.

Fetches 15-25 events per high-signal year (31 years × ~20 events = ~600 total).
No external API calls — all from Qwen's training data.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.story_graph import StoryGraphBuilder, clear_story_data

HIGH_SIGNAL_YEARS = [
    1929,
    1933,
    1937,
    1939,
    1941,
    1945,
    1947,
    1949,
    1950,
    1953,
    1957,
    1963,
    1966,
    1968,
    1969,
    1972,
    1974,
    1978,
    1989,
    1991,
    1997,
    1999,
    2001,
    2003,
    2008,
    2011,
    2014,
    2016,
    2020,
    2022,
    2024,
]


def fetch_year_events(year: int) -> list[dict]:
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": (
                    f"List 15-25 historically significant events that happened in {year}. "
                    "Include specific dates where known. Cover: politics & wars, science & technology, "
                    "culture & arts, sports, disasters, economy, notable births & deaths. "
                    "Return ONLY a JSON array. Each event: "
                    "{'label': 'event name', 'year': " + str(year) + ", "
                    "'description': '1 sentence in Chinese', "
                    "'category': 'politics|science|culture|economy|disaster|sports|birth|death', "
                    "'location': 'city or country'}. "
                    "No markdown, no other text, just the JSON array."
                ),
            }
        ],
        temperature=0.2,
        max_tokens=2000,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  WARN: {year} parse failed ({len(raw)} chars)")
        return []


def main():
    all_events = []
    for year in HIGH_SIGNAL_YEARS:
        print(f"  {year}...", end=" ", flush=True)
        events = fetch_year_events(year)
        all_events.extend(events)
        cats = {}
        for e in events:
            cats[e.get("category", "?")] = cats.get(e.get("category", "?"), 0) + 1
        print(f"{len(events)} events {dict(cats)}")
        time.sleep(0.8)

    print(f"\n  Total: {len(all_events)} events from {len(HIGH_SIGNAL_YEARS)} years")

    # Build graph
    clear_story_data()
    builder = StoryGraphBuilder("World Facts Fine-Grained 1924-2024")

    for decade in range(1920, 2030, 10):
        builder.add_phase(f"{decade}s", f"{decade}s年代的历史事件")

    for ev in all_events:
        label = ev.get("label", f"Event {ev['year']}")
        desc = ev.get("description", "")
        year = ev.get("year", 0)
        loc = ev.get("location", "")

        builder.add_event(label, desc, year, str(year))
        builder.in_phase(label, f"{year // 10 * 10}s")

        if loc:
            builder.add_entity(loc, "place", label)
            builder.participate(loc, label, "地点")

        cat = ev.get("category", "")
        if cat:
            cat_map = {
                "politics": "政治",
                "science": "科技",
                "culture": "文化",
                "economy": "经济",
                "disaster": "灾难",
                "sports": "体育",
                "birth": "出生",
                "death": "逝世",
            }
            cat_cn = cat_map.get(cat, cat)
            builder.add_entity(cat_cn, "concept", "")
            builder.participate(cat_cn, label, "类别")

    builder.build()
    print(f"\n  Fact graph built! {len(all_events)} events across 11 decades")
    print(
        "  Query: python -c \"from agents.tools.cypher_templates import execute_safe_query; e = execute_safe_query('GET_PHASE_EVENTS', {'phase_name': '1960s'}); print(f'{len(e)} events in 1960s')\""
    )


if __name__ == "__main__":
    main()
