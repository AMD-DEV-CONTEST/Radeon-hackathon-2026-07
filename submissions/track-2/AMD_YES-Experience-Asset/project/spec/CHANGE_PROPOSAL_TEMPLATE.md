# Quality or Benchmark Change Proposal

Use this template when evidence suggests a component needs a more suitable
metric, measurement method or optimization direction. Submit it before the new
Candidate is used for a promotion decision.

```markdown
# Change proposal: <short name>

- Date / author:
- Affected component and stage:
- Related AC IDs / L1 milestone / L2 gate:
- Current version and definition:
- Proposed version and definition:
- Business reason and observed bottleneck:
- Public baseline evidence:
- Primary metric and supporting metrics:
- Quality, privacy, state and local-inference floors that cannot regress:
- Frozen comparison fields:
- Expected side effects and trade-offs:
- Rollback profile:
- Compatibility or historical-report treatment:
- Effective only for runs after approval timestamp: yes/no
- Quality-owner decision: pending / approved / rejected
```

The proposal must not quote, describe or reverse-engineer a private blind-test
case, score, threshold, weight, seed, gold output or aggregation rule. Approval
changes future evaluation only; it never rewrites historical results.
