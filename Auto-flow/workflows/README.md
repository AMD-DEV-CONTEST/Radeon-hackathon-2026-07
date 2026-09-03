# Reserved Workflow Integration

This directory is reserved for future workflow-orchestration integration.

## Overview

A workflow engine can provide:

- Step orchestration
- Approval gates
- Conditional branches
- Data transfer between steps
- Resume and recovery mechanisms

## Planned Workflows

| File | Purpose |
|---|---|
| `learn-skill.lobster` | Record a demonstration, compile it, and register the resulting skill |
| `run-skill.lobster` | Match a skill, inject parameters, and execute deterministic replay |
| `repair-skill.lobster` | Diagnose a halted workflow, request approval, and create a repaired version |

## Current MVP Status

The AutoFlow 0.6 MVP currently provides equivalent functionality through its Python modules and command-line interface. Workflow-engine integration is reserved for future development.
