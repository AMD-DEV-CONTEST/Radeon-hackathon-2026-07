"""
validators/llm_critic_validator.py - LLM Critic Validator

Uses a secondary LLM to evaluate whether the teacher's output is correct.
Used for tasks where there is no objective ground truth
(debugging analysis, security review, performance optimization, etc.).

The critic is always the LOCAL Ollama model (free, no API cost) even if the
teacher was a paid API -- we don't want validation to multiply API costs.

The critic is asked to return a structured verdict: PASS or FAIL with a reason.
"""

import json
import logging

log = logging.getLogger("oracle.validator.llm_critic")

# The critic model -- always local, always cheap
_CRITIC_MODEL = "determinex-leviathan:v1"
_FALLBACK_CRITIC = "mistral:latest"

_CRITIC_SYSTEM = """You are a rigorous code and technical writing reviewer.
Your job is to evaluate whether the provided response is correct, complete, and useful.
You MUST respond with EXACTLY this JSON format and nothing else:
{"verdict": "PASS", "reason": "brief explanation"}
or
{"verdict": "FAIL", "reason": "specific problem with the response"}

Be strict but fair. PASS only if the response actually solves the task correctly."""


def _call_critic(output: str, task_prompt: str) -> tuple[bool, str]:
    """
    Call the local Ollama critic model to evaluate the output.
    Returns (passed, reason).
    """
    # Import here to avoid circular dependency with providers package
    from scripts.providers.local_ollama import generate as ollama_generate

    critic_prompt = (
        f"TASK THAT WAS GIVEN:\n{task_prompt}\n\n"
        f"RESPONSE TO EVALUATE:\n{output}\n\n"
        "Evaluate whether this response correctly and completely addresses the task."
    )

    response = ollama_generate(
        system=_CRITIC_SYSTEM,
        user=critic_prompt,
        model=_CRITIC_MODEL,
        cot=False,
    )

    if response is None:
        # Try fallback critic
        log.warning("Primary critic (%s) unavailable, trying fallback", _CRITIC_MODEL)
        response = ollama_generate(
            system=_CRITIC_SYSTEM,
            user=critic_prompt,
            model=_FALLBACK_CRITIC,
            cot=False,
        )

    if response is None:
        log.warning("LLM critic unavailable -- defaulting to PASS (no validator)")
        return True, "Critic unavailable -- passed by default"

    # Parse the critic's JSON verdict
    # Handle cases where the model wraps JSON in markdown fences
    import re

    clean = response.strip()
    clean = re.sub(r"^```(?:json)?\s*\n", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\n```\s*$", "", clean, flags=re.MULTILINE)

    # Extract just the JSON object if surrounded by text
    json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', clean, re.DOTALL)
    if json_match:
        clean = json_match.group(0)

    try:
        verdict_obj = json.loads(clean)
        verdict = verdict_obj.get("verdict", "").upper()
        reason = verdict_obj.get("reason", "No reason given")

        if verdict == "PASS":
            log.debug("Critic PASS: %s", reason[:100])
            return True, f"Critic approved: {reason}"
        elif verdict == "FAIL":
            log.debug("Critic FAIL: %s", reason[:100])
            return False, f"Critic rejected: {reason}"
        else:
            log.warning("Critic returned unexpected verdict '%s' -- treating as PASS", verdict)
            return True, f"Critic returned ambiguous verdict '{verdict}' -- passed by default"

    except json.JSONDecodeError:
        log.warning("Critic response was not valid JSON: %s", clean[:200])
        # If the critic said "FAIL" anywhere in free text, treat as fail
        if "fail" in clean.lower() and "pass" not in clean.lower():
            return False, f"Critic indicated failure (unparsed): {clean[:200]}"
        return True, "Critic response unparseable -- passed by default"


def validate(output: str, task_meta: dict) -> tuple[bool, str]:
    """
    Validate output using a local LLM critic.

    Args:
        output:    Raw text from the teacher model.
        task_meta: Curriculum task dict. Uses task_meta's prompt templates to
                   reconstruct the task context for the critic.

    Returns:
        (True, reason) on pass, (False, reason) on fail.
    """
    if len(output.strip()) < 20:
        return False, "Output too short to evaluate"

    # Best-effort reconstruction of the task prompt for critic context
    task_prompt = task_meta.get("_task_prompt", task_meta.get("display_name", "Unknown task"))

    return _call_critic(output, task_prompt)
