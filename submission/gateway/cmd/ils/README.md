# ils CLI

## inbox watch

`ils inbox watch` keeps a WebSocket connection open and prints inbound UAS chat messages for a logical agent id.

```powershell
.\ils.exe inbox watch --agent-id x1 --format text
```

JSONL output is the default:

```powershell
.\ils.exe inbox watch --agent-id x1 --format jsonl
```

For smoke tests and scripts, exit after the first message:

```powershell
.\ils.exe inbox watch --agent-id x1 --once
```

H5 coordination flow:

1. Start the watcher:

```powershell
.\ils.exe inbox watch --agent-id x1 --format text
```

2. In another terminal, send or ask C1/user to send a message to `x1`.
3. Confirm terminal A prints the actual message body, not just a delivery status.
4. Reply with:

```powershell
.\ils.exe chat send --from-agent-id x1 --from X1 --target-agent-id h5-hermes-aws-hk --text "received"
```

The command registers as a client identity with a logical `agent_id` route. It does not start a brain sidecar and does not modify `cmd/brain`.
