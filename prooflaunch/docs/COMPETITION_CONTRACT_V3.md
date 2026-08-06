# Competition Contract V3

Competition Contract V3 converts the first fifty source-ordered requirements
into fail-closed, machine-tested submission gates. It does not turn local file
presence into evidence of registration, Radeon execution, a demo recording, a
repository fork, or a pull request.

## Frozen official inputs

- ModelScope event 299 detail response: content SHA-256
  `ae96835c2edd086af3714268bab8316ac437768ea0f6e75edf65eb795e4ddaa0`.
- Official AMD contest repository README: commit
  `d95240359c837717230b36bdab12df94f1669cf6`, content SHA-256
  `ee89881dc921ed85d350f62b8671d4d6712499084dc872f9ef51a95c1d8f12bd`.
- Submission deadline: `2026-08-06T23:59:00+08:00`.

The source revision and hashes are deliberate: the official repository changed
after the earlier local rules audit. Any later change must trigger a fresh
source reconciliation instead of silently inheriting this contract.

## Readiness boundaries

The internal scorecard implements the four published dimensions with exact
maxima of 40, 20, 20, and 20. A local readiness score requires observed,
hash-addressed evidence for every credited dimension. Proxy or missing evidence
receives zero. The 95-point threshold is a project release threshold, not an
official judging result.

Submission readiness is the conjunction of two independent groups:

1. eligibility: Luma approval, AMD membership, team size, and an observed key
   inference on Radeon/ROCm;
2. materials and external actions: source, English README, PDF, actual-operation
   video, poster/PPT, official fork, and official pull request.

At the time of the mechanical receipt, the locally present source, README, PDF,
and poster are true. The remaining external or runtime observations are false,
so submission readiness is false.

## Comparison and claim discipline

Top-3 comparisons require immutable revisions, approved licenses, executable
same-hardware runs, overlapping task scope, and a declared time budget. Blind
review uses anonymous content hashes, seeded order, raw counts, and a Wilson
lower bound. Features outside the shared task intersection are labeled
non-comparable. Leadership language is blocked unless the comparison passed and
an independent approval plus evidence locator exist.

The nine-item full Campaign Pack and six-item realtime pack are exact ordered
contracts. A 3840×2160 output may be described as a 4K master; native 4K
generation is never claimed unless it was actually observed.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python scripts/build_v10_competition_contract.py
PYTHONPATH=src .venv/bin/python -m unittest tests.test_v10_competition_contract -v
```

Machine-readable contract:
`config/cortex_x_v10_competition_contract_v3.json`.

Mechanical receipt:
`evidence/v10/competition-contract-v3-mechanical-fixture.json`.
