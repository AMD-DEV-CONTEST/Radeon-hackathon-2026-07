Document ID: RP-KB-005
Revision: 1.0
Classification: competition-public

# Safety, Permission, and Privacy Policy

RadeonPilot recommends, explains, and audits; it never commands real hardware.

## Action gating

- All model-generated actions are proposals, never executed automatically.
- Hazardous actions (restart endpoint, apply quantization, kill process, reset GPU)
  are blocked pending explicit human approval by the sre or ops_commander role.
- The permission_check tool enforces least-privilege: a plain operator cannot clear
  a hazardous gate.

## Privacy boundary

- The Pi bridge binds to 127.0.0.1 and refuses non-loopback hosts and endpoints.
- Built-in Pi file, shell, edit, browser, and network tools are disabled; agents see
  only the evidence pack prepared by the Python controller.
- Audit records redact secrets and store only hashed summaries of free text.
- API keys are localhost placeholders and are never persisted by the application.

## Evidence discipline

- Agents may cite only evidence supplied in the request or retained in session memory.
- If data is missing, agents must say so explicitly instead of guessing.
- No fabricated sensor readings, benchmark numbers, or attestation claims.

## Honest modes

- demo: labelled synthetic, no GPU, used to inspect the workflow on any machine.
- pi: real multi-agent generation over a local ROCm endpoint; fails closed and never
  silently substitutes demo output. A green Radeon badge requires the endpoint PID to
  appear in `amd-smi process --pid` on a Radeon device.
