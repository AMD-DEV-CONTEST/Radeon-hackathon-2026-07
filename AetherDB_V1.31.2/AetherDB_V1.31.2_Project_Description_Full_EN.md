# AetherDB V1.31.2 Project Description and Advantages / Limitations

## Project Overview

AetherDB V1.31.2 is a local-first desktop application designed for
long-form writing, world-building management, IP creation, and
multimodal creative workflows.

Unlike traditional AI writing assistants that only provide text
generation, AetherDB integrates creation, retrieval, generation, review,
binding, and archiving into one controlled environment.

Core capabilities include:

-   Long-form work and chapter management
-   Structured world knowledge management
-   Character, location, organization, event, item, and rule management
-   Relationship and timeline management
-   Entity state tracking
-   Local full-text search and vector retrieval
-   RAG context retrieval
-   AI-assisted analysis and creation
-   Image, audio, and media asset management
-   Multimodal content workflow management
-   Unified model routing for local models, Ollama, and cloud APIs
-   Resource scheduling and isolated model workers
-   AMD Radeon GPU / ROCm execution verification

The project goal is:

> Build a controllable creative intelligence environment where writers
> can manage knowledge, use AI assistance, generate multimodal assets,
> and maintain long-term creative consistency.

------------------------------------------------------------------------

# Problems Addressed

## 1. Fragmented world-building information

Long-form creators usually store information across:

-   Manuscripts
-   Notes
-   Spreadsheets
-   Chat records
-   Images
-   Audio files
-   Different document versions

As projects grow, maintaining consistency becomes increasingly
difficult.

AetherDB organizes these materials into structured databases with
entities, relationships, timelines, and searchable knowledge.

## 2. Long-context AI reliability problems

Large language models may experience:

-   Context forgetting
-   Logical deviation
-   Incorrect assumptions
-   World setting conflicts
-   Hallucinated information

The problem is not only context length, but also that models cannot
reliably know what information they have forgotten.

AetherDB uses:

-   Local BGE-M3 embeddings
-   Full-text search
-   Scope filtering
-   Evidence-based context packaging

to provide relevant information before AI execution.

## 3. AI output should not directly modify official data

AI-generated content may contain errors.

Therefore AetherDB uses:

-   Preview results
-   Temporary changes
-   ChangeSet confirmation
-   User approval

before writing content into official databases.

## 4. Lack of unified multimodal asset management

Generated images and audio should not exist as isolated files.

AetherDB binds assets with:

-   Works
-   Chapters
-   Characters
-   Scenes
-   Timeline states
-   World settings

so they can be searched, reviewed, and reused.

------------------------------------------------------------------------

# System Architecture

## Frontend

Technology:

-   Vue 3
-   Vite
-   Pinia
-   Vue Router
-   vue-i18n
-   Tauri 2

Provides:

-   Writing workspace
-   World management
-   AI configuration
-   Model management
-   Media workflow interface
-   Review and approval interface

## Backend Control Layer

Responsibilities:

-   Data access
-   Permission control
-   Model routing
-   Task management
-   Worker management
-   Resource scheduling
-   Context construction
-   Output verification
-   Database writing control

## Data Layer

Based on:

-   SQLite
-   WAL
-   FTS5
-   sqlite-vec

Stores:

-   Chapters
-   Entities
-   Relationships
-   Timelines
-   Models
-   Tasks
-   Media assets
-   Vector indexes
-   Audit records

## Model Execution Layer

Supports:

-   Native AetherDB workers
-   Ollama runtime
-   OpenAI-compatible APIs
-   Cloud providers
-   Image/audio workers

All model execution is controlled through unified routing and resource
scheduling.

------------------------------------------------------------------------

# Local RAG and BGE-M3

AetherDB uses BGE-M3 as its default multilingual embedding model.

It provides:

-   Semantic retrieval
-   Chapter retrieval
-   Entity retrieval
-   World knowledge retrieval
-   RAG context selection

The embedding system is independently managed by AetherDB.

Ollama and cloud models are generation providers and do not replace the
core retrieval system.

------------------------------------------------------------------------

# Ollama and Cloud API Integration

Ollama is supported as an external local model runtime.

Users may install their own models for:

-   Text polishing
-   Expansion
-   Continuation
-   Rewrite
-   Translation
-   Local creative assistance

AetherDB does not restrict user model selection.

Instead, AetherDB controls:

-   Data scope
-   Context delivery
-   Resource allocation
-   Tool permissions
-   Database write approval

Cloud APIs can also be configured by users.

AetherDB does not automatically upload complete user databases or
manuscripts.

------------------------------------------------------------------------

# Multimodal Creation

## Image Generation

AetherDB can transform:

-   Chapters
-   Characters
-   Scenes
-   World settings

into visual generation workflows.

Generated results enter temporary assets before user approval.

## Image Retrieval

Supports:

-   Text-to-image retrieval
-   Image-to-image retrieval
-   Multimodal search
-   Chapter and entity filtering

## Audio and TTS

Supports:

-   Chapter narration
-   Voice profiles
-   Segmented generation
-   Retry
-   Audio merging
-   Asset binding

------------------------------------------------------------------------

# AMD Radeon GPU / ROCm Adaptation

AetherDB follows:

> Proven, verifiable, reproducible execution.

The project does not claim AMD acceleration only through configuration
labels.

Verification includes:

-   Device detection
-   ROCm runtime checks
-   GPU computation tests
-   Worker execution evidence
-   Backend identification
-   Memory usage records

When AMD acceleration is required, silent fallback is avoided.

------------------------------------------------------------------------

# Main Advantages

## 1. Local-first data ownership

User manuscripts, world settings, relationships, images, and audio
assets remain locally managed.

## 2. Controlled AI workflow

AI suggestions do not directly modify official project data.

## 3. Unified creative knowledge system

Text, structured knowledge, images, and audio are managed inside the
same project scope.

## 4. Flexible model ecosystem

Supports:

-   Native models
-   Ollama
-   Local APIs
-   Cloud APIs
-   Remote inference services

## 5. Resource scheduling and worker isolation

Reduces:

-   Model crashes
-   Memory conflicts
-   GPU resource competition
-   Uncontrolled execution

## 6. Real AMD ecosystem support

ROCm compatibility is demonstrated through actual execution evidence.

------------------------------------------------------------------------

# Current Limitations

## 1. Distribution stability

The development environment is stable, but packaged releases may behave
differently across user environments.

Possible issues include:

-   Different Windows versions
-   Permission differences
-   Firewall restrictions
-   Port conflicts
-   Driver differences
-   ROCm/CUDA differences
-   Missing dependencies

The project is improving:

-   Health checks
-   Dynamic ports
-   Error reporting
-   Worker recovery
-   Cross-platform testing

## 2. User-provided multimodal model configuration

The released application does not bundle all large generation models.

Users need to provide:

-   Ollama models
-   Local APIs
-   Self-hosted services
-   Cloud APIs

AetherDB manages workflow, routing, context, and assets rather than
providing all models and computing resources.

## 3. Hardware requirements

Large AI models require sufficient:

-   Memory
-   VRAM
-   Storage
-   Driver support

## 4. Third-party model differences

Different models may have different:

-   Quality
-   Compatibility
-   Performance
-   Hardware requirements

## 5. External runtime dependency

Ollama and cloud services are external components and their internal
changes cannot be completely controlled.

## 6. Multimodal validation is ongoing

Vision models, image generation models, and TTS systems require
continuous validation across different platforms.

## 7. Development-stage product

AetherDB V1.31.2 is a feature-complete engineering version under active
development, testing, and optimization.

It is not yet a fully mature commercial product covering every possible
environment.

------------------------------------------------------------------------

# Security Principles

AetherDB follows:

-   API keys are never exposed through URLs
-   Private keys are excluded from releases
-   Models cannot directly modify official databases
-   Models cannot directly execute shell commands
-   User data is excluded from source packages
-   Logs are sanitized
-   Model verification uses hashes and manifests
-   GPU acceleration claims require real evidence

------------------------------------------------------------------------

# Competition Demonstration Focus

Recommended demonstration flow:

1.  Open a project and chapter.
2.  Show structured world information.
3.  Retrieve context using local BGE-M3.
4.  Execute AI assistance.
5.  Generate visual/audio assets.
6.  Review generated results.
7.  Bind assets back to chapters and entities.
8.  Show AMD GPU / ROCm execution evidence.

------------------------------------------------------------------------

# Conclusion

AetherDB V1.31.2 provides:

-   Local-first creative management
-   Structured world knowledge
-   Native RAG capability
-   Multimodal asset management
-   Flexible AI integration
-   Worker-based execution isolation
-   AMD ROCm verification capability

Current limitations mainly include:

-   Cross-environment release stability
-   User model configuration requirements
-   Hardware requirements
-   Continuous multimodal validation

AetherDB is positioned as:

"A local-first creative intelligence platform combining structured
knowledge management, controllable AI workflows, multimodal asset
management, and verified hardware acceleration support."
