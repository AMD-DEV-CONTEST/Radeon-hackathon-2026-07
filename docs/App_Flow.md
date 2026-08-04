# THEMIS — App Flow Document
## Version 1.0 | AMD AI DevMaster Hackathon | July 20, 2026

---

## 1. High-Level Application Flow

```mermaid
flowchart TD
    User([👤 Developer]) --> Dashboard

    Dashboard --> |GitHub PR URL| GH_Flow[GitHub PR Flow]
    Dashboard --> |File Upload| Upload_Flow[File Upload Flow]
    Dashboard --> |Benchmark tab| BM_Flow[Benchmark Flow]

    GH_Flow --> Tribunal[Tribunal View — Live Agent Trace]
    Upload_Flow --> Tribunal

    Tribunal --> |Pipeline complete| Report[Report View]

    Report --> |Approve fixes| Fix[Fix Agent — Open PR]
    Report --> |Report only| Export[Export PDF/JSON]

    Fix --> GitHub[(GitHub API)]
    Fix --> Done([✅ Fix PR Opened])
    Export --> Done2([📄 Report Downloaded])

    BM_Flow --> BenchPanel[Benchmark Panel — ROCm Charts]
```

---

## 2. User Journey: GitHub PR Review Flow

```mermaid
sequenceDiagram
    actor Dev as 👤 Developer
    participant UI as React Frontend
    participant API as FastAPI Backend
    participant GH as GitHub API
    participant Tribunal as LangGraph Agents
    participant vLLM as vLLM Server (ROCm)
    participant Qdrant as Qdrant RAG

    Dev->>UI: Paste GitHub PR URL
    UI->>UI: Validate URL format (regex)
    UI->>API: POST /api/review/github<br>{repo, pr_number}
    API->>API: Authenticate (X-API-Key)
    API->>GH: Get PR metadata + files
    GH-->>API: File list (or 406 if >280 files)

    alt Large PR (>280 files)
        API->>API: git clone fallback path
        API->>API: local git diff
    end

    API->>API: Sanitize diff (injection patterns)
    API-->>UI: 202 Accepted {job_id, stream_url}
    UI->>UI: Navigate to /tribunal
    UI->>API: Open WebSocket /api/review/{id}/stream

    API->>Tribunal: Start LangGraph pipeline
    Note over Tribunal: ① TRIAGE AGENT

    Tribunal-->>UI: WS event: agent_started{triage}
    Tribunal->>Tribunal: Parse diff, detect languages, prioritize
    Tribunal-->>UI: WS event: agent_complete{triage}

    Note over Tribunal: ② SECURITY + ③ STYLE (parallel)

    par Security Agent
        Tribunal-->>UI: WS event: agent_started{security}
        Tribunal->>Tribunal: Run Semgrep (Docker)
        Tribunal->>Tribunal: Run Bandit (Docker)
        Tribunal->>Qdrant: RAG query OWASP/CWE collection
        Qdrant-->>Tribunal: Top-5 citations
        Tribunal->>vLLM: LLM synthesis request
        vLLM-->>Tribunal: Security analysis output
        Tribunal-->>UI: WS event: agent_complete{security, findings}
    and Style Agent
        Tribunal-->>UI: WS event: agent_started{style}
        Tribunal->>Tribunal: Run Pylint/ESLint (Docker)
        Tribunal->>Qdrant: RAG query style collection
        Qdrant-->>Tribunal: Top-5 citations
        Tribunal->>vLLM: LLM synthesis request
        vLLM-->>Tribunal: Style analysis output
        Tribunal-->>UI: WS event: agent_complete{style, findings}
    end

    Note over Tribunal: ④ VERIFIER AGENT

    Tribunal-->>UI: WS event: agent_started{verifier}
    Tribunal->>Qdrant: Cross-check each finding vs RAG
    Tribunal->>Tribunal: CWE ID validation (local lookup)
    Tribunal->>Tribunal: Score confidence 0.0–1.0
    Tribunal->>Tribunal: Filter findings < 0.7
    Tribunal-->>UI: WS event: agent_complete{verifier}

    Tribunal-->>UI: WS event: awaiting_approval
    API-->>UI: Job status: awaiting_approval

    UI->>UI: Navigate to /report/{job_id}
    UI->>Dev: Show findings + Human Approval Gate

    Dev->>UI: Click "Approve & Open Fix PR"
    UI->>UI: Show confirmation modal
    Dev->>UI: Confirm

    UI->>API: POST /api/review/{id}/approve-fix {approved: true}
    API->>Tribunal: Resume — start Fix Agent

    Note over Tribunal: ⑤ FIX AGENT

    Tribunal->>vLLM: Generate patches for each verified finding
    vLLM-->>Tribunal: Code patches
    Tribunal->>GH: Create branch themis/fix-pr-{number}
    Tribunal->>GH: Commit patches
    Tribunal->>GH: Open pull request
    GH-->>Tribunal: fix_pr_url

    Tribunal-->>UI: WS event: pipeline_complete{fix_pr_url}
    UI->>Dev: Show success + link to fix PR
```

---

## 3. User Journey: File Upload Flow

```mermaid
flowchart TD
    A([Developer drags files onto upload zone]) --> B{File types valid?}
    B -- No --> C[Show error: unsupported extension]
    B -- Yes --> D[Files staged in upload UI]
    D --> E[Developer selects analysis scope]
    E --> F[Click Convene Tribunal]
    F --> G[POST /api/review/upload multipart form]
    G --> H[Backend writes files to temp dir]
    H --> I[Files sanitized for injection patterns]
    I --> J[No GitHub diff path — skip to Triage directly]
    J --> K[Navigate to /tribunal]
    K --> L[WebSocket stream opens]
    L --> M[5-agent pipeline runs]
    M --> N[Navigate to /report]
    N --> O{Download only or Apply patches?}
    O -- Download --> P[Export JSON/PDF — no GitHub action]
    O -- Apply --> Q[Developer must provide repo + branch info]
    Q --> R[Fix Agent creates PR]
```

---

## 4. Internal: 5-Agent Pipeline State Machine

```mermaid
stateDiagram-v2
    [*] --> Triage : job submitted

    Triage --> SecurityStyle : triage_complete = true
    Triage --> Error : exception

    state SecurityStyle {
        [*] --> Security
        [*] --> Style
        Security --> [*]
        Style --> [*]
    }

    SecurityStyle --> Verifier : both agents complete (reducer merged findings)
    SecurityStyle --> Error : both agents failed

    Verifier --> AwaitingApproval : verified_findings populated
    Verifier --> ReportOnly : verified_findings empty (no issues found)

    AwaitingApproval --> Fix : fix_approved = true
    AwaitingApproval --> ReportOnly : fix_approved = false (user declines)

    Fix --> Complete : fix_pr_url set
    Fix --> Error : GitHub API failure

    ReportOnly --> Complete
    Complete --> [*]
    Error --> [*]

    note right of Triage
        Loop guard active:
        recursion_limit=30
        SHA-256 tool dedup
    end note

    note right of Verifier
        confidence threshold: 0.7
        CWE ID validation
    end note

    note right of AwaitingApproval
        Human-in-the-loop
        Pause state
        Frontend shows approval gate
    end note
```

---

## 5. WebSocket Event Sequence (Browser → Server)

```mermaid
sequenceDiagram
    participant Browser
    participant FastAPI

    Browser->>FastAPI: WebSocket connect<br>/api/review/{job_id}/stream

    FastAPI-->>Browser: {"event":"connected","job_id":"..."}

    FastAPI-->>Browser: {"event":"agent_started","agent":"triage"}
    FastAPI-->>Browser: {"event":"tool_call","agent":"triage","tool":"diff_parser"}
    FastAPI-->>Browser: {"event":"tool_result","agent":"triage","result":"38 files parsed"}
    FastAPI-->>Browser: {"event":"agent_complete","agent":"triage"}

    FastAPI-->>Browser: {"event":"agent_started","agent":"security"}
    FastAPI-->>Browser: {"event":"agent_started","agent":"style"}

    FastAPI-->>Browser: {"event":"tool_call","agent":"security","tool":"semgrep"}
    FastAPI-->>Browser: {"event":"tool_call","agent":"style","tool":"pylint"}

    FastAPI-->>Browser: {"event":"tool_result","agent":"security","findings_count":3}
    FastAPI-->>Browser: {"event":"rag_retrieved","agent":"security","citations":2}
    FastAPI-->>Browser: {"event":"tool_result","agent":"style","findings_count":2}

    FastAPI-->>Browser: {"event":"agent_complete","agent":"security"}
    FastAPI-->>Browser: {"event":"agent_complete","agent":"style"}

    FastAPI-->>Browser: {"event":"agent_started","agent":"verifier"}
    FastAPI-->>Browser: {"event":"agent_complete","agent":"verifier","verified":4,"filtered":1}

    FastAPI-->>Browser: {"event":"awaiting_approval","verified_findings":4}

    Note over Browser,FastAPI: Browser navigates to /report — user reviews

    Browser->>FastAPI: HTTP POST /api/review/{id}/approve-fix

    FastAPI-->>Browser: {"event":"agent_started","agent":"fix"}
    FastAPI-->>Browser: {"event":"tool_call","agent":"fix","tool":"github_create_branch"}
    FastAPI-->>Browser: {"event":"tool_call","agent":"fix","tool":"github_create_pr"}
    FastAPI-->>Browser: {"event":"pipeline_complete","fix_pr_url":"https://github.com/..."}

    FastAPI->>Browser: WebSocket close (normal closure)
```

---

## 6. Error Flows

### vLLM Unavailable

```mermaid
flowchart TD
    A[Request submitted] --> B[Backend calls vLLM health check]
    B --> C{vLLM responding?}
    C -- Yes --> D[Pipeline starts normally]
    C -- No --> E[Return 503 Service Unavailable]
    E --> F[Frontend shows error banner:<br>"GPU inference server is offline.<br>Try again in a moment."]
    F --> G[Frontend shows 'Retry' button]
    G --> H[User retries after 30s]
    H --> B
```

### Docker Sandbox Timeout

```mermaid
flowchart TD
    A[Agent calls sandboxed tool] --> B[Docker container starts]
    B --> C{Tool completes within 30s?}
    C -- Yes --> D[Return tool output]
    C -- No --> E[Container killed, timeout error]
    E --> F[validate_tool_result returns status:error]
    F --> G[Agent logs timeout, continues without tool output]
    G --> H[Verifier scores this finding lower confidence]
    H --> I[Finding marked: 'static analysis unavailable']
```

### GitHub 406 Large PR

```mermaid
flowchart TD
    A[GitHub PR URL submitted] --> B[Primary path: GitHub API]
    B --> C{>280 files?}
    C -- No --> D[API diff retrieval succeeds]
    C -- Yes --> E[Fallback: git clone --depth=1]
    E --> F[Local git diff command]
    F --> G{Clone succeeds?}
    G -- Yes --> H[Continue with local diff]
    G -- No --> I[Return error: Cannot fetch diff]
    I --> J[Frontend shows specific error with guidance]
```

### GitHub Rate Limit Hit

```mermaid
flowchart TD
    A[GitHub API call] --> B{Response 403/429?}
    B -- No --> C[Return result]
    B -- Yes --> D[Read x-ratelimit-reset header]
    D --> E[Calculate sleep duration]
    E --> F[Sleep until reset + 5s buffer]
    F --> G[Retry once]
    G --> H{Second attempt OK?}
    H -- Yes --> C
    H -- No --> I[Raise exception → pipeline error state]
```

---

## 7. Benchmark Flow

```mermaid
sequenceDiagram
    actor Judge as 👤 Hackathon Judge
    participant BenchUI as Benchmark Panel
    participant API as FastAPI Backend
    participant vLLM as vLLM Server (ROCm)

    Judge->>BenchUI: Navigate to /benchmark
    BenchUI->>API: GET /health
    API-->>BenchUI: {vllm: connected, vram_used_gb: 40.1}
    BenchUI->>BenchUI: Update GPU status pill

    Judge->>BenchUI: Click "Run Full Benchmark Suite"
    BenchUI->>API: GET /api/benchmark
    API->>API: Load 10 standard benchmark prompts

    loop For each benchmark prompt
        API->>vLLM: Inference request (timed)
        vLLM-->>API: Response tokens
        API->>API: Record tok/s, TTFT
    end

    API->>API: Calculate speculative decoding speedup
    API->>API: Calculate INT4 vs FP16 delta
    API-->>BenchUI: Benchmark results JSON

    BenchUI->>BenchUI: Render Recharts with results
    BenchUI->>Judge: Live-animated charts filling in
    Note over BenchUI: "Speculative Decoding Speedup: 1.87×"
    Note over BenchUI: "INT4 throughput gain: +47.9%"
```

---

## 8. Navigation Flow Summary

```mermaid
flowchart LR
    subgraph "Always Accessible"
        Nav[Top Navigation Bar]
    end

    subgraph "Pages"
        D[/ Dashboard]
        T[/tribunal Tribunal View]
        R[/report/:id Report View]
        B[/benchmark Benchmark]
    end

    Nav --> D
    Nav --> B

    D --> |Submit PR or files| T
    T --> |Pipeline complete| R
    R --> |Back| D
    R --> |Approve fix| R
    B --> D
```

---

## 9. Human-in-the-Loop Detail Flow

```mermaid
flowchart TD
    A[Verifier Agent completes] --> B[Pipeline pauses]
    B --> C[Frontend navigates to /report]
    C --> D[Developer reads all findings]
    D --> E{Developer satisfied?}
    E -- No / Report only --> F[No GitHub action taken]
    F --> G[Export PDF/JSON if desired]
    E -- Yes --> H[Click 'Approve & Open Fix PR']
    H --> I[Confirmation modal appears]
    I --> J{Developer confirms?}
    J -- Cancel --> D
    J -- Confirm --> K[POST /api/review/approve-fix]
    K --> L[Fix Agent resumes]
    L --> M[Branch created: themis/fix-pr-42]
    M --> N[Patches committed]
    N --> O[Counter-PR opened on GitHub]
    O --> P[PR URL shown in UI with link]
    P --> Q[Developer reviews Fix PR on GitHub]
```
