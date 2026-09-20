# Graph Engine: Active Diagnose and Repair

`scripts/graph_engine.py` is a conservative self-healing loop for the local Agent stack.

```text
health → inspect → diagnose → allow-listed repair → restart → verify
                                      └────────────── rollback on failure
```

The first graph covers the most common Open WebUI failure: a growing chat or
full-document injection exceeding the vLLM context window.

## Safety policy

- Diagnosis is the default; `--apply` is required for changes.
- Only Open WebUI context-compaction and RAG chunk settings are mutable.
- The SQLite database is backed up before every repair.
- A post-repair health failure triggers rollback.
- The graph stops after the configured maximum number of rounds.
- Model weights, user chats, credentials, and business data are never modified.

## Run

Read-only remote diagnosis:

```bash
python scripts/graph_engine.py --target remote
```

Apply safe repairs and write an audit report:

```bash
python scripts/graph_engine.py \
  --target remote \
  --apply \
  --max-rounds 5 \
  --report artifacts/graph_engine_report.json
```

The current graph checks:

- Open WebUI HTTP health on port `8082`
- vLLM model availability on port `8000`
- Open WebUI uses the IPv4 loopback URL `http://127.0.0.1:8000/v1` when both services run on the same host
- context compaction enabled at `20,000` tokens with a `24,000` cap
- RAG chunk size `512`, overlap `128`, and `full_context=false`

The output status is `healthy`, `fixed`, or `blocked`, with findings and
actions recorded in JSON.
