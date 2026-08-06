# P2 managed-mode cutover RUNBOOK (DRAFT — requires maintenance window + approval)

## Scope
Move llama-swap from `peers` (proxies external :8080) to `managed`
(llama-swap owns the llama-server lifecycle on internal port 18081).
Closes G1 (429/concurrency) and G2 (ugly model id). Restart-required.

## Pre-check (before window)
- [ ] Binary SHA confirmed: a80a8aad...f14f9416 (v246, 22df230), 23189302B
- [ ] Backup current config: `cp /opt/llama-swap/poc/ls_phase2.yaml /opt/llama-swap/poc/ls_phase2.yaml.bak`
- [ ] Note current PIDs: llama-swap 5198, llama-server 3687
- [ ] Confirm lora paths exist under /workspace/persistent/screwshell_run/loras/{btl3,cybersec,rag_n7}

## Cutover
1. Stop external llama-server + old llama-swap:
   `pkill -9 -f '/opt/llama-swap/llama-swap'; pkill -9 -f 'llama-server --model .*Qwen3.6'`
2. Deploy managed config:
   `scp deploy/w7900/llama-swap-managed.yaml root@box:/opt/llama-swap/poc/ls_managed.yaml`
3. Start llama-swap with managed config:
   `setsid /opt/llama-swap/llama-swap --config /opt/llama-swap/poc/ls_managed.yaml --listen 127.0.0.1:18080 >/opt/llama-swap/poc/ls_managed.log 2>&1 < /dev/null &`
4. Update ScrewShell UI env `MOL_LLAMACPP_MODEL` to `screwshell-qwen3.6-27b`
   (and `m` still works via alias). Restart UI.

## Verify
- [ ] `GET /v1/models` (auth) shows id `screwshell-qwen3.6-27b` + aliases
- [ ] chat via gateway returns 200 with real content (non-stream + stream)
- [ ] tool-call returns finish_reason=tool_calls
- [ ] `GET /slots` (or managed upstream) shows n_ctx=131072
- [ ] concurrency: 2 parallel requests both 200 (no overload crash); >limit queues/429
- [ ] `GET /metrics`, `/logs`, `/props` reachable via gateway

## Rollback
1. `pkill -9 -f '/opt/llama-swap/llama-swap'`
2. Restart external llama-server: `setsid bash /workspace/persistent/screwshell_run/_run_roomy_server.sh ... &`
3. Restore peers config + restart llama-swap: `setsid /opt/llama-swap/llama-swap --config /opt/llama-swap/poc/ls_phase2.yaml --listen 127.0.0.1:18080 &`
4. Revert UI `MOL_LLAMACPP_MODEL` to the full `roomy//...` peer id
