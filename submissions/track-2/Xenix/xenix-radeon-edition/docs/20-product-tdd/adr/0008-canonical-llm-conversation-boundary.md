# ADR 0008: Canonical LLM Conversation Boundary

- Status: accepted
- Date: 2026-07-15
- Relates to: [ADR 0006](0006-bounded-sqlite-application-state.md) and
  [ADR 0007](0007-remote-integrations-remain-adapters.md)
- Contract: [LLM Conversation Boundary](../llm-conversation-boundary.md)

## Context

The former Agent layer mixed canonical conversation persistence, provider/tool
orchestration, live UI policy, and presentation. Its aggregate Turn/Run-style
state made recovery, ownership, and dependency direction hard to reason about.
It also encouraged Artifact and observability records to look like potential
conversation-recovery inputs.

## Decision

Use one ordered canonical Thread/Message log owned exclusively by
`LLMConversationService`.

- Keep final User, Assistant, ToolCall, and ToolResult Messages durable; use
  one pending sampling Message as the only provisional canonical state.
- Put provider interaction, transcript adaptation, and the LLM-owned AgentTool
  protocol/registry/validation/invocation at the LLM boundary.
- Keep Agent Harness process-local: it coordinates import, live sampling,
  Thread-pause requests, and snapshot-to-Chatbot-event projection. It does not
  directly write or mutate Messages or dispatch Tools. Pending-message
  cancellation is cleanup, not user-facing Stop.
- Inject concrete Tool implementations through LLM-owned interfaces. The LLM
  boundary never imports Harness or concrete/domain Tool modules.
- Make a Tool's bounded direct returned value the only ToolResult value.
  Provider adapters encode it only for transport; XTT and typed ToolFailure are
  values chosen at the LLM-owned Tool boundary, not Harness projections.
- Do not introduce a persistent Turn, Run, execution ledger, or Artifact/Log
  provenance relation as a second conversation authority.

## Consequences

- Chatbot events, Thinking, source attachments, and usage displays are
  projections. They may be rebuilt from a snapshot plus their bounded read-only
  dependencies, but do not repair canonical state.
- A process can lose an incomplete exchange. Xenix deliberately does not infer
  a missing ToolResult from domain side effects, Artifacts, or observability.
- ToolCall and ToolResult remain independent Messages, which gives deletion and
  migration an explicit dependency order.
- Provider adapters choose their own history/wire form without mutating
  canonical Messages.
- Stop is a process-local Thread admission pause. It prevents later provider
  requests but neither persists a recovery state nor promises Tool cancellation
  or rollback. An already executing admitted Tool exchange may settle its
  atomic result set; a new explicit UserMessage is the sole re-entry command.

The contract linked above owns the precise topology, sequences, invariants, and
verification routes; this ADR preserves the decision and its non-goals.
