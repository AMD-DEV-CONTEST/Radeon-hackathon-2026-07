# Security Policy

## Supported version

Security fixes are applied to the latest `main` branch and the most recent
tagged release. Competition snapshots are immutable evidence packages and are
superseded rather than edited in place.

## Reporting a vulnerability

Do not open a public issue for a vulnerability, exposed credential, tenant
isolation failure, approval bypass, unsafe model action, or private-data leak.
Contact the maintainer through the private security-reporting channel on the
GitHub repository. If that channel is unavailable, open a minimal issue asking
for private contact without including exploit details or secrets.

Include the affected revision, reproduction steps, impact, and any known
mitigation. You should receive acknowledgement within three business days and
a status update within seven business days.

## Security boundaries

- Models cannot publish, send, spend, approve, or promote learning.
- Release requires an authenticated, content-bound human approval.
- Tenant tokens and memory secrets must never enter receipts or logs.
- Model, dataset, adapter, and media inputs must retain revision and rights
  provenance.
- Private runtime state belongs under `.prooflaunch-runtime/` and secrets under
  `.prooflaunch-secrets/`; neither directory is part of a public export.
- Competition claims fail closed when required Radeon evidence is absent.

Never use the competition demo with real customer or regulated data.
