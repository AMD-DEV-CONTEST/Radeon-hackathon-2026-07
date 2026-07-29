"""Answer reflection / critique loop for higher-quality private responses."""

from __future__ import annotations

from src.llm.backend import LLMBackend


REFLECT_PROMPT = """You are a strict quality reviewer for a private enterprise assistant.
Given the user question, evidence, and draft answer, return JSON only:
{"final":"improved answer","ok":true|false,"issues":["..."]}
Rules: keep factual grounding; prefer Chinese if user used Chinese; remove invented policies.
"""


def reflect_and_refine(
    llm: LLMBackend,
    question: str,
    evidence: str,
    draft: str,
) -> str:
    messages = [
        {"role": "system", "content": REFLECT_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\nEvidence:\n{evidence[:3000]}\n\nDraft:\n{draft}\n"
                'Return {"final":"..."}.'
            ),
        },
    ]
    raw = llm.chat(messages, max_tokens=512)
    from src.agent.tools import extract_json_action

    action = extract_json_action(raw) or {}
    if "final" in action and str(action["final"]).strip():
        return str(action["final"]).strip()
    return draft
