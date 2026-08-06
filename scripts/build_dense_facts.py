"""Dense fact graph generator v2 — batched per decade for reliable JSON.

Each decade gets 2-3 batches of 25-40 events, split by category.
Uses shorter prompts and English queries for China to avoid content filters.
Target: 2000+ events total (1000 China + 1000 global).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.story_graph import StoryGraphBuilder

client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

DECADES = [
    (1920, "1920s"),
    (1930, "1930s"),
    (1940, "1940s"),
    (1950, "1950s"),
    (1960, "1960s"),
    (1970, "1970s"),
    (1980, "1980s"),
    (1990, "1990s"),
    (2000, "2000s"),
    (2010, "2010s"),
    (2020, "2020s"),
]

# Batch strategy: split each decade into category groups
BATCHES = [
    (
        "politics and wars",
        "政治与战争: major political events, wars, treaties, diplomatic milestones",
    ),
    (
        "science and tech",
        "科技: scientific discoveries, inventions, space missions, medical breakthroughs",
    ),
    (
        "culture and society",
        "文化社会: films, music, literature, art, social movements, sports, disasters",
    ),
]


def fetch_batch(
    scope: str, decade_label: str, decade_start: int, category: str, desc: str
) -> list[dict]:
    """Fetch 25-40 events for one batch."""
    scope_name = "China" if scope == "china" else "Global (including China)"

    prompt = (
        f"List 25-40 notable {desc} events in {scope_name} during the {decade_label} "
        f"({decade_start}-{decade_start + 9}).\n"
        "Return ONLY a JSON array. No markdown. Each object:\n"
        '{"year":YYYY,"label":"event name","cat":"category"}\n\n'
        "Use short English labels for event names."
    )

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=1200,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("\n", 1)[0]

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        # Try to extract JSON array
        import re

        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except:
                pass
    return []


def main():
    builder = StoryGraphBuilder("World Facts 1924-2024")
    for _, label in DECADES:
        builder.add_phase(label, f"{label}年代")

    stats = {"china": 0, "global": 0}

    for decade_start, label in DECADES:
        decade_total = 0
        for cat_key, cat_desc in BATCHES:
            # Skip China politics for sensitive decades
            if cat_key == "politics and wars" and decade_start >= 1960:
                print(f"  {label} 中国 {cat_key}... SKIP (sensitive decade)")
                continue

            # China politics: skip sensitive decades to avoid content filters
            if cat_key == "politics and wars" and decade_start >= 1960:
                print(f"  {label} 中国 politics: SKIP (sensitive)")
            else:
                print(f"  {label} 中国 {cat_key}...", end=" ", flush=True)
                t0 = time.time()
                events = fetch_batch("china", label, decade_start, cat_key, cat_desc)
                for ev in events:
                    ev_label = f"[CN:{decade_start}] {ev['label']}"
                    builder.add_event(
                        ev_label, "", ev.get("year", decade_start + 5), str(ev.get("year", ""))
                    )
                    builder.in_phase(ev_label, label)
                stats["china"] += len(events)
                decade_total += len(events)
                print(f"{len(events)} ({time.time() - t0:.0f}s)")

            print(f"  {label} 全球 {cat_key}...", end=" ", flush=True)
            t0 = time.time()
            events = fetch_batch("global", label, decade_start, cat_key, cat_desc)
            for ev in events:
                ev_label = f"[GL:{decade_start}] {ev['label']}"
                builder.add_event(
                    ev_label, "", ev.get("year", decade_start + 5), str(ev.get("year", ""))
                )
                builder.in_phase(ev_label, label)
            stats["global"] += len(events)
            decade_total += len(events)
            print(f"{len(events)} ({time.time() - t0:.0f}s)")

        builder.build()
        print(f"    Decade total: {decade_total} | Running: {sum(stats.values())}")

    print(f"\n{'=' * 50}")
    print(f"  China:  {stats['china']} events")
    print(f"  Global: {stats['global']} events")
    print(f"  Total:  {sum(stats.values())} events")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
