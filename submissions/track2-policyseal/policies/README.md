# Policies

`v1/` contains PolicySeal's read-only synthetic competition policy. Machine
rules live in `policy.yaml`; reviewer-facing explanations live under
`evidence/`. They are intentionally separate so retrieval text can explain a
decision without becoming an authorization mechanism.

Validate and fingerprint a pack with:

```bash
.venv/bin/python -m policyseal.policy.loader policies/v1
```

The hash covers canonical rule data and every evidence file. These fixtures are
not legal advice, a compliance standard, or an activated enterprise policy.
