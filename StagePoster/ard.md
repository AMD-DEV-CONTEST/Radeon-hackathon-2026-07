# StagePoster MVP Architecture Decision Record

> Document: `docs/ADR-MVP.md`  
> Product: StagePoster  
> Version: 1.0  
> Status: Accepted for MVP  
> Scope: Architecture decisions required to deliver the hackathon poster loop

---

## 1. Purpose

This ADR records the architectural decisions that define the StagePoster MVP.

It prevents the project from repeatedly reopening settled questions during the hackathon and gives frontend, backend, and inference contributors one shared technical direction.

Each decision contains:

- context;
- decision;
- rationale;
- consequences;
- alternatives considered;
- revisit trigger.

---

# ADR-001: Limit the MVP to Poster Generation

## Status

Accepted.

## Context

The long-term StagePoster concept includes:

- posters;
- promotional video;
- VJ visuals;
- music and lyric inputs;
- multiple campaign outputs.

Attempting all outputs during the hackathon would create several incomplete pipelines.

## Decision

The MVP supports only:

```text
structured event brief
+ performer image
+ optional logo
+ optional style reference
→ complete portrait event poster
```

Video and VJ generation remain outside the MVP.

## Rationale

A complete poster flow demonstrates:

- multimodal inputs;
- image generation;
- asset management;
- asynchronous GPU execution;
- brand preservation;
- deterministic composition;
- a usable final deliverable.

This is sufficient to prove the core product thesis.

## Consequences

Positive:

- less workflow complexity;
- easier frontend integration;
- stronger demo story;
- more time for output quality and reliability.

Negative:

- long-term multimodal scope is not fully demonstrated;
- video models and audio handling are deferred.

## Alternatives Considered

- Poster plus short promotional video.
- Poster, video, and VJ in one demo.
- Raw image generation without final composition.

## Revisit Trigger

Revisit only after all poster acceptance criteria pass and demo reliability is established.

---

# ADR-002: Use One Shared Remote Backend for Real Integration

## Status

Accepted.

## Context

The GPU environment contains models and ComfyUI that frontend collaborators should not need to install.

The frontend developer needs a stable integration target.

## Decision

Run the real StagePoster backend on the current GPU server and expose one HTTPS StagePoster API base URL.

```text
Frontend
  ↓ HTTPS
StagePoster Backend
  ↓ private
ComfyUI
```

Frontend switches environments only through `API_BASE_URL`.

## Rationale

This avoids:

- model downloads;
- ROCm setup;
- ComfyUI installation;
- SQLite file sharing;
- asset-directory synchronization;
- machine-specific workflow differences.

## Consequences

Positive:

- minimal frontend setup;
- one source of truth for assets and Jobs;
- faster end-to-end testing.

Negative:

- frontend development depends on server availability for real generation;
- public endpoint requires security and capacity protection;
- unstable temporary tunnel URLs can interrupt integration.

## Alternatives Considered

- Each teammate runs the full backend and ComfyUI locally.
- Frontend calls ComfyUI directly.
- Share SQLite and output directories through Git.
- Deploy backend separately from GPU server.

## Revisit Trigger

Revisit if the project needs multiple backend replicas or production deployment.

---

# ADR-003: Keep ComfyUI Private Behind the Go Backend

## Status

Accepted.

## Context

ComfyUI exposes workflow-, node-, queue-, history-, and file-oriented APIs that are engine-specific.

Direct browser access would tightly couple the frontend to the inference engine.

## Decision

Only the StagePoster Go API is publicly accessible.

ComfyUI is bound to loopback or a private network and is accessed only through a backend Adapter.

## Rationale

The Adapter hides:

- node IDs;
- workflow JSON;
- input directories;
- prompt IDs;
- raw WebSocket messages;
- model paths;
- custom-node failures.

This allows backend workflows to change without frontend changes.

## Consequences

Positive:

- stable public API;
- safer engine exposure;
- centralized authorization and rate limiting;
- cleaner frontend responsibilities.

Negative:

- backend must translate progress and errors;
- backend becomes responsible for output retrieval.

## Alternatives Considered

- Frontend calls ComfyUI directly.
- Reverse proxy selected ComfyUI endpoints.
- Build the product entirely as a ComfyUI extension.

## Revisit Trigger

None for the MVP.

---

# ADR-004: Use Go as the Product API and Orchestration Layer

## Status

Accepted.

## Context

ComfyUI already provides the Python-based inference runtime. StagePoster needs a stable service layer for APIs, file handling, jobs, and orchestration.

## Decision

Use Go for:

- public HTTP API;
- validation;
- Project and Asset management;
- Job lifecycle;
- queue ownership;
- ComfyUI Adapter;
- result delivery;
- logging and tracing;
- deterministic composition orchestration.

## Rationale

Go provides:

- simple deployment;
- strong concurrency primitives;
- clear service boundaries;
- a single compiled backend;
- good suitability for HTTP and worker orchestration.

The model runtime remains in ComfyUI.

## Consequences

Positive:

- inference and product concerns are separated;
- backend can remain stable while workflows change.

Negative:

- some image-processing operations may be easier in Python;
- cross-language process boundaries may be introduced for advanced composition.

## Alternatives Considered

- Python FastAPI for all backend work.
- Node.js backend.
- Expose ComfyUI as the only backend.

## Revisit Trigger

Revisit composition implementation only if required libraries are not practical in Go.

---

# ADR-005: Use SQLite for MVP Metadata Persistence

## Status

Accepted.

## Context

The MVP runs as one backend process on one server and needs durable storage for Projects, Assets, Jobs, Outputs, and Job events.

## Decision

Use SQLite on local server disk.

Enable WAL mode and use short transactions.

Do not commit the runtime database to Git.

## Rationale

SQLite provides:

- no external service;
- low deployment complexity;
- sufficient durability for one-process MVP;
- easy local Mock startup;
- straightforward backup for the demo.

## Consequences

Positive:

- one-command deployment;
- frontend collaborator does not need database setup;
- no Redis/PostgreSQL operational burden.

Negative:

- one backend instance;
- not suitable for shared network-disk access;
- limited scale compared with a client-server database.

## Alternatives Considered

- PostgreSQL.
- Redis plus PostgreSQL.
- JSON files.
- In-memory state only.
- Commit a populated `.db` file to Git.

## Revisit Trigger

Revisit when multiple backend replicas or production multi-user scale is required.

---

# ADR-006: Store Binary Assets on Local Filesystem, Metadata in SQLite

## Status

Accepted.

## Context

Images and outputs are large binary files. SQLite should not become the binary storage layer for the MVP.

## Decision

Store:

- metadata in SQLite;
- uploaded assets and generated outputs under one configured local storage root.

Use backend-generated IDs and storage keys.

## Rationale

This is simple, fast, and compatible with private ComfyUI on the same server.

## Consequences

Positive:

- no object-storage dependency;
- easy transfer between backend and ComfyUI;
- clear separation of metadata and files.

Negative:

- one server owns all runtime files;
- backup and cleanup must be handled;
- horizontal scaling is deferred.

## Alternatives Considered

- Store image blobs in SQLite.
- S3-compatible object storage.
- Upload assets directly into ComfyUI directories.
- Commit uploads and outputs to Git.

## Revisit Trigger

Revisit for production deployment or multi-server workers.

---

# ADR-007: Do Not Commit Runtime Database, Uploads, Models, or Outputs

## Status

Accepted.

## Context

The repository must be easy to clone, but runtime state is machine-specific and often large.

## Decision

Commit:

- migrations;
- seed definitions;
- `.env.example`;
- Mock fixtures;
- Workflow manifests;
- documentation;
- startup scripts.

Ignore:

```text
data/*.db
data/*.db-wal
data/*.db-shm
outputs/projects/
logs/
.env
model files
ComfyUI runtime output
```

On first startup, the backend creates the database and required directories automatically.

## Rationale

This provides “clone and run” without corrupting or merging runtime state.

## Consequences

Positive:

- clean Git history;
- no SQLite merge conflicts;
- no accidental model or user-asset commits.

Negative:

- startup automation and seeds are required;
- frontend cannot rely on a checked-in live database.

## Alternatives Considered

- Commit one SQLite database.
- Commit generated outputs.
- Ask each teammate to manually create tables and directories.

## Revisit Trigger

None.

---

# ADR-008: Use Contract-First Development with a Mock Runner

## Status

Accepted.

## Context

Frontend development should not wait for ComfyUI workflow integration.

Real inference may also be unavailable during some development periods or during the live demo.

## Decision

Implement the public API and Job lifecycle against a Mock Runner before connecting ComfyUI.

Mock and real runners must share:

- request validation;
- Job creation;
- Job stages;
- error shapes;
- Output resource shape.

## Rationale

The frontend can implement:

- upload UI;
- form validation;
- progress UI;
- result UI;
- failure handling;
- refresh recovery.

The backend later replaces only the execution runner.

## Consequences

Positive:

- parallel development;
- stable contract;
- demo fallback;
- easier automated testing.

Negative:

- Mock behavior must not drift from real behavior;
- some time is spent building a second execution path.

## Alternatives Considered

- Wait for real inference before frontend integration.
- Frontend uses hardcoded local JSON only.
- Frontend calls ComfyUI directly until backend is ready.

## Revisit Trigger

None for MVP.

---

# ADR-009: Use Asynchronous Jobs with Frontend Polling

## Status

Accepted.

## Context

Generation can take significantly longer than ordinary HTTP requests.

A public tunnel or proxy may not handle long-lived connections reliably.

## Decision

Creation returns `202 Accepted` and a durable Job ID.

The frontend polls:

```text
GET /jobs/{job_id}
```

ComfyUI WebSocket monitoring remains private inside the backend Adapter.

## Rationale

Polling is:

- simple;
- resilient;
- easy to debug;
- compatible with temporary tunnels;
- sufficient for the hackathon.

## Consequences

Positive:

- no frontend WebSocket or SSE infrastructure;
- page refresh can recover using Job ID.

Negative:

- repeated HTTP requests;
- progress is less immediate than a push channel.

## Alternatives Considered

- Keep the generation HTTP request open.
- Public WebSocket.
- Server-Sent Events.
- Frontend polls ComfyUI directly.

## Revisit Trigger

Revisit for production-scale progress streaming.

---

# ADR-010: Persist Jobs Before Queueing

## Status

Accepted.

## Context

An in-memory queue can lose work during backend restart.

A Job that exists only in memory cannot be recovered or shown to the frontend.

## Decision

The backend must:

1. validate the request;
2. persist the immutable Brief snapshot;
3. persist the queued Job;
4. commit SQLite;
5. enqueue the Job;
6. return the Job resource.

## Rationale

Durable state must exist before execution begins.

## Consequences

Positive:

- refresh-safe Job tracking;
- restart recovery;
- auditable history.

Negative:

- queue and database state must be reconciled;
- startup recovery logic is required.

## Alternatives Considered

- Queue first and persist later.
- ComfyUI queue is the only Job database.
- In-memory Job state.

## Revisit Trigger

None.

---

# ADR-011: Use a Bounded In-Process Queue, Not Redis

## Status

Accepted.

## Context

The MVP has one backend instance and one GPU execution environment.

A distributed queue adds another service and more operational risk.

## Decision

Use a bounded in-process product queue backed by durable SQLite Job state.

Default active GPU concurrency:

```text
1
```

Queue length and per-client limits are configuration.

## Rationale

This is sufficient for one server and one GPU while keeping deployment simple.

## Consequences

Positive:

- no Redis installation;
- fewer failure modes;
- straightforward scheduling.

Negative:

- one backend instance;
- explicit restart recovery is required;
- queue is not distributed.

## Alternatives Considered

- Redis queue.
- Database polling worker.
- Use only ComfyUI's queue.
- Unlimited goroutines.

## Revisit Trigger

Revisit when workers or API servers need independent scaling.

---

# ADR-012: Separate Generative Visual Creation from Deterministic Composition

## Status

Accepted.

## Context

Diffusion models are unreliable for exact text and brand-logo reproduction.

A complete event poster requires both creative visuals and accurate information.

## Decision

Use two logical phases:

```text
ComfyUI visual generation
          ↓
deterministic logo and text composition
          ↓
final output
```

Exact-copy fields and Logo Assets are not delegated to the diffusion model.

## Rationale

This produces a more usable final poster and differentiates StagePoster from a raw text-to-image wrapper.

## Consequences

Positive:

- exact dates and venue names;
- unchanged logo;
- reusable layouts;
- easier multi-size output later.

Negative:

- requires layout presets;
- requires font and composition handling;
- generated artwork must reserve usable text space.

## Alternatives Considered

- Generate all poster text inside ComfyUI.
- Return only a visual background.
- Ask the frontend to compose text and logo.

## Revisit Trigger

The implementation technology for composition may change, but the separation remains.

---

# ADR-013: Use Versioned Backend-Owned Style Presets

## Status

Accepted.

## Context

A frontend form exposing model-level controls would be difficult to use and tightly coupled to the current workflows.

## Decision

The frontend selects:

```text
preset_id
preset_version
```

and may submit a short `prompt_hint`.

The backend owns the preset definition.

## Rationale

A style preset can bind:

- prompt fragments;
- negative prompts;
- workflow compatibility;
- image-conditioning strengths;
- colors;
- texture;
- layout defaults;
- output constraints.

Versioning improves reproducibility.

## Consequences

Positive:

- simple frontend;
- consistent style quality;
- backend can evolve model details.

Negative:

- style additions require backend configuration;
- users do not have arbitrary node-level control.

## Alternatives Considered

- Freeform prompt only.
- Frontend submits model parameters.
- User uploads a complete Workflow JSON.
- One fixed style.

## Revisit Trigger

Revisit after the MVP if a creator-facing advanced mode is needed.

---

# ADR-014: Treat Style Preset, Style Reference, and Prompt Hint as Different Inputs

## Status

Accepted.

## Context

“Style” can refer to:

- a system-designed visual package;
- an uploaded reference image;
- a natural-language direction.

Combining them into one string creates ambiguity.

## Decision

Represent them separately:

- `preset_id` and `preset_version`;
- `style_reference` Asset binding;
- optional `prompt_hint`.

Priority:

1. explicit user constraints;
2. selected style preset;
3. compatible traits inferred from reference images.

Identity and logo preservation override style transformation.

## Rationale

This gives predictable interpretation and clearer validation.

## Consequences

Positive:

- better planning;
- easier debugging;
- no ambiguous frontend field.

Negative:

- planner must resolve conflicts.

## Alternatives Considered

- One freeform style string.
- Reference image only.
- Preset only.

## Revisit Trigger

None for MVP.

---

# ADR-015: Use Conservative Performer Integration as the Default

## Status

Accepted with implementation detail pending.

## Context

High-style image regeneration can distort performer identity.

The MVP must reliably preserve recognizable people.

## Decision

Default to the most reliable available pipeline, favoring:

- subject extraction or conservative reference conditioning;
- generated background and atmosphere;
- limited identity transformation;
- deterministic final composition.

A deeper “reimagine” mode is not required for MVP.

## Rationale

Reliability is more important than maximum stylistic transformation during the hackathon.

## Consequences

Positive:

- higher identity preservation;
- predictable output;
- fewer failed demos.

Negative:

- some results may look more composited than fully regenerated;
- advanced style transformation is deferred.

## Alternatives Considered

- Full identity-reference regeneration.
- Pose and depth-controlled regeneration.
- User chooses multiple advanced modes in MVP.

## Revisit Trigger

Revisit after the default pipeline is reliable on representative demo inputs.

---

# ADR-016: Preserve Logos Through Deterministic Placement

## Status

Accepted.

## Context

Logos are exact brand assets and should not be redrawn by diffusion models.

## Decision

Store and normalize logos as Assets, then place them in the final composition phase.

SVG input must be sanitized and converted to a safe renderable representation.

## Rationale

The uploaded logo must remain the uploaded logo.

## Consequences

Positive:

- brand accuracy;
- predictable alpha handling;
- reusable layout behavior.

Negative:

- requires contrast and placement rules;
- automatic light/dark variants are deferred unless easy to provide.

## Alternatives Considered

- Feed logo into diffusion.
- Ask users to add logo after download.
- Render logo in the frontend only.

## Revisit Trigger

None.

---

# ADR-017: Use Exact Copy from the Creative Brief

## Status

Accepted.

## Context

The model must not invent or rewrite event facts.

## Decision

Store exact copy fields separately from generation prompts and render them deterministically.

Copy assistance is disabled by default.

## Rationale

A visually strong poster with a wrong date is a failed product.

## Consequences

Positive:

- correctness;
- clear ownership of text;
- easier validation.

Negative:

- the system must detect copy that does not fit a selected layout;
- font handling becomes part of the backend design.

## Alternatives Considered

- Model-generated poster text.
- Frontend adds all copy after generation.
- Automatic rewriting by default.

## Revisit Trigger

Optional copy suggestions may be added later, while preserving originals.

---

# ADR-018: Use Versioned Workflow Manifests Instead of Hardcoded Node IDs

## Status

Accepted.

## Context

ComfyUI API workflows contain node IDs that can change between workflow exports.

Hardcoding node IDs throughout business logic creates brittle coupling.

## Decision

Each supported workflow must have a manifest that declares:

- workflow ID;
- version;
- API-format JSON location;
- required models;
- required custom nodes;
- supported Asset roles;
- input-node mappings;
- prompt-node mappings;
- configurable parameter mappings;
- output-node mappings;
- expected output types;
- compatibility constraints.

The Adapter resolves manifest mappings rather than scattering node IDs across the service.

## Rationale

Workflows become replaceable, testable execution assets.

## Consequences

Positive:

- cleaner Adapter;
- easier workflow upgrades;
- explicit runtime requirements.

Negative:

- manifests require maintenance;
- workflow export and validation become part of release preparation.

## Alternatives Considered

- Hardcode node IDs in Go.
- Let frontend submit Workflow JSON.
- Build one fixed workflow and never version it.

## Revisit Trigger

None.

---

# ADR-019: Use API Capability Discovery

## Status

Accepted.

## Context

Supported styles, formats, upload limits, and optional features may change as the backend matures.

## Decision

Expose one capability endpoint and make the frontend use it.

## Rationale

The frontend should not require a release merely because the backend enables or disables one preset.

## Consequences

Positive:

- looser coupling;
- easier demo configuration;
- clearer environment differences.

Negative:

- frontend must handle unavailable capabilities;
- stable IDs are required.

## Alternatives Considered

- Hardcode all options in the frontend.
- Share one manually copied constants file.

## Revisit Trigger

None.

---

# ADR-020: Use RFC 9457-Style Problem Details for HTTP Errors

## Status

Accepted.

## Context

Frontend error handling requires one predictable structure.

## Decision

Use `application/problem+json` with:

- type;
- title;
- status;
- detail;
- instance;
- stable `code`;
- Request ID;
- retryability;
- field-level errors.

Job execution failures appear inside the existing Job resource.

## Rationale

This separates transport/request failure from asynchronous Job failure.

## Consequences

Positive:

- predictable frontend behavior;
- traceable support;
- clear retry semantics.

Negative:

- all handlers and adapters must translate errors consistently.

## Alternatives Considered

- `{ "error": "..." }`.
- raw Go errors.
- raw ComfyUI errors.
- different error structures per endpoint.

## Revisit Trigger

None.

---

# ADR-021: Use Polling for Frontend Progress, Private WebSocket for ComfyUI

## Status

Accepted.

## Context

ComfyUI provides execution events, but the frontend should not depend on its protocol.

## Decision

The backend Adapter may use ComfyUI WebSocket internally.

The frontend polls StagePoster Job resources.

Suggested interval:

- one second during the first ten seconds;
- two seconds afterward;
- stop at terminal state.

## Rationale

This is stable through common HTTPS proxies and tunnels.

## Consequences

Positive:

- simple frontend;
- no public socket infrastructure;
- easy recovery after refresh.

Negative:

- approximate progress;
- additional HTTP requests.

## Alternatives Considered

- Public WebSocket.
- SSE.
- Long polling.
- Raw ComfyUI WebSocket proxy.

## Revisit Trigger

Revisit for production experience improvements.

---

# ADR-022: Expose Only a Stable HTTPS API URL to the Frontend

## Status

Accepted.

## Context

Browsers often block mixed content, and temporary raw IP access creates CORS and certificate problems.

## Decision

Use a stable HTTPS hostname or named tunnel for final integration and judging.

Temporary random tunnels may be used for early development only.

## Rationale

The frontend should depend on one stable URL.

## Consequences

Positive:

- browser-compatible;
- simpler configuration;
- less last-minute demo risk.

Negative:

- requires domain, reverse proxy, or tunnel management.

## Alternatives Considered

- Plain HTTP IP address.
- Frontend runs on the same machine.
- Repeated temporary random URLs through the entire project.

## Revisit Trigger

None before the demo.

---

# ADR-023: Enforce Capacity and Abuse Limits at the Public API

## Status

Accepted.

## Context

A publicly reachable generation endpoint can be used accidentally or maliciously to occupy the GPU.

## Decision

Enforce:

- maximum upload size;
- maximum Assets per Project;
- maximum candidate count;
- maximum active GPU Jobs;
- global queue bound;
- per-client queued-job bound;
- request rate limits;
- optional demo access token;
- CORS allowlist.

## Rationale

The GPU is the scarcest resource.

## Consequences

Positive:

- predictable queue;
- safer public demo;
- clearer failure behavior.

Negative:

- client identity must be approximated before a full account system exists;
- token embedded in a public frontend is not a true secret.

## Alternatives Considered

- Unlimited public access.
- Expose ComfyUI queue directly.
- Add full account and billing system.

## Revisit Trigger

Revisit authentication architecture after the hackathon.

---

# ADR-024: Define Completion as a Usable Final Poster, Not a Successful Model Run

## Status

Accepted.

## Context

ComfyUI may finish successfully while:

- output retrieval fails;
- logo placement fails;
- text composition fails;
- preview generation fails;
- final file is missing or corrupt.

## Decision

A StagePoster Job reaches `completed` only when:

- required generated visual exists;
- deterministic composition succeeds;
- final output passes validation;
- output metadata is persisted;
- preview and full-content URLs are available.

## Rationale

Product-level success is different from engine-level success.

## Consequences

Positive:

- frontend can trust the completed state.

Negative:

- backend has more failure paths to manage.

## Alternatives Considered

- Treat ComfyUI completion as Job completion.
- Let frontend assemble the final output.
- Return partial results as completed.

## Revisit Trigger

None.

---

# ADR-025: Keep One Backend Instance for the MVP

## Status

Accepted.

## Context

SQLite and the in-process queue are intentionally single-node choices.

## Decision

Run one StagePoster backend instance during the MVP and final demo.

## Rationale

This keeps state ownership and queue behavior simple.

## Consequences

Positive:

- predictable deployment;
- no distributed coordination.

Negative:

- temporary backend downtime affects the product;
- no horizontal availability.

## Alternatives Considered

- Multiple replicas against one SQLite file.
- PostgreSQL plus Redis from the start.
- Separate API and worker services.

## Revisit Trigger

Revisit only after the hackathon.

---

## 2. Decision Summary

The StagePoster MVP architecture is:

```text
Frontend
  ↓ stable HTTPS
One Go Backend
  ├── contract-first HTTP API
  ├── SQLite metadata
  ├── local filesystem storage
  ├── bounded in-process Job queue
  ├── Mock Runner
  ├── deterministic poster composition
  └── private ComfyUI Adapter
          ↓
       ComfyUI + GPU
```

The MVP output is one complete event poster, not a raw generated image.

---

## 3. Required Follow-Up Design Documents

Before implementation, maintain:

- `PRD-MVP.md`;
- `api-contract.md`;
- `creative-brief-schema.md`;
- `asset-contract.md`;
- `job-lifecycle.md`;
- `error-codes.md`;
- `workflow-manifest-spec.md`;
- `sqlite-schema.md`;
- `deployment-runbook.md`;
- `frontend-integration.md`.

---

## 4. Unresolved Implementation Decisions

The following are intentionally not settled by this ADR:

1. exact Go router and ORM/library;
2. exact image-composition library or helper process;
3. exact performer extraction or identity-conditioning implementation;
4. final style-preset list;
5. final layout-preset geometry;
6. final public HTTPS provider;
7. exact font bundle and licensing;
8. exact ComfyUI workflow and custom nodes.

These decisions must not violate the accepted boundaries in this ADR.

---

## 5. Architecture Acceptance Checklist

- [ ] Frontend does not depend on ComfyUI.
- [ ] One remote API URL supports real integration.
- [ ] Local Mock mode follows the same contract.
- [ ] SQLite and local storage are created automatically.
- [ ] Runtime files are excluded from Git.
- [ ] Jobs are persisted before queueing.
- [ ] Queue and GPU concurrency are bounded.
- [ ] Text and logos are composed deterministically.
- [ ] Styles and workflows are versioned.
- [ ] Job completion means the final poster is usable.
- [ ] Video and VJ remain outside the MVP.
