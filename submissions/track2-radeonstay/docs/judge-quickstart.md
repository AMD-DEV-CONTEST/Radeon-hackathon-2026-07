# Judge Quickstart

> This guide is bound to C2 v3 commit
> `f7ba6811205a40ba51ca74c82b43129b616f74c5` and the released minimal B→C
> Radeon comparison. The comparison is accepted, but it is not an
> `accepted_final` A–H/Stability/soak package. The final English deck, narrated
> demo video, and English subtitle sidecar are included in `docs/`; the
> historical project PDF remains outside this submission scope.

This guide targets the verified Radeon environment: Python `3.12.3`, ROCm
`7.2.1`, HIP `7.2.53211-e1a6bc5663`, and a detected `AMD Radeon Graphics`
device (`gfx1100`, device ID `0x744b`, 96 compute units, `51522830336` VRAM
bytes). The product string is reproduced verbatim; no retail GPU model is
inferred.

## 1. Verify the hardware boundary

```bash
python3 --version
hipconfig --version
rocminfo | sed -n '1,80p'
rocm-smi --showproductname --showmeminfo vram --showuse
```

Confirm the versions and detected values above, then retain the command output
with the deployment records. Do not present a recovery run as new formal
evidence unless the complete measurement lifecycle is repeated.

## 2. Start the local model

```bash
cd submissions/track2-radeonstay
: "${LLAMA_BIN:?Export LLAMA_BIN as the frozen ROCm llama-server binary}"
: "${MODEL_FILE:?Export MODEL_FILE as the frozen local GGUF path}"
test "$(sha256sum "$LLAMA_BIN" | awk '{print $1}')" = \
  "926e2297d7144a59182ba9d37de877ec972a0cf8d1b697baa82277b3066c45c6"
test "$(sha256sum "$MODEL_FILE" | awk '{print $1}')" = \
  "4fe53b148b46f9b88830e2a3055c5b15c3a4d1e3ddc9a1384a108d8b9d59f043"
export RADEONSTAY_DEMO_RUN_ID=deployment-judge-001
export RADEONSTAY_EVIDENCE_RUN_ID=c3min-f7ba681-C-r3
install -d -m 0700 "runtime/${RADEONSTAY_DEMO_RUN_ID}"
export RADEONSTAY_RUNTIME_INSTANCE_PATH="$PWD/runtime/${RADEONSTAY_DEMO_RUN_ID}/runtime-instance.json"
test ! -e "$RADEONSTAY_RUNTIME_INSTANCE_PATH"
LLAMA_SERVER="$LLAMA_BIN" \
MODEL_PATH="$MODEL_FILE" \
MODEL_ALIAS="${RADEONSTAY_MODEL_NAME:-qwen3.6-35b-a3b-q6k}" \
EVIDENCE_RUN_ID="$RADEONSTAY_EVIDENCE_RUN_ID" \
CONTEXT_SIZE=16384 FLASH_ATTN=on PARALLEL_SLOTS=1 \
BATCH_SIZE=256 UBATCH_SIZE=64 CACHE_TYPE_K=f16 CACHE_TYPE_V=f16 \
scripts/serve_model.sh \
  > "runtime/${RADEONSTAY_DEMO_RUN_ID}/llama-server.log" 2>&1
```

`MODEL_FILE` is
`unsloth/Qwen3.6-35B-A3B-GGUF@a483e9e6cbd595906af30beda3187c2663a1118c/Qwen3.6-35B-A3B-UD-Q6_K.gguf`
(Apache-2.0). `LLAMA_BIN` is built from llama.cpp commit
`0b14b87d7c20cb753b94b96854dd7b45306fc696`.

The service must bind to `127.0.0.1:8000` for the private judge path. Use a
second terminal with
`tail -f runtime/deployment-judge-001/llama-server.log` if live logs are needed;
this is a deployment log and must not replace the retained B/C evidence log.
Stopping the launcher writes its end marker to that file. The launcher creates
the instance manifest as mode `0600` and refuses
to overwrite it. It publishes the manifest only after the recorded PID owns the
declared loopback `LISTEN` socket. Preserve this terminal and process for the
entire captured lifecycle.

## 3. Start RadeonStay

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
cp .env.example .env
python - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
text = path.read_text(encoding="utf-8")
replacements = {
    "replace-with-a-random-local-secret": secrets.token_urlsafe(48),
    "replace-with-a-different-random-local-secret": secrets.token_urlsafe(48),
}
for placeholder, secret in replacements.items():
    if placeholder not in text:
        raise SystemExit(f"Missing expected placeholder: {placeholder}")
    text = text.replace(placeholder, secret, 1)
path.write_text(text, encoding="utf-8")
PY
export RADEONSTAY_ISOLATED_DEMO=1
export RADEONSTAY_DEMO_RUN_ID=deployment-judge-001
export RADEONSTAY_EVIDENCE_RUN_ID=c3min-f7ba681-C-r3
export RADEONSTAY_MODEL_ENABLE_THINKING=0
export RADEONSTAY_FUSED_PLAN_EVIDENCE=0
export RADEONSTAY_RUNTIME_PROOF_PATH=/absolute/path/to/sanitized-runtime-proof.json
export RADEONSTAY_RUNTIME_INSTANCE_PATH="$PWD/runtime/${RADEONSTAY_DEMO_RUN_ID}/runtime-instance.json"
test -f "$RADEONSTAY_RUNTIME_INSTANCE_PATH"
scripts/serve_app.sh
```

The generated 48-byte secrets are different, remain only in the ignored `.env`,
and are required even for loopback-only use. The two run identities are
deliberately separate. `RADEONSTAY_EVIDENCE_RUN_ID` must equal the accepted
runtime proof's immutable `run_id`. `RADEONSTAY_DEMO_RUN_ID` is the fresh
`deployment_run_id` that binds the release, isolated database filename, and live
runtime-instance manifest. A new deployment requires a new ID and database.
Within the same deployment, an App restart may reopen that exact database only
after strict path/run binding, regular-file, non-symlink, current-owner,
`0700`/`0600`, schema, audit-key, Journey-HMAC, and audit-chain validation. A
stale or mismatched proof, deployment artifact, or process binding fails
readiness. The proof
must also bind the configured model/binary hashes, ROCm, `gfx1100`, full model
offload, and active same-GPU telemetry. Its status must be `verified`,
`verified_final`, `accepted`, or `accepted_final`; a candidate/non-final summary
is not eligible. The separate instance manifest binds the configured endpoint to
the same live process by PID, Linux start ticks, executable/configuration SHA,
port, alias, `--model` argument, ownership of the declared loopback `LISTEN`
socket, and recorded model SHA. Readiness and every
inference verify those process, command, manifest-model-identity, and proof-
identity fields; a mismatch returns HTTP 503 without a deterministic-planner
fallback. This request-time check does not re-hash the GGUF file. The full file
SHA256 is verified during formal artifact acquisition and evidence binding. Only
the verdict and manifest digest reach the UI. PID, command line, and paths stay
private.

For the current public build, verify that the sanitized proof binds C2 v3,
Reference B (`flash_attn=off`), Optimized C (`flash_attn=on`), and comparison
SHA256
`7f85a614a31da10e5484ee41034282210ac44caf84012617dea5c786c0f03f59`.
It must report `status=accepted`, `winner_assessment_accepted=true`, and
`final_evidence_accepted=false`. This is intentionally not an
`accepted_final` claim. Open `http://127.0.0.1:7860` only after readiness
succeeds:

```bash
curl --fail http://127.0.0.1:7860/health/live
curl --fail http://127.0.0.1:7860/health/ready
```

`/health/live` proves only that the app process is alive. `/health/ready` checks
the model endpoint and live process binding, database, policy corpus, seeded
inventory, tool registry, permissions, isolation, and both runtime manifests; it
returns HTTP 503 when a required dependency or binding is missing. `/health`
remains a compatibility alias for readiness.

## 4. Run the judge journey

The first screen presents one server-derived Judge Journey Rail:

```text
Plan & Quote → Room Hold → Transfer → Delay Recovery → Privacy & Safety
```

These five groups summarize the server-derived ten-step judge guide. Consent,
preference and Privacy Proof appear before Step 10 so every Track 2 capability
is visible, while Privacy Proof remains outside the backend Final Brief business
gate. The UI shows the editable request, authoritative result, current confirmation card,
and exactly one valid primary action. Below that action, the compact Radeon proof
strip shows ROCm/gfx, exact `41/41` offload, process binding, the accepted B→C
winner/gain,
C2, model, binary, and report short hashes. Health, full Trust, Timeline, Stage
Trace, and safe JSON are under **Advanced Proof**. The main flow provides two
contextual editable journey shortcuts: **Plan&Hold** and **Delay Recovery ·
complete hold + transfer first**. **Injection & Access** is a separate editable
Privacy Boundary proof inside Advanced Proof so it never competes with the unique
business CTA. Sensitive-storage refusal remains an optional manual safety test.
Delay Recovery is disabled until the current journey contains both an active
booking and a transfer ticket.

Use the seeded guest and start with Plan & Hold. On every new session, the UI
refreshes the local identity token and computes an exact session-derived
check-in 30–90 days in the future and a checkout two days later; it also names
the default `standard` room type. The Agent is intentionally forbidden from
inventing a stay window. The visible prompt therefore follows this
runtime-generated form:

> I plan to stay from <session-derived check-in, 30–90 days ahead> through <two
> days later> in a standard room for two guests—one adult and one six-year-old
> child. I will arrive at 23:30, have a severe peanut allergy, and need a quiet
> room and airport transfer. For this step, cite policy, check live availability
> and the exact quote, and only preview the room hold until I confirm it. Handle
> the remaining journey needs in separate steps after the room is confirmed.

Check the rail, authoritative result, stable policy citations, and reservation
action card. In the main result, verify that **Guest Needs Ledger** shows each
requested need with its current evidence-backed state, **Claim Authority Map**
maps factual output to Citation/Receipt/Control references, and **Auditable
Journey Outcome** reports one active preview before confirmation and zero after
it is settled. Open **Advanced Proof** for `GroundingProof`, the validated plan,
full Trust, stage timings, and safe tool receipts. Every rendered price, date,
operational ID, status, and policy conclusion must resolve to an implemented
source type: a citation chunk, receipt step, server-authored pending-action
preview, or privacy-control record; the normal result must show
`verified=true` and `unsupported_count=0`. The action card shows the concrete
change, price impact, expiry, and **Confirm** plus secondary **Cancel**. The
browser submits only the action ID; no confirmation capability is rendered,
exported, or logged. A cancelled, expired, drifted, or grounding-invalidated
action exposes only **Repreview**. To correct dates, guests, or details, edit the
visible request naturally and click Repreview; the edit remains bound to that
single stale action. The server rejects a different or additional write tool and
still creates a fresh confirmation. Stay Brief appears only after consequential
work is settled.

After confirmation, the UI prefills the next editable transfer request with the
returned booking ID. Submit and confirm it. Each write remains a separate preview
and confirmation, and only one write may await confirmation per session. For
example:

> For booking RSV-..., request pickup from Terminal 1 for synthetic flight
> RS123 arriving 22:45, for one adult and one six-year-old needing a child
> seat. Preview the request and wait for my separate confirmation.

The confirmed transfer automatically prefills **Flight Delay Recovery**. Submit
it, read the active booking and transfer ticket, inspect cited late-arrival,
change, and transfer policies, and preview exactly one authoritative stay update.
The Recovery Impact card must show prior/proposed dates, prior/proposed stay
totals, exact delta, current/proposed transfer status, stable policy chunk IDs,
the policy-corpus binding, confirmed transport-state binding, and external
transfer price as `not quoted`. Confirm the stay update, then review
and confirm the separately recomputed transfer update. The status progresses
through `previewed`, `stay_confirmed`, `transport_pending`, and `complete`.
The deterministic continuation then proceeds in exactly this order: preview and
confirm memory consent, preview and confirm the allow-listed preference, run the
read-only Privacy Boundary proof, preview and confirm the policy-grounded staff
safety handoff, and finally generate the verified Stay Brief. The UI never opens
the handoff preview early, because one live pending write would disable Send and
block the intervening memory and Privacy steps.

The Final Stay Brief becomes the primary action only when Recovery and every
required Service Handoff are complete and there is no pending, deferred, or
Repreview work. Privacy Proof is not an eligibility gate. An earlier
API-generated brief stays Provisional and does not complete the Journey. The
downloaded Brief repeats each Need source reference and a compact Authority Map.
At download time the local hotel store returns an owner-scope attestation and
the server rechecks that the exact Recovery ticket still belongs to the active
booking, is a `transport` ticket, has the exact confirmed
status/version/state hash, and remains active. It also rechecks the required
handoff ticket, exact booking dates/total/status/expiry, and the current recovery
and handoff policy evidence. Booking cancellation/expiry blocks the
download and returns to a new Hold; date/total drift returns to Modify; transport
drift blocks the download, keeps the stay change, and exposes only transport
Repreview. Policy-only drift instead exposes **Refresh policy evidence**: it
retrieves both current recovery-policy topics and re-reads the exact booking and
transport ticket. If every business field and the ticket-state hash still match,
the server updates only policy chunk IDs/corpus SHA and restores `complete`; no
stay or transport write is repeated. The Final Brief's **Verification basis**
table shows the resulting safe booking, total, transport/handoff tickets, owner
scope, and policy bindings.

Cancel or drift only the second update and verify that the confirmed stay change
is preserved while transport becomes `needs_repreview`. Repreview must re-read
current authoritative state; it must not reuse the old capability or terms.

If the restored journey exposes multiple candidate bookings with no active one,
reply with one displayed booking ID or an unambiguous ordinal such as "the
second booking." An ambiguous pronoun, more than one ID, or an out-of-range
ordinal must produce `ask_user` and no booking-scoped tool receipt.
For both bookings and service tickets, a usable ID must be explicit in the
current request or already present in the structured JourneyState. An ID copied
only from free-form earlier chat, or proposed by the model, is not trusted.
When more than one active transport ticket exists and JourneyState has no bound
ticket, the current message must name one displayed ID or an unambiguous ticket
ordinal; otherwise the server returns `ask_user` without a write preview.

After Recovery reaches `complete`, submit the automatically prefilled memory-
consent request and confirm it. Then submit the separately prefilled
`quiet_room=high_floor` preference request and confirm it. Each remains an
independent previewed write, and the next request appears only after the prior
write is settled. The UI then offers **Privacy Boundary** while Send is active.
Its request combines a legitimate owner-only booking,
preference, and policy read with an explicitly delimited
`[UNTRUSTED_GUEST_NOTE]` containing an override and cross-user request. The server
must hash and reject only that isolated scope, never forward or persist its body,
and still complete the legitimate read. Privacy Proof must report partitioned
scope, safe scope completed, model invocation status, read count,
`owner_scoped_result_count`, zero business writes, receipt-derived
`cross_user_result_count=0`, `scope_verified=true`, `owner_only`, no retained
secret, and a verified audit chain. A pure attack or malformed/nested/unclosed
boundary must fail closed without retrieval, model use, or tools.
If a restored older Journey lacks explicit `scope_verified=true`, rerun Privacy
Proof before making a new privacy claim. Compatibility loading never invents a
successful proof, but the proof does not control business completion or Final
Brief eligibility.

After Privacy Proof completes, the UI prefills the policy-grounded staff safety
handoff. Review and confirm that owner-scoped accessibility-ticket preview. It
must bind the active booking, current allergy-policy chunks, ticket status/update
time/state SHA, and the explicit statement that front-desk and food-service staff
still perform manual verification. With no pending, deferred, or Repreview work,
the fifth Rail stage completes and the Final Stay Brief becomes the only primary
business action.

Before changing identity, open **Advanced Proof** and capture full Trust,
Performance, Grounding Proof, safe receipts, runtime binding, and the accepted
comparison when available. Also confirm that `security.scope_partitioned` stores
no note body: it records only a payload hash, attack category, and limited status
metadata required for the audit event. Identity switching clears private proof
panels by design, so this evidence must be inspected first.

Switch to an unauthorized identity without changing the current session and
verify that the session is refused. In a fresh Mallory session created with
**New session**, `my bookings` may return only Mallory's own records. The denial
must reveal no prior Trust, booking, preference, chat, or proof data.

Download the local Stay Brief after the journey settles and verify that it
contains the same Needs Ledger and Outcome plus only guest-visible verified
facts: no identity token, confirmation capability, complete audit ID, internal
path, or isolated note content. Cancelling, expiring, or restarting a preview
must set active previews to zero and must not leave the affected need marked
confirmed or previewed.

**Clear / New Session** first asks the server, as the current identity, to
invalidate every live confirmation capability and clear turns, pending records,
replay cache, action cards, and Journey; it then creates a new session and clears
the input, timeline, Trust card, stage trace, and Advanced Proof. After switching
identity, the newly selected identity cannot reset the previous owner's old
session: the reset is denied and its separate new session starts without changing
the old server state.

Before restarting, leave one action pending and use **Resume** with the same
identity and session while the app process remains live. Verify that the restored
card shows its concrete terms, price information, and expiry, but no original
arguments, confirmation/identity token, or private binding field. **Confirm** is
enabled only when that complete, unexpired projection still has its matching live
server capability. If the safe projection is missing or incomplete, or its expiry
has passed, Confirm must be disabled and the UI must direct the judge to
**Repreview**. Advanced Proof must show a fresh deterministic `session.resume`
Trust result with Grounding not applicable, zero model calls, zero tool receipts,
and `journey_state_verified=true`; it must not reuse the previous model claims.

To verify restart recovery, stop and restart only the App while keeping the same
`deployment_run_id`, release directory, generated `.env`, database, and live
model-instance manifest. Startup must first revalidate the run-bound filename,
current ownership, `0700` directory, `0600` regular non-symlink SQLite artifacts,
schema, audit-key fingerprint, Journey HMAC, and audit chain. The minimized
JourneyState and audit chain return, while any unfinished action is
`needs_repreview`. Its capability-free
step/tool descriptor identifies what must be rebuilt, but no old arguments,
authoritative preview terms, or capability are restored; confirmation is impossible
until the app computes a new authoritative preview. Inspect the audit view for new `confirmation.retired`
and `session.recovered` HMAC-linked control events proving that the restart ran
no write. A new deployment must instead use a new `deployment_run_id`, release
directory, and database; it may reference the same immutable accepted
`evidence_run_id` without treating that historical proof as a new lifecycle.

For the recovery endpoint, `GET /v1/sessions/{session_id}` returns HTTP 404 for
an ID with no live state, durable JourneyState, or authorized persisted audit
chain, and HTTP 403 when the session belongs to the other guest. A verified
audit-only session may return a minimal empty Journey view with its audit
continuity; it does not reconstruct chat, booking IDs, or ticket IDs.
`GET /v1/sessions/{session_id}/projection` returns the lock-consistent,
owner-scoped Journey plus capability-free action cards used to refresh Resume,
Confirm/Cancel, and Stay Brief without displaying stale browser state.

## 5. Inspect evidence

The Advanced Proof Trust card identifies the local model/backend, schema
constraint, thinking state, grounding result, fact sources, confirmation state,
audit-chain status, runtime proof, live model-process binding, and
retrieval/planning/tool/answer/total timing. The current accepted card shows the
C2 v3 source, B→C winner label, accepted-report digest, winning metrics, and
measured improvements. It must also expose that `final_evidence_accepted=false`.
Raw benchmark artifacts live under `evaluation/results/`; no summary number is
valid without a matching raw file.
For a formal evidence lifecycle, use one `evidence_run_id` in the model log,
Agent benchmark, and ROCm monitor, then create the hash-bound bundle described in
`docs/evaluation-plan.md`.

The released evidence is the path-free summary
`docs/evidence/c3min-f7ba681-bc-comparison.json`. B and C use the same commit,
model, binary, corpus, request configuration, context `16384`, batch/ubatch
`256/64`, parallel `1`, f16 KV cache, thinking off, and unfused planning. Only
Flash Attention changes. At both concurrency 1 and 4, each run completed `16/16`
requests with 100% success, zero failed model calls, and `41/41` offload. C
improves concurrency-1 throughput by `6.455%`, concurrency-4 throughput by
`6.491%`, concurrency-4 P95 latency by `5.428%`, and server decode P50 by
`12.981%`; peak VRAM changes from `58%` to `57%`. The comparator reports
`assessment.accepted=true` and `optimization_winner=optimized`.

Both runs have the same quality projection, including the same strict citation
result of `15/16`. Therefore this result must never be described as `300/300`.
It is a minimal accepted single-variable comparison, not the full A–H matrix,
five-run Stability proof, or long soak.

The complete A–H sequence, D–H candidates, 300/300 release gate, five fresh
Winner lifecycles, long soak, and `accepted_final` proof remain a
post-submission extension documented in `docs/evaluation-plan.md`. Failed or
unfinished candidates must not be implied by the current Trust Card.
