# E5–E8 evidence correction — 2026-08-05

This append-only notice corrects the commit binding of
`../20260805T000000Z/manifest.json`; it does not rewrite or delete the earlier
packet.

The earlier packet declares `fc32868` as the exact clean source while the packet
itself, its public-export regression test, and the live route-decision export
fix first coexist at `5c227d6`. Therefore its integrated-product and test-count
claims cannot be reproduced from the commit it names.

Until a replacement packet is captured from the final clean integration head:

- treat the earlier packet as historical diagnostic material;
- do not use it as exact-commit evidence or as an A0 baseline;
- keep W7900 execution explicitly `NOT_RUN`;
- do not infer device, model, latency, throughput, VRAM, or seven-fixture
  results from local scripted tests.

The replacement packet is intentionally deferred until the current fixes have
an exact commit. Recording an uncommitted tree as a clean baseline would repeat
the same evidence error this notice corrects.
