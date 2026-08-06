# ADR 0009: Deliver local OCR as a verified native Paddle bundle

- Status: accepted
- Date: 2026-07-22
- Relates to: [ADR 0003](0003-filesystem-for-datasets-models-results.md),
  [ADR 0006](0006-bounded-sqlite-application-state.md), and
  [ADR 0007](0007-remote-integrations-remain-adapters.md)

## Context

Installing Python, pip, PaddlePaddle, and PaddleOCR on a user's machine made local
OCR depend on runtime package resolution and library-selected global model caches.
The app could consequently report a private runtime as ready without owning or
verifying every model file it used. Knowledge import needs an offline-capable,
repairable component with one clear deployment identity and no application-state
authority.

## Decision

Build an Xenix-owned Windows x64 OCR worker from the official PaddleOCR general-OCR
pipeline and official Paddle Inference C++ runtime. Deliver the worker, its native
dependency closure, and the default model pack as one optional immutable archive.
Runtime and model-pack identities remain distinct even when one archive carries
both.

The desktop client downloads only the artifact named by its embedded catalog,
verifies the archive and every manifested member, self-tests the staged generation,
and atomically activates it under the Xenix runtime home. It never resolves Python
packages or downloads Paddle/model dependencies from upstream at install time.

One spawned Knowledge import worker owns one native OCR child and reuses its
initialized model for all OCR-routed pages in that attempt. The child returns only
engine-neutral text regions and has no SQLite, Artifact, canonical-content, index,
or release authority.

## Consequences

- “One-click setup” means one downloaded unpack-and-run archive, not one physical
  executable; the official Windows runtime requires colocated DLLs and model files.
- The OCR cache is rebuildable. Readiness requires the exact catalog, runtime,
  model-pack, member-manifest, and protocol identities, not mere file presence.
- A release includes the OCR bundle as a typed immutable release artifact;
  the app installer itself does not embed the large runtime.
- The unreleased Python sidecar has no migration or compatibility path.
- This decision admits general text detection and recognition only. Structured
  document understanding, PP-StructureV3, VLM, and multimodal embeddings require
  separate product decisions.
