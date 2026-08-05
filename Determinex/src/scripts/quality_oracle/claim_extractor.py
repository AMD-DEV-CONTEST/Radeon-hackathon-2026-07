"""claim_extractor.py — Extract verifiable factual claims from model responses.

Uses Claude structured output (tool_use) to decompose a response into discrete,
checkable assertions. Each claim is independently verifiable against a KB.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic

_CLIENT: anthropic.Anthropic | None = None


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _CLIENT


@dataclass
class Claim:
    text: str  # The claim as a standalone assertion
    claim_type: str  # "factual" | "procedural" | "causal" | "definitional"
    subject: str  # Main subject/entity being claimed about
    confidence: float = 1.0  # Extractor confidence (0-1)
    source_span: str = ""  # Verbatim text span the claim was extracted from


_EXTRACT_TOOL = {
    "name": "extract_claims",
    "description": "Extract all verifiable factual claims from the response",
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The claim as a standalone declarative sentence",
                        },
                        "claim_type": {
                            "type": "string",
                            "enum": ["factual", "procedural", "causal", "definitional"],
                        },
                        "subject": {
                            "type": "string",
                            "description": "Primary entity or concept this claim is about",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Extractor confidence 0.0-1.0",
                        },
                        "source_span": {
                            "type": "string",
                            "description": "Verbatim text this claim was extracted from (≤80 chars)",
                        },
                    },
                    "required": ["text", "claim_type", "subject", "confidence", "source_span"],
                },
            }
        },
        "required": ["claims"],
    },
}

_SYSTEM = """You are a claim extractor. Given a text response, identify every discrete verifiable claim it makes.

A claim is a statement that can be independently checked as true or false against a knowledge base. Extract:
- Factual claims: X is Y, X happened in Z, X has property Y
- Procedural claims: To do X you must Y, X works by doing Y
- Causal claims: X causes Y, X results in Z
- Definitional claims: X means Y, X is defined as Z

Do NOT extract:
- Opinions or value judgements ("this is better than")
- Tautologies or obvious truths
- Claims from the original question/context (only from the response)
- Hedged claims with "may", "might", "possibly" unless clearly asserting

Each claim should be atomic (one assertion) and self-contained (no pronouns without referent)."""


class ClaimExtractor:
    """Extract verifiable claims from model responses using Claude structured output."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def extract(self, response: str, task_context: str = "") -> list[Claim]:
        """Extract all verifiable claims from response.

        Args:
            response: The model response to analyze
            task_context: Optional context about what task the response is solving
                         (helps extractor understand domain)

        Returns:
            List of Claim objects
        """
        user_content = response.strip()
        if task_context:
            user_content = f"[Task context: {task_context[:500]}]\n\n[Response to analyze:]\n{response.strip()}"

        try:
            msg = _client().messages.create(
                model=self.model,
                max_tokens=2048,
                system=_SYSTEM,
                tools=[_EXTRACT_TOOL],
                tool_choice={"type": "tool", "name": "extract_claims"},
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:
            print(f"  [claim_extractor] API error: {e}")
            return []

        for block in msg.content:
            if block.type == "tool_use" and block.name == "extract_claims":
                raw = block.input.get("claims", [])
                claims = []
                for c in raw:
                    try:
                        claims.append(
                            Claim(
                                text=c["text"],
                                claim_type=c.get("claim_type", "factual"),
                                subject=c.get("subject", ""),
                                confidence=float(c.get("confidence", 1.0)),
                                source_span=c.get("source_span", "")[:80],
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                return claims

        return []

    def extract_code_claims(self, response: str, task_prompt: str = "") -> list[Claim]:
        """Specialized extraction for code-task responses.

        Focuses on behavioral claims: 'this function does X', 'the output is Y'.
        """
        context = (
            f"This is a code solution. Task: {task_prompt[:300]}"
            if task_prompt
            else "This is a code solution."
        )
        claims = self.extract(response, context)
        # Filter to claims relevant to code behavior
        return [c for c in claims if c.claim_type in ("factual", "procedural", "causal")]
