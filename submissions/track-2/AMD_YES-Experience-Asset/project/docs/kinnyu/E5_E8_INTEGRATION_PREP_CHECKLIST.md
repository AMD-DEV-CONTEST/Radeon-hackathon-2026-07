# E5–E8 Integration Prep Checklist

- Updated: 2026-08-05 AEST
- Lane: Kali / Khalil — E5–E8 integration and `A0` Baseline
- Authority: `spec/FINAL_SPRINT_EXECUTION_PACKAGE.md` (this checklist adds no
  new rule; on any conflict the package wins)
- Deadline: 2026-08-06 23:59 UTC+8

This is the operational pre-flight and execution checklist for the single
E5–E8 integration lane defined by the final-sprint execution package. Each
item is either verified here with a date or left unchecked for the integrator.

## 1. Pre-flight: refs, pins, and branch

- [x] `origin/main` matches the package pin
      `335f798c853263a2220d992d9e85f5fe5f9b7862` (verified 2026-08-05).
- [x] E5 PR #40 head is `e3ff011` (verified 2026-08-05).
- [x] E6 PR #31 head is `8f03f3c`, still Draft / `CHANGES_REQUESTED`
      (verified 2026-08-05).
- [x] E7 PR #34 head is `31df834` (verified 2026-08-05).
- [ ] Re-run `git fetch origin --prune` immediately before integration starts
      and re-verify the four pins above; if any head moved, record the new
      head and re-check its diff before importing.
- [ ] Create one integration branch from current `origin/main` (for example
      `integration/e5-e8-a0`). Do not develop on `main`; do not open one PR
      per sub-step.
- [ ] On Radeon Cloud, use `/workspace/amd-track2-agent/repo` as the
      integration checkout, keep the Agent and vLLM environments separate,
      and keep all private services loopback-bound (`127.0.0.1`) by default;
      do not expose them publicly without explicit authorization.

## 2. Import order and operations

Use the remote branches as implementation sources, not as accepted milestones.

- [ ] **E5 from PR #40 as one stack.** It already contains PR #35 (`60c1ec2`);
      do not treat #35 and #40 as two sequential release gates. Its
      deterministic packet proves the disclosed local/fake GraphRAG cases
      only; E5 T11 (external W7900 exact-head local-inference gate) remains
      open and is tracked in section 3.
- [ ] **E6 from PR #31 by replaying the feature diff.** Exclude its PR #28
      baseline merge commit instead of cherry-picking the merge history.
      Importing #31's pure policy code is not E6 completion; the integrated
      head must drive the real E5 projection and stored E7 draft through
      SQLite, Runtime/production LangGraph, API, App, persistence/restart,
      and exact version/hash-bound approval seams.
- [ ] **E7 from PR #34 by replaying the feature/fix diff.** At the integrated
      head, recheck its two previously reported blockers (section 3): expired
      deletion must not permanently lock an asset, and E6 must recompute the
      same canonical approval binding/hash used by E7. Green isolated tests or
      the fix author's own evidence do not substitute for this recheck.
- [ ] **Apply the E6 consumer facts recorded in PR #42.** PR #41, #42, and
      #44 do not need to merge first; #44's 20K qualification is outside the
      critical path.
- [ ] **Retain PR #28's substantive state, permission, phased-RAG, and
      handoff semantics** without importing its stale review cadence as a
      product dependency.
- [ ] Preserve API/schema compatibility with E1–E4 and checked-in contracts;
      run dependency/checkpoint migrations explicitly instead of copying only
      endpoint files.

Before freezing `A0`, verify the observable contracts in the authoritative
package rather than treating a successful import as feature acceptance:

- [ ] **E5 / M4 observable matrix:** complete the package's `E5 / M4 must work`
      checks, including version/hash-bound readiness, summary-only candidate
      discovery, user-confirmed bounded detail retrieval, visible no-match or
      decline, durable correction/invalidation/retry/resume, and proof that
      historical retrieval does not mutate current statements.
- [ ] **E6 / M5 observable matrix:** complete the package's `E6 / M5 must work`
      checks for all five route decisions, route-specific contracts, truthful
      ineligibility, structured privacy findings/actions, exact-bound approval,
      and approval staleness after any bound input changes.
- [ ] **E7 delivery matrix:** complete the package's `E7 delivery must work`
      checks for stored Chinese or English drafts, user-facing preview,
      self-contained HTML/editable Markdown/canonical JSON with one shared
      version/hash, `SUPERSEDED` exports, second-confirmation idempotent
      deletion, and one visible partial-failure/retry path.

## 3. Gaps that must close at the integrated head

- [ ] **`sensitivity_tags` producer gap.** E5 produces no `sensitivity_tags`,
      while #31's deterministic detector reads them. Provide a small general
      deterministic text detector or an explicit user-provided privacy
      proposal that the Runtime validates. If no trustworthy proposal source
      runs, fail closed or require explicit review; an empty proposal list
      must not silently mean risk-free.
- [ ] **`EvidenceStrength.DIRECT` gap.** E1–E5 never produce `DIRECT`. All
      five `RouteDecision`s must execute, but they do not all have to be
      `READY`; preserve truthful `BLOCKED`/`INELIGIBLE` customer/evaluator
      results. Never weaken the predicate or invent `DIRECT` evidence.
- [ ] **E7 expired-deletion blocker.** Confirm at the integrated head that an
      expired deletion request does not permanently lock an asset.
- [ ] **E6/E7 approval-hash binding.** Confirm E6 recomputes the same
      canonical approval binding/hash that E7 consumes; any bound input change
      makes the approval stale.
- [ ] **Context numbers stay separate.** `20480` tokens is the approved
      business budget ceiling for tokenized input plus reserved output;
      `8192` tokens is the only verified W7900 window. `A0` uses the verified
      8K service configuration with deterministic trimming/chunking. Do not
      describe 8K as the permanent business limit or 20K as verified
      capability.
- [ ] **E5 T11 evidence.** The external W7900 exact-head local-inference run
      may share a device window with the real-model compatibility probe, but
      the retained record must separately identify: one schema-valid positive
      proposal, one semantic hard-negative, and the exact E5 schema
      compatibility result.

## 4. Verification commands

Repository checks on the integration branch (run at the final integrated head
before PR handoff, and rerun only if that head changes; after each import, run
the affected targeted checks rather than repeating every full gate):

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
git diff --check
```

Agent behavior (persistent environment):

```bash
source /workspace/amd-track2-agent/venvs/agent/bin/activate
pytest
ruff check .
```

On Radeon Cloud:

```bash
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
```

- [ ] List in the integration PR the exact invocations of the E5–E7 and
      browser/E2E commands introduced by the integrated code; the package
      does not guess future filenames.
- [ ] Run the milestone/artifact gate with the real canonical output, progress
      record, and M4/M5 retrieval trace when those files exist; retain its exact
      invocation and result in the integration evidence.
- [ ] Execute the package's full seven-case functional matrix and its separate
      public adversarial/failure checklist. Record every expected terminal
      state and retain failures; the seven functional-case runs are not a
      substitute for the separate adversarial/failure matrix.
- [ ] Run `bash scripts/pre_stop_checkpoint.sh` before risky tests, leaving
      the Pod, or destroying/replacing the instance.

## 5. `A0` freeze, evidence, and handoff

After the complete user path is green through the actual product surface
(React UI plus API, or a documented temporary operator path only where a UI
element is genuinely missing, with every gap named in the limitation list).
A CLI-only final result is not sufficient:

- [ ] Freeze exact application commit, prompts, fixture inputs/expected
      terminal states, Runtime policy, database seed, retrieval index,
      renderer, generation settings, model profile, and evidence directory.
- [ ] Use the known-good local BF16/`S0`-compatible service; frozen Stage 1
      finalists feed only the owner's Stage 2 comparison and never replace
      `S0` in the `A0` freeze.
- [ ] Run all seven public fixtures once, preserving complete failures.
- [ ] Record one complete W7900 flow demonstrating local inference,
      plan/retrieve/tool/verify/persist/deliver, allow/deny, restart/resume,
      privacy approval, phased RAG, and final rendering.
- [ ] Keep raw/large evidence append-only under
      `/workspace/amd-track2-agent`; push small sanitized evidence and
      report-ready summaries to Git immediately.
- [ ] Integration PR includes: outcome and exact commit; affected ACs and
      E5/E6/E7/E8/E9 boundary; commands and observed results; sanitized
      evidence paths/hashes; W7900 execution status (`PASS`,
      `NOT_RUN_INFRA_BLOCKED`, or `NOT_APPLICABLE`); known
      failures/limitations and submission impact; secret/private-data scan
      result; rollback commit/command.
- [ ] Every retained evidence packet records its independent decision
      (`PASS`, `CONDITIONAL`, `FAIL`, or `NOT VERIFIED`) in addition to the
      integration PR's W7900 execution status.
- [ ] Handoff to the owner and Ethan includes exact commit SHA, all
      launch/test commands, manifest/hash files, evidence paths, observed
      terminal states, failures, limitations, rollback command, and the
      clean-checkout reproduction result. Stage 2 starts only after this
      freeze.

Review surfaces (not stage-start approvals): the owner checks only E6
privacy/approval policy and W7900 evidence; Ethan checks only E7 canonical
hashes, approval staleness, export, deletion, and retry behavior; one
independent non-author teammate or coding Agent checks the consolidated diff.
A coding-Agent review qualifies only when a non-author teammate initiates it
or signs off on its findings. Only the package's substantive failure list may
stop integration or submission.
