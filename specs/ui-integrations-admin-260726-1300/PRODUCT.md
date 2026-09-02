# UI-5 Product Specification — Controlled Integrations and Admin Operations

## Goal

Let a project member prepare a single SCM change, inspect its server-created diff, and explicitly confirm it. Give a system administrator a safe operations summary without exposing credentials, tokens, filesystem paths, or raw secrets.

## User flows

1. A project member enters an issue title and optional description, then selects **Preview change**. This creates no external write.
2. The UI renders the exact target, operation, and item list returned by the server. It can only execute with the opaque, one-time confirmation ID.
3. The member explicitly confirms the browser dialog. Reuse of the ID is rejected by the server, preventing duplicate writes.
4. A system administrator sees health, queue, cache, GPU summary, recent failures, and backup summary. A regular user sees no operations panel and receives HTTP 403 if they call the operations API directly.

## Non-goals

- No webhook setup or secret input is placed in the browser.
- This UI does not promise automatic rollback; the execution result documents that rollback remains a reviewed destination-system procedure.
