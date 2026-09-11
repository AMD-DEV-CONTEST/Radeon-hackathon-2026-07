# Memloom Agent Architecture (Track 2)

> English architecture diagram for the AMD Track 2 submission. A rendered SVG is at `assets/agent-architecture.svg`; an editable Mermaid version is below.

## Rendered diagram

![Memloom Agent architecture](assets/agent-architecture.svg)

## Mermaid source (editable)

```mermaid
flowchart TB
    subgraph SRC["AI Agent sources"]
        CC["Claude Code sessions (.jsonl)"]
        CX["Codex sessions (.jsonl)"]
    end
    subgraph CLIENT["Memloom desktop client — main process (Electron)"]
        AD["Session adapters<br/>incremental cursor · main sessions only"]
        DI["Distill<br/>extract candidates"]
        ME["Merge<br/>new · link · update · duplicate"]
        RE["Review<br/>accept · edit · reject · later"]
        CA["Canonical<br/>only trusted source"]
        AD --> DI --> ME --> RE --> CA
        HG["↑ human review gate — AI proposes, human decides"]
    end
    subgraph REUSE["Reuse"]
        RT["Retrieve (Agent)<br/>AGENTS.md · CLAUDE.md · .memloom/"]
        RC["Recall (Human)<br/>active recall · re-expression"]
    end
    subgraph MODEL["Local model service"]
        V["vLLM on AMD GPU (loopback)<br/>gfx1100 · ROCm 7.2.1 · BF16 · 8192 ctx"]
    end
    subgraph STORE["Local-first storage (atomic writes)"]
        ST["canonical · pending · rejected · duplicates · run records · recall state"]
    end
    CC --> AD
    CX --> AD
    CA --> RT
    CA --> RC
    DI -. model calls .-> V
    ME -. model calls .-> V
    CA --> ST
```

## Component description

| Layer | Components | Responsibility |
|---|---|---|
| Agent sources | Claude Code / Codex session files | Raw collaboration records, read incrementally from the last cursor position |
| Desktop client (main process) | Session adapters → Distill → Merge → Review → Canonical | Bounded staged pipeline: extract long-term valuable candidates, classify new/link/update/duplicate, gate on human confirmation, store the single trusted version |
| Human review gate | Review UI (renderer) | The user accepts, edits, rejects, or defers each candidate; the system never bypasses this gate |
| Reuse | Retrieve / Recall | Deploy assistant-facing versions to `AGENTS.md`/`CLAUDE.md` + `.memloom/`; support human re-expression and recall |
| Local model service | vLLM on AMD GPU | OpenAI-compatible endpoint on loopback; all inference runs on the AMD Radeon GPU (gfx1100, ROCm 7.2.1, BF16) |
| Local-first storage | Atomic JSON files | canonical / pending / rejected / duplicates / run records / recall state — no cloud dependency |
