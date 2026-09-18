# Security Boundaries

Radeon Sentinel is a hackathon prototype, not an autonomous production
operator.

## Tool policy

- Diagnostic tools are allow-listed and receive schema-validated arguments.
- Tools run against synthetic fixtures or a sandboxed demo service.
- State-changing tools are simulated and require explicit human approval.
- Arbitrary shell execution, unrestricted filesystem access, and remote
  production credentials are out of scope.
- Every plan, tool request, approval decision, result, and error is written to a
  local audit record.

## Privacy policy

- Core model inference, retrieval, memory, and audit storage remain local.
- Demo data is synthetic.
- Logs must redact secrets and personal identifiers before indexing.
- No external telemetry is enabled by default.

## Reporting

Do not report real vulnerabilities or include real production logs in a public
hackathon issue. Use synthetic reproduction data and contact the repository
owner privately for sensitive reports.
