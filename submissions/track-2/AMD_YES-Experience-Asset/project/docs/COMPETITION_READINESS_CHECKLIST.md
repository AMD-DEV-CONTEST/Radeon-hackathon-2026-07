# Track 2 Competition Readiness Checklist

Status: `TEAM-VISIBLE / WORKING CHECKLIST`

Final deadline: **2026-08-06 23:59 Beijing/Singapore time (UTC+8)**.

This file turns the formal contest requirements and the team's evidence plan
into an owner-visible checklist. It is not a substitute for the current
[official rules](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0)
or [official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07).
When a rule changes, update the authoritative summary first, then this file.

The detailed official-requirement-to-plan audit, completion expectation and
known-gap list is maintained in
[`COMPETITION_REQUIREMENT_COVERAGE.md`](COMPETITION_REQUIREMENT_COVERAGE.md).

Use `TODO`, `IN PROGRESS`, `PASS`, `BLOCKED`, or `N/A` in the Status column.
Do not put legal names, email addresses, credentials, private data, or hidden QA
material in this public/team-visible checklist; retain only an opaque evidence
reference where necessary.

## 0. Master competition execution board

This is the team's **single contest-facing task board**. L3 remains authoritative
for implementation detail, but day-to-day status is updated here. A green PR is
not `PASS`: only the quality owner may promote a row after the required evidence
exists. Missing an internal date triggers re-planning; it does not silently
remove an acceptance criterion or authorize an unsupported claim.

All dates below are internal targets in UTC+8. `PASS` requires an evidence link
or retained packet, not a verbal report.

| ID | Internal target | Primary owner | Required task | Depends on | `PASS` evidence / exit condition | Current status |
|---|---|---|---|---|---|---|
| T00 | Jul 24 | Quality/integration owner | Review and publish the Agent/risk-hardening contract | Owner authorization for commit/push/PR | Contract checks pass; reviewed PR merged; PR #7/#8 receive the new base | PASS — PR #9 merged; the hardened contract is on `main` and both implementation lanes received it |
| T01 | Jul 25 | Each of the three members | Confirm contest eligibility and the exact shared Team Name | Individual account access | Section 1 complete for all three members; private proof retained outside Git | PASS — team owner confirmed all three records are consistent on Jul 24; proof remains outside Git |
| T02 | Jul 26, 18:00 | Lane A + quality owner | Resolve PR #10 review, integrate it into PR #7 and accept E1-A1 contracts | T00 | `AgentRunStateV1`, `WorkPlanV1`, proposal/policy/execution/verification records, OpenAPI and public progress contract reviewed together; malformed approved arguments fail closed; exact relation binding is enforced | PASS — corrections were integrated and the final contract was accepted with PR #7 |
| T03 | Jul 27, 12:00 | Lane B + quality owner | Bind PR #8 to the exact accepted E1-A contract and accept the React/typed-mock foundation | T02 and frozen E1-A1 API fields | React build/browser evidence; no invented backend state; progress UI uses the exact accepted contract | PASS — final E1-A contracts were re-vendored, reviewed and merged with PR #8 |
| T04 | Jul 26, 23:00 | Lane A | Complete E1-A2 durable fake Agent loop | T02 | Fake model performs plan/retrieve/propose/validate/execute/verify/persist; restart, malformed-argument, denial and retrieval-scope tests pass | PASS — PR #7 review accepted the durable loop and its fail-closed negative paths |
| T05 | Jul 27, 18:00 | Lane A + integration owner | Complete E1-A3 on the current Radeon Cloud W7900 | T02, working SSH/pod, frozen model/runtime inputs | Current-pod manifest, GPU identity, 14B load, structured response, inert Tool Call proposal, Runtime allow/deny and terminal result, all bound to the exact tested commit | PASS — PR #7 review accepted the exact-commit E1-A3 packet at `evidence/milestones/e1-a3-real-w7900/20260725T121500Z/`; no performance Baseline is claimed |
| T06 | Jul 27 | Quality owner | Run the combined E1 gate and merge in dependency order | T02–T05 | PR #7 then PR #8 reviewed/merged; combined backend/frontend smoke passes; evidence packet retained | PASS — PR #12 was approved and merged at `main@cc5281a`; the failure-terminal/parser correction and exact-current-commit W7900/ROCm/14B packet `evidence/milestones/e1-combined/20260727T055758Z/` were accepted |
| T07 | Jul 28 | `Eas000n` + quality owner | E2/M1: deliver the first useful Experience Brief vertical slice | T06 and pipeline-plan acceptance | Real user input → M1 artifact → edit/save/pause/resume; `Vertical Slice V1` and early `Serving Reference S1` retained | IN PROGRESS — PR #13 merged at `main@b053f66`; bounded Issue #15 is active on `codex/e2-m1-experience-brief`. Local contract/backend/UI and failure-path checks are implemented; W7900 S1, frozen V1 evidence and quality-owner promotion remain open |
| T08 | Jul 29 | `1olaqua616-web` + quality owner | E3/M2: timeline and Critical Moment Map | T07 gate for integration/Ready/merge | Missing/conflicting/correction cases pass; prior M1 correction invalidates affected results visibly | TODO — bounded E3 preparation may overlap E2 only under the approved pipeline rules |
| T09 | Jul 30 | `Eas000n` + quality owner | E4/M3: Decision and Evidence Ledger plus judge-visible Agent loop | T08 gate for integration/Ready/merge | One continuous plan/RAG/Tool Call/Runtime decision/effect/verification/persistence run; forged/unsupported calls fail visibly | TODO |
| T10 | Aug 1 | `1olaqua616-web` owns E5; `Eas000n` owns E6; quality owner gates both | E5/M4 then E6/M5: current Knowledge Card, phase-gated historical RAG and five route decisions | T09 gate; E6 integration/Ready/merge additionally requires E5 promotion | Insight and Boundary Map; pre-readiness/pre-confirmation retrieval denials; summary candidates plus confirm/no-match path; five materially different route decisions; privacy and stale-approval tests | TODO — E5 and E6 are sequential promotions with only bounded N+1 preparation |
| T11 | Aug 2 | `1olaqua616-web` + quality owner | E7: private preview, approved external export, bilingual output and deletion | T10 gate for integration/Ready/merge | HTML/Markdown/JSON agree on version/hash; preview is not approval; deletion/retry tests and UI evidence pass | TODO |
| T12 | Aug 3 | `Eas000n` owns E8-A; `1olaqua616-web` owns E8-B; quality owner signs off | E8: freeze correctness-first complete-product Baseline v1 | T11 gate | All public fixture categories, full E2E, W7900 proof, server/Agent/UX records, retained failures and immutable manifest | TODO — two evidence lanes may run in parallel only after E7 promotion |
| T13 | Aug 3 | Lane A + quality owner | Evaluate at most one quantized Candidate Q1 | T12; successful Q0 compatibility/rollback probe | Same frozen product workload, declared difference, repeated results and quality floors; otherwise mark `N/A` and retain BF16 | TODO / N/A — optional, must not delay T14–T16 |
| T14 | Aug 3 | Quality owner coordinates; both lanes supply material | Freeze English Project Specification, README, video script and PPT/Poster content | Structure starts immediately; final claims require T09 minimum and preferably T12 | Every claim points to accepted evidence; architecture, local deployment and AMD optimization are explained in English | TODO — outline/storyboard starts in parallel now, not after product completion |
| T15 | Aug 5 | All three | Clean reproduction and full submission rehearsal; if a public WebUI is chosen, pass the E9 access/session/queue gate | T12 and T14; public WebUI additionally requires the frozen demo path | Fresh checkout/setup, 3–5 minute timed demo, signed-out link check, secret/privacy scan and rollback rehearsal pass; optional public UI also proves bounded overload and tunnel shutdown | TODO |
| T16 | Aug 6, internal 12:00 | Team owner, with all three approving | Submit the final package before the official 23:59 deadline | T01, T12, T14, T15 | Official-repo PR, accessible video/material links, final commit/tag/archive and submission URL recorded | TODO — 12-hour safety buffer; external publication still requires explicit authorization |

### Schedule recovery gate

The dependency recovery through PR #7 and PR #8 is complete. The remaining E1
recovery sequence does not weaken any acceptance criterion:

1. The first packet at
   `evidence/milestones/e1-combined/20260726T220422Z/` remains retained with its
   failed T06 review. The bounded local correction remains at
   `evidence/milestones/e1-combined/20260727T050325Z/`; the current
   exact-commit W7900 review packet is
   `evidence/milestones/e1-combined/20260727T055758Z/`; PR #12 accepted it and
   promoted T06 to `PASS`.
2. The quality owner reviews the corrected E2–E8 pipeline plan.
3. Only after that plan is accepted, create one bounded E2 Issue for the M1
   Experience Brief vertical slice with all three auditable checkpoints. E3
   may open as a dependency-blocked Draft only after the E2 contract
   checkpoint. Do not open the whole E2–E9 backlog.
4. If T07 or a later product gate slips, stop optional quantization, public
   tunnel, extra
   renderer and non-selected-route polish; preserve the thin end-to-end
   product, local Agent proof and required submission materials.
5. English specification, README structure, evidence index and video storyboard
   may proceed in parallel. Only verified claims and numbers enter the final
   material.

### What the quality/integration owner personally does

| Moment | Your action | What you decide |
|---|---|---|
| Now | Review the corrected E2–E8 pipeline plan | Accept the single-owner staggered route, or retain the paired-lane default before the E2 Issue is created |
| Every PR | Check scope, affected `AC-*`, evidence packet, failed cases, privacy/permission boundary and reproducible commands | Request changes or allow dependency-ordered merge; green CI alone is insufficient |
| Every milestone | Run the public gate plus the private quality-owner review, then inspect the real user-visible artifact | Mark `PASS`, conditional Medium with owner/deadline, or `BLOCKED` |
| Every W7900/performance claim | Verify exact commit/model/runtime/fixture identity and that all runs, including failures, were retained | Accept a reference/Baseline/Candidate claim or reject incomparable evidence |
| Daily | Update only changed rows, name the next blocker/owner, and ensure cloud work is committed/pushed before risky runs or session end | Whether work stays on the current gate or is re-planned |
| Final rehearsal/submission | Verify the full demo story, English package, signed-out links, three-member eligibility and reproducibility | Final go/no-go and explicit external-publication authorization |

### Drift-control rules

1. Work only on the earliest unblocked row; later work may prepare mocks or
   materials but cannot claim the earlier gate passed.
2. Do not open the whole E2–E9 backlog at once. Under the pending pipeline
   plan, create only the next stable single-owner milestone Issue after the
   previous combined gate passes.
3. If schedule slips, preserve the non-negotiable slice: one complete useful
   journey, all five route decisions, one polished selected deliverable, local
   W7900 evidence, durable state, bounded tools/privacy and reproducible proof.
4. Cut optional work first: public tunnel, extra renderers, multiple model
   Candidates, additional domains and equal visual polish for every route.
5. Any change to product behavior, permissions, durable schema, core model
   route or competition claim requires a prospective documented decision; do
   not hide it inside an implementation PR.

## 1. Three-member eligibility

Complete this table for **each** member. One member's approval does not prove
the other two are eligible.

| Member slot | Legal-name/contact registration completed | Luma joined and approved | AMD AI Developer Program registered | Same exact Team Name | Valid GitHub ID | Valid Discord ID | Evidence owner | Status |
|---|---|---|---|---|---|---|---|---|
| Member 1 / integration & quality | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | Team owner | PASS |
| Member 2 / Lane A | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | Lane A owner | PASS |
| Member 3 / Lane B | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | Lane B owner | PASS |

The team owner confirmed all three rows on 2026-07-24. The private source
records stay outside Git and must be rechecked against the final submission
form before T16; `PASS` here records the team-owner confirmation, not a public
disclosure of member identity.

Before submission, verify the spelling of the Team Name and member identifiers
against the actual registrations rather than copying them from chat.

## 2. Track 2 capability proof

The rules require at least two listed Agent capabilities. This architecture
targets all five, but the team may claim only capabilities backed by real
product and W7900 evidence:

| Target capability | Observable proof in product/demo | Owner | Status |
|---|---|---|---|
| Multi-step planning | Agent shows the current goal, acceptance condition, milestone plan, next highest-value question/action, and replan/safe-stop outcome | Lane A + Lane B | TODO |
| Tool invocation | Local model emits a structured tool proposal; Runtime validates schema, identity, allowlist and approval before an observable state/tool effect | Lane A | TODO |
| Local multi-turn memory | Saved canonical asset, milestone state and prior version survive a process/session restart and influence the resumed plan | Lane A | TODO |
| Permission/privacy control | Forged/disallowed tool calls are rejected; sensitive export/deletion remains blocked until the required human approval | Lane A + Lane B | TODO |
| Local RAG | Agent grounds M1–M4 only in current sources/same-asset versions; after card readiness it discovers summary candidates, and after user confirmation reads only selected history with provenance while preserving current facts | Lane A | TODO |

Core inference must stay on the local W7900/ROCm/vLLM path. A shared or closed
remote model API may not replace any proof above.

## 3. Agent-loop demo gate

The 3–5 minute demo should show one continuous, real run rather than unrelated
screens:

- [ ] Clarify the user's goal, private-material boundary, allowed actions, and
  acceptance condition.
- [ ] Read the local Experience Asset/source/history and show a multi-step plan.
- [ ] Show actual W7900/ROCm/vLLM identity and a local application-to-model trace.
- [ ] Show one structured tool proposal and Runtime allow/deny/argument check.
- [ ] Produce and save at least one user-visible milestone artifact.
- [ ] Show either a verified delivery or a visible `needs_input` / safe-stop /
  recovery path.
- [ ] Resume from saved state or inspect a prior version to demonstrate memory.
- [ ] Prove the RAG order: no cross-asset retrieval before M4 card readiness;
      summary candidates first; user confirmation before selected detail; no
      match/decline is visible and does not block delivery.
- [ ] Show route eligibility, privacy findings, explicit approval, and a real
  HTML/Markdown/JSON artifact from the same version.
- [ ] If an optimization is claimed, show comparable Baseline/Candidate evidence
  with conditions and failures—not only the best number.

## 4. Required English submission package

| Deliverable | Minimum content/evidence | Owner | Status |
|---|---|---|---|
| Project Specification Document | Scenario, Agent architecture diagram, core capabilities, model/local deployment, Radeon inference optimization | Quality owner coordinates | TODO |
| Source and English README | Clean setup, dependencies, launch, local model configuration, test/reproduction commands | Lane A + Lane B | TODO |
| 3–5 minute demo video | Actual application on W7900; complete Agent loop; readable evidence and terminal result | Lane B + quality owner | TODO |
| English PPT or Poster | Problem, user flow, architecture, differentiation, AMD evidence, measured result, limitations | Lane B | TODO |
| Sanitized evidence index | Exact commit/config, accepted milestone packets, Baseline/Candidate, stable media checksum/link | Lane A + quality owner | TODO |
| Official repository PR | Fork official repository; title `Track 2, <Team Name>, <Application Name>`; English text and accessible links | Team owner | TODO |

The official submission PR, media upload, or public publication remains an
explicit external action. Preparing the files does not authorize publishing.

## 5. Public demo decision

**Default decision: no persistent public Web UI is required.** The official
deliverable is the recorded real-GPU demo plus reproducible source. Use a local
or SSH-forwarded UI during development and rehearsal.

If the team chooses the optional live URL, implement and verify the approved
[`E9 public-demo requirement contract`](kinnyu/E9_PUBLIC_DEMO_ACCESS_AND_QUEUE_REQUIREMENTS.md).
Its access-code sessions and bounded queue protect the deployment boundary;
they are not a multi-user product and do not modify the accepted business
workflows.

Only use `rc-tunnel` when a judge-facing live URL provides clear value and the
user separately authorizes publication after the following gate passes:

- [ ] Application authentication and a non-default credential are verified.
- [ ] Only the Web UI/application port is exposed; raw vLLM, SSH, databases,
  Jupyter and admin panels remain private.
- [ ] Demo data is synthetic, public, or explicitly authorized and contains no
  private source/history.
- [ ] Upload, export, deletion and tool permissions have least-privilege limits.
- [ ] Error pages, logs and UI do not reveal filesystem paths, secrets or raw
  prompts/traces.
- [ ] A smoke test passes from a separate unauthenticated/authenticated browser.
- [ ] One-worker FIFO queueing, capacity six, duplicate-click idempotency,
      session isolation, truthful status and restart handling pass on the exact
      demo commit.
- [ ] Queue wait and downstream service time are recorded separately; worker
      count two remains disabled unless the W7900 concurrency gate passes.
- [ ] The URL owner and shutdown time are recorded; the tunnel is removed after
  the approved review window.

If any item is not verified, use the recorded demo instead. Never tunnel
`127.0.0.1:8000` when that is the raw vLLM endpoint.

## 6. ROCm baseline and optional optimization evidence

| Gate | Purpose | Must retain | Status |
|---|---|---|---|
| E1 viability | Prove the selected 14B BF16 model, structured response and inert Tool Call proposal work on W7900/ROCm | Environment/model manifest, load trace, parsed response/proposal, failure/rollback notes | TODO |
| E2 `Serving Reference S1` | Measure a small model-service/tool-call workload early enough to discover compatibility, latency or VRAM blockers | Frozen serving workload, exact accepted E1 profile and repeated operating measurements | TODO |
| E2 `Vertical Slice V1` | Prove and measure the first complete M1 product journey without treating it as the formal product baseline | Frozen fixture/workflow, product result, Agent-task measurements and failures | TODO |
| E8 Baseline v1 | Freeze the complete correctness-first product before tuning claims | Immutable three-layer manifest, all runs/failures, report, accepted commit | TODO |
| Quantization `Q0` probe | Optionally test exact W7900/ROCm/vLLM compatibility without claiming an optimization | Isolated smoke workload, compatibility result, failure and rollback notes | TODO / N/A |
| Quantized Candidate `Q1` | Pursue formal optimization evidence only after Baseline v1 and exact compatibility review | Prospective declared variable, same frozen product workload/model lineage, repeated results, quality floors, rollback | TODO / N/A |

Quantization is a declared experimental variable, so it cannot literally be
identical to the BF16 Baseline. Freeze the task/input, model source and revision,
context/generation/measurement conditions, and every **undeclared** field. Do
not describe E1 viability, S1, V1 or Q0 as the formal product Baseline or as an
optimization win. Quantization can support a measured AMD optimization claim;
it is not documented here as a guaranteed extra 20 points. The current rule
text couples the optional bonus wording to use of the Radeon Cloud model API
with quantization, distillation or another optimization method. Self-hosted
vLLM quantization clearly supports the base AMD inference-optimization
evidence, but the team must obtain written organizer clarification before
claiming that it independently qualifies for the optional bonus.

## 7. Final safety, IP, and reproducibility gate

- [ ] Clean checkout reproduces setup, tests and the intended demo path.
- [ ] License/source/revision or hash is recorded for model, data, code and
  externally derived assets.
- [ ] No model weights, caches, databases, private inputs, secrets, cookies,
  tokens, SSH material, hidden QA or unrestricted raw traces are in Git.
- [ ] Submitted source/data does not include unique commercial IP or customer
  data that should not be covered by contest submission terms.
- [ ] Every performance/local-run claim points to the exact accepted commit,
  manifest, commands, sample size and retained failures.
- [ ] English links and media permissions work in a signed-out browser.
- [ ] `bash scripts/pre_stop_checkpoint.sh` passes before the final cloud stop.
- [ ] Final repository, release tag/archive, media checksum and official PR URL
  are recorded by the team owner.

## 8. Cut-line and sign-off

Record these before the final week; leaving all three blank is a schedule risk:

| Decision | Value | Owner | Status |
|---|---|---|---|
| Feature cut-line | Five route decisions/contracts and one complete selected deliverable must remain; only non-selected-route visual polish, extra renderers, public tunnel and multiple optimization Candidates may be reduced | Quality owner | PASS — fixed before recovery work |
| Scope freeze | Active since P0/L3 approval; no new P0 requirement enters without explicit owner change control | Quality owner | PASS — approved scope is fixed |
| Functional freeze | Begins only after E7 trial and quality acceptance; after that only blocking correctness/privacy/reproducibility fixes and evidence/material work enter | Team owner | TODO — cannot precede E7 acceptance |
| E8 Baseline freeze | Begins only when the complete correctness-first product and immutable Baseline v1 manifest pass the E8 gate; any later behavior change requires a new Baseline version and rerun | Quality owner | TODO |
| Submission rehearsal | 2026-08-05 12:00 UTC+8; clean setup, full demo, English links, signed-out access and rollback rehearsal | All three members | PASS — date fixed |

Final sign-off requires: no Critical/High defect; every conditional Medium has
an owner/deadline; core inference and Agent loop are demonstrated locally;
three-member eligibility is confirmed; and every required English artifact is
ready before the official deadline.
