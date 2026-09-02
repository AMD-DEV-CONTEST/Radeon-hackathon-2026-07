# AI Runtime Setup Direction

## Purpose

This document records a future product direction. F04-A does not implement an
installer, hardware scanner, Provider write API, automatic fallback, or
configuration persistence.

The product goal is to let an enterprise operator understand and initialize
the AI environment without creating a second Provider selection system outside
the existing Runtime composition boundary.

## Current boundary

The current source of truth remains:

```text
ProviderRuntimeOrchestrator
  -> discovery and explicit selection
  -> validation
  -> AnalysisProviderFactory
  -> selected AnalysisProvider
  -> credential-free GET /api/runtime projection
```

The browser only reads the final public projection. It does not inspect local
ports, environment variables, API keys, GPU devices, configuration files, or
model directories.

`GET /api/runtime` currently reports the selected Provider, safe model
identifier, execution mode, selection source, Runtime status, and Provider
health. It does not report AMD GPU or ROCm details and does not expose the full
discovery candidate list.

## Future installation flow

```text
AlphaNoah installation
  -> server-side environment scanner
  -> ProviderRuntimeOrchestrator discovery
  -> detect eligible Ollama, vLLM, and OpenAI-compatible candidates
  -> present safe candidates to the operator
  -> operator explicitly selects one Runtime
  -> validate endpoint, model, and credential reference
  -> save non-secret configuration through an audited setup API
  -> ProviderRuntimeOrchestrator resolves the selection on startup
  -> GET /api/runtime reports the active result
```

The future scanner should be a thin product-facing use of the existing
discovery and validation capabilities. It must not duplicate Provider probing
inside React or add a competing selection precedence.

## Product surface

The first setup experience should contain:

- Environment check: safe AMD GPU/ROCm capability when a future backend
  contract explicitly provides it.
- Local Runtime candidates: eligible Ollama and vLLM installations returned by
  the orchestrator's discovery boundary.
- Cloud Provider candidates: explicitly configured OpenAI-compatible services;
  credentials remain server-side references, never browser values.
- Current selection: the one Provider actually composed into the application.
- Validation result: bounded health and model availability categories without
  raw response bodies.
- Explicit save and restart implications: no silent Provider changes and no
  automatic fallback.

## Required future backend contracts

These are gaps, not F04-A implementation commitments:

1. A safe environment/doctor projection that reuses
   `ProviderRuntimeOrchestrator` discovery and validation.
2. An allowlisted hardware capability projection if AMD GPU/ROCm identity must
   be displayed.
3. An authenticated, audited write boundary for saving a Provider selection.
4. A clear activation/restart contract for applying a changed selection.

The existing `runtime-status-v1` response must not be expanded informally. A
new contract version or a separate bounded endpoint should be designed and
tested before exposing additional information.

## Safety and privacy constraints

- Never expose API keys, tokens, Authorization headers, or credential values.
- Never return raw environment variables, local paths, discovery response
  bodies, prompts, model output, or tracebacks.
- Never treat discovery as permission to select or change a Provider.
- Never show an unverified Provider, GPU, or model as Online.
- Never auto-fallback from the operator's selected Provider.
- Keep browser setup operations separate from Runtime business actions and
  human approval state.

## F04-A placeholder behavior

F04-A creates the product entry in Settings but limits it to one read-only
operation: refresh `GET /api/runtime`.

- AMD GPU is shown as "Not reported by Runtime API".
- Local and cloud rows describe only the currently selected execution mode.
- No candidate discovery is claimed.
- No configuration can be changed.

This makes the missing capability visible without inventing a second detection
system or overstating the release candidate's verified environment.
