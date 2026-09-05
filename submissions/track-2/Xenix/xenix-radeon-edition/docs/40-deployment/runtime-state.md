# Runtime State

## When to Use

Developers and support operators use this runbook to locate active state, investigate a local failure, back up or restore a user environment, reset damaged state, or prepare support evidence. A wrong reset can remove conversations, settings, registered datasets, models, and artifacts.

## Locate and Inspect

`XENIX_APP_HOME` selects an explicit runtime home; otherwise Xenix uses its platform default. On Windows this is normally `%LOCALAPPDATA%\Xenix`. Resolve the active home before acting, especially when tests or isolated runs override it.

Treat its contents by ownership:

- config: application settings and persistent install identity, including
  `agent_settings.json`, independent `embedding_settings.json`, and worker settings;
- logs: local JSON diagnostic evidence;
- state: SQLite authority and app-owned dataset state;
- artifacts: generated reports, exports, models, and task work;
- `artifacts/knowledge/objects/source/`: SHA-256-addressed immutable source snapshots
  registered through ArtifactService; preserve with SQLite;
- `artifacts/knowledge/objects/canonical/`: envelope-addressed immutable canonical
  bundles (`manifest.json`, compressed envelope/Docling JSON, and referenced assets);
  preserve with SQLite;
- `artifacts/knowledge/staging/` and `.import-trash/`: app-owned publication and
  startup-reclamation areas; do not sweep them manually while Xenix owns the home;
- `artifacts/knowledge/tasks/imports/<attempt-id>/logs.jsonl`: bounded content-free
  import lifecycle events. Inspect through the Knowledge Workspace `Task queue`;
  absence of document text, source paths, passwords, credentials, and raw exceptions
  is intentional. Worker results retain only outcome, failure stage, and a safe
  diagnostic code;
- Knowledge vector generations: rebuildable derived indexes whose readiness is owned by SQLite metadata;
- `cache/knowledge-ocr/`: optional native Paddle Inference OCR generations, explicit
  model packs, downloads/staging, and the small atomic active-generation pointer;
  rebuildable, potentially large, and not an authority for imported content;
- cache and temp: rebuildable acceleration or transient support output;
- source import files outside the runtime home: user-owned inputs, not reset targets.

Inspect evidence by symptom:

| Symptom | Start with |
| --- | --- |
| startup or persistence failure | application log, active database, schema/migration error |
| provider behavior | Agent settings and application log; never copy credentials into a report |
| ML worker failure | worker settings, task log, local/remote validation result |
| Knowledge import failure | Workspace `Task queue` state and its View Log event timeline; application log for coordinator/runtime diagnostics |
| local OCR setup or repair failure | Knowledge Settings typed setup reason, then the application log and the app-owned OCR staging/generation manifests; do not copy raw document content into support evidence |
| missing dataset, model, or report | database registration plus referenced app-owned file |
| semantic Knowledge lookup failure | Knowledge Settings index state/task error, then vector-generation metadata and its contained derived index; do not alter canonical objects |
| telemetry failure | [Observability](observability.md) and local exporter errors |
| packaged-only failure | [Packaging](packaging.md) and packaged smoke evidence |

## Backup and Restore

Stop Xenix before copying mutable state. For a consistent backup, preserve the entire runtime home, or at minimum the database, config, app-owned dataset state, and artifacts together. Record the source home and time. User-owned source files require their own backup policy.

To restore, stop Xenix, preserve the failed current home separately, restore the backup as one set, then start with the restored home. Verify that startup succeeds and that representative conversations, settings, datasets, artifacts, models, and worker configuration resolve. A successful launch alone is not restore proof.

## Recovery and Reset

Use this order:

1. Stop or quiesce Xenix and any local workers.
2. Identify the active home and forecast what the proposed action will remove.
3. Back up recoverable state.
4. Choose the smallest intervention.
5. Restart and verify the failed workflow plus representative retained state.

Prefer an empty isolated `XENIX_APP_HOME` for diagnosis; it changes no existing state. Database quarantine/rebuild loses SQLite-owned registrations and history from the active database but preserves the renamed database for investigation. A full runtime-home reset additionally removes settings, logs, app-owned datasets, artifacts, caches, and local task state. Never include user-owned source files in a runtime reset.

Knowledge vector maintenance is deliberately narrower than a runtime reset. It may
reconcile missing or corrupt derived generations, proven unregistered vector
directories, and stale vector-owned staging. It does not delete source snapshots,
canonical generations, unrelated staging, or unknown files. Live vector paths are
first detached into same-volume private trash; SQLite readiness is removed only
after that detach succeeds. A Windows sharing violation therefore leaves the
metadata and live path available for a later retry. Residual private trash is safe
to retry after handles close. Reconciliation runs before the first configured
semantic operation and can be requested explicitly through that service. A
maintenance failure is logged and deferred so the optional vector projection cannot
block keyword retrieval or unrelated application functions. Operators should stop
Xenix before intervening manually.

Vector build, search, and maintenance share one lifecycle lock within the owning
process. A runtime home must therefore have one vector owner: secondary diagnostics,
benchmarks, and smoke runs use an isolated runtime home, and operators must stop the
owner before another process performs maintenance. The normal application and smoke
entry points enforce their own single-instance boundaries; the derived-store lock is
not a cross-process substitute for those boundaries.

The Knowledge index coordinator serializes keyword and text-vector rebuild tasks.
Lookup never performs a rebuild. Corpus-triggered jobs coalesce, manual jobs are
submitted from Workspace or Knowledge Settings, and a compatibility-changing
Embedding save may enqueue a job after explicit confirmation. `Needs rebuild` keeps
keyword use available; `Needs attention` directs the user to retry rather than
making Lance or a task row a content authority.

The Workspace `Task queue` is a bounded read model over import, content-preparation,
and index-task owners. It does not make those task rows interchangeable. Import logs
remain import-owned; index build detail and retry remain index-service-owned.

Local OCR setup downloads only the immutable artifact named by the catalog embedded
in the installed Xenix build. It verifies the outer size/digest, safe archive shape,
runtime member manifest, runtime/model/protocol identities, and native self-test in
staging before replacing `active.json`. The fixed OCR pipeline configuration is
compiled into the worker, so it cannot be resolved from a build-tree path, process
working directory, or companion configuration file. A separate verification record
binds the
active generation, model, engine/protocol, and manifest hash to a recent full member
scan and self-test. Fast status reads only bounded manifests/that record; absent or
stale verification reports `checking` and is refreshed in a background task before
the runtime can execute. A missing generation is `not installed`; an identified but
invalid generation requires repair. Deleting the OCR cache removes a rebuildable
optional capability, not Knowledge source/canonical content. Xenix does not use or
clean `%USERPROFILE%/.paddlex`.

Source development uses the generated catalog and exact archive under
`dist/knowledge-ocr` as a local bundle source when no explicit OCR source override is
present. This changes transport only: the same cache, digest, member-manifest,
self-test, verification-record, and atomic-activation state machine remains
authoritative. A missing local source, unavailable release origin, integrity failure,
and self-test failure retain distinct content-free reason codes in Knowledge
Settings; arbitrary exception text is not persisted or displayed.
Generation directory names are fixed-length content addresses over the catalog's
runtime, model-pack, and artifact identities. Descriptive identities stay in the
manifest and active pointer. Setup self-tests the final generation path—not only a
short staging path—before publishing `active.json`, so native Windows model-path
failures cannot be reported as ready.

Knowledge retrieval projection v3 uses deterministic Unit identities. The v22→v23
migration preserves source/canonical content, clears active v2 retrieval pointers,
and lets the derivation owner republish Units and indexes. Vector status derives the
expected identities from bounded document metadata; builds consume one frozen
SQLite projection snapshot and may publish/succeed only while that identity remains
current.

Knowledge Import performs a separate startup-only reconciliation before its worker
starts. SQLite source/canonical references are materialized first; only strictly
recognized, unreferenced source CAS directories, canonical bundles, and source or
canonical staging shapes are atomically detached to `artifacts/knowledge/.import-trash`
and then deleted best effort. Unknown files, links/junctions, malformed objects,
vector staging, and out-of-root references fail closed or remain untouched. A busy
Windows handle may leave private trash for a later startup retry. This reclamation
does not infer document lifecycle, rebuild Units, or replace backup/restore.

For migration-specific failure paths, use [Local State Evolution](local-state-evolution.md).

## Remote Workers and Support Bundles

After restoring or changing worker settings, revalidate the selected SSH worker before trusting it. Clear remote staged/cache data only after confirming the remote root and that no active task depends on it. Worker authority and local finalization are owned by [Product TDD](../20-product-tdd/README.md); known setup gaps remain recorded in [ADR 0005](../20-product-tdd/adr/0005-ssh-ml-worker-pool.md).

`pdm run diagnostic-bundle` creates a local support archive without the raw database. Treat it as sensitive: it contains logs, task logs, the persistent install id, and database summaries. Before manual sharing, review the archive, approve the recipient and retention period, and arrange deletion. The script and its tests own the exact manifest.
