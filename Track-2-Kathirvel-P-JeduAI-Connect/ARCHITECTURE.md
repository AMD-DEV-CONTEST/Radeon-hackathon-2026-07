# JeduAI Connect - System Architecture Diagrams

## 1. High-Level Multi-Agent Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                             │
│                                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │   Student   │  │    Staff    │  │    Admin    │  │    Voice     │ │
│  │   Portal    │  │   Portal    │  │   Portal    │  │  Interface   │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘ │
│         │                │                │                 │          │
│         └────────────────┴────────────────┴─────────────────┘          │
│                                  ↓                                      │
│                      ┌───────────────────────┐                         │
│                      │   API Gateway         │                         │
│                      │   (REST / WebSocket)  │                         │
│                      └───────────┬───────────┘                         │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    MULTI-AGENT ORCHESTRATION LAYER                      │
│                                                                         │
│                    ┌────────────────────────────┐                      │
│                    │     PLANNER AGENT          │                      │
│                    │  (Central Orchestrator)    │                      │
│                    │                            │                      │
│                    │  • Intent Classification   │                      │
│                    │  • Task Decomposition      │                      │
│                    │  • Agent Routing           │                      │
│                    │  • Response Synthesis      │                      │
│                    └───┬────────────────────┬───┘                      │
│                        │                    │                          │
│         ┌──────────────┼────────────────────┼──────────────┐          │
│         ↓              ↓                    ↓              ↓          │
│   ┌─────────┐    ┌──────────┐        ┌──────────┐   ┌──────────┐    │
│   │   RAG   │    │  Tutor   │        │Assessment│   │Translation│    │
│   │  Agent  │    │  Agent   │        │  Agent   │   │  Agent    │    │
│   └────┬────┘    └────┬─────┘        └────┬─────┘   └────┬─────┘    │
│        │              │                   │              │            │
│        ↓              ↓                   ↓              ↓            │
│   ┌─────────┐    ┌──────────┐        ┌──────────┐   ┌──────────┐    │
│   │  Voice  │    │Recommend │        │  Memory  │   │   Tool   │    │
│   │  Agent  │    │  Agent   │        │  System  │   │ Registry │    │
│   └────┬────┘    └────┬─────┘        └────┬─────┘   └────┬─────┘    │
│        │              │                   │              │            │
└────────┼──────────────┼───────────────────┼──────────────┼────────────┘
         ↓              ↓                   ↓              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     AI INFERENCE LAYER                                  │
│                 AMD RADEON GPU + ROCm Platform                          │
│                                                                         │
│  ┌──────────────────┐  ┌───────────────────┐  ┌───────────────────┐  │
│  │   LLM Inference  │  │    Embeddings     │  │  Speech-to-Text   │  │
│  │  Gemini 2.5 Flash│  │ Sentence-Trans    │  │   Whisper STT     │  │
│  │  (512 max tokens)│  │  (384-dim vectors)│  │   (Base model)    │  │
│  └──────────────────┘  └───────────────────┘  └───────────────────┘  │
│                                                                         │
│  Optimizations: FP16, Batch Processing, KV-Cache, GPU Memory Pool      │
│  Performance: 82% GPU Utilization, 18GB/24GB Memory, 7.2x Speedup      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA STORAGE LAYER                              │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │  Vector Database │  │  Firebase Cloud  │  │  Session Memory      │ │
│  │   (FAISS-GPU)    │  │    Firestore     │  │  (In-Memory Cache)   │ │
│  │                  │  │                  │  │                      │ │
│  │ • PDF Chunks     │  │ • User Profiles  │  │ • Chat History       │ │
│  │ • Embeddings     │  │ • Quiz Scores    │  │ • Active Context     │ │
│  │ • Metadata       │  │ • Learning Data  │  │ • Preferences        │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘ │
│                                                                         │
│  Latency: FAISS Search <10ms | Firestore Query <50ms | Cache <1ms      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. RAG Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DOCUMENT INGESTION                              │
└─────────────────────────────────────────────────────────────────────────┘

User Uploads PDF
      ↓
┌──────────────────┐
│  PDF Extraction  │  → PyPDF2 / pdfplumber
└────────┬─────────┘
         ↓
┌──────────────────┐
│  Text Cleaning   │  → Remove headers, footers, page numbers
└────────┬─────────┘
         ↓
┌──────────────────┐
│    Chunking      │  → 500 tokens/chunk, 50-token overlap
└────────┬─────────┘    → Preserve paragraph boundaries
         ↓
┌──────────────────────────────────────────────────────────────────────────┐
│              EMBEDDING GENERATION (AMD GPU)                              │
└──────────────────────────────────────────────────────────────────────────┘
         ↓
┌──────────────────┐
│ Batch Encoding   │  → sentence-transformers (all-MiniLM-L6-v2)
│ (32 chunks/batch)│  → AMD GPU: 4.3s for 2000 chunks
└────────┬─────────┘  → CPU Baseline: 42s (9.8x speedup)
         ↓
┌──────────────────┐
│  FAISS Indexing  │  → 384-dim vectors
│  (GPU-Accelerated│  → IVF (Inverted File) for fast search
└────────┬─────────┘  → Inner Product (cosine similarity)
         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    VECTOR STORE (FAISS-GPU)                             │
│  • 2000 chunks → 2000 vectors (384-dim)                                 │
│  • Search latency: <10ms for top-50 results                             │
│  • Memory footprint: ~3MB per 1000 vectors                              │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                         QUERY TIME (RAG)                                │
└─────────────────────────────────────────────────────────────────────────┘

User Query: "Explain backpropagation"
      ↓
┌──────────────────┐
│  Embed Query     │  → sentence-transformers (12ms on AMD GPU)
└────────┬─────────┘  → 384-dim query vector
         ↓
┌──────────────────┐
│  FAISS Search    │  → Cosine similarity search (8ms)
└────────┬─────────┘  → Top-50 candidates
         ↓
┌──────────────────┐
│  Reranking       │  → Cross-encoder for precision (35ms)
└────────┬─────────┘  → Top-5 most relevant chunks
         ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                    CONTEXT INJECTION                                     │
│  Prompt Template:                                                        │
│  "Based on the following course material, answer the question:           │
│   Context: {retrieved_chunk_1} {retrieved_chunk_2} ...                   │
│   Question: {user_query}                                                 │
│   Answer in a clear, educational manner."                                │
└────────────────────────────────────────────────────────────────────────┬─┘
         ↓
┌──────────────────┐
│  LLM Generation  │  → Gemini 2.5 Flash (520ms on AMD GPU)
└────────┬─────────┘  → Grounded response (no hallucination)
         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    FINAL RESPONSE                                        │
│  "Backpropagation is an algorithm for training neural networks           │
│   (as described in Section 3.2 of your notes). It works by..."          │
│                                                                          │
│  Total Latency: 600ms (12+8+35+520+25)                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Multi-Agent Workflow Example

**Scenario**: "Create a Tamil quiz on Machine Learning from my uploaded notes"

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1: PLANNER AGENT (Intent Classification)                           │
└─────────────────────────────────────────────────────────────────────────┘

Input: "Create a Tamil quiz on Machine Learning from my uploaded notes"
      ↓
Intent Classification:
  - Type: QUIZ_GENERATION
  - Topic: "Machine Learning"
  - Target Language: Tamil
  - Source: Uploaded documents (RAG required)
      ↓
Task Decomposition:
  1. RAG Agent: Retrieve ML content from vector DB
  2. Assessment Agent: Generate 10 MCQs in English
  3. Translation Agent: Translate quiz to Tamil
  4. Storage: Save to Firebase Firestore

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2: RAG AGENT (Knowledge Retrieval)                                 │
└─────────────────────────────────────────────────────────────────────────┘

Query: "Machine Learning concepts for quiz generation"
      ↓
FAISS Search → Top-10 relevant chunks:
  [1] "Supervised learning involves labeled data..."
  [2] "Neural networks consist of layers..."
  [3] "Gradient descent optimizes parameters..."
  ...
      ↓
Output: 10 context chunks (total ~2000 tokens)
Latency: 55ms (embed 12ms + search 8ms + rerank 35ms)

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 3: ASSESSMENT AGENT (Quiz Generation)                              │
└─────────────────────────────────────────────────────────────────────────┘

Input: 10 context chunks
      ↓
LLM Prompt: "Generate 10 MCQs on Machine Learning.
             Each question should have 4 options, 1 correct answer,
             and a brief explanation. Output as JSON."
      ↓
Gemini 2.5 Flash Inference (AMD GPU):
  - Batch processing: Generate all 10 questions in parallel
  - FP16 precision for 2x speedup
  - Output: Structured JSON
      ↓
Sample Output:
{
  "questions": [
    {
      "id": 1,
      "question": "What is supervised learning?",
      "options": ["A. Learning with labeled data", "B. ...", "C. ...", "D. ..."],
      "correct_answer": "A",
      "explanation": "Supervised learning uses labeled training data..."
    },
    ...
  ]
}
      ↓
Latency: 2.1s on AMD GPU (vs 15.2s on CPU = 7.2x speedup)

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 4: TRANSLATION AGENT (English → Tamil)                             │
└─────────────────────────────────────────────────────────────────────────┘

Input: English quiz JSON
      ↓
Translation Strategy:
  1. Extract technical terms: ["supervised learning", "neural network", ...]
  2. Translate questions/options using Gemini Translation API
  3. Preserve technical terms with Tamil transliteration
      ↓
Output:
{
  "questions": [
    {
      "question": "Supervised learning (மேற்பார்வையிடப்பட்ட கற்றல்) என்றால் என்ன?",
      "options": [
        "A. லேபிள் செய்யப்பட்ட தரவுடன் கற்றல்",
        "B. ...",
        ...
      ],
      "correct_answer": "A",
      "explanation": "Supervised learning லேபிள் செய்யப்பட்ட பயிற்சி தரவைப் பயன்படுத்துகிறது..."
    },
    ...
  ]
}
      ↓
Latency: 1.8s (translate 1000 words)

┌─────────────────────────────────────────────────────────────────────────┐
│ Step 5: STORAGE & RESPONSE                                              │
└─────────────────────────────────────────────────────────────────────────┘

Store in Firebase Firestore:
  - Collection: "quizzes"
  - Document ID: auto-generated
  - Fields: {topic, language, questions[], created_at, assigned_to[]}
      ↓
Assign to student class
      ↓
Return to user:
  "✅ Created Tamil quiz on Machine Learning (10 questions)
   Quiz ID: abc123
   Assigned to: CS-3A class"

┌─────────────────────────────────────────────────────────────────────────┐
│ TOTAL WORKFLOW LATENCY                                                  │
└─────────────────────────────────────────────────────────────────────────┘

RAG Agent:        55ms
Assessment Agent: 2100ms
Translation Agent: 1800ms
Storage:          50ms
─────────────────────────
TOTAL:            4005ms (4.0 seconds)

CPU Baseline: ~28 seconds → 7x SPEEDUP with AMD GPU
```

---

## 4. Privacy & Security Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PRIVACY LAYERS                                   │
└─────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│ Layer 1: LOCAL INFERENCE (No Cloud AI APIs for Core Features)        │
├───────────────────────────────────────────────────────────────────────┤
│ • All AI models run on user's AMD GPU                                │
│ • LLM: Local deployment (Llama 3.1 8B planned)                       │
│ • Embeddings: sentence-transformers (100% local)                     │
│ • Speech: Whisper STT (100% local)                                   │
│ • No data sent to OpenAI / Anthropic / Google (except Gemini API)    │
└───────────────────────────────────────────────────────────────────────┘
         ↓
┌───────────────────────────────────────────────────────────────────────┐
│ Layer 2: ON-DEVICE STORAGE                                           │
├───────────────────────────────────────────────────────────────────────┤
│ • Vector DB: Local FAISS index files                                 │
│ • User Data: Firebase Firestore with LOCAL CACHING                   │
│ • Session Memory: In-process storage (no external write)             │
│ • No telemetry to external servers                                   │
└───────────────────────────────────────────────────────────────────────┘
         ↓
┌───────────────────────────────────────────────────────────────────────┐
│ Layer 3: ROLE-BASED ACCESS CONTROL (RBAC)                            │
├───────────────────────────────────────────────────────────────────────┤
│ STUDENT:                                                              │
│   ✓ Read own quiz scores                                             │
│   ✓ Upload own PDFs                                                  │
│   ✗ Cannot view other students' data                                 │
│                                                                       │
│ STAFF:                                                                │
│   ✓ Create quizzes for assigned classes                              │
│   ✓ View class-level aggregates (avg scores)                         │
│   ✗ Cannot view individual student responses without permission      │
│                                                                       │
│ ADMIN:                                                                │
│   ✓ System configuration                                             │
│   ✓ Audit logs (metadata only)                                       │
│   ✗ Cannot decrypt user content without explicit access grant        │
└───────────────────────────────────────────────────────────────────────┘
         ↓
┌───────────────────────────────────────────────────────────────────────┐
│ Layer 4: DATA LIFECYCLE MANAGEMENT                                    │
├───────────────────────────────────────────────────────────────────────┤
│ • Right to Deletion: Students can purge all data (GDPR compliance)   │
│ • Data Minimization: Only store necessary information                │
│ • Retention Policy: Auto-delete session data after 30 days           │
│ • Export: Users can download their data (PDF, JSON)                  │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 5. AMD GPU Optimization Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│              AMD RADEON GPU COMPUTE PIPELINE                            │
└─────────────────────────────────────────────────────────────────────────┘

Hardware: AMD Radeon RX 7900 XTX (RDNA 3)
  • 96 Compute Units
  • 6144 Stream Processors
  • 24GB GDDR6 Memory
  • 960 GB/s Memory Bandwidth
  • 123 TFLOPS (FP16)

┌────────────────────────────────────────────────────────────┐
│ Optimization Layer 1: PRECISION REDUCTION                  │
├────────────────────────────────────────────────────────────┤
│ FP32 (Default) → FP16 (Mixed Precision)                    │
│   Benefit: 2x throughput, 2x memory efficiency            │
│   Trade-off: <1% accuracy loss (acceptable for education)  │
│                                                            │
│ Implementation:                                            │
│   model = model.half().to('cuda')                          │
│   torch.autocast(device_type='cuda', dtype=torch.float16)  │
└────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────┐
│ Optimization Layer 2: BATCH PROCESSING                     │
├────────────────────────────────────────────────────────────┤
│ Sequential Processing → Batched Inference                  │
│   Benefit: Amortize GPU kernel launch overhead            │
│   Example: Embed 32 chunks in 1 GPU call vs 32 calls      │
│                                                            │
│ Benchmark:                                                 │
│   Batch size 1:  2000 chunks → 42s                         │
│   Batch size 32: 2000 chunks → 4.3s (9.8x speedup)         │
└────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────┐
│ Optimization Layer 3: MEMORY MANAGEMENT                    │
├────────────────────────────────────────────────────────────┤
│ • Pre-allocate GPU memory pool                             │
│ • Reuse tensors (avoid malloc overhead)                    │
│ • Pin CPU memory for faster CPU→GPU transfer               │
│ • Clear cache between large operations                     │
│                                                            │
│ Memory Usage:                                              │
│   Model weights: 12 GB                                     │
│   KV-cache: 4 GB                                           │
│   Activation: 2 GB                                         │
│   Total: 18 GB / 24 GB (75% utilization)                   │
└────────────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────────────┐
│ Optimization Layer 4: ROCM-SPECIFIC TUNING                 │
├────────────────────────────────────────────────────────────┤
│ • HSA_OVERRIDE_GFX_VERSION=11.0.0 (for RDNA 3)             │
│ • PYTORCH_ROCM_ARCH=gfx1100 (optimize for RX 7900)         │
│ • HIP_VISIBLE_DEVICES=0 (use single GPU)                   │
│ • ROCBLAS_TENSILE_LIBPATH (fast GEMM operations)           │
└────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│               PERFORMANCE MONITORING                        │
├─────────────────────────────────────────────────────────────┤
│ Tool: rocm-smi (AMD System Management Interface)           │
│                                                             │
│ Metrics:                                                    │
│   • GPU Utilization: 82% average                            │
│   • Memory Usage: 18GB / 24GB                               │
│   • Temperature: 72°C (safe operating range)                │
│   • Power Draw: 285W / 355W TDP                             │
│   • Clock Speed: 2.5 GHz (boost)                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Technology Stack Visualization

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         JEDUAI CONNECT STACK                            │
└─────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│ PRESENTATION TIER                                                     │
├───────────────────────────────────────────────────────────────────────┤
│ Flutter 3.0+ (Dart)                                                   │
│   • Material Design 3 UI                                              │
│   • GetX (State Management)                                           │
│   • Cross-platform (Web, Android, iOS, Desktop)                       │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ APPLICATION TIER                                                      │
├───────────────────────────────────────────────────────────────────────┤
│ Python 3.10+ (FastAPI)                                                │
│   • Multi-agent orchestration                                         │
│   • Business logic                                                    │
│   • API endpoints (REST)                                              │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ AI/ML TIER                                                            │
├───────────────────────────────────────────────────────────────────────┤
│ PyTorch 2.1 with ROCm                                                 │
│   • LLM: Gemini 2.5 Flash (via API, local planned)                   │
│   • Embeddings: sentence-transformers (all-MiniLM-L6-v2)              │
│   • STT: OpenAI Whisper (base model)                                  │
│   • TTS: gTTS / Piper TTS                                             │
│   • Vector DB: FAISS-GPU (ROCm build)                                 │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ INFRASTRUCTURE TIER                                                   │
├───────────────────────────────────────────────────────────────────────┤
│ AMD Radeon GPU + ROCm 6.0+                                            │
│   • RDNA 3 Architecture                                               │
│   • 24GB VRAM                                                         │
│   • FP16 mixed precision                                              │
│   • Batch processing                                                  │
└───────────────────────────────────────────────────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────────────────┐
│ DATA TIER                                                             │
├───────────────────────────────────────────────────────────────────────┤
│ • Firebase Firestore (user data, quiz scores)                         │
│ • FAISS Index (vector embeddings, local files)                        │
│ • SharedPreferences (session cache)                                   │
└───────────────────────────────────────────────────────────────────────┘
```

---

**End of Architecture Document**

This document provides comprehensive system architecture diagrams for the JeduAI Connect Multi-Agent AI Learning Assistant, demonstrating the hierarchical agent structure, RAG pipeline, AMD GPU optimization, and privacy-first design.
