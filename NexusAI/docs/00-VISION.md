# NexusAI Vision

**Version:** 1.0  
**Status:** Approved for MVP  
**Project:** NexusAI

## Vision

NexusAI is a GPU-accelerated Universal Knowledge Intelligence Platform that transforms unstructured information into interactive, explorable worlds.

Instead of reducing every dataset to a chatbot conversation, NexusAI ingests information, extracts structure, connects entities and events, and presents the resulting knowledge through domain-specific visual experiences.

## Mission

Transform fragmented information into connected, visual, explainable knowledge.

## Core Product Idea

Every dataset is represented through a shared World Model:

- World
- Entity
- Relationship
- Event
- Source
- Observation

The shared Nexus Core powers multiple domain experiences called Worlds.

## Initial Worlds

### MemoryWeaver
Transforms personal media and records into explorable memories, timelines, places, and relationship graphs.

### WorldForge
Transforms fictional works and lore into explorable characters, locations, factions, histories, and relationships.

### Detective
Transforms investigation material into evidence graphs, timelines, source-backed observations, and contradiction analysis. AI-generated inferences must be clearly distinguished from verified source facts.

### CodeVerse
Transforms source-code repositories into interactive software maps and 3D cities representing architecture, dependencies, execution paths, quality signals, and performance information.

## Product Principles

1. **Visual before textual**  
   Show relationships and structure whenever visualization communicates them better than prose.

2. **Graph before LLM**  
   Deterministic retrieval and structured graph queries should find relevant information. The LLM reasons over retrieved context rather than acting as the database.

3. **One Core, Many Worlds**  
   Domain experiences reuse a shared ingestion, world-model, graph, retrieval, and reasoning foundation.

4. **Local and open-source first**  
   Avoid paid AI APIs. Prefer open-source models and local or hackathon-provided AMD Radeon Cloud compute.

5. **Progressive intelligence**  
   The interface remains responsive while expensive processing continues asynchronously.

6. **Evidence and inference are different**  
   NexusAI preserves provenance and confidence so users can distinguish source-backed facts from model-generated observations.

## Differentiator

Typical AI application:

Upload → LLM → Chat

NexusAI:

Upload → Parse → Understand → Connect → Retrieve → Visualize → Explore → Reason

## AMD Radeon Strategy

AMD Radeon Cloud and ROCm are used for compute-heavy AI workloads such as:

- local LLM inference
- embedding generation
- speech transcription
- vision understanding
- object detection
- OCR acceleration where supported
- other GPU-compatible model inference

The user-facing web experience must remain usable independently of long-running GPU jobs.

## Success Criteria

A successful hackathon release allows a user to:

1. Enter NexusAI and select a World.
2. Import or select a dataset.
3. See the dataset represented as structured knowledge.
4. Explore entities, relationships, events, and sources visually.
5. Ask natural-language questions.
6. Receive answers grounded in retrieved graph/source context.
7. Inspect why an answer was produced.
8. Experience at least one visually memorable flagship workflow.

## Product Positioning

NexusAI is not four unrelated applications. MemoryWeaver, WorldForge, Detective, and CodeVerse are demonstrations of a shared Universal Knowledge Intelligence Platform.

The hackathon release is the first product milestone, not an architectural dead end.
