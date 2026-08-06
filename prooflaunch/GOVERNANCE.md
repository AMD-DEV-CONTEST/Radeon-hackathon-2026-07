# ProofLaunch Governance

ProofLaunch is currently maintainer-led. `sylvanccc` is the release and code
owner for the initial public repository; Team Banyan is the AMD competition
identity.

## Decision model

- Routine fixes: one maintainer approval after required checks pass.
- New capabilities or dependencies: issue-first review and one maintainer
  approval.
- Security, tenant isolation, release authority, model supply chain, licensing,
  evidence schemas, competition claims, or Radeon receipts: code-owner approval
  is mandatory and self-approval is not permitted.
- Breaking changes: documented migration plan and release note.

Maintainers may request changes even when automated checks pass. Generated
assets, model grades, and synthetic reviews are supporting evidence, not a
substitute for accountable human review.

## Pull request flow

1. Triage for scope, rights, security, and claim impact.
2. Automated tests and package validation.
3. Domain review for product, model, Radeon, and evidence changes.
4. Visual review for user-facing changes.
5. Maintainer approval and squash merge.

Stale pull requests may be closed after 30 days without progress. Closing is
not a rejection of the idea; a smaller, current proposal may be reopened.

## Releases

Releases are cut from reviewed commits, use semantic versioning, record checksums
for competition artifacts, and keep truthful blockers visible. No release may
claim live Radeon execution without independently inspectable receipts and the
required demonstration video.
