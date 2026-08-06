"""Random-walk place enrichment: pick random places, fetch Wikipedia, add events.

Target: 10 places per pass, 10-20 events per place, ~150 new events total.
"""

import json
import random
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from database.neo4j_client import Neo4jClient
from memory.story_graph import StoryGraphBuilder

client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
WIKI_URL = "https://en.wikipedia.org/w/api.php"


def fetch_wiki_events(place: str) -> list[tuple]:
    """Fetch key historical events for a place from Wikipedia + LLM."""
    # Try Wikipedia extract first
    params = {
        "action": "query",
        "format": "json",
        "titles": place,
        "prop": "extracts",
        "exintro": True,
        "explaintext": True,
    }
    wiki_text = ""
    try:
        resp = requests.get(
            WIKI_URL, params=params, timeout=15, headers={"User-Agent": "GraphVoice/1.0"}
        )
        pages = resp.json()["query"]["pages"]
        for p in pages.values():
            wiki_text = p.get("extract", "")[:2000]
    except:
        pass

    # LLM generates events (with or without wiki context)
    context = f"Wikipedia summary: {wiki_text[:1500]}" if wiki_text else ""
    prompt = (
        f"List 10-15 historically significant events that happened in/at {place}. "
        f"Include events from 1900-2024. {context}\n"
        "Return ONLY a JSON array: [{'event':'event name','year':YYYY}]. "
        "No markdown, no other text."
    )

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=800,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]

    events = []
    try:
        data = json.loads(raw)
        for item in data:
            yr = item.get("year", 0)
            ev = item.get("event", "")
            if yr and ev:
                events.append((f"[PLACE:{place}] {ev}", yr))
    except json.JSONDecodeError:
        pass

    return events


def main():
    # Get 10 random places with few events
    places = Neo4jClient.execute(
        "MATCH (p:Entity {type: 'place'}) OPTIONAL MATCH (p)-[:IN_EVENT]->(ev:Event) "
        "RETURN p.name AS name, count(ev) AS events ORDER BY events ASC LIMIT 40"
    )

    # Weight towards places with fewer events, random selection
    weighted = [p["name"] for p in places for _ in range(max(1, 5 - p["events"]))]
    selected = random.sample(weighted, min(10, len(weighted)))

    print(f"Selected {len(selected)} places for enrichment:\n")
    for s in selected:
        print(f"  - {s}")

    builder = StoryGraphBuilder("World Facts 1924-2024")
    for y in range(1920, 2030, 10):
        builder.add_phase(f"{y}s", f"{y}s")

    total = 0
    for place in selected:
        print(f"\n  {place}...", end=" ", flush=True)
        t0 = time.time()
        events = fetch_wiki_events(place)
        for label, year in events:
            builder.add_event(label, "", year, str(year))
            builder.in_phase(label, f"{year // 10 * 10}s")
            builder.participate(place, label, "地点")
        total += len(events)
        print(f"{len(events)} events ({time.time() - t0:.0f}s)")
        builder.build()
        time.sleep(0.5)

    print(f"\n{'=' * 50}")
    print(f"  Added {total} events to {len(selected)} places")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
