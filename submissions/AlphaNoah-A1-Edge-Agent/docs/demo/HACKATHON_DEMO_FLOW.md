# AMD AI DevMaster Hackathon Demo Flow

> **AlphaNoah A1 Edge Agent** — *An AMD ROCm-powered industrial asset maintenance edge agent.*

Document status: **Target architecture / planned runbook.** The scenario,
device, SOP, history, people and repair outcomes are simulated. It is not the
current runnable path.

Phase note (2026-07-23): this packaging-machine runbook is preserved as a planned
industrial validation direction and is not implemented. The implemented
[Food SOP Closed-loop](FOOD_SOP_CLOSED_LOOP.md) is the first validation skill,
not AlphaNoah's product scope.

## 1. Demo Objective

Demonstrate that A1 is more than a local chatbot:

- a QR code grounds the interaction in one physical asset identity;
- a local AMD ROCm model interprets a fault description;
- typed Skills retrieve local, simulated history and guidance;
- deterministic code owns the work-order state and tool effects;
- a human approves a high-impact step and supplies the repair outcome;
- verification closes the loop or triggers controlled recovery;
- only verified experience is promoted to local memory;
- the judged path works without a cloud AI API.

## 2. Simulated Asset and Input

| Field | Demo value |
|---|---|
| Asset ID | `PACK-003` |
| Asset type | Packaging Machine |
| Site | `DEMO-SITE` (fictional) |
| Data class | Fully simulated hackathon fixture |
| QR payload | Opaque simulated reference resolving to `PACK-003` |

Employee input:

> 3号包装机运行约10分钟后自动停机，重新启动后暂时恢复，但今天已经发生两次。

No real factory, customer, device telemetry, SOP, prompt or maintenance record is used.

## 3. Controlled Fixture Set

The future demo fixture should be deliberately small and public-safe:

- one simulated asset profile for `PACK-003`;
- two or three simulated recent event summaries;
- one simulated SOP excerpt labeled “demo only, not operational guidance”;
- one open-work-order template;
- one simulated supervisor identity and one simulated technician identity;
- one successful verification observation set;
- one recurrence/failed verification observation set.

Fixture provenance and license must be recorded before public release. Values must not be copied from AlphaNoah commercial repositories or real customers.

## 4. Main Twenty-step Flow

| Step | Demonstration action | Typed operation/state | Evidence shown |
|---:|---|---|---|
| 1 | Scan the QR code or open the simulated QR link | `identify_asset` begins | QR input and resolver status |
| 2 | Resolve and load `PACK-003` | `identify_asset → success` | `asset_id`, asset type, context version |
| 3 | Show the selected asset context | task state `submitted` | simulated recent events/open orders |
| 4 | Employee submits the fault description | bounded local input | original input reference and timestamp |
| 5 | Local model extracts a structured Incident | `parse_incident` | provider=`local`, schema-valid fields, latency |
| 6 | A1 finds missing information and asks once | `request_clarification`; `waiting_information` | missing field and bounded question |
| 7 | Retrieve local asset history | `retrieve_asset_history` | asset-scoped record IDs and provenance |
| 8 | Retrieve the simulated local SOP | `retrieve_sop` | document ID/version and demo-only label |
| 9 | Calculate Event Importance Score | deterministic score | six factors and policy version |
| 10 | Produce classification, risk interpretation and recommendation | `assess_incident` | model proposal separated from policy result |
| 11 | Create a local work order | `create_work_order` | work-order ID and idempotency result |
| 12 | Enter the approval gate | state=`waiting_confirmation` | exact proposed action and risk summary |
| 13 | Simulated supervisor approves | `request_approval → success` | actor, decision, time and action hash |
| 14 | Simulated technician submits repair result | `record_repair_result` | human-authored action and observation refs |
| 15 | A1 evaluates recovery criteria | `verify_recovery` | criteria, observation window and evidence |
| 16 | If successful, close the work order | `close_work_order`; state=`resolved` | verification ID and guarded transition |
| 17 | If failed, reopen and escalate/retry | `reopen_work_order` / `escalate_work_order` | failure evidence, attempt and branch reason |
| 18 | Draft an experience summary | `summarize_experience` | verified sources and limitations |
| 19 | Update local event memory when eligible | `update_memory` | target layer, raw pointer and provenance |
| 20 | Show execution proof | observability panel | AMD GPU, ROCm, model, latency, state trace, `Cloud API Calls: 0` |

Step 20 must display measured evidence. If a metric is unavailable, the UI says unavailable; it does not substitute a guessed value.

## 5. Structured Incident Example

The following is an illustrative target shape, not a real model result or private prompt:

```json
{
  "asset_id": "PACK-003",
  "symptoms": ["automatic_stop_after_runtime"],
  "reported_runtime_minutes": 10,
  "restart_temporarily_restores_operation": true,
  "reported_occurrences_today": 2,
  "missing_fields": ["operator_panel_error_code"],
  "source": "employee_report"
}
```

The model proposes this structure. Pydantic/schema validation checks types and allowed fields; deterministic code persists it and decides whether clarification is required.

## 6. Single Clarification

Planned demo question:

> 停机时操作面板是否显示错误代码或报警编号？

The answer is a simulated fixture. The demo permits one clarification round so the workflow remains bounded. If no answer arrives, the state remains `waiting_information` or moves to a controlled human-triage path; the model does not invent the missing code.

## 7. Typed Skill and Tool Evidence

The UI or trace view should show a concise status for every invoked Skill:

```json
{
  "skill_name": "retrieve_asset_history",
  "status": "success",
  "progress": 1.0,
  "confidence": 1.0,
  "recoverable": true,
  "latency_ms": 0,
  "evidence": {
    "asset_id": "PACK-003",
    "record_refs": ["simulated-record-id"]
  },
  "failure_mode": null,
  "error_code": null
}
```

`latency_ms: 0` is a schema placeholder, not a measured result. Runtime evidence must replace it before the object is presented as an execution record.

## 8. Success Branch

### 8.1 Simulated outcome

The technician submits a simulated action and reports that the machine remained stable for the demo's declared observation period. The observation period and criteria are explicitly marked as simulation, not an industrial safety standard.

### 8.2 State path

```text
in_progress
→ pending_verification
→ verification_succeeded
→ resolved
→ experience_candidate
→ local L3 memory (after policy/human checks)
```

### 8.3 Required evidence

- human repair-result record;
- verification criteria and simulated observations;
- successful `VerificationResult`;
- close transition guard result;
- source links in the experience summary;
- no raw claim that the model performed the repair.

## 9. Failure Branch

### 9.1 Simulated outcome

The same stop recurs during the simulated observation period. A1 records the failed verification and does not promote the proposed repair as successful experience.

### 9.2 State path

```text
in_progress
→ pending_verification
→ verification_failed
→ reopened
→ reassessed
→ escalated
```

For an optional bounded retry demo, `reassessed` may return to `in_progress` only if the retry budget and simulated policy permit it. The model cannot increase the budget or bypass approval.

### 9.3 Required evidence

- recurrence observation linked to `PACK-003`;
- failed `VerificationResult`;
- previous attempted action retained as ineffective/unresolved evidence;
- deterministic reopen reason and attempt count;
- escalation reason when retry is unsafe or exhausted;
- no “successful experience” memory update.

## 10. Human Confirmation Moment

The demo pauses visibly at `waiting_confirmation` and displays:

- selected asset;
- structured incident and uncertainty;
- local history/SOP references;
- proposed work-order action;
- deterministic risk flags;
- approve/reject controls for the simulated supervisor.

Approval is persisted with the exact action hash. If the proposed action changes, the approval becomes invalid and a new request is required.

## 11. Local Memory Moment

The trace shows:

1. active task state in L1;
2. asset-scoped recent events retrieved from L2;
3. an optional verified experience retrieved from L3;
4. the raw simulated record referenced but not loaded until relevant;
5. success promoted only after verification, while failure remains negative evidence.

This is system-level record memory, not model-internal long-term memory.

## 12. AMD ROCm Evidence Panel

The final panel should contain:

- GPU: AMD Radeon 8060S;
- architecture: `gfx1151`;
- ROCm version from the running machine;
- Ollama/backend and model identity;
- cold load and measured warm latency;
- current or sampled GPU utilization with collection source;
- schema-valid result count;
- work-order state trace;
- `Cloud API Calls: 0` for the verified offline run.

The supplied environment audit reports `gfx1151` detection, approximately 1% to 91% GPU-utilization change under inference and approximately 1.7–2.7 seconds warm response on one prototype workload. Public presentation requires the original runtime evidence and full benchmark metadata; these are not universal promises.

## 13. Suggested Five-minute Presentation

| Time | Presenter focus |
|---|---|
| 0:00–0:30 | Problem and local-first AMD ROCm positioning |
| 0:30–1:00 | Scan QR and show `PACK-003` context isolation |
| 1:00–2:00 | Local Incident extraction, one clarification and local retrieval |
| 2:00–3:00 | Typed Skill trace, work-order creation and human approval |
| 3:00–4:00 | Submit simulated repair and show success branch |
| 4:00–4:30 | Switch to recorded failure branch: reopen and escalate |
| 4:30–5:00 | Memory update rules and AMD/ROCm/offline evidence panel |

## 14. Demo Failure Containment

| Demo failure | Controlled fallback |
|---|---|
| QR camera unavailable | Open the same simulated QR link; display that it is a fallback |
| Local model unavailable | Stop and show Provider health failure; do not substitute cloud output |
| Invalid structured output | Show one bounded retry, then explicit failure |
| Supervisor decision not supplied | Remain `waiting_confirmation`; do not auto-approve |
| Verification input absent | Remain `pending_verification`; do not close |
| GPU metric unavailable | Show metric unavailable while retaining other device evidence |

Pre-recorded screenshots may explain a failure branch, but they must be labeled recorded and cannot be presented as live output.

## 15. Acceptance Checklist

- [ ] Every asset-scoped record displays `PACK-003` or a safe simulated reference.
- [ ] Model inference is local and its backend/device metadata is visible.
- [ ] At least one typed Skill call shows schema, status and evidence.
- [ ] State changes are attributed to deterministic code, not the LLM.
- [ ] Human approval interrupts and resumes the workflow.
- [ ] Success closes only after verification.
- [ ] Failure reopens and escalates or follows a bounded retry.
- [ ] Only verified outcomes are candidates for long-term experience.
- [ ] Local history and simulated SOP provenance are visible.
- [ ] Offline proof supports `Cloud API Calls: 0`.
- [ ] No real customer, site, device, SOP, prompt, secret or model weight is present.

## 16. Current Implementation Boundary

This document is a runbook for future implementation and review. The current
repository implements a same-host QR form, Industrial Event persistence,
explicit local Ollama text analysis, DecisionHook, Runtime-level HumanReview
and the Food validation task/evidence/review loop.

It does **not** implement this runbook's asset resolver, local history/SOP
retrieval, automatic work-order creation, approval Web UI, physical-phone
access, conversation/vector memory, metrics panel or experience promotion.
See the authoritative
Current Implementation Status.
The possible evolution toward sensor and robot systems is documented separately
in Future Is Robots?.
