# 4:50 Demo Script — English Narration and Subtitles

> This script supersedes the historical MP4 and SRT archived outside the
> repository boundary. Those historical PDF, PPTX, video, and subtitle artifacts
> are not final submission materials; regenerate them from the frozen C2 source
> and accepted evidence.

This script is for one real RadeonStay UI journey on the target AMD Radeon and
ROCm environment. Record the submission, responses, previews, confirmations,
and denial from the same application and model-service lifecycle. The schedule
allows extra time for the two-call Recovery and memory segments because the
historical, explicitly non-final B/C/D evidence measured 12.1–13.2-second
single-request P95 latency. Idle inference waits may be shortened only in the
edit, with a visible `Inference wait shortened — same live run` notice and the
real request timing left on screen; never replace live output with pre-rendered
results.

The narration below is also the source text for the English subtitle track.
Keep subtitles to two lines and away from the Gradio controls being demonstrated.

| Time | Screen and operator action | English narration / subtitle | Evidence to keep visible |
| --- | --- | --- | --- |
| 0:00–0:10 | Title card: **RadeonStay — Safe journey recovery when reality changes after preview**. | “RadeonStay keeps a disrupted family stay, transfer, and staff handoff local, reversible, and auditable.” | Project name, Track 2, repository revision or final submission identifier. |
| 0:10–0:32 | Target terminal. Show ROCm/HIP, the detected Radeon identity, native llama.cpp HIP startup, 41/41 layer offload, and timestamped utilization/VRAM during inference. Briefly show the sanitized proof and runtime-instance manifest SHA, never its PID or path. | “The core model runs locally through llama.cpp on AMD Radeon with ROCm, and each request is bound to this live process and the accepted configuration.” | Preserve the reported product string exactly. Show distinct evidence and deployment run IDs. Do not infer a retail model name. |
| 0:32–0:45 | Open the Gradio UI. Show the five-group **Judge Journey Rail**, current `Step n/10`, generated session, two contextual journey shortcuts, compact ready state, and the separate privacy proof under Advanced Proof without expanding it yet. | “One server-derived guide covers quote, hold, transfer, delay recovery, and privacy and safety proof without a second workflow state.” | Rail ends with **Privacy & Safety**; local service boundary and healthy readiness remain visible in the compact proof strip. |
| 0:45–1:08 | Select **Plan&Hold** and submit the multilingual request with generated dates, `standard` room, late arrival, child, allergy, transfer, exact quote, and preview-only hold. | “One request combines local policy retrieval, live inventory, deterministic pricing, multi-step planning, and a write that remains a preview.” | Actual live request and result; shortened inference waits retain the visible notice and real request timing. |
| 1:08–1:28 | Show the authoritative result, Needs Ledger, Authority Map and citations; review and confirm the room-hold card. | “Every factual claim has an implemented authority, and confirmation atomically revalidates identity, inventory, price, and state using only the safe action ID.” | `GroundingProof.verified=true`, zero unsupported claims, preview before confirmation, safe action ID, and receipt. |
| 1:28–1:50 | Submit the automatically prefilled transfer request, review its independent preview, and confirm it. | “The returned booking ID is evidence, not authorization. Ownership is rechecked, and transfer creation receives its own approval.” | Matching masked booking ID, separate action/receipt, and Rail advancing to Delay Recovery. |
| 1:50–2:37 | Submit the prefilled delay-recovery request. Show Recovery Impact, confirm the stay change, then submit and confirm the separately recomputed transfer update. | “Delay recovery preserves confirmed work while recomputing only unsettled state after a flight disruption.” | Two real model requests; `previewed → stay_confirmed → transport_pending → complete`, old/new totals, delta, `not quoted` external price, policy and ticket-state bindings. |
| 2:37–3:10 | Follow the automatically selected continuation: submit and confirm memory consent, then submit and separately confirm one allow-listed quiet-room preference. | “Long-term memory is off by default. Consent and preference storage are separate, reversible actions.” | Two real model requests, confirmed consent, separately confirmed preference, and never more than one pending write. |
| 3:10–3:32 | Run the automatically offered **Injection & Access** privacy request. Show the safe result and Privacy Proof; never reopen the isolated body. | “The server rejects the malicious scope, completes the legitimate owner read, and proves zero writes and zero cross-user results.” | Partitioned scope, safe scope completed, `scope_verified=true`, writes `0`, cross-user results `0`, no retained note body. |
| 3:32–3:52 | Follow the returned safety-handoff continuation and confirm its accessibility-ticket preview. | “Automation cannot certify an allergen-free stay, so RadeonStay records a policy-grounded human handoff.” | Fifth Rail stage, active-booking and policy binding, explicit manual verification, separate confirmation. |
| 3:52–4:06 | Generate the unique Final Stay Brief and show its local download. | “The final brief is available only after every required business action is settled and revalidated.” | Final label, completed Rail, current booking/tickets/policy, zero active previews, no secret metadata. |
| 4:06–4:23 | Expand **Advanced Proof once**. Show Trust, real timings, grounding/privacy proofs, process/request binding, C2/winner/report digests, and the accepted Reference-to-Winner card. | “One card connects the live request to local inference, factual authority, audit continuity, and the accepted Radeon optimization report.” | Reference may be A or B; show 300/300, P50/P95, concurrency-4 throughput, VRAM/energy, 41/41, `accepted=true`, and `optimization_winner=optimized`. |
| 4:23–4:42 | Without creating a new session, switch to the unauthorized guest and request the active booking. Show the bounded denial and cleared private panels. | “Changing identity does not transfer the journey. No booking, preference, prior chat, or proof data crosses users.” | Same session ID, bounded denial, empty private panels, and zero cross-user results. |
| 4:42–4:50 | Closing card: local RAG, typed tools, planning, consented memory, permissions, Radeon proof, and repository/QR link. | “RadeonStay remains safe even when reality changes after preview.” | Final repository URL or QR code and available deliverables. |

## Required Recording Rules

1. Pre-warm the model before recording, but start the captured journey with a
   fresh application session and a known synthetic database state.
2. Keep one system clock or timestamp source visible around shortened waits so
   edits cannot be mistaken for substituted output.
3. The GPU proof must combine native ROCm/HIP initialization, positive final
   model-layer offload, and non-zero utilization plus VRAM use during a captured
   inference window. `rocm-smi` device presence alone is insufficient. The
   captured deployment must show a valid runtime-process binding and opaque
   instance-manifest digest while clearly labeling the proof's
   `evidence_run_id` separately from the live `deployment_run_id`; never expose
   its PID, command line, or path.
4. Confirmation capabilities must never enter a captured UI, API export, or log;
   the UI shows only safe action IDs. Mask the middle of every synthetic booking,
   ticket, session, request, action, and audit ID consistently; never expose a
   complete unique identifier. Do not show `.env`, secrets, SSH addresses,
   private hostnames, internal paths, or real personal data.
   After a mixed privacy request is submitted, show only the isolated payload
   digest/category, limited partition-status metadata, and Privacy Proof; do not
   reopen or display the note body.
5. The final performance card may be filled only from the complete
   quality-qualified A-or-B Reference and accepted Winner bundles generated from
   the final clean commit. If those artifacts are unavailable, omit the numerical
   comparison rather than estimate values.
6. Capture at 2560×1440 or higher when possible so JSON fields remain legible in
   a 1080p export. Rehearse browser zoom and scrolling before the final take.
7. All hotel guests, bookings, flights, and preferences shown are synthetic.
