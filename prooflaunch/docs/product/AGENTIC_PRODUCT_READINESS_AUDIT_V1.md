# Agentic product readiness audit V1

ProofLaunch uses the 12-point production definition as a release audit, not a
feature checklist. Every item is compiled from a concrete file, locator and
SHA-256. A local regression pass cannot convert missing production evidence
into a pass.

## Current decision

`local_governed_demo_ready_enterprise_production_not_ready`

| ID | Control | Status | Current boundary |
|---|---|---|---|
| PR-01 | Typical context utilization | Pass | 24 observed local calls: median 2.80%, p95 2.91% of 32,768 tokens |
| PR-02 | Externalized state | Pass | SQLite, CAS, events and approvals recover after restart |
| PR-03 | Long-session compaction | Pass | 24 frozen 60-message cases preserve critical state and exclude archived canaries |
| PR-04 | Human approval | Pass | Content-bound release gate with named actor and reason |
| PR-05 | Code-enforced permission | Pass | Tenant principal scopes runs, artifacts, memory, cache, jobs and events |
| PR-06 | Tool sandbox | Pass | Reviewed Docker adapter observed with no network, read-only root, non-root identity, resource limits, escape denial and boundary-only secret injection |
| PR-07 | Durable execution | Pass | Lease reclaim, stale-worker rejection and restart resume are tested |
| PR-08 | Structured validation | Pass | Schema and content-hash drift fail before release |
| PR-09 | Traffic guardrails | Gap | 250-case synthetic gate and content-free HTTP telemetry pass; deployed hit/false-block/escape rates remain unobserved |
| PR-10 | Failure-mode eval coverage | Pass | Five named failure modes, at least 152 synthetic representative cases each |
| PR-11 | Human-calibrated judges | Gap | 100 digest-pinned local predictions, a blinded 100-case/300-label queue, and a token-bound browser labeling console are sealed; real human label count remains 0 and no TPR/TNR receipt exists |
| PR-12 | CI and trace retention | Gap | Full CI plus local 90-day content-free request tracing are executable; protected remote check and deployed 100% coverage remain unobserved |

Compile and verify:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/compile_agentic_product_readiness_audit.py
PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_agentic_product_readiness
```

The resulting receipt is
`evidence/v10/agentic-product-readiness-audit.json`. It proves nine
repository-level controls and identifies three gaps. It does not prove 4A
preference, Top-1 standing, Radeon execution, publication, causal lift,
revenue, enterprise isolation or production readiness.
