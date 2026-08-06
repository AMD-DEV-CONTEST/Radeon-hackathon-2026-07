# ColorGraph Landscape Annotation Guideline v2

> Frozen identifier: `colorgraph.landscape-annotation/v2`  
> Frozen date: 2026-07-30  
> Scope: real-camera Landscape Gold Set truth for shot, scene, mask, depth,
> content-aware balance, representative-frame, ranking and repair acceptance.

This version normatively incorporates
[`LANDSCAPE_ANNOTATION_V1.md`](LANDSCAPE_ANNOTATION_V1.md), frozen at SHA-256
`b807fce3ffb021983871a468783e196573ac128eceeacfbeed53a2c92da47945`,
for common timebase, source, shot-boundary, scene, mask, relative-depth and
independent-review rules. If that file no longer matches the recorded hash,
v2 evidence is invalid. The additions below are semantic and are the reason
for the new identifier.

Any further semantic change requires a new guideline identifier, manifest
version and independently reviewed annotation set.

## 1. Content-aware exposure and white-balance truth

Annotators work from the frozen camera source through the declared input
transform and a calibrated reference display. They must not inspect either
candidate algorithm while establishing the reference.

For every scored sample record:

- exact source frame index and PTS;
- shot ID and whether the next sample crosses a shot boundary;
- expert reference exposure correction in EV;
- expert reference correlated color temperature in kelvin and Tint in the
  frozen ColorGraph convention;
- regions excluded from neutral estimation, including sky, snow, neon,
  saturated single-color surfaces and deliberate mixed-light accents;
- reference clipping-risk decision and measured highlight/shadow clipping
  ratio after the frozen delivery transform;
- ambiguity, confidence and written justification.

Night, snow, sunset, mixed light and rapid exposure change must each appear in
the frozen test split. The reviewer verifies sample time, exclusion masks,
display transform and reference values. Unresolved disagreement is rejected,
not averaged after looking at test results.

Acceptance compares candidate and predeclared baseline against the same
reference. Report exposure MAE/bias, white-balance error in mired, Tint MAE,
residual temporal flicker excluding declared cuts, and clipping risk.

## 2. Representative-frame truth

For each frozen shot, independently label every proposed candidate frame as
`usable` or `unusable`, with one or more reasons:

- transition contamination;
- blur or unstable camera motion;
- black/low-entropy content;
- severe clipping;
- occlusion;
- unrepresentative composition or transient subject state.

Annotators then define the acceptable-frame set without knowing which
selection came from the adaptive method or midpoint baseline. At least one
acceptable frame is required; otherwise the shot is rejected from scoring.

The downstream scene comparison uses the same frozen scene truth and the
same grouping algorithm/configuration, changing only representative-frame
selection. Report candidate/baseline usable rate and downstream scene
boundary F1 with source-cluster bootstrap confidence intervals.

## 3. Scene comparison additions

The v1 scene definition and taxonomy remain unchanged. For algorithm
comparison, each source group stores candidate, predeclared greedy baseline
and human reference boundaries/labels. Calibration thresholds are frozen
using calibration sources only. Test sources may be opened once for final
report generation and may not be used to revise thresholds.

Report per-source boundary F1 and label macro-F1, then macro-average by source
group. A claimed improvement requires the predeclared minimum and a
source-cluster bootstrap 95% lower bound above zero.

## 4. Repair acceptance truth

Repair cases are produced from frozen source, Grade Graph, renderer and
quality-report digests. Before running the repair system, independent experts
label each case as:

- `should_accept`: a minimal repair is possible without violating intent; or
- `should_rollback`: every tested repair should be rejected.

For accepted repairs record whether:

- all target objectives pass or improve by the frozen minimum;
- no technical hard metric regresses;
- no non-target region or quality metric regresses;
- intent drift remains within the frozen limit.

For rollback cases, accepting any candidate is an unexpected acceptance.
Report repair success rate, rollback accuracy, unsafe acceptance, hard
regression, side-effect and intent-drift violation rates, plus accepted
objective improvement and intent drift. The frozen test set must contain both
repairable and rollback cases.

## 5. Expert ranking truth

Ranking follows the blinded, randomized paired-comparison protocol in
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md). Each source group belongs
to exactly one split. At least three qualified reviewers rate every pair;
reviewer reliability is estimated from train only, temperature from
calibration only, and final accuracy/log-loss/confidence intervals from test
only.

Candidate feature vectors, render/graph digests, pair identity, reviewer
response and viewing-environment evidence are frozen before unblinding.
Rule-wins, CLIP and SigLIP2 baselines use the same pairs. A trained preference
model is eligible only if every required baseline comparison passes its
predeclared accuracy and log-loss confidence-interval gates.

## 6. Manifest and evaluation binding

Every v2 manifest must record this guideline path and SHA-256. Each metric
section binds exact manifest material IDs:

- analysis samples additionally bind every sample to a material ID;
- representative, scene and repair records carry one material ID each;
- ranking records bind their source IDs and splits to manifest source groups.

`colorgraph evaluate --gold-audit ... --require-passed-gold` recomputes the
audit, verifies all media/annotation/license/guideline hashes, rejects
cherry-picked test subsets and requires explicit frozen metric gates. A
formula fixture without those conditions remains `engineering_only`, even
when every numeric gate passes.
