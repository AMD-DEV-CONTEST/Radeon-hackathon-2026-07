# API Latency Runbook

## Symptoms

The `api` service reports elevated p95 latency, timeout errors, or worker queue
growth. A common cause is resource saturation when CPU utilization remains above
90% and the request queue exceeds normal capacity.

## Diagnosis

1. Inspect API health metrics and confirm that saturation is sustained.
2. Search API logs for `timeout`, `queue`, and downstream connection errors.
3. Verify database and dependency health before changing the API service.
4. Preserve the incident timestamp, query, evidence, and tool outputs.

## Remediation

Reduce load or add capacity before considering a restart. A restart can briefly
hide saturation and must require explicit operator approval plus a rollback
plan. Radeon Sentinel only simulates this action in the hackathon demo.
