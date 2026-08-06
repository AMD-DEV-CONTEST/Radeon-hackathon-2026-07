"""Test structurization with LLM-generated biographies of real people.

Uses Qwen to produce Wikipedia-style summaries from training data,
then runs the text→graph→text validation pipeline.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from memory.evaluator import compute_loss, identify_failure_modes, print_report, summarize_results
from memory.story_graph import clear_story_data
from memory.structurizer import build_graph, regenerate_narrative, structurize_text


def generate_bio(person: str, lang: str = "zh", length: int = 600) -> str:
    """Ask LLM to generate a Wikipedia-style short biography from its knowledge."""
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    prompt = f"""Write a Wikipedia-style biography of {person} in {lang == "zh" and "Chinese" or "English"}.
Include: birth/death dates, key life events, major achievements, personal struggles, and legacy.
Write in a factual, encyclopedic tone. Keep under {length} words."""

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=1200,
    )
    return resp.choices[0].message.content.strip()


def run_pipeline(name: str, bio_text: str) -> dict:
    clear_story_data()
    print(f"  [1/4] Structurizing ({len(bio_text)} chars)...")
    t0 = time.time()
    data = structurize_text(bio_text)
    print(
        f"    Entities: {len(data.get('entities', []))}, Events: {len(data.get('events', []))}, "
        f"Phases: {len(data.get('phases', []))}, Time: {time.time() - t0:.1f}s"
    )

    build_graph(data).build()

    print("  [3/4] Regenerating...")
    t0 = time.time()
    regenerated = regenerate_narrative(data, lang="Chinese")
    print(f"    Length: {len(regenerated)} chars, Time: {time.time() - t0:.1f}s")

    metrics = compute_loss(bio_text, regenerated)
    metrics["name"] = name
    metrics["original_length"] = len(bio_text)
    metrics["regenerated_length"] = len(regenerated)
    metrics["entity_count"] = len(data.get("entities", []))
    metrics["event_count"] = len(data.get("events", []))
    return metrics


def main():
    # Well-known people across domains
    people = [
        ("Marie Curie (居里夫人)", "Marie Curie"),
        ("Frida Kahlo", "Frida Kahlo"),
        ("Alan Turing (图灵)", "Alan Turing"),
    ]

    results = []
    for name, person in people:
        print(f"\n{'─' * 50}")
        print(f"  Processing: {name}")

        # Generate biography from LLM knowledge
        print("  Generating bio...")
        t0 = time.time()
        bio_text = generate_bio(person)
        print(f"    Generated: {len(bio_text)} chars in {time.time() - t0:.1f}s")

        try:
            metrics = run_pipeline(name, bio_text)
            results.append(metrics)
            print_report(metrics, name)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback

            traceback.print_exc()

    if results:
        summary = summarize_results(results)
        modes = identify_failure_modes(results)
        print("=" * 60)
        print("  OVERALL SUMMARY (Real People)")
        print("=" * 60)
        print(f"  Tests:             {summary['test_count']}")
        print(f"  Avg Bigram:        {summary['avg_entity_overlap']:.1%}")
        print(f"  Avg LLM Score:     {summary['avg_llm_score']:.1f}/10")
        print(f"  Score Range:       {summary['min_score']:.1f}–{summary['max_score']:.1f}")
        print("  Failure Modes:")
        for m in modes:
            print(f"    • {m}")
        print("=" * 60)

        for r in results:
            print(
                f"    {r['name']:20s}  bigram={r['entity_preservation']:.2f}  "
                f"llm={r.get('llm_score', 0):.1f}/10  e={r['entity_count']} ev={r['event_count']}"
            )

        # Save
        out = Path(__file__).parent / "real_validation_results.json"
        import json

        out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n  Results: {out}")


if __name__ == "__main__":
    main()
