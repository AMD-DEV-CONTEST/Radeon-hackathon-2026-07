# Safety Case V2 execution contract

This workstream implements release-blocking mechanics for TODO 1051–1097. It
does not assert that a live campaign is compliant or that Safety Case V2 is
frozen.

## Claim and disclosure gates

Every express, implied, comparative, testimonial, origin, medical, or financial
claim carries a stable identity, prior evidence locator, publication ordering,
and net-impression decision. Comparative claims add an exact comparison basis;
testimonials add verified experience and a prominent material-connection
disclosure; origin claims require qualification. Medical and financial content
cannot pass without a named specialist human approval.

Personal data requires a consent locator. AI-generated or materially edited
creative requires an AI provenance label. These are independent blockers.

## Channel and execution isolation

Google, TikTok, YouTube, Meta, and Amazon each receive a revisioned, SHA-256
bound policy snapshot and a format allowlist. The current artifacts exercise
drift detection against official policy hubs; they deliberately mark live
freshness as pending because the fixture hash is not represented as a hash of
the providers' live pages. Release therefore remains blocked until a dated
policy review binds the exact policy content used.

Direct and indirect prompt injection have separate findings. Paths must stay
under the approved root; network targets must be exact lowercase HTTPS hosts;
commands must be bare allowlisted executables and reject shell controls. Model,
data, and adapter revisions and hashes must match independently.

## Red team and risk acceptance

The mandatory suite contains memory poisoning, Agent collusion, reward
hacking, cross-Agent propagation, hallucinated sources, logo misuse, cultural
harm, and false comparison. A probe passes only when it was attempted, its
mechanical detector fired as expected, release was blocked, and an evidence
locator exists. Missing, duplicated, or failed probe kinds fail closed.

Risk acceptance requires a named accountable person, reason, residual risk,
and ISO-8601 expiry. It never overrides the critical blocker or the human
release gate.

## Evidence boundary

`config/cortex_x_v10_safety_case_contract.json` is executable policy.
`evidence/v10/safety-case-mechanical-fixture.json` is a controlled negative-
control receipt. It proves mechanics only. TODO 1098–1100 remain open until a
real output Safety Case, independent red-team rerun, and final frozen release
record exist.
