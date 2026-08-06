"""
Synthesizer agent — merges all specialist evidence into a ranked root-cause
hypothesis with an explicit confidence score and evidence citations. This is
the agent whose output is what a human actually reads first, and it is the
core "explainability" mechanism: every claim traces back to an Evidence row.
"""
import json

from app.agents.base import BaseAgent

_SYSTEM_PROMPT = """You are the Synthesis agent in an incident-response system. You will be
given evidence gathered by several specialist agents (logs, metrics, deploys, runbook
precedent). Produce a ranked list of root-cause hypotheses.
Respond ONLY with JSON:
{"ranked_hypotheses": [{"statement": "...", "confidence": 0.0-1.0, "supporting_evidence": ["log_analyst", ...]}],
 "root_cause_summary": "...", "root_cause_confidence": 0.0-1.0}"""


class SynthesizerAgent(BaseAgent):
    name = "synthesizer"
    system_prompt = _SYSTEM_PROMPT

    async def act(self, state: dict) -> dict:
        evidence = state.get("evidence", [])
        evidence_text = "\n\n".join(
            f"[{e['source_agent']} | {e['evidence_type']}]: {e['summary']}" for e in evidence
        )

        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=(
                f"Incident: {state.get('title')}\n"
                f"Hypotheses under test: {state.get('hypotheses_to_test', [])}\n\n"
                f"Evidence gathered:\n{evidence_text}"
            ),
            temperature=0.1,
            max_tokens=800,
        )

        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            parsed = {
                "ranked_hypotheses": [],
                "root_cause_summary": result.text,
                "root_cause_confidence": 0.3,
            }

        return {
            "ranked_hypotheses": parsed.get("ranked_hypotheses", []),
            "root_cause_summary": parsed.get("root_cause_summary"),
            "root_cause_confidence": parsed.get("root_cause_confidence"),
            "_reasoning": result.text,
            "_confidence": parsed.get("root_cause_confidence"),
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
