# Configuration Drift Runbook

## Symptoms

The `worker` service rejects jobs after an unreviewed configuration change. Logs
may contain `config version mismatch`, missing environment values, or a checksum
that differs from the approved release manifest.

## Diagnosis

1. Compare the running configuration version with the approved manifest.
2. Search worker logs for `config`, `checksum`, and validation failures.
3. Identify the deployment that introduced the drift.
4. Do not print secret values while comparing configuration.

## Remediation

Prepare a rollback to the last approved configuration. Require a human approval
record before applying any change. The demo restart tool is simulated and does
not alter a real service.
