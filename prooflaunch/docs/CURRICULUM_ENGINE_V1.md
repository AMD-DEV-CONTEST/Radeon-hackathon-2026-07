# Curriculum Engine V1

Curriculum Engine V1 closes the four remaining mechanical requirements in
Workstream 12 without claiming trained-model uplift.

Critic-collusion prevention requires at least two blinded verifiers with
different principals and model/checkpoint lineages, different prompt hashes,
and independent tool replay. The producer principal or exact producer
checkpoint cannot judge its own output. Duplicate critics, shared prompt
lineage, unblinded candidate identity, or missing replay block the receipt.

Effectiveness is measured as a matched comparison. Failure-driven and static
arms must use the same task, environment revision, task seed, and checkpoint.
The report exposes task-success difference, verifier-score difference, mean
step difference, discordant wins/losses, and safety regressions. Promotion also
requires observed model inference, external held-out tasks, at least 100 pairs,
positive task and verifier effects, and no safety regression.

The included 24-pair receipt is a project-owned controlled non-model fixture.
It verifies arithmetic, pairing, static-control wiring, and fail-closed report
generation only. `promotion_eligible=false` is intentional; the observed
mechanical difference is not presented as curriculum or model improvement.

```bash
PYTHONPATH=src python scripts/build_v10_curriculum_evaluation.py
PYTHONPATH=src python -m unittest -v tests.test_v10_curriculum_evaluation
```

The frozen report is `evidence/v10/curriculum-evolution-report.json`.
