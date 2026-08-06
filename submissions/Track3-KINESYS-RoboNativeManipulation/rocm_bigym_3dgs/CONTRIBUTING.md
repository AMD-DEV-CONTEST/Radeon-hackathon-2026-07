# Contributing

1. Work on a focused branch and keep unrelated local changes out of the diff.
2. Do not commit gated data, PLYs, checkpoints, demonstrations, real UUIDs,
   credentials or private infrastructure addresses.
3. Run `make verify` and `make smoke-reconstruction` before opening a PR.
4. Preserve fail-closed behavior: missing quality, reward, render or provenance
   evidence must not be converted into success.
5. New visual claims need full-size rendered evidence, not only unit tests.

Code is accepted under Apache-2.0. Contributors remain responsible for the
licenses of any external data used in their own runs.
