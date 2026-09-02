"""
Multi-step task planning layer (AMD Track 2 capability #2).

Given a raw scan request for a token, `TaskPlanner.plan()` decides which of
the 7 CIA tools to invoke, in what order, and with what arguments — before
any tool actually runs. This is deliberately a visible, inspectable planning
step (not hidden inside a ReAct loop) so a reviewer can see exactly why the
agent chose the module sequence it did for a given input.

Planning rules (mirrors how the production engine already treats missing
modules — see rugbuster-scoring-engine/rugbuster_scoring_engine/engine.py
`_avax_confidence`, which counts available modules to derive a confidence
level rather than assuming every payload is complete):

  1. Contract-only checks run first: contract_backdoor and holder_concentration
     need only the contract address and are the cheapest calls (one eth_getCode,
     one holder-list page). Running them first means a CRITICAL backdoor or
     concentration finding is available even if later steps fail or the caller
     only supplied a contract address.
  2. tx_entropy and holder_cluster_age run next — still contract-only, but each
     needs its own transfer/holder-list fetch so they're ordered after the
     single-call checks.
  3. deployment_latency runs only if deploy_timestamp is known.
  4. funding_origin runs only if deployer_address is known.
  5. wash_pattern runs last and only if BOTH deployer_address and
     deploy_timestamp are known, since it is a cross-signal check (dev-sell
     timing + deployer history) that depends on the outputs of steps 3-4
     being meaningful.

Any module whose required inputs are missing is skipped rather than run with
guessed defaults — this is surfaced back to the caller as `skipped_modules`
so the confidence level downstream (in orchestrator.py) reflects it, the same
way the production engine reports `missing_modules`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ScanRequest:
    chain: str
    contract_address: str
    deployer_address: Optional[str] = None
    deploy_timestamp: Optional[int] = None


@dataclass
class PlanStep:
    tool_name: str
    args: dict[str, Any]
    rationale: str


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    skipped_modules: list[dict[str, str]] = field(default_factory=list)


class TaskPlanner:
    """Deterministic, explainable planner. See module docstring for the rules."""

    def plan(self, request: ScanRequest) -> Plan:
        plan = Plan()
        base = {"chain": request.chain, "contract_address": request.contract_address}

        plan.steps.append(
            PlanStep(
                "contract_backdoor",
                dict(base),
                "Contract-only, single bytecode fetch — run first to surface critical backdoor risk early.",
            )
        )
        plan.steps.append(
            PlanStep(
                "holder_concentration",
                dict(base),
                "Contract-only, single holder-list fetch — cheap early CRITICAL-risk signal.",
            )
        )
        plan.steps.append(
            PlanStep("tx_entropy", dict(base), "Contract-only; needs a transfer-list fetch.")
        )
        plan.steps.append(
            PlanStep("holder_cluster_age", dict(base), "Contract-only; needs a holder-list fetch.")
        )

        if request.deploy_timestamp is not None:
            plan.steps.append(
                PlanStep(
                    "deployment_latency",
                    {**base, "deploy_timestamp": request.deploy_timestamp},
                    "deploy_timestamp supplied — can measure sniper latency.",
                )
            )
        else:
            plan.skipped_modules.append(
                {"module": "deployment_latency", "reason": "deploy_timestamp not provided"}
            )

        if request.deployer_address:
            plan.steps.append(
                PlanStep(
                    "funding_origin",
                    {"chain": request.chain, "deployer_address": request.deployer_address, "depth": 3},
                    "deployer_address supplied — can trace funding chain.",
                )
            )
        else:
            plan.skipped_modules.append(
                {"module": "funding_origin", "reason": "deployer_address not provided"}
            )

        if request.deployer_address and request.deploy_timestamp is not None:
            plan.steps.append(
                PlanStep(
                    "wash_pattern",
                    {
                        **base,
                        "deployer_address": request.deployer_address,
                        "deploy_timestamp": request.deploy_timestamp,
                    },
                    "Both deployer_address and deploy_timestamp available — cross-signal "
                    "wash-trading check runs last, after the signals it correlates with.",
                )
            )
        else:
            plan.skipped_modules.append(
                {"module": "wash_pattern", "reason": "requires both deployer_address and deploy_timestamp"}
            )

        return plan
