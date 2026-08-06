"""Ultra-dense fact generator — pipe-delimited format for maximum throughput.

Generates 50-80 facts per year for China and Global in a single compact format.
Target: 100 facts/year × 100 years × 2 scopes = ~20,000 total facts.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.story_graph import StoryGraphBuilder

client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

# Generate 5-year windows for efficiency
YEARS = [(y, y + 4) for y in range(1920, 2025, 5)]


def fetch_window(scope: str, start: int, end: int) -> list[tuple]:
    """Fetch facts for a 5-year window. Returns list of (label, year, type)."""
    scope_name = "China" if scope == "china" else "Globally"
    prompt = (
        f"List 200 notable people, events, and places in {scope_name} from {start}-{end}.\n"
        "One per line. Format: name|type|year\n"
        "Types: person,event,place,discovery,film,book,treaty,battle\n"
        "No numbering, no markdown, just the list."
    )

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4000,
    )
    text = resp.choices[0].message.content.strip()

    results = []
    for line in text.split("\n"):
        line = line.strip()
        parts = line.split("|")
        if len(parts) >= 3 and parts[1].strip():
            try:
                year = int(parts[2].strip())
                if start <= year <= end + 1:
                    results.append((parts[0].strip(), year, parts[1].strip()))
            except ValueError:
                pass
    return results


def main():
    builder = StoryGraphBuilder("World Facts 1924-2024")
    for y in range(1920, 2030, 10):
        builder.add_phase(f"{y}s", f"{y}s")

    stats = {"china": 0, "global": 0}

    for start, end in YEARS:
        for scope in ["china", "global"]:
            prefix = "CN" if scope == "china" else "GL"
            print(f"  {start}-{end} {scope}...", end=" ", flush=True)
            t0 = time.time()
            facts = fetch_window(scope, start, end)

            for label, year, ftype in facts:
                ev_label = f"[{prefix}] {label}"
                builder.add_event(ev_label, f"{ftype}", year, str(year))
                builder.in_phase(ev_label, f"{year // 10 * 10}s")

            stats[scope] += len(facts)
            per_year = len(facts) / 5
            print(f"{len(facts)} facts ({per_year:.0f}/yr, {time.time() - t0:.0f}s)")

        total = sum(stats.values())
        print(f"    Window total: {total} | ~{total / (2024 - start) * 5:.0f}/yr")
        builder.build()
        time.sleep(1)

    print(f"\n{'=' * 50}")
    print(f"  China:  {stats['china']} facts")
    print(f"  Global: {stats['global']} facts")
    print(f"  Total:  {sum(stats.values())} facts")
    per_yr = sum(stats.values()) / 100
    print(f"  Avg:    {per_yr:.0f} facts/year")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
