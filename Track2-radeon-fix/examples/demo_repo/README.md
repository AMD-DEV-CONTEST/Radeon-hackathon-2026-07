# Radeon Code Agent self-contained demo

This tiny repository is intentionally self-contained so the Track 2 video
does not depend on a SWE-bench image or an external package registry.

Issue: `clamp` should preserve the lower bound when the upper bound is below
it. The current implementation returns the upper bound in that case.

Run the public check with:

```bash
python3 -m pytest -q
```
