# `cmd/brain`

`cmd/brain` is the current UAS AI runtime: a Go single binary that connects to the UAS Gateway through `internal/uasclient`, receives chat events, calls an Anthropic-compatible LLM endpoint, and replies to the peer agent.

It replaces the deprecated Python `brain/` experiment for active deployments.

## Current role

- Runtime language: Go.
- Transport: UAS Gateway via `internal/uasclient`.
- Protocol surface: existing `ils` / Gateway chat events.
- Default agent type: `hermes`, matching the current Gateway allowlist.
- LLM API shape: Anthropic Messages API.
- Default LLM base URL: `https://api.deepseek.com/anthropic`.
- Default model: `deepseek-v4-flash`.

`brain` is intentionally stateless. Each inbound chat event triggers one LLM roundtrip and one outbound reply. Multi-turn context must be included by the caller or added later as an explicit design.

## Build

From the repository root:

```sh
go build -o brain ./cmd/brain
```

On Windows:

```powershell
go build -o brain.exe ./cmd/brain
```

## Test

```sh
go test ./cmd/brain
```

## Configuration

Required:

| Flag | Environment | Description |
|------|-------------|-------------|
| `--agent-id` | `UAS_AGENT_ID` | This brain's Gateway agent id. |
| `--llm-api-key` | `DEEPSEEK_API_KEY` | LLM API key. |

Common:

| Flag | Environment | Default | Description |
|------|-------------|---------|-------------|
| `--gateway-url` | `UAS_GATEWAY_URL` | `wss://api.upser.pro` | UAS Gateway WebSocket URL. |
| `--agent-name` | `UAS_AGENT_NAME` | agent id | Display name used in outbound messages. |
| `--agent-type` | `UAS_AGENT_TYPE` | `hermes` | Gateway agent type. Keep `hermes` unless the Gateway allowlist changes. |
| `--gateway-password` | `GATEWAY_PASSWORD` | empty | Gateway password. |
| `--llm-base-url` | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/anthropic` | Anthropic-compatible LLM base URL. |
| `--llm-model` | `UAS_LLM_MODEL` | `deepseek-v4-flash` | LLM model id. |
| `--max-tokens` | - | `1024` | LLM `max_tokens`. |
| `--temperature` | - | `0.7` | LLM temperature. |
| `--llm-timeout-sec` | - | `60` | LLM HTTP timeout. |
| `--no-heartbeat` | - | `false` | Skip orchestrator HTTP heartbeat. |

## Run locally

Use real secrets only in the local shell environment; do not commit them.

```sh
export UAS_GATEWAY_URL='ws://<gateway-host>:8001'
export GATEWAY_PASSWORD='<gateway-password>'
export DEEPSEEK_API_KEY='<deepseek-api-key>'

./brain \
  --agent-id cc-c1-brain \
  --agent-name C1-brain \
  --agent-type hermes \
  --llm-model deepseek-v4-flash
```

Windows PowerShell:

```powershell
$env:UAS_GATEWAY_URL = 'ws://<gateway-host>:8001'
$env:GATEWAY_PASSWORD = '<gateway-password>'
$env:DEEPSEEK_API_KEY = '<deepseek-api-key>'

.\brain.exe `
  --agent-id cc-c1-brain `
  --agent-name C1-brain `
  --agent-type hermes `
  --llm-model deepseek-v4-flash
```

Expected startup log:

```text
brain online agent_id=cc-c1-brain name=C1-brain gateway=ws://<gateway-host>:8001 model=deepseek-v4-flash
[uasclient] ready connection_id=<connection-id> mode=agent
```

## Trigger a roundtrip

`brain` is passive. It responds only after a peer sends a chat event to its `agent_id`.

For black-box testing with a peer agent:

```sh
GATEWAY_PASSWORD='<gateway-password>' ./ils chat send \
  --gateway-url ws://<gateway-host>:8001 \
  --from-agent-id cc-c1-brain --from C1-brain \
  --target-agent-id <peer-agent-id> \
  --text 'C1 brain online. Reply in one short line.'
```

A successful reply from `brain` looks like:

```text
brain: reply sent conv=<conversation-id> peer=<peer-agent-id> delivered=1 in_tok=<n> out_tok=<n>
```

## Deployment templates

- Linux systemd: `deploy/brain.service`
- Windows NSSM: `deploy/brain-windows-nssm.md`
- Environment template: `deploy/brain.env.example`

## Guardrails

- Do not add third-party IM platforms; keep the UAS/OB communication boundary.
- Do not write runtime or long-running agent code in Python.
- Do not revive the deprecated Hermes plugin route unless C1 explicitly reopens it.
- Do not commit API keys, Gateway passwords, or raw secret-bearing logs.
