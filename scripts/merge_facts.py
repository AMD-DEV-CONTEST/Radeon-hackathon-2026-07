"""Merge fine-grained facts into existing fact graph without clearing.
Handles parse failures, content filters, and rate limits.
Target: 500+ total events from 31 high-signal years + 11 decades.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import BadRequestError, OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.story_graph import StoryGraphBuilder

YEARS = [
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

client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)


def fetch(year):
    try:
        resp = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"List 15-20 historically significant events of {year}. "
                        "Include specific dates. Cover politics, science, culture, sports, disasters. "
                        "Use Chinese for descriptions. Return ONLY a JSON array: "
                        "[{'label':'event name','year':"
                        + str(year)
                        + ",'description':'Chinese desc','category':'politics|science|culture|economy|disaster|sports','location':'city/country'}]"
                    ),
                }
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
        return json.loads(raw)
    except BadRequestError as e:
        if "inappropriate" in str(e):
            print("blocked")
            return []
        raise
    except json.JSONDecodeError:
        # Try smaller prompt
        resp2 = client.chat.completions.create(
            model=QWEN_LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": f"List 10 historical events of {year}. Return JSON array. Use Chinese.",
                }
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw2 = resp2.choices[0].message.content.strip()
        if raw2.startswith("```"):
            raw2 = raw2.split("\n", 1)[1].rsplit("\n", 1)[0]
        try:
            return json.loads(raw2)
        except:
            return []


def main():
    builder = StoryGraphBuilder("World Facts 1924-2024")

    # Ensure decades exist
    for d in range(1920, 2030, 10):
        builder.add_phase(f"{d}s", f"{d}s")

    total = 0
    for year in YEARS:
        print(f"  {year}...", end=" ", flush=True)
        events = fetch(year)
        for ev in events:
            label = f"{year}-{ev.get('label', '?')}"  # year prefix ensures uniqueness
            desc = ev.get("description", "")
            loc = ev.get("location", "")
            dec = f"{year // 10 * 10}s"
            builder.add_event(label, desc, year, str(year))
            builder.in_phase(label, dec)
            if loc:
                builder.add_entity(loc, "place", label)
                builder.participate(loc, label, "地点")
        total += len(events)
        cats = {}
        for e in events:
            cats[e.get("category", "?")] = cats.get(e.get("category", "?"), 0) + 1
        print(f"{len(events)} events")
        time.sleep(0.6)

    builder.build()
    print(f"\n  Done: {total}+ events ingested (MERGE avoids duplicates)")
    print('  Query years: curl http://localhost:8080/api/ask -d \'{"query":"1969年发生了什么"}\'')


if __name__ == "__main__":
    main()
