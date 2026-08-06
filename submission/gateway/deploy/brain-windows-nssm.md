# Windows NSSM deployment for `cmd/brain`

This is a template for running the Go `brain.exe` runtime as a Windows service with NSSM.

Do not put real keys or passwords in this file. Configure them only on the target host.

## Files

Recommended layout:

```text
C:\UnionAgents\
  brain.exe
  logs\
    brain.out.log
    brain.err.log
```

Build or copy `brain.exe` from the repository root:

```powershell
go build -o brain.exe ./cmd/brain
```

## Environment variables

Set these on the service through NSSM. Use real values only on the target host.

```text
UAS_GATEWAY_URL=ws://<gateway-host>:8001
GATEWAY_PASSWORD=<gateway-password>
UAS_AGENT_ID=<agent-id>
UAS_AGENT_NAME=<agent-name>
UAS_AGENT_TYPE=hermes
DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
DEEPSEEK_API_KEY=<deepseek-api-key>
UAS_LLM_MODEL=deepseek-v4-flash
```

Optional tuning:

```text
BRAIN_MAX_TOKENS=1024
BRAIN_TEMPERATURE=0.7
BRAIN_LLM_TIMEOUT_SEC=60
```

## Install service

Open an elevated PowerShell and run:

```powershell
nssm install unionagents-brain C:\UnionAgents\brain.exe
nssm set unionagents-brain AppDirectory C:\UnionAgents
nssm set unionagents-brain AppParameters "--agent-id %UAS_AGENT_ID% --agent-name %UAS_AGENT_NAME% --agent-type %UAS_AGENT_TYPE% --gateway-url %UAS_GATEWAY_URL% --llm-base-url %DEEPSEEK_BASE_URL% --llm-model %UAS_LLM_MODEL% --max-tokens %BRAIN_MAX_TOKENS% --temperature %BRAIN_TEMPERATURE% --llm-timeout-sec %BRAIN_LLM_TIMEOUT_SEC%"
nssm set unionagents-brain AppStdout C:\UnionAgents\logs\brain.out.log
nssm set unionagents-brain AppStderr C:\UnionAgents\logs\brain.err.log
nssm set unionagents-brain AppRotateFiles 1
nssm set unionagents-brain AppRotateOnline 1
nssm set unionagents-brain AppRotateBytes 10485760
nssm set unionagents-brain Start SERVICE_AUTO_START
nssm set unionagents-brain AppRestartDelay 5000
```

Set service environment as one multiline value:

```powershell
nssm set unionagents-brain AppEnvironmentExtra `
  "UAS_GATEWAY_URL=ws://<gateway-host>:8001" `
  "GATEWAY_PASSWORD=<gateway-password>" `
  "UAS_AGENT_ID=<agent-id>" `
  "UAS_AGENT_NAME=<agent-name>" `
  "UAS_AGENT_TYPE=hermes" `
  "DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic" `
  "DEEPSEEK_API_KEY=<deepseek-api-key>" `
  "UAS_LLM_MODEL=deepseek-v4-flash" `
  "BRAIN_MAX_TOKENS=1024" `
  "BRAIN_TEMPERATURE=0.7" `
  "BRAIN_LLM_TIMEOUT_SEC=60"
```

Start and inspect:

```powershell
nssm start unionagents-brain
nssm status unionagents-brain
Get-Content C:\UnionAgents\logs\brain.err.log -Tail 50
```

Expected startup log:

```text
brain online agent_id=<agent-id> name=<agent-name> gateway=ws://<gateway-host>:8001 model=deepseek-v4-flash
[uasclient] ready connection_id=<connection-id> mode=agent
```

## Stop / remove

```powershell
nssm stop unionagents-brain
nssm remove unionagents-brain confirm
```

## Notes

- `UAS_AGENT_TYPE=hermes` is intentional: current Gateway allowlisting expects Hermes-compatible agents.
- `brain.exe` reads `GATEWAY_PASSWORD` and `DEEPSEEK_API_KEY` from the service environment.
- Keep logs local and rotate them; do not paste secrets into logs or docs.
