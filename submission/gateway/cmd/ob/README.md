# OB Cockpit

OB (Operation Bridge) is the desktop-facing cockpit for Gateway chat routing.

This command was migrated from the standalone `unionagents-desktop` workspace so the Gateway, ILS, and OB communication path can be versioned and reviewed in one repository.

## Run

```powershell
go run ./cmd/ob
```

Common environment variables:

- `UA_AGENT_ID`: OB agent id, defaults to `ob-main`.
- `UA_GATEWAY_URL`: Gateway WebSocket URL, defaults to `wss://api.upser.pro/ws`.
- `UA_ORCHESTRATOR_URL`: Orchestrator HTTP URL, defaults to `https://api.upser.pro`.
- Emergency fallback: set `UA_GATEWAY_URL=wss://111.228.42.18:3389/ws` to bypass Cloudflare/H6 and connect directly to JD-ECS.
- `UA_OB_PORT`: local HTTP port, defaults to `19800`.
- `GATEWAY_PASSWORD`: Gateway password used during login.

## Communication Contract

- OB sends `agent_id` during `/auth/login`.
- OB stores returned `app_id`.
- OB connects WebSocket with both `app_id` and `token`.
- OB sends `/chat` with `from_agent_id = UA_AGENT_ID` and `conv_id = UA_AGENT_ID`.
- OB accepts both `chat` and legacy `chat:reply` inbound message types.
