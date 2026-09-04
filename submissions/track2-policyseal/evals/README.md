# Evaluations

`goldens/` is the independent P0 acceptance bundle. It contains 30 end-to-end
scenarios, 60 semantic snippets, 20 evidence-retrieval questions, and six
three-turn Review Copilot dialogues. Expected answers were authored separately
from parsers, policy evaluation, and application output.

Validate the frozen counts, source hashes, controlled enums, rule/evidence
references, and synthetic-data guardrails with:

```bash
make validate-evals
```

Changing these files after the Phase 1 gate requires explicit Golden review and
a dedicated commit. Application code must never rewrite expected answers.
