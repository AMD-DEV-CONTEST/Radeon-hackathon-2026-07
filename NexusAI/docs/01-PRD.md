# NexusAI Product Requirements Document

**Version:** 1.0  
**Scope:** Hackathon MVP

## 1. Product Summary

NexusAI converts heterogeneous, unstructured data into a shared knowledge representation and exposes that knowledge through interactive domain-specific Worlds.

## 2. Primary User Journey

1. User opens NexusAI.
2. User enters the World Selector.
3. User selects MemoryWeaver, WorldForge, Detective, or CodeVerse.
4. User imports supported data or opens a prepared demo dataset.
5. NexusAI creates an ingestion job and displays progress.
6. Parsed information is converted into the Nexus World Model.
7. The user explores a visual representation.
8. The user asks a question.
9. NexusAI retrieves relevant graph/source context.
10. The reasoning layer generates a grounded explanation.
11. The UI highlights relevant visual nodes and sources.

## 3. MVP Requirements

### Platform
- Responsive web interface.
- Four selectable Worlds.
- Shared Nexus Core.
- Health/status endpoint.
- Processing-job status.
- Source provenance.
- Basic natural-language query interface.
- Streaming or progressive response UX.

### Ingestion
MVP support should prioritize:
- TXT
- Markdown
- PDF text extraction
- images
- audio
- Git repositories or repository ZIPs

Additional formats may be added after the core pipeline works.

### World Model
The platform must support:
- worlds
- entities
- relationships
- events
- sources
- observations
- provenance
- confidence metadata

### Retrieval
- Structured filtering/querying.
- Graph traversal.
- Vector similarity where appropriate.
- Hybrid retrieval interface for the reasoning layer.

### AI
- Open-source/local-first models.
- AMD Radeon Cloud for heavy inference.
- Model adapters so individual models can be replaced.
- LLM must not be the authoritative data store.

## 4. World Requirements

### MemoryWeaver MVP
- Import a small prepared media dataset.
- Display a timeline.
- Display people/event/location relationships.
- Open source items connected to a memory.
- Ask grounded questions about the imported dataset.

### WorldForge MVP
- Import a story/lore document.
- Extract characters, locations, factions, and events.
- Display a relationship graph.
- Display a story timeline.
- Ask questions grounded in the source material.

### Detective MVP
- Import a prepared fictional/synthetic case dataset.
- Display an evidence board and timeline.
- Link claims and observations to sources.
- Flag potential contradictions as AI-assisted observations, never unquestionable facts.
- Allow users to inspect supporting evidence.

### CodeVerse MVP
- Analyze a supported repository.
- Extract files, classes/functions where supported, and dependencies.
- Display a dependency graph.
- Render a simplified 3D software city.
- Ask architecture questions grounded in parsed repository data.

## 5. Non-Goals for MVP

- Production-scale multi-tenancy.
- Enterprise authentication.
- Processing arbitrary petabyte-scale datasets.
- Perfect support for every programming language.
- Real-world law-enforcement decision automation.
- Autonomous conclusions about guilt, identity, or intent.
- Replacing professional investigative or legal judgment.
- Training foundation models from scratch.

## 6. Performance Goals

- UI navigation should feel immediate.
- Long-running ingestion must be asynchronous from the user's perspective.
- Previously processed demo datasets should load quickly.
- AI output should stream when possible.
- Visualizations must not wait for LLM completion before showing retrieved context.

## 7. Cost Constraint

Hackathon development and demo operation target: **₹0 direct spend**.

Use:
- open-source software
- free development tooling
- AMD Radeon Cloud instances supplied by the hackathon
- local development resources

## 8. Demo Success

The flagship demo should demonstrate:
- real ingestion or a small live ingestion sample
- a preprocessed rich dataset
- interactive graph exploration
- visible source grounding
- GPU-backed AI inference
- one memorable visual transformation, with CodeVerse 3D as the leading candidate
