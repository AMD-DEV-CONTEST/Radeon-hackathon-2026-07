# E1-B CI metadata recovery

The first post-fix GitHub run `30200347339` passed its source/static/public QA
steps but failed the required PR metadata step with:

```text
FAIL AC-22: no non-empty public evidence item
```

Cause: the PR used the visually valid Markdown form
`**Test/fixture result:**`, while the public checker requires an unformatted
`Test/fixture result:` label followed directly by a non-empty value.

Recovery: PR #8 now uses the parser-compatible label, reports 89/89 Vitest,
links the exact `c3318db` implementation and `c025e0d` evidence commits, and
maps all three owner review constraints. The live PR body passes
`qa/scripts/check_pr_metadata.py` locally. This packet commit triggers the new
GitHub synchronize run; owner acceptance remains pending.
