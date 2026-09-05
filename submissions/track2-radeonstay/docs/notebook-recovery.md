# Radeon Cloud Notebook recovery

This runbook restores RadeonStay after recreating the single allowed Radeon
Cloud Notebook. It is a disaster-recovery path, not a substitute for the formal
C2/C3 evidence lifecycle.

The current recoverable release is C2 v3 commit
`f7ba6811205a40ba51ca74c82b43129b616f74c5` with the accepted minimal B→C
comparison. Its optimized C profile is suitable for the public deployment, but
its proof must remain `status=accepted` with
`final_evidence_accepted=false`. It is not an `accepted_final` claim.

## Before recreating the Notebook

Keep these files outside the Pod and verify their SHA256 values:

- the deployment Git bundle;
- the exact `llama-server` runtime archive, including its sibling shared
  libraries;
- the accepted `runtime-proof.json` and its SHA256;
- the frozen `release-profile.json` and its SHA256;
- `scripts/restore_notebook.sh`;
- the recovery manifest and checksum file.

For the current deployment, preserve the reviewed accepted B→C
`runtime-proof.json` and `release-profile.json` recorded in the private recovery
manifest. They must bind Reference B, Optimized C, C2 v3, and comparison SHA256
`7f85a614a31da10e5484ee41034282210ac44caf84012617dea5c786c0f03f59`.
Do not label either artifact `accepted_final`. That promotion is allowed only
after the complete A–H candidate set, five-run Stability, and long-soak process
in the
[evaluation plan](evaluation-plan.md#post-submission-final-runtime-proof-and-recovery-profile)
passes.

Do not copy `.env`, identity keys, SQLite databases, audit data, chats, or Tunnel
state into a replacement deployment. Generate fresh secrets and a fresh database
for each new deployment. An App-process restart inside that same deployment
deliberately reopens its existing run-bound database instead of creating or
copying one. The 27.3 GiB Q6_K model is reproducibly downloaded from its fixed Hugging Face
revision and checked against the documented SHA256 instead of being included in
the private recovery kit.

## Create the replacement Notebook

1. Create the Radeon Cloud template with **Storage = Persistent (PVC)**.
2. Launch the Notebook and wait for the workspace to reach 100% readiness.
3. Open a **Jupyter Terminal**. Do not run the restore from SSH: an SSH login may
   not inherit `FRP_BROKER_URL` even when the Pod supports Tunnel.
4. Confirm that the dedicated PVC directory is writable and choose an absolute
   RadeonStay state root below it.
5. Upload the recovery-kit files to the Notebook without placing them inside the
   recovered Git repository.

Check Tunnel injection before starting either recovery path. The strict restore
script fails before dependency installation or model download when the Tunnel
installer or injected variables are absent. It never overwrites an existing
release directory, model, partial download, `.env`, or credentials file.

## Restore the current accepted B→C release

The checked-in `restore_notebook.sh` intentionally accepts only the future
`accepted_final` schema. It will reject the current accepted/non-final proof, so
do not weaken its validation or pass placeholder Stability/soak values. Restore
the current public version as follows:

1. verify the recovery-manifest hashes, Git bundle integrity, C2 v3 commit,
   runtime archive, model file, accepted proof, and release profile;
2. extract the bundle into a new release directory, create a Python 3.12 virtual
   environment, and install the frozen `requirements.lock`;
3. create a new deployment run ID, `0700` runtime directory, fresh `0600` `.env`,
   fresh run-bound database, and new runtime-instance path—never copy old private
   state;
4. start the model and App with the exact Optimized C profile in
   [Judge Quickstart](judge-quickstart.md): context 16384, parallel 1,
   batch/ubatch 256/64, Flash Attention on, f16/f16 KV, thinking off, fused
   plan/evidence off, and `41/41` layer offload;
5. bind `RADEONSTAY_EVIDENCE_RUN_ID=c3min-f7ba681-C-r3`, while keeping the new
   deployment run ID separate; verify liveness, readiness, authentication,
   `process_binding_valid=true`, `status=accepted`, and
   `final_evidence_accepted=false`;
6. install the official `rc-tunnel` from the repository's Radeon Cloud User
   Guide, expose only the authenticated UI port, and retain the printed URL and
   credential-file location outside Git.

This path reproduces the current deployment; it does not recapture Radeon
telemetry or create a new evidence lifecycle. Preserve the deployment logs under
the PVC state root and do not write them into the source checkout.

## Future accepted_final automated restore

After A–H, five-run Stability, and the long soak pass, use the hashes, ref, and
commit from the private recovery manifest:

```bash
bash restore_notebook.sh \
  --source-bundle ./source.bundle \
  --source-sha256 <SOURCE_BUNDLE_SHA256> \
  --bundle-ref <BUNDLE_REF> \
  --expected-commit <DEPLOY_COMMIT> \
  --llama-runtime ./llama-runtime.tar.gz \
  --llama-runtime-sha256 <LLAMA_RUNTIME_SHA256> \
  --release-profile ./release-profile.json \
  --release-profile-sha256 <RELEASE_PROFILE_SHA256> \
  --runtime-proof ./runtime-proof.json \
  --runtime-proof-sha256 <RUNTIME_PROOF_SHA256> \
  --state-root /absolute/path/on/the/pvc/radeonstay
```

The script performs these fail-closed stages:

1. validates Python 3.12, required commands, Tunnel injection, hashes, and Git
   bundle integrity;
2. creates a new release directory and installs `requirements.lock` into an
   isolated virtual environment;
3. restores and verifies the exact ROCm `llama-server` runtime;
4. downloads and verifies the pinned Q6_K model;
5. verifies that the immutable `accepted_final` proof, release profile, C2
   commit, winner, model, exact `41/41` offload, ROCm, Radeon architecture, CU
   count, VRAM identity, five-run Stability, and long-soak bindings agree;
6. generates fresh audit, identity, and UI credentials with mode `0600` and a
   deployment-run-bound isolated SQLite database;
7. starts the model on loopback with the recorded optimized profile;
8. starts the authenticated Web UI on loopback and checks readiness plus the
   anonymous-access rejection;
9. installs the official `rc-tunnel`, exposes the UI port, and prints the public
   URL and credential-file path.

Artifacts and logs remain under the supplied PVC state root. On failure, only
the processes created by the current restore attempt are stopped; logs,
downloads, source, and manifests are preserved for diagnosis.

## Single-Notebook application hot upgrade

The competition account permits only one Notebook. When the verified local
`llama-server` is healthy and its model, binary, listener, and effective launch
configuration still match the pinned identities, an application-only upgrade
may reuse that one model process instead of starting a second 27.3 GiB model.
This is an operational deployment path, not a substitute for a fresh formal
evidence lifecycle.

The target environment validated on 2026-08-06 used Python 3.12.3, ROCm 7.2.1,
`gfx1100`, 96 compute units, and approximately 48 GiB of VRAM. The loopback
model profile was Q6_K, context 16384, parallel 1, batch/ubatch 256/64, Flash
Attention on, f16/f16 KV cache, thinking off, fused plan/evidence off, and all
41 model layers offloaded through the configured `--n-gpu-layers 999`. This is
the released C profile; changing any of those values requires a new comparison
and proof. Keep the exact model and binary SHA256 values documented in the main
README as the authoritative identities; do not infer a retail GPU name from
`gfx1100`.

Use this fail-safe rollout sequence:

1. create a Git bundle from an isolated snapshot commit so uncommitted source
   is included without committing or pushing the operator's working tree;
2. recover that bundle into a new, current-user-owned `0700` release directory
   and install `requirements.lock` into a new Python 3.12 virtual environment;
3. generate fresh audit and identity secrets, a new deployment ID, a new
   deployment-bound SQLite filename, and a new private runtime-instance
   manifest; preserve only the existing UI credential pair during a seamless
   public handover;
4. before creating the manifest, verify the existing process PID and Linux
   start ticks, executable and model SHA256 values, raw command-line SHA256,
   effective service-configuration SHA256, model alias, loopback port, and
   ownership of the loopback listening socket;
5. start the new App on loopback port 7862 and verify liveness, readiness, an
   authenticated model-backed request, anonymous UI rejection, and
   `process_binding_valid=true`;
6. record the old App command and release path, terminate only that App, then
   start the already-verified new release on loopback port 7861 so the existing
   official Tunnel process continues forwarding without reconfiguration;
7. verify local and public liveness/readiness plus the authentication gate, and
   keep the prior release intact for an explicit rollback.

Never copy the previous database or its WAL/SHM files into the new release.
Never create a runtime-instance manifest from a remembered command: derive it
from the live `/proc` identity and validate it with
`evaluation/runtime_binding_evidence.py` before the App starts. If any identity
or listener check differs, stop the hot upgrade and use the full restore path
with a new model lifecycle. The App may be rolled back by stopping only the new
App and restarting the preserved prior release; the shared model and Tunnel
processes must not be restarted during that rollback.

## Restart only the App in the same deployment

Do not rerun `restore_notebook.sh` merely because the App process stopped. Keep
the existing model process and release directory, then start the App from that
release's project directory with the same generated `.env`, virtual environment,
`HOME`, and `TMPDIR` recorded by the restore. Before starting it, verify that the
old App PID is no longer alive and that the App port is free.

The restart is accepted only when all of these invariants still hold:

- `RADEONSTAY_DEMO_RUN_ID` is unchanged and the database filename ends in that
  exact deployment run ID;
- the runtime directory is a current-user-owned `0700` directory;
- the database and any WAL, SHM, or journal sidecars are current-user-owned
  regular files with mode `0600`, never symbolic links;
- the existing database passes the SQLite schema, persisted audit-key
  fingerprint, Journey HMAC, and audit-chain checks during service startup;
- the still-live model matches the private runtime-instance manifest and the
  accepted release configuration.

A failed check is not repaired by renaming, copying, chmodding, or replacing the
database. Preserve the release for diagnosis and create a new deployment run if
its identity cannot be established. New deployments remain unique because the
restore script refuses an existing release directory and generates a fresh
deployment run ID unless `--run-id` supplies a new one.

An unconfirmed action is not executable after an App restart. Its minimized
Journey checkpoint may be restored, but the old capability is retired and the
UI requires a fresh authoritative Repreview. Confirmed bookings, tickets,
consented preferences, Journey progress, and the persistent audit chain remain
available after successful recovery.

## Evidence boundary after recovery

The recovery path deliberately separates two identities:

- `evidence_run_id` is the immutable `run_id` inside the accepted runtime proof;
- `deployment_run_id` is a fresh recovery-attempt identity used by the release
  directory, isolated database filename, and live runtime-instance manifest.

The accepted proof is preserved byte-for-byte. Readiness binds it through
`RADEONSTAY_EVIDENCE_RUN_ID`, while the current database and live model process
bind to `RADEONSTAY_DEMO_RUN_ID`. The release profile's model, binary, service
configuration, hardware identity, winner, and C2 hashes connect those two
scopes without pretending that historical telemetry belongs to the replacement
process. The Trust Card therefore presents the historical accepted
C2/winner/ROCm result together with a separately verified current PID,
executable, command line, model identity, and loopback LISTEN socket. It does not
claim that the old telemetry was recaptured on the replacement Pod.

Do not use the deployment run ID as new formal evidence, and do not relabel the
preserved evidence run ID as a new lifecycle. A new Pod is a new execution
lifecycle: use a fresh evidence run ID and re-run ROCm telemetry, quality,
performance, and binding collection before claiming a new C2/C3 result.
