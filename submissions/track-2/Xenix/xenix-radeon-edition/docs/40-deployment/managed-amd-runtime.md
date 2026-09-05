# Managed Radeon Capability Deployments

Use this route to deploy, repair, inspect, or retire one Radeon Chat (LLM),
Embedding, or OCR capability. The Radeon Edition is a Windows-desktop control
plane, not a hosted Xenix backend, an ML Worker target, or an offline mode.

## Edition, capability, and placement boundary

Radeon support is native to this edition in source and packaged runs. It has no
build feature flag, runtime feature flag, runtime hook, optional package mode,
or retirement-only mode. Packaging always includes the Radeon control plane,
guided UI, manifests, and resources; see
[Packaging](packaging.md#radeon-edition-capability-deployments).

Chat, Embedding, and OCR are separate lifecycle units. Each has a fixed
capability deployment adapter and manifest-verified option catalog; the adapters share
AmdAiDeploymentService only as a lifecycle coordinator. A successful
deployment registers only its own immutable managed provider projection. The
LLM, Embedding, and OCR settings owners remain the sole provider-selection
authorities.

Only these placements accept new deployment intent:

- private_ssh is a user-confirmed Linux Radeon SSH server.
- local_wsl is an explicitly selected existing WSL2 distribution on the Windows
  desktop.

They are execution locations, not provider types. The historical local_linux
same-host controller is retained only to inspect and safely clean up historical
records; it cannot receive a new deployment, repair, or resume command. Legacy
combined-profile records remain readable retirement history and are never split
automatically into three capability records.

## Safe installation

Start from the Radeon deployment control in the relevant capability's Settings
block, not from ML Worker settings.

### Private SSH

Enter host, user, port, and the local identity-file path. Xenix discovers the
server public key and displays its endpoint, algorithm, and SHA-256 fingerprint
for the user to compare with the server or cloud owner. There is no
server-public-key form field. Cancel, failed discovery, or closing the
confirmation saves no trust decision and starts no authenticated target command.

Xenix prefers a scanner-only public-key probe. If a managed-cloud SSH front
door filters that probe, it falls back to one unauthenticated OpenSSH handshake
with a fresh temporary `known_hosts` file. That file is discarded before the
confirmation dialog is shown; the fallback does not reuse user configuration,
credentials, agent state, global host keys, or a target runtime command.

After explicit confirmation, Xenix pins the exact discovered public key, saves
the immutable enrollment, and starts the selected capability option's fixed profile.
A later key mismatch fails closed; it is never silently replaced. Password
authentication, global SSH configuration or agent fallback, and changed-key
continuation are unsupported. Private-key bytes never enter Xenix state.

The enrolled target remains available for a later capability even after every
deployment using it has been removed. Choose that existing target rather than
creating a second identity for the same managed remote root; Xenix will not let
another target ID take over an already fenced root.

### Local WSL

Choose one discovered WSL2 distribution explicitly. A default-distribution
change cannot redirect an existing deployment. Local WSL has no SSH host,
identity-file, server-key, or host-key confirmation step. The workflow does not
install WSL, a distribution, a driver, or an SSH daemon, and it does not claim
native Windows ROCm.

Preflight must still prove the selected distribution's manifest compatibility,
per-capability capacity, Radeon/ROCm availability, Windows-to-WSL loopback,
protocol behavior, and self-test before provider registration. This runbook
does not claim that a local WSL Radeon target has been physically verified.

### Common admission and activity

Neither placement creates a host, tunes GPU/cache/forward ports, or falls back
to CPU, ML Worker, or an API. Chat may select only a packaged, revision-pinned,
license-reviewed model option admitted for that placement. It cannot accept an
arbitrary model ID, artifact path, runtime command, or launch argument. Input
failures start no worker. Connectivity, compatibility, and component failures retain typed,
stable support outcomes; measured incompatibility is not inferred from a
connection failure.

One Chat model is one installation, component generation, vLLM process, and
managed provider. Different exact Chat component digests may coexist at one
execution location when a fresh observed-capacity check admits them; an exact
duplicate is rejected. No existing process is stopped, resized, replaced, or
evicted to make room. Qwen3.5 9B and Qwen3.5 4B are admitted only for the exact
verified Private SSH cell; they remain absent from Local WSL choices pending
physical acceptance.

The guided dialog keeps a bounded semantic activity log for the active
capability. It distinguishes trust or local inspection, installation
checkpoints, Radeon/ROCm preflight, component preparation, runtime startup,
self-test, and provider registration. Long steps add elapsed-time heartbeats.
The log is not lifecycle authority and must not contain fabricated percentage
progress, raw SSH/package/model output, endpoints, credentials, paths, tokens,
ports, PIDs, or exception messages.

## Provider availability and Settings drafts

Deployment owns a managed provider projection but not a selection. When
availability changes, it requests a provider-list refresh only. Settings applies
that refresh on the next explicit close and reopen; it never reloads or
overwrites an open LLM, Embedding, or OCR draft. The user explicitly selects
and saves a managed provider in the ordinary capability Settings surface.

Installation/generation lifecycle and desired presence are local durable facts.
Target processes, files, loopback forwards, live URLs, ports, bearer secrets,
and health are session-local facts. Do not copy them into Settings, diagnostics,
or support tickets.

Every use of a Private SSH binding re-proves its exact remote process receipt.
A transient SSH connection or timeout denies that operation but does not by
itself prove that the remote identity or an otherwise live local forward has
changed. Xenix retains the realization for a later read-only identity probe; it
returns the binding only after that probe proves the same receipt. A proven
process/receipt mismatch still closes and forgets the forward.

## Retirement, inventory, and no rollback

**Remove** first persists only a durable retirement request for that capability
deployment. Its acknowledgement does not mean that a target process, target
path, WSL distribution, or remote server has been physically cleaned. The
coordinator later performs physical cleanup according to current inventory and
only when it can prove the exact identity and control fence.

Reconcile, Repair, and retirement are forward-only. There is no rollback
journal, aggregate ready state, compensating rewrite, or replay of a failed
user operation. A new capability generation has a new provider identity and
does not redirect an earlier provider. An in-flight materialization cannot
publish a binding or projection after the persisted retirement request wins.

Removing one LLM follows the same exact-installation retirement path and cannot
remove another model's provider, process, or files. Removal remains blocked while
that exact managed provider is selected for any LLM-owned role.

If materialization failed before the capability owner received a managed
provider projection, retirement treats that exact projection as already absent
and continues to identity-fenced physical cleanup. If the projection exists,
the capability Settings owner remains authoritative and may block removal while
selected.

Identity-fenced retirement may record a generation tombstone before it stops
provisioning, transfer, or runtime start. Partial acquisition remains until
inventory-backed cleanup can prove ownership; it is not a rollback target.
Neither deleting source nor changing a package authorizes deletion of an
unknown target path or termination of an unknown process.

## Evidence and support

The UI displays a localized explanation and a stable support code. Safe guided
logs include only the operation, capability, execution-location kind, derived
condition/phase, checkpoint flags, semantic activity milestone, optional input
field name, stable error code, and exceptional-path exception class. They do
not include host, user, port, identity path, public key or fingerprint, SSH
output, request representation, or exception message.

Collect only a redacted installation ID, capability, generation/manifest
digest, execution-location kind, phase, typed failure code, inventory state,
and local log or diagnostic-bundle references. Never include private keys, host
keys, bearer secrets, live endpoint URLs, ports, PIDs, raw model paths, or
provider document payloads.
