# Agent Tool and Privacy Policy

Radeon Sentinel uses a default-deny tool broker. Only named, schema-validated
diagnostics are allowed. Read-only tools may run automatically against synthetic
fixtures. Any state-changing tool requires an explicit human approval for the
specific arguments.

Core inference, retrieval, case memory, and audit records remain local in the
target deployment. Secrets and personal data must be redacted before indexing.
The hackathon demo never receives production credentials and never executes
arbitrary shell commands.
