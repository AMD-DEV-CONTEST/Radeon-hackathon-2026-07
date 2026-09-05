# ADR 0010: Treat managed AMD ROCm deployments as a removable local control plane

- Status: accepted
- Date: 2026-07-28
- Extends: [ADR 0007](0007-remote-integrations-remain-adapters.md)
- Relates to: [ADR 0006](0006-bounded-sqlite-application-state.md),
  [ADR 0008](0008-canonical-llm-conversation-boundary.md), and
  [ADR 0009](0009-official-paddle-native-local-ocr.md)

## Context

The Windows Xenix desktop needs a guided way to deploy a fixed, verified Chat,
Embedding, and OCR profile on a compatible Radeon Linux host reached through
Private SSH. The remote execution target must not
become a product backend, an inference gateway, a second settings authority, or
an extension of the batch SSH worker pool in ADR 0005.

The capability must also be removable after release without making ordinary
startup, local persistence, existing providers, Knowledge, OCR, diagnostics, or
packaging depend on AMD code.

## Decision

Introduce an optional AMD composition slice headed by
`AmdAiDeploymentService`. It is a forward-only control plane, not a data-plane
adapter or settings owner.

- Desktop SQLite owns installation identity, immutable placement, desired
  presence, component-generation lifecycle, and bounded installation
  attestations. A placement change creates a new installation.
- A versioned manifest owns exact runtime, model, protocol, self-test,
  capacity, compatibility, and artifact descriptors. There is no model chooser,
  ambient plugin discovery, or automatic CPU/placement/external-API fallback.
- The declared artifact source, revision, byte size, and SHA-256 own artifact
  identity. An explicitly coded transport mirror may be tried only to obtain
  those same bytes; it never changes the declared source or revision, and a
  size-and-hash failure rejects the artifact rather than falling back to a
  different version, model, or provider.
- The composed product placement is Private SSH: Windows Xenix remains the
  application and settings authority, while a Linux Radeon execution session
  owns only target files, processes, loopback forwards, live bindings, health,
  and runtime incarnations. Those facts are memory-only and never appear in
  provider settings or SQLite lifecycle rows. Experimental same-host Linux
  placement code is not a current desktop product entry or acceptance claim.
  Its controller remains composed only as the cleanup owner for historical
  `local_linux` generations; new Local installation intent is rejected.
- LLM, Embedding, and OCR settings owners independently own their
  generation-specific managed provider projections and selections. Deployment
  requests registration through capability-owned ports; it never writes another
  domain's settings or changes a selection.
- One explicit guided Install command validates the endpoint and identity-file
  fields, performs read-only server-host-key discovery, and pauses for the user
  to confirm the exact algorithm and SHA-256 fingerprint. Cancel or discovery
  failure performs no durable write and starts no authenticated target command.
  Acceptance binds the displayed fingerprint to the exact public key passed into
  the existing immutable enrollment, installation-intent, and forward-reconcile
  sequence. There is no separate target editor or Save action.
- Private SSH is limited to OpenSSH public-key authentication, an explicit
  identity-file handle, and an isolated pinned server-host-key record. First-use
  discovery is an explicit trust-on-first-use decision, not proof of server
  identity: the dialog instructs the user to compare the fingerprint with the
  server/cloud owner. Silent acceptance, password authentication, global SSH
  config or agent fallback, and changed-host-key continuation are unsupported.
  Private-key bytes never enter Xenix state.
- The guided command first commits one SQLite target/installation transaction,
  then SettingsStore security handles, through monotonic checkpoints. SQLite
  therefore exposes the exact hidden command identity after a process stop
  between authorities. A reopened dialog rediscovers it; an exact retry
  continues the unfinished security/reconcile work. Conflicting immutable
  identities fail typed. Partially completed checkpoints are not compensated or
  rolled back.
- Each runtime incarnation receives a fresh protected secret by a restricted
  launch handoff. A service that cannot reject unauthenticated loopback requests
  is not admitted.
- Long-running deployment exposes a session-local, closed-vocabulary activity
  stream. The control plane and placement emit only semantic milestones for
  target inspection, component preparation, runtime start, self-test, and
  provider registration. Qt adds monotonic ordering, elapsed duration, and
  bounded heartbeats. Progress is never lifecycle authority and carries no
  endpoint, credential, key, target output, path, token, process, port, or
  exception detail.
- Reconcile, repair, upgrade, restart, and retirement move only toward the
  currently desired state. There is no rollback journal, aggregate `READY`, or
  replay of a failed user operation. A new generation registers a new provider
  identity and never redirects an old generation.
- Remove first commits durable desired absence. That short transaction is the
  linearization point: an in-flight materialization observes a transient
  cancellation signal, does not publish new runtime bindings or provider
  projections after retirement wins, and then continues through ordinary
  forward retirement. Normal reconcile and repair never issue that signal.
- A placement may stop an unfinished provisioning recipe only under an explicit
  committed retirement request and its exact target-side process/receipt fence.
  It preserves a stopped provisioning receipt until identity-matched retirement
  cleanup succeeds; partial acquisition is not a rollback target. The immediate
  Remove acknowledgement therefore means `retiring requested`, not that an
  unverified remote path has already been deleted.
- The explicit target-side retirement operation first records an exact
  generation retirement tombstone under that generation's control fence. Recipe
  execution, target-asset transfer, and runtime start reject that tombstone;
  cleanup removes it only with the matching target, installation, generation,
  and manifest fence.
- Build inclusion and retirement-only admission are composition concerns at the
  app/package boundary. They may omit AMD code from a later package or reject new
  deployment while retaining cleanup ownership, but they never alter generic
  capability semantics or authorize deletion of an unverified target path.

AMD code is an explicit, removable composition slice. Generic services do not
import it. If the slice is absent, historical managed references remain typed
`provider_implementation_unavailable` projections, released SQLite migrations
remain readable inert history, and no selection or fallback is rewritten. A
released removal first retires all installations and removes owner projections;
a later release may delete the slice and its bounded composition anchors.

## Consequences

- ADR 0005 and `services/ml` remain batch-worker behavior; they are neither a
  supervisor nor a configuration dependency for AMD deployments.
- Runtime packages such as ROCm, vLLM, and RapidOCR are target artifacts, not
  base desktop dependencies.
- Invalid or incomplete user input fails before host-key discovery. A cancelled
  or failed trust challenge produces no durable write or authenticated target
  command. A later target-connectivity or compatibility failure retains exact
  enrollment/installation checkpoints so Repair or Remove can continue forward.
  Target-observation failures have their own typed status channel and never
  masquerade as measured profile incompatibility.
- Private SSH is the current product path and is not called offline. There is no
  Linux desktop distribution or native Windows ROCm claim.
- Removing AMD code is a controlled feature cut-off, not a migration rollback.
