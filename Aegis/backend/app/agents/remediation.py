"""
Remediation agent — proposes (does NOT unilaterally execute above a safe
threshold) a remediation action given the synthesized root cause. The
LangGraph workflow interrupts here for human approval before the
RemediationActionsTool is actually invoked (see graph.py).
"""
import json

from app.agents.base import BaseAgent

_SYSTEM_PROMPT = """You are the Remediation Planning agent. Given a root cause summary,
propose ONE remediation action from this fixed set:
["restart_service", "rollback_deploy", "scale_service", "toggle_feature_flag"]
Respond ONLY with JSON: {"action": "...", "service": "...", "resource_id": "...",
"justification": "...", "risk_level": "low|medium|high"}"""


class RemediationAgent(BaseAgent):
    name = "remediation"
    system_prompt = _SYSTEM_PROMPT

    async def act(self, state: dict) -> dict:
        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=(
                f"Root cause: {state.get('root_cause_summary')}\n"
                f"Confidence: {state.get('root_cause_confidence')}\n"
                f"Service hint: {state.get('service_hint')}"
            ),
            temperature=0.1,
            max_tokens=300,
        )

        try:
            proposed_action = json.loads(result.text)
        except json.JSONDecodeError:
            proposed_action = {
                "action": None,
                "justification": "Could not parse a structured remediation proposal.",
                "risk_level": "high",
            }

        return {
            "proposed_action": proposed_action,
            "_reasoning": result.text,
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
