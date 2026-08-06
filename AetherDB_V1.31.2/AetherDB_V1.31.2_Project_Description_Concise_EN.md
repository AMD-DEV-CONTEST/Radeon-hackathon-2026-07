# AetherDB V1.31.2 Project Description and Advantages / Limitations

## 1. Project Overview

AetherDB V1.31.2 is a local-first desktop application designed for
long-form writing, world-building management, IP creation, and
multimodal creative workflows.

Unlike a simple AI chat assistant, AetherDB provides an integrated
environment for:

-   Long-form document and chapter management
-   Structured world knowledge management
-   Character, location, event, organization, and relationship
    management
-   Timeline and entity state tracking
-   Local search and vector retrieval
-   RAG-based context retrieval
-   AI-assisted analysis and creation
-   Image, audio, and media asset management
-   Multimodal generation workflow management
-   Unified routing for local models, Ollama, and cloud APIs
-   Model resource scheduling and isolated worker execution
-   AMD Radeon GPU / ROCm execution verification

The goal is to provide a complete workflow:

Creation → Retrieval → Generation → Review → Binding → Archive

rather than separating writing, AI tools, images, audio, and knowledge
management into independent applications.

------------------------------------------------------------------------

# 2. Problems Addressed

## Long-form context management

Large creative projects contain thousands of pages of information,
including characters, relationships, events, locations, and rules.

Traditional AI tools often suffer from:

-   Context forgetting
-   Logical deviation
-   Incorrect assumptions
-   World setting conflicts
-   Hallucinated information

AetherDB uses structured databases, local vector retrieval, scope
filtering, and evidence-based context packaging to provide relevant
information before model execution.

## AI output reliability

AI-generated content should not directly modify official project data.

AetherDB uses:

-   Preview results
-   Temporary changes
-   ChangeSet confirmation
-   User approval

to ensure generated content only becomes official after review.

## Multimodal asset management

Generated images and audio are stored as managed assets instead of
isolated files.

Assets can be connected with:

-   Chapters
-   Characters
-   Scenes
-   Timeline states
-   World settings
-   Generation information

------------------------------------------------------------------------

# 3. Core Architecture

## Frontend

Technologies:

-   Vue 3
-   Vite
-   Pinia
-   Vue Router
-   Tauri 2

Provides:

-   Writing workspace
-   World database management
-   AI configuration
-   Model management
-   Media workflow interface
-   User review and approval

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
-   Ollama local runtime
-   OpenAI-compatible APIs
-   Cloud providers
-   Specialized image/audio workers

All model tasks are controlled by unified routing and resource
scheduling.

------------------------------------------------------------------------

# 4. Local RAG and BGE-M3

AetherDB uses BGE-M3 as its default multilingual text embedding model.

It handles:

-   Chapter embeddings
-   World knowledge retrieval
-   Entity retrieval
-   RAG context selection
-   Semantic search

The embedding system is managed by AetherDB itself, including:

-   Model version
-   Hash verification
-   Vector dimensions
-   Backend selection
-   Runtime evidence

Ollama and cloud models may handle generation tasks, but they do not
replace AetherDB's core retrieval system.

------------------------------------------------------------------------

# 5. Ollama and Cloud API Integration

Ollama is supported as an external local model runtime.

Users may install their own models for:

-   Text polishing
-   Expansion
-   Continuation
-   Rewrite
-   Translation
-   Local creative assistance

AetherDB does not restrict user model choices.

However, AetherDB controls:

-   Data access scope
-   Context delivery
-   Resource usage
-   Tool permissions
-   Database write approval

Cloud APIs are also supported through user configuration.

AetherDB does not require cloud models and does not automatically upload
complete user databases.

------------------------------------------------------------------------

# 6. Multimodal Creation

## Image generation

Users can create visual assets from:

-   Chapters
-   Characters
-   Scenes
-   World settings

Generated assets enter temporary review status before becoming official
assets.

## Image retrieval

Supports:

-   Text-to-image search
-   Image-to-image search
-   Multimodal retrieval
-   Work/chapter/entity filtering

## Audio and TTS

The audio system supports:

-   Chapter narration
-   Voice profiles
-   Segment generation
-   Retry
-   Audio merging
-   Asset binding

------------------------------------------------------------------------

# 7. AMD Radeon GPU / ROCm Compatibility

AetherDB follows the principle:

"Proven, verifiable, reproducible."

The project does not claim GPU acceleration only through configuration
labels.

Verification includes:

-   Device detection
-   ROCm runtime verification
-   GPU computation tests
-   Worker execution evidence
-   Backend identification
-   Memory usage records

The project avoids silent fallback when AMD acceleration is required.

------------------------------------------------------------------------

# 8. Main Advantages

## 1. Local-first data ownership

User manuscripts, world settings, relationships, images, and audio
assets remain locally managed.

## 2. Controlled AI workflow

AI suggestions do not directly modify official data.

## 3. Unified world knowledge and multimodal assets

Text, images, audio, and structured knowledge exist inside the same
project scope.

## 4. Flexible model ecosystem

Supports:

-   Native models
-   Ollama
-   Local APIs
-   Cloud APIs
-   Remote inference services

## 5. Advanced resource management

Worker isolation reduces:

-   Model crashes
-   Memory conflicts
-   GPU resource competition
-   Uncontrolled execution

## 6. Real AMD ecosystem integration

ROCm support is demonstrated through actual execution verification
instead of simple claims.

## 7. Designed for long-term creation

AetherDB focuses on maintaining creative assets over time, not only
generating temporary content.

------------------------------------------------------------------------

# 9. Current Limitations

## 1. Distribution stability

The development environment is stable, but packaged releases may
encounter issues on different user machines.

Possible causes:

-   Different Windows versions
-   Permissions
-   Firewall/security software
-   Port conflicts
-   Driver differences
-   ROCm/CUDA differences
-   Missing dependencies
-   Model environment differences

The project is improving:

-   Health checks
-   Dynamic ports
-   Error reporting
-   Worker recovery
-   Cross-platform testing

## 2. Multimodal models require user configuration

The released application does not bundle all large generation models.

Users need to provide:

-   Ollama models
-   Local APIs
-   Self-hosted services
-   Cloud APIs

AetherDB provides workflow management, routing, context control, and
asset management rather than all AI models and computing resources.

## 3. Hardware requirements

Large AI models require:

-   More memory
-   More VRAM
-   Suitable drivers
-   Larger storage

## 4. Third-party model differences

Model quality, compatibility, and performance depend on the selected
model.

## 5. External runtime dependency

Ollama and cloud services are external components. Their updates and
behavior cannot be completely controlled by AetherDB.

## 6. Multimodal validation is ongoing

Image generation, vision models, and TTS require continuous testing
across:

-   Windows
-   Linux
-   ROCm
-   CUDA
-   CPU environments

## 7. Not yet a fully commercial release

AetherDB V1.31.2 is a feature-complete engineering version under active
development, testing, and cross-platform improvement.

------------------------------------------------------------------------

# 10. Security Boundaries

AetherDB follows these principles:

-   API keys are not exposed through URLs
-   Private keys are excluded from releases
-   Models cannot directly modify official databases
-   Models cannot directly execute shell commands
-   User data is not included in source packages
-   Logs are sanitized
-   Model verification uses manifests and hashes
-   GPU capability claims require real evidence

------------------------------------------------------------------------

# 11. Competition Demonstration Focus

Recommended demonstration:

1.  Open a project and chapter.
2.  Show structured world information.
3.  Retrieve related context using local BGE-M3.
4.  Execute AI assistance through configured models.
5.  Generate visual/audio assets.
6.  Review and approve generated assets.
7.  Bind assets back to chapters and entities.
8.  Display AMD GPU / ROCm execution evidence.

------------------------------------------------------------------------

# 12. Conclusion

AetherDB V1.31.2 provides:

-   Local-first creative management
-   Structured world knowledge
-   Native RAG capability
-   Multimodal asset management
-   Flexible AI model integration
-   Worker-based execution isolation
-   AMD ROCm verification capability

Its current limitations are mainly related to:

-   Cross-environment packaging stability
-   User-provided model configuration
-   Hardware requirements
-   Continuous multimodal validation

AetherDB is positioned as:

"A local-first creative intelligence platform with structured knowledge
management, controllable AI workflows, multimodal asset management, and
verified hardware acceleration support."
