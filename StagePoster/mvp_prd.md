# StagePoster MVP Product Requirements Document

> Document: `docs/PRD-MVP.md`  
> Product: StagePoster  
> Version: 1.0  
> Status: Proposed for implementation  
> Scope: Hackathon MVP  
> Owners: Backend team, frontend collaborator, workflow/inference contributor

---

## 1. Product Summary

StagePoster is a multimodal promotional-content generation system for music events.

Users provide:

- performer or band images;
- event or brand logos;
- style references;
- event facts;
- exact promotional copy;
- a visual style preset;
- an optional natural-language creative direction.

StagePoster returns one or more complete promotional posters that preserve:

- recognizable performer identity;
- exact event information;
- original logo appearance;
- a coherent visual style;
- a publishable portrait layout.

The MVP is not a general-purpose image generator. It is a guided creative-production pipeline that transforms structured event inputs into usable promotional artwork.

---

## 2. Problem Statement

Creating event posters currently requires several disconnected steps:

1. gathering performer images and brand assets;
2. defining a visual direction;
3. generating or sourcing a background;
4. integrating people into the composition;
5. laying out accurate dates, venues, titles, and ticket information;
6. producing downloadable final artwork.

Conventional text-to-image systems are insufficient because they frequently:

- alter faces;
- redraw logos incorrectly;
- misspell text;
- produce inconsistent layouts;
- require users to understand prompt engineering;
- return artwork that still needs manual finishing.

StagePoster addresses this by separating generative visual creation from deterministic brand and text composition.

---

## 3. Product Vision

> Turn a creative brief, performer assets, and event information into a publishable music-event poster through one guided workflow.

The long-term product may generate:

- posters;
- social media variants;
- promotional video;
- VJ loops;
- campaign asset sets.

The MVP proves only the poster-generation loop.

---

## 4. MVP Goal

The MVP must demonstrate the complete journey:

```text
Create project
→ Upload performer, logo, and optional style reference
→ Select a style
→ Enter exact event information
→ Submit generation
→ Observe asynchronous progress
→ Receive one or two complete poster outputs
```

The result must be more complete than a raw diffusion image. It must include exact event copy and an unchanged logo when one is supplied.

---

## 5. MVP Scope

### 5.1 Included

- one project type: music event;
- one output type: portrait poster;
- one primary performer image;
- optional event or brand logo;
- optional style-reference image;
- optional background-reference image;
- structured Creative Brief;
- four to six backend-owned style presets;
- one or more deterministic layout presets;
- asynchronous generation jobs;
- SQLite metadata persistence;
- local server file storage;
- private ComfyUI integration;
- local Mock mode;
- remote HTTPS API for frontend integration;
- final poster preview and download.

### 5.2 Deferred

- promotional video;
- VJ content;
- audio analysis;
- beat-synchronized generation;
- full poster editor;
- arbitrary drag-and-drop layout;
- multi-user accounts;
- production billing;
- team permissions;
- Redis;
- PostgreSQL;
- object storage;
- multiple backend replicas;
- public ComfyUI access;
- user-authored ComfyUI workflows;
- model-level controls in the frontend;
- social export variants;
- advanced copywriting assistant.

---

## 6. Target Users

### 6.1 Primary MVP User

A musician, band member, event organizer, or creator who has:

- at least one performer image;
- event information;
- a desired visual direction;
- limited design time or design experience.

### 6.2 Secondary User

A designer or creative operator who wants to generate rapid campaign concepts before final manual refinement.

### 6.3 Hackathon Demo Audience

Judges and viewers who need to understand the product within one short live demonstration.

---

## 7. Core User Story

> As an event organizer, I want to upload a performer photo and logo, choose a visual style, and enter accurate event information so that I can receive a complete promotional poster without manually assembling the design.

---

## 8. Supporting User Stories

### Project

- As a user, I can create a project for one event.
- As a user, I can return to the project and see its uploaded assets and generation history.

### Assets

- As a user, I can upload a performer image.
- As a user, I can upload a transparent event or brand logo.
- As a user, I can upload a style-reference image.
- As a user, I can preview uploaded assets before generating.

### Creative Brief

- As a user, I can enter exact title, date, time, venue, and performer information.
- As a user, I can choose a versioned visual-style preset.
- As a user, I can add one short creative-direction hint.
- As a user, I can choose an output format and candidate count within allowed limits.

### Generation

- As a user, I receive a Job ID immediately after submission.
- As a user, I can see whether the system is planning, preparing assets, generating, or composing the final poster.
- As a user, I can refresh the page without losing the task.
- As a user, I can see an actionable error when generation fails.

### Output

- As a user, I can preview the final poster.
- As a user, I can download the full-resolution poster.
- As a user, I receive exact event copy rather than model-generated text.
- As a user, an uploaded logo remains visually unchanged.

---

## 9. Product Principles

### 9.1 Creative Brief, Not Raw Prompt

The frontend expresses user intent through structured fields. The backend owns model prompts, workflow selection, and generation parameters.

### 9.2 Exact Information Is Deterministic

Dates, venue names, artist names, calls to action, and logos are composed after generative visual creation.

### 9.3 Frontend Is Decoupled from ComfyUI

The frontend communicates only with the StagePoster API.

### 9.4 Mock and Real Modes Share One Contract

The frontend must work against either mode by changing only the API base URL.

### 9.5 One Reliable Loop Beats Many Partial Features

The poster workflow must be complete before work begins on video or VJ generation.

---

## 10. End-to-End Product Flow

### Step 1: Project Creation

The user creates a project with:

- project name;
- project type;
- optional frontend-local reference.

Expected result:

- the backend creates a Project record;
- the frontend receives a stable Project ID.

### Step 2: Asset Upload

The user uploads:

- one primary performer image;
- zero or one event logo;
- zero or more style references within limits;
- zero or one background reference.

Expected result:

- each file is validated;
- each file receives an Asset ID;
- each usable asset reaches `ready`;
- preview URLs are returned.

### Step 3: Creative Brief

The user enters:

- event name;
- date;
- optional time;
- venue;
- city;
- performer name;
- headline;
- optional subtitle;
- optional call to action;
- optional lyrics excerpt;
- style preset;
- layout preset;
- optional palette;
- optional prompt hint;
- output preset;
- candidate count.

Expected result:

- the frontend submits only asset IDs and structured fields;
- the backend validates compatibility before using the GPU.

### Step 4: Generation Job

The backend:

1. saves an immutable Creative Brief snapshot;
2. resolves a Generation Plan;
3. creates a durable Job;
4. returns `202 Accepted`;
5. queues execution.

Expected result:

- frontend receives Job ID immediately;
- duplicate submission is prevented through idempotency.

### Step 5: Visual Generation

The backend worker:

1. prepares model inputs;
2. resolves the versioned API workflow;
3. submits to private ComfyUI;
4. tracks execution;
5. retrieves generated artwork.

### Step 6: Deterministic Composition

The backend:

1. selects the resolved layout;
2. places exact event text;
3. places the original logo;
4. creates the final poster;
5. validates dimensions and readability constraints;
6. creates a preview.

### Step 7: Result Delivery

The frontend polls the Job endpoint until terminal status.

On success it displays:

- candidate previews;
- full-resolution output links;
- event and generation metadata as needed.

---

## 11. Functional Requirements

## FR-1: Health and Capability Discovery

The backend must provide:

- service health;
- operating mode;
- supported asset types;
- supported style presets;
- supported layout presets;
- supported output presets;
- upload and queue limits;
- supported optional features.

The frontend must use capability discovery instead of duplicating all backend configuration.

## FR-2: Project Management

The system must support:

- project creation;
- project retrieval;
- project asset listing;
- project job history retrieval, if implemented in the first release.

Project deletion is not required for MVP.

## FR-3: Asset Upload

The system must:

- accept multipart uploads;
- validate format and size;
- detect actual MIME type;
- normalize supported images;
- generate previews;
- store metadata in SQLite;
- store files on local disk;
- return stable opaque Asset IDs;
- prevent internal path disclosure.

## FR-4: Creative Brief Validation

The system must validate:

- required event fields;
- exact-copy length;
- supported schema version;
- style and layout IDs;
- output preset;
- candidate count;
- Asset existence;
- Project ownership of Assets;
- Asset readiness;
- binding role and Asset type compatibility;
- rights confirmation.

Validation must occur before GPU execution.

## FR-5: Style Presets

The backend must provide at least four coherent visual presets.

Each preset must define:

- stable ID;
- version;
- display name;
- compatible workflow;
- prompt fragments;
- negative prompt fragments;
- image-conditioning behavior;
- compatible layout presets;
- default visual parameters;
- preview asset for frontend display, when available.

Candidate initial presets:

- `retro_japan_80s`;
- `neon_cyberpunk`;
- `indie_editorial`;
- `dark_rock`;
- optional `dream_pop`;
- optional `minimal_festival`.

The final MVP may ship with fewer presets if quality is stronger.

## FR-6: Generation Plan

For every accepted generation request, the backend must resolve an internal immutable Generation Plan.

It must include:

- Creative Brief snapshot reference;
- workflow ID and version;
- style preset ID and version;
- layout preset ID and version;
- asset bindings;
- prompt and negative prompt;
- preprocessing instructions;
- model execution settings;
- deterministic composition settings;
- output settings.

The frontend does not submit or modify this object.

## FR-7: Job Management

The system must:

- create a durable Job before queueing;
- provide Job status, stage, and approximate progress;
- persist terminal state;
- support recovery or deterministic interruption handling after restart;
- prevent duplicate work through idempotency;
- expose sanitized failures;
- return output references on completion.

Cancellation and retry are desirable but may be implemented after the basic loop.

## FR-8: Mock Runner

Mock mode must:

- expose the same API contract;
- use the same Job lifecycle;
- simulate stage transitions;
- return a fixture poster;
- support at least one simulated failure path;
- require no ComfyUI or model installation.

## FR-9: ComfyUI Adapter

The adapter must privately handle:

- input-image upload or mapping;
- API-format workflow submission;
- prompt ID persistence;
- execution monitoring;
- queue and history lookup;
- output retrieval;
- error translation;
- temporary connection recovery.

Raw ComfyUI messages and paths must not appear in the frontend contract.

## FR-10: Deterministic Poster Composition

The composition stage must:

- use exact text from the Creative Brief;
- preserve logo appearance;
- use a versioned layout preset;
- support the selected output dimensions;
- create final PNG output;
- create a frontend preview;
- fail the Job if required composition cannot be completed.

## FR-11: Output Delivery

The backend must provide:

- preview endpoint;
- full output endpoint;
- accurate MIME type;
- valid width and height metadata;
- opaque Output ID;
- no directory listing or internal path exposure.

---

## 12. Non-Functional Requirements

### NFR-1: Deployability

The backend must run as one service process against:

- one local SQLite database;
- one local storage root;
- one private ComfyUI endpoint.

### NFR-2: Frontend Integration

The frontend must be able to switch between local Mock and remote GPU backend by changing only:

```text
API_BASE_URL
```

### NFR-3: Persistence

Projects, Assets, Jobs, and Outputs must survive backend restart.

### NFR-4: Traceability

Every request and Job must be traceable using:

- Request ID;
- Project ID;
- Job ID;
- internal ComfyUI Prompt ID.

### NFR-5: Capacity Protection

The system must enforce:

- upload size limits;
- Asset-count limits;
- candidate-count limits;
- queue limits;
- per-client queued-job limits;
- bounded GPU concurrency.

### NFR-6: Security

The system must:

- keep ComfyUI private;
- restrict CORS;
- validate uploaded files;
- sanitize SVG;
- avoid committing secrets;
- avoid returning filesystem paths;
- protect the public demo from unlimited GPU use.

### NFR-7: Failure Clarity

Errors must follow one documented machine-readable structure and state whether retry may succeed.

### NFR-8: Demo Reliability

Mock mode must remain available as a fallback if real inference becomes unavailable during judging.

---

## 13. Technical Operating Model

```text
Frontend
  ↓ HTTPS
StagePoster Go API
  ├── SQLite
  ├── local asset/output storage
  ├── bounded Job queue
  ├── Mock Runner
  └── ComfyUI Adapter
          ↓ private connection
       ComfyUI
          ↓
        GPU
```

For the hackathon, the recommended real-integration setup is one backend instance hosted on the current GPU server.

---

## 14. API Surface Required for MVP

Required:

```text
GET  /health
GET  /capabilities
POST /projects
GET  /projects/{project_id}
POST /projects/{project_id}/assets
GET  /projects/{project_id}/assets
POST /projects/{project_id}/generations
GET  /jobs/{job_id}
GET  /outputs/{output_id}/preview
GET  /outputs/{output_id}/content
```

Desirable after the core loop:

```text
POST /jobs/{job_id}/cancel
POST /jobs/{job_id}/retry
```

Not required:

- frontend WebSocket;
- SSE;
- Project deletion;
- Asset deletion;
- user account APIs;
- node-level workflow APIs.

---

## 15. Job Stages

```text
queued
→ planning
→ preparing_assets
→ submitting
→ waiting_for_engine
→ generating
→ retrieving_outputs
→ compositing
→ finalizing
→ completed
```

Terminal states:

```text
completed
failed
canceled
```

The frontend should display stage labels. Progress percentages are approximate.

---

## 16. Success Metrics

### Product Success

- A user can complete the full flow without understanding ComfyUI.
- Exact event information appears correctly in the final poster.
- Uploaded logos are preserved.
- The final result is visibly more complete than a raw generated image.
- The complete demo can be understood in under three minutes.

### Engineering Success

- Frontend can integrate through one API base URL.
- Mock and real modes share the same contract.
- No model or ComfyUI installation is needed for frontend development.
- A backend restart does not erase Project, Asset, or Job records.
- Invalid requests are rejected before GPU usage.
- Public API does not expose ComfyUI directly.

### Demo Success

- One prepared demo project can reliably produce or retrieve a completed poster.
- A second live input can demonstrate dynamic generation.
- A Mock fallback can complete the UI flow if inference fails.

---

## 17. Acceptance Criteria

The MVP is accepted only when all critical criteria pass.

### Critical

- [ ] Project can be created.
- [ ] Primary performer image can be uploaded and previewed.
- [ ] Optional logo can be uploaded and previewed.
- [ ] A supported style can be selected.
- [ ] Exact event information can be submitted.
- [ ] Generation returns a Job ID immediately.
- [ ] Job state can be polled after page refresh.
- [ ] Real or Mock generation reaches a terminal state.
- [ ] Completed Job returns at least one poster preview and full output.
- [ ] Final poster contains exact required event text.
- [ ] Uploaded logo is not regenerated by the model.
- [ ] ComfyUI is not public.
- [ ] Runtime SQLite database and generated files are excluded from Git.

### Strongly Desired

- [ ] Identity of the performer remains recognizable.
- [ ] At least two style presets produce visibly different directions.
- [ ] Queue limits prevent accidental GPU overload.
- [ ] A failed Job returns a clear actionable error.
- [ ] Retry creates a new Job rather than rewriting history.

---

## 18. Milestones

### Milestone 1: Contract and Mock Loop

Deliver:

- frozen Creative Brief schema;
- Asset contract;
- Job lifecycle;
- standardized errors;
- SQLite schema;
- Mock Runner;
- frontend-complete Mock flow.

Exit condition:

> Frontend can complete upload, generation, progress, and output screens without ComfyUI.

### Milestone 2: Asset and Workflow Bridge

Deliver:

- real asset preprocessing;
- workflow manifests;
- private ComfyUI Adapter;
- workflow submission;
- Job-to-ComfyUI traceability;
- output retrieval.

Exit condition:

> A real Job can produce a generated visual asset.

### Milestone 3: Poster Composition

Deliver:

- versioned layout preset;
- exact-copy rendering;
- logo placement;
- final poster output;
- previews and downloads.

Exit condition:

> A generated visual becomes a complete publishable poster.

### Milestone 4: Demo Hardening

Deliver:

- fixed HTTPS endpoint;
- CORS allowlist;
- queue protection;
- seeded demo project;
- Mock fallback;
- failure recovery;
- demo script.

Exit condition:

> The project can be demonstrated reliably from the deployed frontend.

---

## 19. Risks and Mitigations

### Risk: Performer identity changes too much

Mitigation:

- begin with subject cutout or conservative reference conditioning;
- avoid deep reimagining in the default workflow;
- provide one reliable workflow before advanced identity transformation.

### Risk: Generated composition leaves no room for text

Mitigation:

- use style and workflow prompts that reserve layout-safe areas;
- use layout-aware workflow variants;
- validate composition before final output.

### Risk: Logo becomes visually corrupted

Mitigation:

- exclude logo from diffusion generation;
- place it only in deterministic composition.

### Risk: Public endpoint is abused

Mitigation:

- strict queue limit;
- per-client limit;
- rate limiting;
- optional access token;
- CORS restriction;
- limited candidate count.

### Risk: GPU or ComfyUI fails during demo

Mitigation:

- Mock mode;
- seeded completed outputs;
- prepared demo project;
- reconnect and history reconciliation;
- avoid last-minute model changes.

### Risk: Scope expands into video

Mitigation:

- video and VJ remain explicitly out of MVP;
- no development begins until poster acceptance criteria pass.

---

## 20. Open Questions

These must be resolved before implementation freeze:

1. Is the primary performer strategy:
   - cutout plus generated background;
   - identity-reference regeneration;
   - both, with one default?
2. Which final style presets ship in the MVP?
3. Which layout preset is the default?
4. Is exact typography rendered in Go or through a dedicated composition helper?
5. What public HTTPS exposure method is used for the final demo?
6. Is cancel/retry required before the first frontend integration?
7. Which fonts can be legally bundled or installed on the server?

---

## 21. Final MVP Definition

StagePoster MVP is complete when a frontend user can upload a performer image and optional logo, choose a visual style, enter exact music-event information, submit an asynchronous generation request, and receive a complete portrait poster from a shared GPU backend without interacting with ComfyUI or manually assembling the final design.
