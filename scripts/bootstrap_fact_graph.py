"""Bootstrap the world fact graph (1924-2024).

Uses LLM to generate key world events by decade, then ingests into Neo4j
using the same story graph schema (Entity + Event + Phase).

After bootstrapping, the fact graph serves as a shared ground-truth
that can be cross-referenced against users' personal narratives.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.story_graph import StoryGraphBuilder, clear_story_data

DECADES = [
    (1920, 1929, "1920s"),
    (1930, 1939, "1930s"),
    (1940, 1949, "1940s"),
    (1950, 1959, "1950s"),
    (1960, 1969, "1960s"),
    (1970, 1979, "1970s"),
    (1980, 1989, "1980s"),
    (1990, 1999, "1990s"),
    (2000, 2009, "2000s"),
    (2010, 2019, "2010s"),
    (2020, 2024, "2020s"),
]


FACT_EXTRACTION_PROMPT = """Generate the most important world events for the {decade} ({start}-{end}).

Include across these categories:
- Politics & Wars (e.g., WWII, Cold War, decolonization, treaties)
- Science & Technology (e.g., moon landing, internet, DNA discovery, vaccines)
- Culture & Society (e.g., civil rights movements, major films/music, social changes)
- Economy (e.g., Great Depression, oil crisis, financial crashes, globalization)
- Disasters & Environment (e.g., Chernobyl, tsunamis, climate agreements)

Return a JSON object with "events" array. Each event has:
- "label": short name (Chinese or English)
- "year": integer year
- "description": 1-2 sentences in Chinese
- "category": one of [politics, science, culture, economy, disaster]
- "location": where it happened (city or country)

IMPORTANT:
- Generate exactly 8-12 events per decade
- Cover diverse categories
- Use Chinese for descriptions
- Events must be historically accurate and verifiable
- Return ONLY the JSON array, no markdown

Format:
{{"events": [{{"label": "二战爆发", "year": 1939, "description": "...", "category": "politics", "location": "欧洲"}}]}}"""


def fetch_decade_events(decade_label, start, end):
    """Fetch key events for a decade from LLM."""
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    prompt = FACT_EXTRACTION_PROMPT.format(decade=decade_label, start=start, end=end)

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
    )

    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(raw).get("events", [])


def build_fact_graph(all_events):
    """Build the fact graph from all decade events."""
    builder = StoryGraphBuilder("World Facts 1924-2024")

    # Create decade phases
    for _, _, label in DECADES:
        builder.add_phase(label, f"{label}年代的重大事件")

    # Track unique locations
    locations = set()

    for event in all_events:
        # Each event becomes an Event node
        builder.add_event(
            label=event["label"],
            description=event["description"],
            order=event["year"],
            time_period=str(event["year"]),
        )

        # Assign to decade phase
        decade = f"{event['year'] // 10 * 10}s"
        builder.in_phase(event["label"], decade)

        # Track location as entity
        loc = event.get("location", "")
        if loc and loc not in locations:
            locations.add(loc)
            builder.add_entity(loc, "place", event["label"])

        # Link location to event
        if loc:
            builder.participate(loc, event["label"], "地点")

        # Create category entity
        cat = event.get("category", "")
        if cat:
            cat_name = {
                "politics": "政治与战争",
                "science": "科学与技术",
                "culture": "文化与社会",
                "economy": "经济",
                "disaster": "灾难与环境",
            }.get(cat, cat)
            builder.add_entity(cat_name, "concept", event["category"])
            builder.participate(cat_name, event["label"], "类别")

    # Create causal links for closely related events
    sorted_events = sorted(all_events, key=lambda e: e["year"])
    for i in range(len(sorted_events)):
        for j in range(i + 1, min(i + 4, len(sorted_events))):
            a, b = sorted_events[i], sorted_events[j]
            # Same category, within 3 years → likely related
            if a["category"] == b["category"] and b["year"] - a["year"] <= 3:
                builder.causes(a["label"], b["label"], f"同属{a['category']}类别，时间相近")

    builder.build()
    return builder


def main():
    print("=" * 60)
    print("  Bootstrapping World Fact Graph (1924-2024)")
    print("=" * 60)

    all_events = []
    for start, end, label in DECADES:
        print(f"\n  Fetching {label} ({start}-{end})...")
        t0 = time.time()
        events = fetch_decade_events(label, start, end)
        all_events.extend(events)
        print(f"    Got {len(events)} events ({time.time() - t0:.0f}s)")
        time.sleep(1)  # Rate limit

    print(f"\n  Total: {len(all_events)} events across 11 decades")

    clear_story_data()
    build_fact_graph(all_events)

    print("\n  Fact graph built!")
    print(f"  Events: {len(all_events)}")
    print("  Categories: politics, science, culture, economy, disaster")
    print(
        "  Query example: python -c \"from agents.tools.cypher_templates import execute_safe_query; events = execute_safe_query('GET_PHASE_EVENTS', {'phase_name': '1960s'}); [print(e['event'], e['time_period']) for e in events]\""
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
