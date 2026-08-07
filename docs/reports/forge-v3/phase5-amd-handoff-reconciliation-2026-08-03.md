# CESARops Forge V3 — AMD Provisioner Handoff Reconciliation (2026-08-03)

Scope: `core/forge-amd-provisioner` audit, safe-local validation, V3 integration prep.  
Constraint honored: **no live AMD login/provisioning performed**.

## 1) V3 completion commit and branch

- V3 integration branch: `forge-v3-integration`
- V3 completion commit: `341f63e6b700412f974c42a606b5165c19026496`
- Remote tracking: `origin/forge-v3-integration` at same SHA

## 2) AMD integration branch

- Branch: `forge-v3-amd-integration`
- Remote tracking: `origin/forge-v3-amd-integration`
- Current HEAD: `341f63e6b700412f974c42a606b5165c19026496`

## 3) Phase 0 safety state (V2 + tree status)

- V2 baseline remains available on `main` at `942b0dc`
- `git log -- core/forge-amd-provisioner` shows provisioner path currently rooted in baseline commit lineage in this repo copy.
- Working tree not clean (pre-existing untracked):
  - `Cargo.toml.orig`
  - `core/forge-test-lab/`
  - `forge_src/dispatch.html.bak`
  - `forge_src/main.rs.bak`
  - `reports/`
  - `var/`

## 4) Evidence ingestion reconciliation

### Located
- Full provisioner crate source/tests/examples:
  - `core/forge-amd-provisioner/src/*.rs`
  - `core/forge-amd-provisioner/examples/run_amd_provisioner.rs`
  - `core/forge-amd-provisioner/endpoints.json`
- Forge V3 integration evidence docs:
  - `docs/reports/forge-v3/phase0..phase4`
- Knowledge repo manifest references to AMD audits:
  - `/var/cesarops/forge-knowledge-repo/MANIFEST.md`

### Not located as concrete files
- Sonnet AMD Provisioner Evidence Audit Report artifact file
- Later Gemini/Sonnet completion report artifact files
- `/var/cesarops/forge-knowledge-repo/evidence/` is currently empty in this environment

Conclusion: prior audit/completion narratives remain **claims** unless tied to code/tests/runtime artifacts below.

## 5) Current truth matrix (code + runtime evidence)

Legend: `VerifiedLocally | ImplementedNotExercised | FixtureVerified | Simulated | Broken | Missing | Unknown`

| Capability | Classification | Evidence |
|---|---|---|
| playwright-rs dependency | VerifiedLocally | `Cargo.toml` line with `playwright-rs = "0.15.1"`; `Cargo.lock` entries for `playwright-rs`/macros; `cargo check` success. |
| Chromium launch | VerifiedLocally | `src/playwright.rs::run_browser_proof`; runtime log: `Chromium launched`. |
| actual screenshot capture | VerifiedLocally | `page.screenshot_to_file("/tmp/forge_browser_proof.png")`; artifact exists size 4254 bytes; SHA256 `3878570f4a62a0d65f57cf1754e0269e56ec797f4e36e26b44c172eb6e800401`. |
| Xvfb | Broken | `src/browser.rs` starts fixed `:99`; runtime repeatedly reports `Server is already active for display 99`; non-deterministic startup ownership. |
| x11vnc | Broken | `src/browser.rs` uses `-bg`; spawned daemon detaches; many leaked `x11vnc` processes remain after tests (`ps`/`ss` evidence). |
| websockify/noVNC | Broken | `src/browser.rs` uses `websockify ... -D`; detached process persists; listener seen on `0.0.0.0:6080` (not isolated per run). |
| localhost-only binding | Broken | x11vnc uses `-localhost`, but websockify binds all interfaces (`ss`: `0.0.0.0:6080`). |
| MissionSpec route | Missing | No backend route for AMD provisioner found; only V3 demo route exists in `forge_src/main.rs`. |
| MissionSpec embedded panel | Missing | No concrete UI/backend bridge implementation found for admin AMD provisioning session. |
| manual-authentication pause | FixtureVerified | `run_browser_flow` waits on selector and prints pause instructions; exercised by local fixture test logs. |
| actual AMD portal navigation | ImplementedNotExercised | Navigation to `AMD_CLOUD_URL` implemented in `run_browser_flow`; only local fixture URL exercised. |
| authenticated dashboard detection | FixtureVerified | Selector `#dashboard-ready` wait implemented and passed in local fixture tests. |
| instance form interaction | Missing | Explicit TODO in `src/playwright.rs` for DOM interactions/selectors/click flow. |
| instance creation | Simulated | Instance ID derived from hash (`amd-inst-<hash>`), not AMD API/portal result. |
| instance metadata extraction | Missing | No parsing of real instance ID/IP/image/billing metadata from AMD portal/API. |
| SSH connection | ImplementedNotExercised | Real `ssh` command invocation in `src/health.rs`; no successful real-host execution evidence in this run. |
| AMD GPU/ROCm validation | ImplementedNotExercised | `rocm-smi --json` via SSH implemented; no live ROCm success artifact. |
| model startup | Missing | No remote model bootstrap command orchestration after provision. |
| `/v1/models` health check | ImplementedNotExercised | Real HTTP check implemented; exercised mainly as failure path to `.example.com` in lifecycle test. |
| registry isolation | FixtureVerified | `FORGE_REGISTRY_PATH` override in `src/registry.rs`; isolation tests in `src/tests.rs` pass. |
| staging registration | ImplementedNotExercised | Registration path exists in worker; no verified staging registration artifact from real validated endpoint. |
| production registration guard | FixtureVerified | Guard in `src/worker.rs` blocks simulated/local-browser modes to persistent registries; tests pass. |
| duration measurement | Broken | Success path uses `Instant`; failed-health path hardcodes `startup_duration: 5000` in `src/worker.rs`. |
| cleanup and destruction | Broken | Drop attempts `kill`, but detached daemons (`-bg`, `-D`) survive; large leaked process/socket footprint observed. |
| credential handling | FixtureVerified | `src/credentials.rs` permission checks + shell metachar rejection; unit test verifies rejection logic. |
| test isolation | FixtureVerified | Per-test isolated registry helper + cleanup in `src/tests.rs`; tests pass with isolated paths. |
| idempotency | Broken | `is_endpoint_registered` pre-check exists, but `register_endpoint` only appends; `endpoints.json` has duplicate active entries. |

## 6) Reconciliation with prior Sonnet audit claims

### Confirmed by current evidence
- Real Playwright + Chromium launch and screenshot: **confirmed**
- Xvfb/x11vnc/websockify spawn attempts: **confirmed**
- Credentials parsing + some registry guards: **confirmed**

### Improved vs earlier “simulated/missing” concerns
- Real navigation + selector wait logic now present: **implemented and fixture-verified**
- Real SSH command invocation and ROCm parsing path present: **implemented (not live-exercised)**
- Timing via `Instant` added for success path: **implemented**

### Still unresolved / regressed risk
- Instance creation + metadata extraction remain simulated/missing
- MissionSpec integration remains absent
- Cleanup/process isolation remains unsafe (detached process leaks)
- Websockify interface binding not localhost-only
- Failure duration still synthetic constant in one path

## 7) Required safe-local test runs and outputs

Requested commands:

1. `cargo check -p forge-amd-provisioner` from repo root  
   - Result: package not found in root workspace layout (`did not match any packages`)

Fallback run in crate (same crate validated):

- `cd core/forge-amd-provisioner && cargo check` → **PASS**

2. `cd core/forge-amd-provisioner && cargo test --all-targets` → **PASS**
   - `6 passed; 0 failed`

3. `cd core/forge-amd-provisioner && cargo clippy --all-targets -- -D warnings`
   - Result: **blocked** (`cargo-clippy` component missing in current toolchain)

Additional safe evidence run:
- `cargo test test_provisioner_lifecycle -- --nocapture` (local fixture only)
  - fixture page loaded with title `AMD Login`
  - selector `#dashboard-ready` detected
  - real screenshot written (`/tmp/forge_browser_proof.png`)

## 8) Local browser proof artifacts

- Screenshot: `/tmp/forge_browser_proof.png`
- Size: `4254` bytes
- SHA256: `3878570f4a62a0d65f57cf1754e0269e56ec797f4e36e26b44c172eb6e800401`
- Log evidence includes:
  - Chromium launch
  - fixture page title read
  - dashboard marker detected

## 9) Remaining defects (blocking and non-blocking)

Blocking before Gate A/B:
1. Browser bridge cleanup leak (`x11vnc -bg`, `websockify -D` detached)
2. Websockify binding not localhost-only (`0.0.0.0:6080`)
3. No MissionSpec admin route/panel/tokenized proxy control

Blocking before Gate B/C/D:
4. No real instance form automation + metadata extraction
5. No verified real SSH/ROCm/model startup success path artifacts
6. Idempotency/registry dedupe weakness (duplicate active endpoints)

Quality/correctness:
7. `startup_duration` synthetic `5000` on failed-health path
8. Fixed display `:99` collision risk

## 10) V3 integration map (minimum safe boundary)

`MissionSpec admin action -> V3 InfrastructureMission -> ForgeAMDProvisioner -> InteractiveBrowserSession -> Human auth/MFA -> Provision -> SSH/ROCm/model validation -> Staging-only registration -> ProvisioningReport -> Human Review`

Implementation boundary requirements:
- Single `mission_id` + `run_id` preserved end-to-end
- Reuse V3 chain-of-custody artifact model (`forge_src/v3_slice.rs` pattern)
- Stage-gated state machine; no direct production registration path

## 11) MissionSpec integration status

Current status: **Absent** (no concrete AMD admin API + no embedded panel wiring found).

Minimum admin-only interface needed:
- Action: `Provision AMD ROCm Worker`
- States:
  - `AwaitingBrowser`
  - `AwaitingHumanAuthentication`
  - `BrowserAuthenticated`
  - `Provisioning`
  - `InstanceReady`
  - `SSHVerified`
  - `ROCmVerified`
  - `ModelEndpointVerified`
  - `RegisteredStaging`
  - `Failed`
  - `Destroyed`
- Session controls:
  - short-lived token
  - localhost-only proxy path
  - immediate terminate action
  - credential redaction in logs

## 12) Supervised live-test plan (A–E, no silent advance)

### Gate A — Real AMD Login Proof (no instance creation)
- Start browser session with operator present
- Navigate to real AMD URL
- Manual login/MFA
- Capture authenticated URL/title/stable selector proof
- Explicit operator confirmation checkpoint before exit

### Gate B — Single Instance Provisioning
- Operator approval required to proceed
- Launch one MI300X instance only
- Capture real instance ID/IP/image/timestamps/billing state
- Stop before registration

### Gate C — Infrastructure Validation
- SSH into instance
- Run `amd-smi`/`rocm-smi` and capture stdout/stderr + exit codes
- Launch selected vLLM model endpoint
- Query `/v1/models`; capture full response + timing

### Gate D — Staging Forge Integration
- Register endpoint in **Staging only**
- Dispatch one bounded V3 mission
- Preserve mission/worker/endpoint/model IDs + artifact hashes
- Verify same run visibility in MissionSpec/Forge admin

### Gate E — Cleanup
- Export proof bundle
- Remove staging endpoint
- Destroy cloud instance and verify billing end-state
- Tear down browser/profile/session artifacts

Advance policy: each gate requires explicit operator acknowledgment + persisted evidence artifact before next gate.

## 13) Credential and registry safety findings

Strengths:
- Credentials permission enforcement + shell injection guard
- Simulation-to-persistent-registry blocks present and tested
- Test registry isolation infrastructure present

Risks:
- Detached browser bridge daemons persist across runs
- websockify interface exposure not constrained to localhost
- Registry append-only behavior allows duplicate active entries

## 14) Rollback plan

- Operational rollback target: `main` @ `942b0dc` (stable V2 baseline)
- V3 fallback branch: `forge-v3-integration` @ `341f63e`
- AMD intake branch isolation: `forge-v3-amd-integration` (no live provisioning performed)

If AMD integration changes are introduced later:
1. keep changes on `forge-v3-amd-integration`
2. verify via gated A→E evidence before merge
3. if any gate fails, revert branch to last known good SHA and keep V2 in service

## 15) Exact implementation order (smallest safe path)

1. Fix browser bridge lifecycle (remove daemon-detach mode; deterministic PID ownership; reliable teardown)
2. Enforce localhost-only noVNC proxy binding and tokenized access
3. Add MissionSpec admin-only AMD session route + panel state wiring
4. Implement real instance form automation + metadata extraction
5. Correct duration accounting on all paths (no synthetic constants)
6. Harden registry dedupe/idempotency semantics
7. Add staging-only registration + V3 InfrastructureMission adapter preserving mission/run IDs
8. Execute supervised gates A→E with evidence bundle at each gate

## 16) Go / No-Go recommendation for real AMD login

Recommendation: **NO-GO for unattended progression beyond Gate A.**  
Conditional allowance: **Gate A only** may proceed under operator supervision **after** fixing browser-session isolation/cleanup and localhost-only proxy controls.  
Rationale: current process leakage + network exposure + missing MissionSpec admin controls violate safe live-test posture.

