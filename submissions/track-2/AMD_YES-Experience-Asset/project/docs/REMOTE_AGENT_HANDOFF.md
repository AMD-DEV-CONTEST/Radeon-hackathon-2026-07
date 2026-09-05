# Primary ↔ Radeon Worker Handoff

Last updated: 2026-07-22 AEST

Status: `DEFERRED`. The user chose not to configure or use V4 Flash until a
Responses-compatible DeepSeek service/key is available. This document records
the already-tested boundary only; it is not an active setup instruction.

## Purpose

The Radeon Cloud worker saves primary-agent tokens on small, bounded work. It
is a development helper only. The submitted Agent's core inference continues
to run locally through vLLM, ROCm, and the W7900.

```text
Primary Codex / developer
  -> selects one small, self-contained text task
  -> launches one ephemeral worker request over SSH
  -> AMD DeepSeek-V4-Flash shared API
  -> worker returns analysis, draft text, or a proposed patch
  -> primary agent reviews, tests, and decides whether to keep it
```

## Delegation contract

Delegate only tasks that have:

- one explicit outcome;
- a small file or log scope;
- no secret access;
- no architecture, dependency, permission, or data-boundary decision;
- a verification command the primary agent can run.

Good tasks include log classification, README edits, test drafts, isolated
boilerplate, and summarizing benchmark output. Do not delegate Git publication,
credential setup, destructive commands, public tunnelling, or final acceptance.

## Verified compatibility boundary

On 2026-07-22, the AMD endpoint passed a direct
`/chat/completions` smoke test. Codex CLI 0.144.2 instead called
`/responses`, which the endpoint returned as HTTP 404; that Codex version also
rejected `wire_api = "chat_completions"`. If this option is reconsidered later:

- use `scripts/deepseek_worker.py` only for separately approved, bounded
  text-only V4 Flash delegation;
- use Codex CLI separately with a provider it supports;
- do not give the V4 Flash worker shell, file, Git, or secret access;
- do not add a protocol-conversion gateway without a separately reviewed
  dependency and security decision.

The worker does not execute the task itself. It returns a proposal that the
primary agent applies and verifies.

## Setup and invocation

```bash
source scripts/activate_remote_env.sh

# Enter the key only for the current shell. Do not add this command to history.
read -rsp "AMD model API key: " AMD_MODEL_API_KEY
echo
export AMD_MODEL_API_KEY

python3 scripts/deepseek_worker.py \
  "Summarize the failure in logs/example.txt and suggest one next check."
```

For a proposed file edit, put the bounded task in a temporary task file and
write the response outside the repository:

```bash
task_file=$(mktemp)
result_file=$(mktemp)
$EDITOR "$task_file"
python3 scripts/deepseek_worker.py --task-file "$task_file" --output "$result_file"
$PAGER "$result_file"
rm -f "$task_file" "$result_file"
```

The primary agent makes any accepted edit, inspects `git diff`, runs tests, and
owns the final commit/publication decision.

## Credential boundary

The API key is shell-only. It must not appear in `.env`, shell profiles,
Codex configuration, task prompts, logs, Git history, or `/workspace` files.
Because a key was visible in a supplied screenshot, rotate it before ongoing
use. The official Radeon Cloud guide calls the shared Qwen/DeepSeek endpoints
free and says they consume no instance credits. The current Token Factory modal
also displays per-token "Pricing from LLMGateway" metadata. Until AMD clarifies
that discrepancy, monitor the account and do not assume unlimited usage.
