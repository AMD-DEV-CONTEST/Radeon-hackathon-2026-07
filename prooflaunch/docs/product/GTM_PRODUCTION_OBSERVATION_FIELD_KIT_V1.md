# GTM production observation field kit V1

Date: 2026-08-02

## Outcome

A delivered, human-approved campaign can now produce a deterministic offline ZIP
that converts the preregistered experiment into a field-operable observation
workflow. The kit is not an evidence result. It is an empty, exact contract for
collecting the first real result without loosening attribution, privacy, budget or
human-release boundaries.

## Binding

Every kit is bound to the exact run ID, campaign ID, experiment ID, approved
`gtm-strategy.json` SHA-256, registered metrics, maximum registered minimum sample,
and budget tier. Generation fails unless the run has reached `bundle_ready` after
an authenticated human approval and all strategy artifacts reproduce exactly.

The ZIP contains:

- `capture.html`: network-free browser tool that hashes an authorized aggregate
  source export with Web Crypto and exports the exact observation JSON;
- `attribution-plan.json`: strategy-bound candidate/baseline arm tags, five-event
  taxonomy, aggregate dimensions, finance reconciliation fields and privacy rules;
- `attribution-tags.csv`: two exact, human-applied arm rows with distinct
  `utm_content` and `pl_arm` values;
- `binding.json`: immutable run, experiment, strategy, sample and budget binding;
- `experiment.json`: exact preregistered experiment;
- `metrics-template.csv`: candidate and comparable-baseline aggregate schema;
- `observation-template.json`: fail-closed non-valid placeholder contract;
- `economics-template.json`: second-stage contribution-economics contract, usable
  only after the server returns an observation SHA-256;
- `README.md` and `manifest.json` with member hashes and authority boundaries.

## Data and authority boundary

The source export is read locally only to calculate SHA-256. It is never uploaded,
copied into the ZIP or embedded in the observation JSON. The contract accepts no
audience identifiers, comments, transcripts, testimonials or creative bodies.
The ZIP contains neither tenant nor operator credentials and performs no network
request or automatic submission.

The attribution plan permits only aggregate exports grouped by experiment, arm,
channel and observation window. A first-party ephemeral key may be used upstream
for deduplication, but it cannot be exported. Names, emails, phone numbers, user,
device, cookie and IP identifiers, fingerprints and raw content are explicitly
prohibited. No tracking pixel or cross-site identity resolution is included.
Arm tags label exposures only and never establish that assignment was randomized.

Before aggregate import, the separate manual-publication receipt contract binds
the exact approved candidate asset, channel, candidate tags, public URL,
publication time and hashed operator/platform receipt. This adds traceability
without giving the Agent external publishing authority; see
`GTM_MANUAL_PUBLICATION_RECEIPT_V1.md`.

The product Experiment Lab exposes two dynamic controls without increasing the
static DOM budget:

1. `Download production observation kit` requires the tenant session, the exact
   delivered run and the operator approval token.
2. `Load observation JSON` verifies experiment and strategy identity, then fills
   the existing bounded aggregate form. A human must still inspect and submit it.
3. `Submit economics JSON` is enabled only after an observation exists, requires
   the operator token, verifies the exact observation ID and server-returned
   observation SHA-256, and posts the reviewed contribution-economics contract.
4. `Record publication receipt` imports one local JSON attestation, requires the
   operator token, and binds it to the approved asset and exact candidate tags.

The server remains authoritative. It rechecks the source kind and SHA-256, positive
timezone-aware window no longer than 31 days, deduplication, bot filtering, metric
bounds, registered sample floor, comparable baseline and zero-budget spend rule.
It appends an immutable observation event but never publishes, spends, mutates the
approved strategy or promotes learning automatically.

## API

`GET /v1/runs/{run_id}/production-observation-kit`

Required:

- authenticated tenant bearer bound to the run;
- `X-ProofLaunch-Approval-Token`;
- delivered, approved run with intact strategy artifacts.

The response is `application/zip`, `Cache-Control: no-store`, an exact SHA-256 ETag,
and evidence class `approved-experiment-empty-production-observation-kit`.

Observation submission remains:

`POST /v1/runs/{run_id}/outcomes`

Revenue reconciliation remains:

`POST /v1/runs/{run_id}/outcomes/{observation_id}/economics`

## Verification

The deterministic compiler test checks stable ZIP bytes, exact member inventory,
strategy, attribution-plan and sample binding, distinct candidate/baseline tags,
event-to-metric mapping, PII prohibitions, zero-budget enforcement code, local Web
Crypto hashing, absence of network calls and absence of authorization headers. The production API
test checks 403 without operator approval, authenticated ZIP delivery, SHA-256 ETag,
manifest boundaries and compatibility with the existing observation, economics and
learning loop. UI tests keep the 1,750-node static DOM budget and verify both controls.

This is a production-observation capability, not a production observation. Until a
real rights-cleared experiment runs and its authorized aggregate export is submitted,
production effect, causal lift, revenue causality, annual breakout, Top-1 status and
4A-level effect remain unobserved.
