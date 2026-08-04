# 4:35 Demo Script — English Narration and Subtitles

This script is for one real RadeonStay UI journey on the target AMD Radeon and
ROCm environment. Record the submission, responses, previews, confirmations,
and denial from the same application and model-service lifecycle. Idle inference
waits may be shortened with a visible `Inference wait shortened — same live run`
notice; never replace live output with pre-rendered results.

The narration below is also the source text for the English subtitle track.
Keep subtitles to two lines and away from the Gradio controls being demonstrated.

| Time | Screen and operator action | English narration / subtitle | Evidence to keep visible |
| --- | --- | --- | --- |
| 0:00–0:12 | Title card: **RadeonStay — Private, auditable hotel journeys on AMD Radeon + ROCm**. | “RadeonStay keeps the model, hotel policies, tools, and guest state inside one private local environment.” | Project name, Track 2, repository revision or final submission identifier. |
| 0:12–0:40 | Target terminal. Show ROCm/HIP version and detected Radeon identity, then the real llama.cpp startup lines for the ROCm/HIP backend and positive GPU layer offload. Briefly show timestamped GPU utilization and VRAM samples captured during an actual inference window. | “The core model runs locally through llama.cpp on AMD Radeon with ROCm. Native backend initialization, positive layer offload, and active GPU telemetry prove that this inference is not a CPU-only or remote API demo.” | Preserve the detected product string exactly. Show the same run ID and GPU identity used by the server log and monitor; do not infer a retail GPU model name. |
| 0:40–0:52 | Open the Gradio UI, keep the generated **Session** visible, and click **Refresh health**. | “The UI talks to the local RadeonStay service and its private model endpoint.” | `Local service boundary`, local-model backend, and healthy service state. |
| 0:52–1:20 | Select the authorized guest. Submit the prefilled multilingual request for future dates, 23:30 arrival, a child with a severe peanut allergy, airport transfer guidance, availability, an exact quote, and a preview-only room hold. If the wait is shortened, keep the submit frame and the first returned frame from the same request. | “One guest request combines local policy retrieval, live inventory, deterministic pricing, multi-step planning, and a consequential action that must remain a preview until confirmation.” | The actual request and resulting answer in **Guest journey**. No fabricated or manually pasted response. |
| 1:20–1:42 | Open **Citations**, then **Plan**. Pause long enough to read the late-arrival, allergy, and airport-transfer sections and the bounded policy → availability → quote → hold workflow. | “Policy claims come from local cited sections. The model proposes a schema-validated workflow, while the server checks its tools, arguments, order, and dependencies before execution.” | Citation document, section, excerpt, and source path; the complete typed plan. |
| 1:42–2:00 | Open **Tool receipts**, then **Performance**. Point out the inventory and quote receipts, local model backend, stage timings, and model-call trace. | “Availability and price come only from deterministic local tools, never from model memory. The Performance panel exposes the local backend and measured stages for this exact request.” | Authoritative quote currency and amount, successful read receipts, `model_backend`, `timings_ms`, and trace configuration. |
| 2:00–2:20 | Open **Pending writes**, scroll to the confirmation area, review the room-hold preview, and click **Confirm exactly this pending action**. Show the successful confirmation receipt and returned booking ID. | “The room hold has not executed yet. Its single-use token binds the actor, session, tool, original arguments, and authoritative preview. Only this explicit confirmation creates the hold.” | Preview terms before confirmation, masked token field, successful receipt, booking ID, and audit entry. |
| 2:20–2:48 | In the same session, replace the next request with: **For the booking I just made, create an airport pickup request from Terminal 1 for synthetic flight RS123 at 22:45, for one adult and one six-year-old who needs a child seat. Preview it before execution.** Submit, review the transport-ticket preview, and confirm it. | “The follow-up says ‘for the booking I just made.’ Session-bound conversation memory resolves that reference without exposing another guest’s data. The transfer request still receives its own preview and approval.” | The pronoun-based request, resolved owned booking ID in the typed tool call, separate pending action, and separate confirmation receipt. |
| 2:48–3:13 | Submit: **Enable local preference memory. Preview it and wait for my confirmation.** Review the consent preview and confirm it. | “Long-term preference memory is disabled by default. Authorization is a dedicated write, and the guest must opt in before any preference can be stored.” | `memory.set_consent`, `enabled=true`, pending preview, confirmation, and consent receipt. |
| 3:13–3:36 | Submit: **Save quiet_room=high_floor as my local preference. Preview it and wait for my confirmation.** Review and confirm the independent save action. | “Saving a preference is a second, independent write. The allow-listed key and value are shown before the guest confirms them.” | `memory.remember_preference`, exact key/value, distinct token, distinct confirmation, and saved receipt. |
| 3:36–3:50 | Submit: **List the preferences I have allowed you to store. Do not write anything.** Show the read-only result. | “A later read proves that the preference was stored only after consent and remains scoped to this guest.” | `memory.get_preferences`, read receipt, returned `quiet_room=high_floor`, and no pending write. |
| 3:50–4:07 | Without clicking **New session**, change the signed identity to the unauthorized guest. Keep the unchanged **Session** visible and submit a request to access the booking just created. Show the bounded denial. | “Changing identity does not transfer ownership of the bound session. The server refuses the cross-user request without returning the booking, preference, or prior chat data.” | Same session ID before and after the identity change, bounded error text, empty private panels, and denial audit evidence when visible. |
| 4:07–4:27 | Show the final, immutable evidence artifacts or a chart generated from them. Compare **B configuration** with **Best accepted configuration** using placeholders until the complete target bundles exist. | “The final comparison changes only controlled inference settings. Quality must not regress, no core metric may materially regress, and at least one core metric must improve before the optimized result is accepted.” | Use only complete hash-bound bundles. Display `[B_QUALITY]`, `[BEST_QUALITY]`, `[B_CORE_METRICS]`, `[BEST_CORE_METRICS]`, and `[ACCEPTANCE_STATUS]` until verified values are available; never record placeholders in the final cut. |
| 4:27–4:35 | Closing card: local RAG, typed tools, multi-step planning, consented memory, permission control, raw evidence, and repository/QR link. | “RadeonStay makes private hotel automation local, inspectable, and reversible.” | Final repository URL or QR code and the available deliverables. |

## Required Recording Rules

1. Pre-warm the model before recording, but start the captured journey with a
   fresh application session and a known synthetic database state.
2. Keep one system clock or timestamp source visible around shortened waits so
   edits cannot be mistaken for substituted output.
3. The GPU proof must combine native ROCm/HIP initialization, positive final
   model-layer offload, and non-zero utilization plus VRAM use during a captured
   inference window. `rocm-smi` device presence alone is insufficient.
4. Keep confirmation tokens masked. Do not show `.env`, secrets, SSH addresses,
   private hostnames, or real personal data.
5. The final performance card may be filled only from complete B and best-run
   evidence bundles generated from the final clean commit. If those artifacts
   are unavailable, omit the numerical comparison rather than estimate values.
6. Capture at 2560×1440 or higher when possible so JSON fields remain legible in
   a 1080p export. Rehearse browser zoom and scrolling before the final take.
7. All hotel guests, bookings, flights, and preferences shown are synthetic.
