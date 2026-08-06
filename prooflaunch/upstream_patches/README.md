# Upstream patches

This directory is the only permitted home for project-owned modifications to a
frozen upstream. An empty registry is intentional: no patch has been applied in
the current evidence state.

Every future patch entry must bind:

- upstream project ID and immutable 40-character revision;
- SHA-256 of the patch bytes;
- the upstream issue or pull-request URL that explains provenance;
- a concrete reason the adapter/wrapper path is insufficient;
- named regression tests and a migration rollback revision.

A patch is not admitted merely because its file exists. It must pass
`PatchRecord`, the registered regression tests, the replacement migration
parity test, the source-license gate, and a pinned-revision Radeon smoke. AMD or
ROCm compatibility fixes should be proposed upstream before they are treated as
a long-lived local delta.

