# Application Scenarios

FastAgentFactory focuses on a fully local personal AI assistant that can maintain context, retrieve private knowledge, call real tools, coordinate specialist agents, and produce durable artifacts.

## 1. Personal AI Assistant

Typical work includes reviewing files, organizing information, creating content, querying data, scheduling reminders, and coordinating multiple tools. Cross-session memory preserves relevant preferences and prior decisions, while factual claims still require explicit retrieval or tool evidence.

- Recommended pattern: `react_agent`.
- Runtime support: dynamic tool visibility, Tool Gateway, workspace files, MCP/skills, checkpoints, and interruption recovery.

## 2. Financial Research Example

Three built-in U.S. equity agents demonstrate a realistic multi-agent workflow:

- **U.S. Equity Market Radar:** major indexes, leading/declining equities, and most-active names.
- **U.S. Listed Company Researcher:** Yahoo Finance prices, SEC company facts, trends, and user material.
- **U.S. Equity Portfolio Risk Guard:** concentration, volatility, drawdown, S&P 500 beta, correlation, and stress tests.

The main assistant can coordinate them to produce a time-stamped report, document abnormal or missing data, and send the result only under the configured email policy. Output is not investment advice.

## 3. Multi-step Research and Delivery

For tasks with stable phases—collect, analyze, generate, verify, and deliver—`plan_and_execute` provides an explicit plan while each step still uses the unified tool gateway. Checkpoints make interrupted work recoverable.

Examples include industry research, due-diligence summaries, policy comparisons, and document packages.

## 4. Private Knowledge Q&A

Users can ingest local PDFs, Markdown, text, and supported attachments into a package or session knowledge space. Agents retrieve candidate passages, open the relevant source, and cite it in the answer. Knowledge scope follows package and session ownership.

## 5. Scheduled Monitoring

Scheduled tasks can produce recurring market briefs, reminders, data checks, or report updates. The scheduler stores execution state independently from ordinary chat while surfacing task activity across sessions. Active sessions can receive status cards when a scheduled run changes state.

## 6. Artifact-oriented Content Production

Agents can generate Markdown reports, presentations, structured data, images, and other files in the active workspace. Artifact metadata is preserved for preview, download, acceptance, and delivery instead of embedding large binary content in model context.

## 7. Agent Manufacturing at Scale

Natural-language requirements can be transformed into reusable AgentPackages with validated prompts, tools, skills, resources, knowledge, dependencies, and runtime patterns. This supports business templates without hard-coding each workflow into the platform.

## 8. Controlled Agent Evolution

Published agents can be evolved from trace evidence, tool failures, user feedback, or changed objectives. Evolution updates the same package contracts and passes validation before publication.

## 9. Multi-agent Collaboration

The main agent decomposes a broad goal, selects specialist agents by capability and description, establishes semantic delivery criteria, and dispatches isolated tasks. Sub-agents report completion or blockage; the main agent reviews artifacts and composes the final result.

## Scenario-to-pattern Guide

| Scenario | Recommended pattern | Main reason |
| --- | --- | --- |
| Open-ended personal assistance | `react_agent` | Tool path changes dynamically |
| Structured research pipeline | `plan_and_execute` | Explicit phases and checkpoints |
| Private knowledge Q&A | Either | Depends on whether synthesis has multiple stages |
| Scheduled monitoring | Package pattern + scheduler | Schedule triggers the same runtime |
| Multi-agent research | Main agent + collaboration scheduler | Isolated parallel specialists and semantic acceptance |

## Out-of-scope or High-risk Uses

The platform should not autonomously execute irreversible financial transactions, legal commitments, destructive host operations, or external communications without an appropriate approval policy. External data can be unavailable or inconsistent; reports must retain source time, anomaly notes, and domain-specific disclaimers.
