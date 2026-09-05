# Context Lifecycle & Memory Management

This document outlines the lifecycle control and context memory management strategies implemented in the Klint framework, ensuring that language models do not suffer from context bloat or "infinite snowballing" of diagnostic logs during complex task execution.

## 1. Domain Validation Phase: Stateless Memory

During the initial XML domain modeling phase (`executor.rs`), the framework employs a **Stateless Context Design**.

When generating the initial `main.xml` and validating it against TeaQL's rules (e.g., privacy rules like `KSML-PRIVACY-001-WARN`), the evaluation report can be extremely lengthy. To prevent context overflow, Klint avoids appending each new attempt to a long-running chat history.

Instead, every repair attempt receives a freshly constructed, stateless prompt array consisting of exactly:
1. **System Prompt**: Base instructions.
2. **Grammar & Whitelist**: System constraints.
3. **Task Definition**: The user's original objective.
4. **Assistant Candidate**: The previously rejected model output.
5. **Diagnostic Error**: The specific evaluation report for this failure.

When Attempt N fails, Attempt N+1 completely discards Attempt N's evaluation report. The LLM only ever sees the *latest* failure, guaranteeing that prompt tokens remain stable (e.g., ~7300 tokens) regardless of how many repair loops occur (up to the limit of 11).

## 2. Assist Phase: "Burn-After-Reading" (Ephemeral) Memory

During the Assist phase (`generic_executor.rs`), where the agent writes, compiles, and tests custom Rust business logic, the framework must maintain a **Stateful Conversation History** to allow for multi-step reasoning and terminal interactions.

However, long-running terminal outputs (such as `cargo teaql evaluate` or massive `cargo check` logs) can quickly exhaust the LLM's context window. To solve this, Klint implements an **Ephemeral Cleanup Mechanism** ("阅后即焚").

### How it works:
1. **Tagging**: When the agent executes a command that produces massive but transient diagnostic output (e.g., the KSML evaluation report), the underlying engine tags its standard output with an `<!-- ephemeral -->` marker.
2. **Stateful Consumption**: The `generic_executor` detects this tag (`raw_out.contains("<!-- ephemeral -->")`) and formats the message explicitly starting with the `<!-- ephemeral -->` prefix before handing it to the LLM. The LLM reads the diagnostics and fixes the code in the current turn.
3. **Turn-based Cleansing**: Upon entering the *next* conversation turn, the `generic_executor` proactively purges any historical messages that start with this tag:
   ```rust
   // Clean up ephemeral messages from previous turns
   self.messages.retain(|m| !m.content.starts_with("<!-- ephemeral -->"));
   ```

### Benefits
This dual-layer memory lifecycle ensures that:
- **Maximum Resolution**: The LLM always sees the un-truncated, full diagnostic logs when it needs them to fix a bug.
- **Zero Bloat**: Once the bug is fixed and the turn ends, the massive logs are immediately wiped from the context window.
- **Infinite Scalability**: Complex tasks like `moving-company-platform` can run indefinitely without hitting `finish_reason: length` constraints.
