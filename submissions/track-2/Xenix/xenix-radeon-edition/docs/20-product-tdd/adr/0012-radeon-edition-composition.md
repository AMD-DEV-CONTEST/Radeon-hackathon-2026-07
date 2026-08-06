# ADR 0012: Make Radeon deployment native to the Radeon Edition

- Status: accepted
- Date: 2026-08-03
- Supersedes: the optional-package and retirement-only build-mode portions of
  [ADR 0010](0010-managed-amd-rocm-deployments.md)
- Relates to: [ADR 0007](0007-remote-integrations-remain-adapters.md),
  [ADR 0008](0008-canonical-llm-conversation-boundary.md),
  [ADR 0009](0009-official-paddle-native-local-ocr.md), and
  [ADR 0011](0011-kserve-page-ocr-provider-boundary.md)

## Context

This repository is the Radeon Edition, not a generic Xenix package with an AMD
feature gate. The prior optional-slice and retirement-only build modes made the
application topology depend on environment and packaging state. They also made
historical cleanup a global mode, even though only an individual historical
installation needs restricted treatment.

At the same time, Chat, Embedding, and OCR must remain capability-owned. A
managed Radeon deployment may register their provider projections, but it must
never select them or leak AMD-specific runtime concepts into generic settings,
inference, Knowledge import, or worker code.

## Decision

- The application composition root always constructs the Radeon control plane
  and provides an AMD-owned Settings contribution. Packaging always includes the
  same runtime resources and imports; there is no AMD enable, build, or
  retirement-only switch.
- Settings owns a small contribution protocol. The AMD contribution renders a
  Radeon runtime card and opens the long-running guided deployment dialog. The
  generic Settings dialog never imports AMD.
- The managed deployment keeps its existing provider-projection authority, while
  LLM, Embedding, and OCR settings remain the only selection authorities. OCR
  receives the same explicit provider selector as the other capability settings.
- A deployment change only requests a managed-provider refresh. Settings applies
  that refresh on the next explicit close-and-reopen, preserving unsaved LLM and
  Embedding drafts in the current dialog.
- Current Private SSH records remain deployable. Any other durable non-removed
  record is projected as historical and exposes only safe Remove behavior. This
  record-scoped rule replaces a process-wide retirement-only mode.

## Consequences

- A corrupt or missing Radeon runtime is a Radeon Edition startup/packaging
  fault, not a silently disabled capability.
- The user sees Radeon setup beside AI provider settings, then explicitly selects
  Chat, Embedding, and OCR providers through their ordinary settings surfaces.
- Future removal of this edition's Radeon capability is a deliberate source and
  product-boundary change, not an environment-variable behavior. It never grants
  cleanup authority over unknown targets.
- ADR 0010 remains authoritative for the fixed profile, SSH trust, forward
  reconciliation, exact cleanup, and provider-projection lifecycle.
