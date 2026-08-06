# GTM Tool Execution Sandbox V1

ProofLaunch executes untrusted or model-directed tool jobs through a separate
Docker boundary. The reviewed adapter runs as a non-root user with no network,
a read-only root filesystem, every Linux capability dropped,
`no-new-privileges`, CPU/memory/PID limits, a `noexec` temporary filesystem,
read-only code and secret mounts, and exactly one writable job workspace.

`scripts/run_tool_sandbox_proof.py` creates the container without a shell,
captures Docker's inspected runtime settings, runs behavioral escape probes,
validates the signed receipt, and removes only the uniquely named probe
container it created. `scripts/tool_sandbox_probe.py` proves:

- the scoped workspace is writable;
- root-filesystem and workspace-parent writes are blocked;
- DNS and direct TCP egress are blocked;
- a secret can be mounted at the tool boundary without entering the
  environment, job context, or persisted receipt.

The authoritative result is
`evidence/v10/tool-execution-sandbox-v1.json`. A unit test alone cannot turn
PR-06 green; the readiness compiler validates this observed Docker receipt.

This boundary does not authorize publishing, ad spend, account connection, or
customer-data collection. It also does not prove hosted deployment, Radeon
execution, all future connector implementations, 4A preference, lift, or
revenue.
