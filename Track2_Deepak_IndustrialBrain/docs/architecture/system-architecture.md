# IndusMind AI System Architecture

```mermaid
flowchart LR
    U[Admin / Engineer] --> R[React + TypeScript]
    R -->|JWT REST API| S[Spring Boot]
    S --> AUTH[Spring Security]
    S --> PG[(PostgreSQL)]
    S --> FILES[(Original Files)]
    S -->|Internal REST| F[FastAPI AI Service]
    F --> EX[PyPDF / DOCX / CSV extraction]
    EX --> OCR[Tesseract OCR fallback]
    EX --> ENT[Entity + event extraction]
    ENT --> CHUNK[Page-aware chunking]
    CHUNK --> V[(ChromaDB)]
    V --> RET[Evidence retrieval]
    RET --> G{Gemini key?}
    G -->|Yes| GEM[Gemini grounded generation]
    G -->|No| OFF[Offline evidence summary]
    GEM --> CITE[Citations + confidence]
    OFF --> CITE
    CITE --> S
```

## Responsibility boundaries

- React presents workflows but never calls the AI service directly.
- Spring Boot is the system of record and security boundary.
- PostgreSQL stores users, document metadata, and query logs.
- FastAPI owns document intelligence, retrieval, citations, and RCA support.
- ChromaDB runs in embedded persistent mode, avoiding another server.
- Gemini is optional; evidence retrieval and deterministic summaries work offline.

