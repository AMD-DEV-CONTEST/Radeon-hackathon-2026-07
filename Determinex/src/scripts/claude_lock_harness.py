import argparse
import re
from pathlib import Path

# To be used later when connecting to actual API
# import litellm

CORPUS_LOCKED_DIR = Path("corpus/programbench/locked")


def extract_keywords(text: str) -> set:
    """Extract simple alphanumeric lowercase keywords from text."""
    words = re.findall(r"\b[a-z0-9_]+\b", text.lower())
    # Exclude basic stop words
    stop_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "is",
        "it",
        "this",
        "that",
        "with",
    }
    return set(words) - stop_words


def load_locked_lessons() -> dict:
    """Load all lessons.md from the locked tools corpus."""
    lessons = {}
    if not CORPUS_LOCKED_DIR.exists():
        return lessons

    for tool_dir in CORPUS_LOCKED_DIR.iterdir():
        if not tool_dir.is_dir():
            continue
        lesson_file = tool_dir / "lessons.md"
        if lesson_file.exists():
            with open(lesson_file, encoding="utf-8") as f:
                lessons[tool_dir.name] = f.read()
    return lessons


def find_relevant_lessons(target_failure_description: str, lessons: dict, top_n: int = 3) -> list:
    """Find the top_n most relevant lessons based on simple keyword intersection."""
    target_keywords = extract_keywords(target_failure_description)

    scores = []
    for tool_name, lesson_content in lessons.items():
        lesson_keywords = extract_keywords(lesson_content)
        # Jaccard-ish similarity
        intersection = len(target_keywords.intersection(lesson_keywords))
        scores.append((intersection, tool_name, lesson_content))

    # Sort by highest intersection
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[:top_n]


def build_claude_prompt(target_tool: str, failure_desc: str, relevant_lessons: list) -> str:
    """Construct the few-shot prompt for Claude."""
    prompt = f"You are an expert systems engineer tasked with unlocking the tool '{target_tool}' in ProgramBench.\n"
    prompt += (
        f"The tool is currently failing with the following issue/assertion:\n{failure_desc}\n\n"
    )

    if relevant_lessons and relevant_lessons[0][0] > 0:
        prompt += "To assist you, here are the lessons learned from similar tools that we have successfully locked at 100%:\n"
        prompt += "-" * 80 + "\n"
        for score, tool_name, content in relevant_lessons:
            prompt += f"### Lessons from previously locked tool: {tool_name}\n"
            prompt += f"{content}\n"
            prompt += "-" * 80 + "\n"

    prompt += "\nBased on the above context, please provide the necessary code patch or structural fix to resolve the failure in the target tool."
    return prompt


def main():
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Determinex Claude API Harness for ProgramBench Tools"
    )
    parser.add_argument(
        "--tool", type=str, required=True, help="The name of the unlocked target tool"
    )
    parser.add_argument(
        "--failure", type=str, required=True, help="Description of the test failure or assertion"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the generated prompt without calling the API"
    )
    args = parser.parse_args()

    lessons = load_locked_lessons()
    print(f"[+] Loaded {len(lessons)} locked lessons from {CORPUS_LOCKED_DIR}")

    relevant = find_relevant_lessons(args.failure, lessons)
    prompt = build_claude_prompt(args.tool, args.failure, relevant)

    if args.dry_run:
        print("\n[!] DRY RUN: Generated Prompt Payload\n")
        print(prompt)
    else:
        # TODO: Integrate with LiteLLM/Claude API endpoint
        print("[!] API execution not yet wired. Use --dry-run to view prompt.")


if __name__ == "__main__":
    main()
