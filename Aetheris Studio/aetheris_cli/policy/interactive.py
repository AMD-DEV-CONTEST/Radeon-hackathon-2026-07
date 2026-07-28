"""
Interactive authorizer implementation for terminal chat sessions.
Prompts the human operator for confirmation when a destructive or gated tool execution is requested.
"""

import sys
from aetheris_cli.policy.authorizer import Authorizer, Decision, DecisionOutcome, ToolRequest


class InteractiveAuthorizer(Authorizer):
    def decide(self, request: ToolRequest) -> Decision:
        sys.stdout.write(f"\n  [confirm gate required] Tool: {request.tool}\n")
        if request.content:
            sys.stdout.write(f"  Content preview:\n{request.content[:1000]}\n")
            if len(request.content) > 1000:
                sys.stdout.write("  ... (truncated preview)\n")
        
        try:
            sys.stdout.write("  Approve tool execution? [y/N]: ")
            sys.stdout.flush()
            answer = sys.stdin.readline().strip().lower()
            if answer in ("y", "yes"):
                return Decision(
                    outcome=DecisionOutcome.ALLOW,
                    reason="Approved interactively by operator",
                    is_automated=False,
                )
            else:
                return Decision(
                    outcome=DecisionOutcome.DENY,
                    reason="Declined interactively by operator",
                    is_automated=False,
                )
        except (KeyboardInterrupt, EOFError):
            return Decision(
                outcome=DecisionOutcome.DENY,
                reason="Cancelled by operator interrupt",
                is_automated=False,
            )
