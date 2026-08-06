#!/usr/bin/env python3
"""
Warden — Export Attack Sample Outputs & Defensive Comparison.

Extracts representative attack samples across all 13 OWASP LLM families,
runs them through Warden's orchestrator, and generates a structured
JSON audit report in `benchmarks/results/attack_payload_samples.json`.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "benchmarks" / "results"
MANIFEST_PATH = REPO_ROOT / "attack_samples_v2" / "manifest.jsonl"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from warden.config import WardenConfig
from warden.cli import create_router
from warden.memory.audit_log import AuditLog
from warden.guards.policy import PolicyEngine
from warden.guards.diff_guard import DiffGuard
from warden.camel.interpreter import CaMeLInterpreter
from warden.orchestrator import WardenOrchestrator

def main():
    print("========================================================================")
    print("  EXPORTING REPRESENTATIVE ATTACK SAMPLES & DEFENSIVE COMPARISON        ")
    print("========================================================================")

    config = WardenConfig.from_env()
    router_obj = create_router(config)
    audit = AuditLog("warden_audit.db")
    audit.initialize()
    policy = PolicyEngine("policies/default.yaml")
    policy.load()
    diff_guard = DiffGuard()
    camel = CaMeLInterpreter(llm=router_obj.tier2, policy=policy)
    orchestrator = WardenOrchestrator(
        router=router_obj, camel=camel, diff_guard=diff_guard,
        policy=policy, audit=audit
    )

    family_samples = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    fam = data.get("family", "unknown")
                    if fam not in family_samples:
                        family_samples[fam] = data

    report_items = []
    for fam, sample in family_samples.items():
        raw_text = sample.get("prompt", "") or sample.get("text", "")
        expected = sample.get("expected", "block")

        res = orchestrator.guard_input(raw_text, source="user_input")

        without_warden = {
            "llm_status": "EXPOSED — Prompt processed by generative LLM",
            "vulnerability_risk": f"LLM processes raw '{fam}' prompt at 280W GPU TDP",
            "early_exit_blocked": False
        }

        with_warden = {
            "decision": res.decision.value.upper() if hasattr(res.decision, "value") else str(res.decision).upper(),
            "action": res.action,
            "explanation": res.explanation,
            "is_safe": res.is_safe,
            "early_exit_blocked": not res.is_safe
        }

        report_items.append({
            "sample_id": sample.get("id", f"sample_{fam}"),
            "family": fam,
            "raw_input_prompt": raw_text[:200] + ("..." if len(raw_text) > 200 else ""),
            "expected_action": expected,
            "without_warden_impact": without_warden,
            "with_warden_defense": with_warden
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "attack_payload_samples.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"total_families_evaluated": len(report_items), "attack_samples": report_items}, f, indent=2)

    print(f"Successfully generated attack audit report with {len(report_items)} family samples!")
    print(f"Saved to: {out_file}")

if __name__ == "__main__":
    main()
