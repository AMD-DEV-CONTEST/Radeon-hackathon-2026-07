# NexusAI System Architecture

**Version:** 1.0

## 1. High-Level Architecture

```text
Browser
  |
  v
Next.js Web Application
  |
  | HTTPS / SSE
  v
FastAPI Control Plane
  |
  +--------------------+
  |                    |
  v                    v
PostgreSQL          Job Dispatch
                       |
                       v
                AMD Radeon Cloud Worker
                       |
          +------------+-------------+
          |            |             |
          v            v             v
        LLM          Vision        Speech/OCR
          |            |             |
          +------------+-------------+
                       |
                       v
                Nexus Processing Core
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
     World Model     Graph         Embeddings
        |              |              |
        +--------------+--------------+
                       |
                       v
                 Retrieval Layer
                       |
                       v
                 Reasoning Layer
                       |
                       v
               Grounded API Response
                       |
                       v
           Interactive Visual Experience
```

## 2. Two-Plane Deployment

### Experience / Control Plane
Designed to be Vercel deployable.

Responsibilities:
- render UI
- manage navigation
- accept user requests
- expose lightweight API routes
- submit processing jobs
- retrieve job status
- serve stored graph/timeline data
- stream responses

### Compute Plane
Runs on AMD Radeon Cloud.

Responsibilities:
- maintain GPU-capable runtime
- load open-source models
- process heavy inference
- generate embeddings
- transcribe audio
- analyze images
- execute long-running ingestion stages

This split prevents serverless constraints from dictating the AI architecture.

## 3. Canonical World Model

### World
Top-level knowledge space.

### Entity
A uniquely identifiable object or concept within a World.

### Relationship
A typed directed connection between entities.

### Event
A time-associated occurrence.

### Source
Original material from which knowledge was extracted.

### Observation
A derived claim produced by deterministic logic or AI.

Every Observation should be able to store:
- producer/model
- confidence
- source references
- timestamp
- method/version

## 4. Data Flow

```text
Source Upload
   |
   v
Source Registration
   |
   v
Parser Selection
   |
   v
Normalized Content
   |
   +--> Deterministic Metadata
   |
   +--> AI Extraction
   |
   v
Entities / Events / Observations
   |
   v
Relationship Construction
   |
   v
World Graph
   |
   +--> Timeline Index
   |
   +--> Vector Index
   |
   v
Ready World
```

## 5. Query Flow

```text
User Question
   |
   v
Intent / Query Planner
   |
   +--> Structured Query
   |
   +--> Graph Traversal
   |
   +--> Vector Retrieval
   |
   v
Ranked Context + Provenance
   |
   v
Reasoning Model
   |
   v
Grounded Answer
   |
   +--> Sources
   |
   +--> Relevant Node IDs
   |
   +--> Relevant Edge IDs
   |
   v
UI Highlights the Explanation
```

## 6. World Adapter Contract

Each World may define:
- supported source types
- domain entity types
- domain relationship types
- extraction rules
- visualization mappings
- prompt/context templates
- domain-specific deterministic analyzers

Worlds must not bypass the shared provenance model.

## 7. Suggested Repository Layout

```text
NexusAI/
├── apps/
│   ├── web/
│   └── api/
├── nexus/
│   ├── ingestion/
│   ├── world/
│   ├── graph/
│   ├── timeline/
│   ├── retrieval/
│   ├── embeddings/
│   └── reasoning/
├── worlds/
│   ├── memoryweaver/
│   ├── worldforge/
│   ├── detective/
│   └── codeverse/
├── ai/
│   ├── runtime/
│   ├── llm/
│   ├── vision/
│   ├── speech/
│   └── ocr/
├── infrastructure/
│   ├── vercel/
│   ├── rocm/
│   └── docker/
├── tests/
├── docs/
└── demo/
```

## 8. Deployment Principle

The repository is a monorepo, but not every component must run on the same machine.

- Web/control plane: Vercel-compatible.
- Persistent database: external PostgreSQL or another deployment chosen later.
- Heavy AI worker: Radeon Cloud.
- Local demo indexes: Radeon worker or development machine.

This is intentional hybrid architecture, not a deployment compromise.

## 9. First Engineering Milestone

1. Start Next.js web app.
2. Start FastAPI control plane.
3. `GET /api/health` returns healthy status.
4. Web displays Nexus Core status.
5. World Selector lists all four Worlds.
6. Deploy the web/control-plane foundation to Vercel.
7. Add Radeon Cloud worker connectivity in the next compute milestone.
