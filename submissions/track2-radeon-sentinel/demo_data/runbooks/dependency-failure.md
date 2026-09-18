# Dependency Failure Runbook

## Symptoms

The `checkout` service returns errors because the upstream `payments`
dependency is unavailable or exceeds its timeout budget. Retries can amplify
the incident when the dependency is already degraded.

## Diagnosis

1. Inspect checkout health and error rate.
2. Search logs for `dependency`, `upstream`, `connection`, and `timeout`.
3. Confirm the upstream status before retrying or restarting checkout.
4. Prefer graceful degradation or a circuit breaker over uncontrolled retries.

## Remediation

Enable the documented fallback only after validating business impact. A service
restart is not a dependency fix and requires explicit approval even in the
simulated demo.
