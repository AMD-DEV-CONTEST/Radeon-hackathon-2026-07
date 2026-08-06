# Local State Evolution

Application operators and storage developers use this runbook when startup migration or persisted-state recovery is involved.

## Runtime Contract

Xenix migrates known supported SQLite versions forward in place during startup. Source and migration tests own the current version and exact supported edges; do not copy those mechanical facts into documentation.

Automatic migration does not create a pre-migration backup and has no rollback path. Back up the active runtime state before a risky migration, release transition, manual repair, or destructive recovery. A migration failure can prevent startup and must not be hidden by accepting ambiguous data.

## Developer Contract

- Add a new forward edge; never rewrite an edge that may exist in a deployed database.
- Advance the source-owned current version only with the edge that reaches it.
- Prove both fresh bootstrap and upgrade from the prior supported state.
- Repair known bad app-owned values in a forward data migration. Do not weaken ORM reads to tolerate them indefinitely.
- Before raw SQL touches an enum-backed field, inspect the model's configured persisted representation and prove the migrated row loads through the current ORM.

The nearest `src/xenix/services/storage/AGENTS.md` owns migration-author tripwires. Migration functions, models, and tests own SQL, table/field shape, version values, and edge composition.

## Derived-State Reconciliation

Knowledge vector bytes are rebuildable projections; their SQLite generation rows
are the readiness authority. Vector maintenance is not a schema migration and does
not infer ownership from an arbitrary file name or recursively sweep Knowledge
storage. It serializes with vector build and search, accepts only strictly contained
generation paths, and removes only metadata-backed missing/corrupt projections,
manifest-proven metadata orphans, and stale vector-owned staging.

For a corrupt live projection, maintenance first atomically renames the contained
path into same-volume private trash, then removes its SQLite row, then attempts
physical deletion. Physical trash deletion is best effort. If Windows still holds
the live path and the rename cannot complete after bounded retries, the row remains;
maintenance must not report or manufacture a different readiness state. Source
snapshots, canonical content, non-vector staging, symlinks, and unknown sentinels are
outside this cleanup authority.

Import-owned source/canonical orphan reclamation is also not a schema migration. It
runs before the Import worker starts, takes its live references from SQLite, and
recognizes only the exact sharded CAS/staging layouts owned by the current content
store. It atomically detaches definite crash orphans to private same-volume trash;
unknown, corrupt, link-like, referenced, and out-of-root shapes remain untouched.
This authority is separate from vector reconciliation and never deletes vector
generations or arbitrary staging entries.

Knowledge document removal is a library-membership change, not startup recovery or
physical cleanup. One guarded SQLite transaction deactivates membership and is the
visibility cutover. Retrieval and corpus fingerprints admit active membership only;
index convergence follows through an independent corpus-change task. Import,
derivation, canonical, Artifact, and task-log lineage remains managed state and is
not synchronously dismantled. A future retention/reachability policy may reclaim
eligible app-owned payloads under its own authority. Re-importing the same
same-library SHA-256 reactivates the existing identity. The original user-selected
file remains outside every app cleanup root.

Observable Knowledge index tasks are SQLite business metadata, not Lance authority.
When their table is introduced, use a fixed forward migration and prove both the
prior supported fixture and fresh bootstrap. Queued/running rows recovered after an
application restart may be replayed by the single index coordinator; successful or
failed terminal rows remain bounded operational evidence. Readiness is still derived
from current Units, profile/corpus fingerprints, the accepted generation, and any
active task—never from a competing persisted `is_ready` flag.

## Failure and Recovery

Distinguish these cases before acting:

- **Unsupported version:** preserve the database, confirm that no supported edge applies, then restore a compatible backup or quarantine it and bootstrap fresh.
- **Corrupt database:** stop the app, back it up if readable, quarantine it, bootstrap fresh, and retain the quarantined file for analysis.
- **Migration failure:** preserve the original and logs; fix the forward edge or restore the pre-migration backup before retrying.
- **Fresh bootstrap:** creates empty current state. It is not recovery of conversations, registrations, or artifacts.
- **Restore:** replaces the active state with a consistent backup and requires post-startup data checks.

Use [Runtime State](runtime-state.md) for backup sets, reset blast radius, restore order, and verification. Do not delete or overwrite the only failing database while diagnosing it.
