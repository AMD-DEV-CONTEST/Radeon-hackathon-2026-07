"""Evaluate structurization quality: compare original vs regenerated text."""

import difflib

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL


def compute_loss(original: str, regenerated: str) -> dict:
    """Compute quality metrics between original and regenerated text.

    Returns dict with:
      - text_similarity: 0-1 ratio
      - entity_preservation: rough entity overlap
      - llm_score: 1-10 LLM-based quality score
      - llm_feedback: qualitative analysis
    """

    # 1. Text similarity
    similarity = round(difflib.SequenceMatcher(None, original, regenerated).ratio(), 3)

    # 2. Entity overlap (fuzzy - Chinese n-gram overlap)
    entity_preservation = _fuzzy_entity_overlap(original, regenerated)

    # 3. LLM quality score (1-10) + feedback combined
    score, feedback = _llm_quality_score(original, regenerated)

    return {
        "text_similarity": similarity,
        "entity_preservation": entity_preservation,
        "llm_score": score,
        "llm_feedback": feedback,
    }


def _fuzzy_entity_overlap(a: str, b: str) -> float:
    """Fuzzy entity overlap using Chinese character bigrams."""

    def bigrams(s):
        return set(
            s[i : i + 2]
            for i in range(len(s) - 1)
            if "\u4e00" <= s[i] <= "\u9fff" and "\u4e00" <= s[i + 1] <= "\u9fff"
        )

    ba, bb = bigrams(a), bigrams(b)
    if not ba:
        return 1.0
    return round(len(ba & bb) / len(ba), 3)


def _llm_quality_score(original: str, regenerated: str) -> tuple[float, str]:
    """LLM rates quality from 1-10 and provides feedback."""
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return 0.0, ""

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    prompt = f"""Rate the quality of a regenerated biography on a scale of 1-10.
The regenerated text was produced from a structured graph extracted from the original.
Score based on: narrative coherence, emotional preservation, thematic fidelity, key events retained.

First give the score as "SCORE: X.X", then 2-3 bullet points in Chinese explaining the score.

## Original
{original[:2000]}

## Regenerated
{regenerated[:2000]}"""

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=400,
    )
    text = resp.choices[0].message.content.strip()

    # Extract score
    score = 0.0
    import re as _re

    m = _re.search(r"SCORE:\s*([\d.]+)", text)
    if m:
        score = float(m.group(1))
    # Remove score line from feedback
    feedback = _re.sub(r"SCORE:\s*[\d.]+\s*", "", text).strip()

    return score, feedback


def _llm_compare(original: str, regenerated: str) -> str:
    """Use LLM to qualitatively compare original and regenerated."""
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    prompt = f"""Compare these two biographies. Identify what was PRESERVED and what was LOST.

## Original
{original[:2000]}

## Regenerated (from graph)
{regenerated[:2000]}

Answer in 3-5 bullet points in Chinese. Focus on:
1. What narrative elements were preserved (emotion, causality, theme)?
2. What was lost or oversimplified?
3. What improvement would most increase the quality?"""

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=400,
    )
    return resp.choices[0].message.content.strip()


def print_report(metrics: dict, title: str = ""):
    """Print a readable quality report."""
    print(f"\n{'=' * 60}")
    print(f"  Quality Report: {title}")
    print(f"{'=' * 60}")
    print(f"  Text Similarity:  {metrics['text_similarity']:.1%}")
    print(f"  Entity Overlap:   {metrics['entity_preservation']:.1%}")
    if metrics.get("llm_score", 0) > 0:
        print(f"  LLM Quality:      {metrics['llm_score']:.1f}/10")
    if metrics.get("llm_feedback"):
        print("\n  LLM Analysis:")
        for line in metrics["llm_feedback"].strip().split("\n"):
            print(f"    {line.strip()}")
    print(f"{'=' * 60}\n")


def summarize_results(all_results: list[dict]) -> dict:
    """Summarize results across multiple test cases."""
    if not all_results:
        return {}

    sims = [r["text_similarity"] for r in all_results]
    ents = [r["entity_preservation"] for r in all_results]
    scores = [r.get("llm_score", 0) for r in all_results]

    return {
        "avg_text_similarity": round(sum(sims) / len(sims), 3),
        "avg_entity_overlap": round(sum(ents) / len(ents), 3),
        "avg_llm_score": round(sum(scores) / len(scores), 1) if any(scores) else 0,
        "test_count": len(all_results),
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
    }


def identify_failure_modes(all_results: list[dict]) -> list[str]:
    """Analyze failure patterns across test cases."""
    modes = []

    avg_ent = (
        sum(r["entity_preservation"] for r in all_results) / len(all_results) if all_results else 0
    )
    if avg_ent < 0.5:
        modes.append(
            "ENTITY_LOSS: Bigram overlap low → extraction may use different phrasing than original. Check LLM prompt to use exact entity names from source text."
        )

    avg_score = (
        sum(r.get("llm_score", 0) for r in all_results) / len(all_results) if all_results else 0
    )
    if avg_score < 5:
        modes.append(
            f"QUALITY_LOW: Average LLM score {avg_score:.1f}/10 → regeneration missing key narrative elements"
        )

    for r in all_results:
        fb = r.get("llm_feedback", "")
        if "情感" in fb or "emotion" in fb.lower():
            modes.append(
                "EMOTIONAL_FLATNESS: Emotional nuance lost in structurization → add 'emotional_weight' to events or 'feeling' entities"
            )
            break

    return modes or ["PASS: No significant failure modes detected"]
