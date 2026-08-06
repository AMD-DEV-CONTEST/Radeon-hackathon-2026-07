# Contributing to ProofLaunch

ProofLaunch accepts focused contributions that preserve its evidence-first,
human-release design. This repository is also an AMD Track 1 competition
package, so changes to claims, models, media, or Radeon evidence receive extra
review.

## Before opening a pull request

1. Open or link an issue that states the user problem and affected surface.
2. Keep the change small enough to review independently.
3. Add or update tests for every behavior change.
4. Do not add credentials, customer data, private review assignments, model
   weights, or media without redistribution rights.
5. Update evidence receipts only from the command that produced them. Never
   hand-edit a passing receipt.

## Local verification

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/validate_amd_track1_package.py
```

For web changes:

```bash
cd web
npm ci
npm run build
```

## Pull request requirements

Every pull request must identify:

- the problem and intended outcome;
- the exact test commands and results;
- claim or evidence changes;
- new dependencies, licenses, models, datasets, or media;
- security, privacy, GPU-memory, and compatibility impact;
- screenshots or recordings for user-visible changes.

At least one maintainer approval is required. Changes to release gates,
security boundaries, model supply-chain locks, rights records, or competition
claims require the code owner and may not be self-approved.

## Review priorities

Reviewers evaluate correctness first, then evidence integrity, security and
tenant isolation, rights provenance, reproducibility, Radeon portability,
performance, accessibility, and visual quality. A polished output cannot
override a failed truth or release gate.

See [GOVERNANCE.md](GOVERNANCE.md) and the pull request template for the full
merge policy.
