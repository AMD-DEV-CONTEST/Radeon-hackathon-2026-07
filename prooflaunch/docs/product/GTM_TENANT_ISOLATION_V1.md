# ProofLaunch tenant isolation v1

## Shipped boundary

The local product vertical slice now authenticates protected API requests with a
server-configured bearer-token map. The token, not a browser field or model
output, resolves the tenant principal. A launch may omit `strategy.org_id`; the
server injects it. A conflicting client value is rejected.

Tenant scope is enforced for runs, content-addressed artifact grants, previews,
event reads, jobs, effect observations, unit economics, learning memory,
approvals, bundles and idempotency namespaces. Every persisted run event and job
payload carries the immutable tenant ID. Cross-project or cross-organization
learning-memory promotion is rejected by the store.

The browser holds the bearer token in `sessionStorage` only. It is not put in a
URL, local recovery record, source file or log. Because native `EventSource`
cannot attach this authorization header, the UI uses bounded authenticated JSON
event polling with `Last-Event-ID`. Switching or clearing a token clears all
tenant-bound run and artifact references in the browser.

## Adversarial checks

The regression suite proves that a second configured tenant cannot read the
first tenant's run, preview, outcomes, economics, memory, events or bundle. It
cannot discover an artifact grant by hash, reuse the first tenant's idempotency
cache result, inject the first tenant's organization ID, or cause event/job
payloads to lose their tenant binding. CAS bytes may deduplicate physically, but
access is granted independently only after the second tenant uploads the same
bytes.

## Truth boundary

This is a single-node SQLite vertical slice suitable for the local competition
demo. It is not a claim of enterprise distributed tenancy. Production still
requires audited OIDC/SAML identity, SCIM lifecycle, short-lived credentials,
KMS-backed secret rotation, database row-level security, tenant-aware object
storage policies, queue/worker isolation, per-tenant quotas, deletion/export
workflows, security review and multi-region disaster recovery tests.

The model never receives authority to choose or change tenant identity. This
boundary remains code-owned beneath Graph, node Loops and the global Harness.
