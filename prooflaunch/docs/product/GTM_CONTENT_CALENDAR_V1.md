# GTM Content Calendar V1

Date: 2026-08-01  
Runtime artifact: `content-calendar.json`

## Outcome

The seven-day theme list now compiles into an operational, content-addressed
calendar. It is not a publishing queue disguised as a document: every slot has
an absolute UTC instant, an explicit IANA timezone, a local display instant, a
review deadline, dependencies, a named approval role and a manual activation
boundary.

Postiz informed the external-service boundary in the open-source radar, but no
AGPL implementation code is embedded. The current deadline path retains the
proven Python runtime and implements the required constraint scheduling behind
its own typed artifact.

## Scheduling constraints

- Exactly seven slots, derived from the strategy's approved primary and
  secondary channel drafts.
- The operator supplies an IANA timezone; the browser timezone is never
  inferred silently.
- Every activation instant has a 24-hour human-review window.
- Slots are separated by at least 18 hours and at most one slot occupies a
  local calendar date.
- A channel may appear at most four times in the seven-slot window.
- Professional routes skip local weekends; consumer-organic routes may use
  them.
- Zero-budget calendars cannot contain a paid channel.
- No automatic rescheduling, publishing, activation or budget allocation.

## Slot dependency graph

Every slot is blocked on:

1. the exact evidence claim ID;
2. the exact channel-native draft ID;
3. the content-bound human release decision.

The resulting calendar enters the same GTM artifact-set digest as the strategy,
channel portfolio, copy and experiment. A timezone, deadline or slot mutation
therefore invalidates the prior release decision.

## Verification

- All 48 business/lifecycle/budget/risk combinations compile across UTC,
  New York, Tokyo and London.
- A New York daylight-saving transition preserves the intended local time and
  produces unique UTC instants.
- Weekend routing differs intentionally between B2B professional routes and
  B2C short-video routes.
- Invalid IANA timezones, digest tampering, paid leakage and automatic release
  fail closed.
- Runtime, HTTP and UI tests verify that the same calendar appears in the human
  preview and final evidence bundle.

## Truth boundary

This proves scheduling and approval mechanics. It does not prove that any slot
was published, reached an audience or produced creative, causal or revenue
effect.
