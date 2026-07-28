"""
Automated authorizer implementation for non-interactive execution.
Evaluates tool execution requests deterministically against a PolicySpec without human intervention.
"""

from aetheris_cli.policy.authorizer import Authorizer, Decision, DecisionOutcome, ToolRequest
from aetheris_cli.policy.spec import PolicySpec, is_risky_bash_command


class AutomatedAuthorizer(Authorizer):
    def __init__(self, spec: PolicySpec):
        self.spec = spec

    def decide(self, request: ToolRequest) -> Decision:
        tool = request.tool.lower().strip()

        if self.spec.plan_only:
            return Decision(
                outcome=DecisionOutcome.DENY,
                reason="Execution blocked because --plan-only flag is active",
                is_automated=True,
            )

        if tool == "bash":
            if not self.spec.allow_bash:
                return Decision(
                    outcome=DecisionOutcome.DENY,
                    reason="Bash tool execution requires explicit --allow-bash flag",
                    is_automated=True,
                )
            
            if is_risky_bash_command(request.content):
                if not self.spec.allow_risky_bash:
                    return Decision(
                        outcome=DecisionOutcome.DENY,
                        reason=f"Risky bash command detected. Requires explicit --allow-bash=risky flag. Command: {request.content!r}",
                        is_automated=True,
                    )

            return Decision(
                outcome=DecisionOutcome.ALLOW,
                reason="Bash tool approved by --allow-bash policy",
                is_automated=True,
            )

        if tool in self.spec.allowed_tools:
            return Decision(
                outcome=DecisionOutcome.ALLOW,
                reason=f"Tool '{tool}' approved by explicit --allow policy",
                is_automated=True,
            )

        return Decision(
            outcome=DecisionOutcome.DENY,
            reason=f"Tool '{tool}' is not in the declared allowlist (--allow {tool})",
            is_automated=True,
        )
