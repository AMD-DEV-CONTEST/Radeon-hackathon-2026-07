# Accident Rights Agent

**DataLink - AMD AI DevMaster Hackathon, Track 2**
Private AI Agent Development and Local Deployment
Submission candidate: `v1.0.0-submission-candidate`

## Executive Narrative

Accident Rights Agent is built around one commercial promise: preserve evidence,
make deadlines visible, and keep a human claims professional in control. The
approved demonstration therefore follows the same path a reviewer would use in
practice: open a synthetic Golden Case, reconstruct source-linked evidence,
switch to an independent conflict case, keep vehicle uncertainty and liability
hypotheses visible, turn missing material into owned tasks, and stop every draft
at a human approval gate.

The system does not sell certainty. It creates a defensible operating record.
For an insurer, that means a faster first review, fewer evidence gaps, auditable
reasoning, and controlled communication without sending sensitive case data to
a public model API.

### Evaluation path shown in the final demo

1. Private AMD Radeon deployment and local endpoint proof.
2. Golden Case intake, materials, Evidence Graph, and traceable timeline.
3. Conflict-case switching, vehicle parameters, and actionable missing evidence.
4. Multiple liability hypotheses and separated responsibility/payment objects.
5. Rights tasks, owners, deadlines, versioned drafts, Verifier, and Human Approval.
6. Measured Case Capsule, Prefix Cache, concurrency, and 30-minute stability results.
7. A controlled insurer pilot based on redacted cases and measurable workflow savings.

## 1. Problem

A traffic accident can generate dashcam video, scene photos, an accident
determination, vehicle specifications, appraisal reports, service receipts,
insurance documents, and later correspondence. These materials arrive at
different times, may contradict one another, and are difficult to review as one
case. Technical vehicle parameters can be confused with legal classification,
while review or re-appraisal deadlines continue to run.

The problem affects more than vehicle owners. Claims professionals and
rights-service teams need a shared, traceable case record rather than an opaque
liability answer. A general-purpose chat model introduces three unacceptable
risks: it may turn an unverified observation into a definitive fact, cite a
non-existent or outdated rule, or merge accident liability, civil compensation,
and insurance payment into one unsupported conclusion.

Accident Rights Agent focuses on a concrete scenario: after a collision between
a motor vehicle and a two-wheel electric vehicle, reconstruct the evidence,
preserve alternative hypotheses, identify procedural deadlines, and prepare
reviewable rights-protection tasks before evidence or procedural options are
lost.

The practical loss is not only legal. Claims teams repeatedly rebuild case
context from messages and attachments, chase the same missing documents, and
hand off conclusions without a reproducible evidence chain. A missed deadline
or unsupported payment estimate can create rework, escalation, and avoidable
customer distrust.

## 2. Solution

Accident Rights Agent is a private multimodal case workspace running on AMD
Radeon GPU + ROCm. It accepts video, images, and PDFs; reconstructs an Evidence
Graph and timeline; evaluates material completeness, vehicle classification,
and liability hypotheses; retrieves versioned legal sources; plans evidence and
deadline tasks; and produces an auditable draft for human review.

The product has two explicitly separated modes:

- `mock` uses deterministic adapters for functional testing without a GPU;
- `local_vllm` calls Qwen3-VL through the co-located loopback endpoint
  `http://127.0.0.1:8000/v1`.

Both modes use the same CaseState, Evidence Graph, rules, RAG, memory,
Verifier, Human Approval, and UI. If the local model is unavailable, the real
mode stops; it never falls back to a public model API.

### Actual evaluation access path

The application UI is not displayed through Radeon Cloud Jupyter or a Cloud
Proxy. The evaluator opens Chrome on a Mac and forwards only the Gradio
loopback port:

`Mac Chrome -> SSH Tunnel (-L 7860:127.0.0.1:7860) -> Radeon Cloud Gradio -> LangGraph -> local vLLM 127.0.0.1:8000 -> AMD Radeon GPU`

Port 8000 is neither forwarded nor exposed. Browser display stays on the Mac;
case processing and model inference stay inside Radeon Cloud.

## 3. Innovation

### Evidence before conclusions

Every material fact carries a Fact ID, Evidence ID, source location,
confidence, and verification state. Conflicts are recorded instead of silently
overwritten. The Agent can therefore say what is known, why it is known, and
what must still be checked.

### Technical compliance is not legal status

The Vehicle Agent compares technical parameters but does not automatically
equate an exceeded parameter with an official legal classification. It keeps
four classes and multiple hypotheses when the evidence is incomplete.

### Dynamic local case memory

Immutable source files, append-only Fact Memory, task-scoped Working Memory,
and a verifiable Case Capsule provide long-horizon context without repeatedly
sending the entire case history to the model.

### Deterministic deadlines and controlled action

Deadlines are calculated by versioned rules and a workday calendar, not by
model arithmetic. Documents remain drafts until a human approves the exact
version and input hash. The system cannot mark an external submission as sent
or accepted.

### Performance and quality are measured together

AMD experiments record tokens, TTFT, TPOT, latency, throughput, GPU load,
VRAM, OOM, ProtectedField retention, Verifier results, and business-quality
scores. Performance gains are not accepted if protected facts or semantic
quality fall below the baseline.

## 4. Agent Architecture

The Gradio workspace sends the active case to a LangGraph Case Orchestrator.
Evidence Reconstruction parses PDFs and images, samples video frames, and
creates source-linked evidence nodes. The Evidence Graph organizes facts,
timeline events, conflicts, gaps, and source locations.

The business workflow then coordinates four specialized roles:

1. **Case Intake Agent** checks material completeness and routes evidence gaps.
2. **Vehicle Agent** evaluates vehicle-classification hypotheses without
   collapsing technical and legal concepts.
3. **Liability Agent** builds violation, causal-force, counterfactual, and
   multi-hypothesis analyses.
4. **Rights Agent** calculates deadlines, plans supplemental evidence, and
   drafts review or appraisal materials.

Local Legal RAG supplies versioned `LegalCitation` objects. The Verifier checks
evidence and legal IDs, unsupported assertions, internal consistency, risk
language, and protected fields. Human Approval controls any preparation for
external use. LangGraph state and retries are persisted through SQLite
checkpoints.

## 5. Multimodal Evidence Reconstruction

Video is not sent to the model as an unbounded stream. OpenCV samples candidate
frames by interval and scene change, rejects severely blurred, dark, bright, or
near-duplicate frames, keeps at most 24 frames, and sends no more than eight
images in one vision request. PDFs retain page and paragraph references;
scanned PDFs are rendered locally before multimodal extraction.

Each source is written atomically into its case directory with SHA256, role,
MIME type, and timestamp. The intake rejects path traversal, symlinks, empty
files, false extensions, and oversized files. Model-extracted facts begin as
`unverified` and must reference an existing Evidence Node before conflict
detection or human review can advance their state.

The clean Golden Case contains 12 sources, 18 facts, three timeline events,
nine valid synthetic PDFs, JPEG images, and H.264 MP4 video. It contains no
real personal data and does not represent real-world accident-recognition
accuracy.

The independent conflict fixture is equally important: it proves that case
switching resets the active view, contradictory evidence remains visible, and
missing vehicle attributes become tasks instead of unsupported classifications.

## 6. RAG and Legal Reasoning

The legal corpus stores official bibliographic identity, issuing authority,
jurisdiction, version, publication and effective dates, article/paragraph/item,
verbatim excerpt, source location, source URL, and content hash. The current
submission contains 15 documents and 59 audited excerpts. Retrieval combines
keyword and local vector results, followed by an optional local reranker.
Embedding and reranking accept only local model directories.

Legal reasoning is fail-closed. A definitive legal statement without a valid
`LegalCitation` is rejected by schema validation or the Verifier. The Liability
Agent also keeps three outputs separate: accident liability, civil compensation
allocation, and insurance payment estimation. If policy terms, limits, losses,
or required documents are incomplete, insurance payment remains
`insufficient_data`.

## 7. Dynamic Memory Compression

The baseline sends the full case history, facts, citations, and workflow state
to the model. The optimized path sends a Case Capsule, task-relevant facts,
required Evidence/Law IDs, protected fields, and the current workflow state.
Raw evidence is never lossily compressed.

ProtectedField covers dates, deadlines, amounts, liability ratios, vehicle
identifiers, party roles, Fact/Evidence/Law IDs, legal versions, and approval
status. The workflow performs a set-consistency check before and after context
selection and blocks the node if any protected value is lost.

On the Radeon comparison workload, input fell from 11,808 to 5,795 tokens, a
50.9% reduction, while ProtectedField retention remained 100%. Combined with
Prefix Cache, TTFT p50 fell from 9.003 seconds to 0.113 seconds. These results
apply to the fixed Golden Case workload and are not presented as universal
ratios for every case.

## 8. Rights Workflow

The Rights Workflow performs service-date identification, deterministic
deadline calculation, task planning, evidence-gap planning, and document draft
generation. Date confidence prioritizes human confirmation, service receipts,
signed or electronic delivery records, and document dates. Conflicting credible
dates remain `disputed`.

Review and re-appraisal deadlines use versioned national rule packages and the
2026 workday calendar. The workflow can prepare tasks for vehicle-property
inspection, re-inspection, supplemental appraisal, or litigation appraisal.
Operational suggestions such as retaining an in-person stamped copy or using
EMS are presented as traceability options, never as invented statutory
requirements.

For claims operations, the output is deliberately structured as **evidence,
owner, due date, next action, and draft status**. This turns analysis into a
reviewable plan while leaving the insurer's existing roles and approval gates
in place.

## 9. Human Approval and Safety

The Policy Gate aggregates evidence citation, legal citation, internal
consistency, risk-language, and protected-field checks. Passing the gate means
only that a draft may enter human review. Approval is bound to the document
version and input hash; a changed fact or draft invalidates the old approval.

The system rejects language such as guaranteed victory, certain legal vehicle
status, or inevitable primary liability. It also blocks advice to hide, delete,
modify, or fabricate evidence. The output is an information-organization and
decision-support artifact, not a final determination by an authority or legal
opinion.

Accident liability, civil allocation, and insurance payment remain three
separate objects. Missing policy terms or loss inputs keep payment at
`insufficient_data`; they never produce a fabricated amount.

## 10. AMD ROCm Optimization

The measured environment uses a Navi31 `gfx1100` Radeon GPU with 48 GB GDDR6,
ROCm 7.2.1, PyTorch ROCm 2.9.1, vLLM 0.16.1.dev0, and
Qwen3-VL-8B-Instruct. Fair comparisons keep the GPU, model, Golden Case,
request order, `temperature=0`, and output limit constant.

The baseline uses full history, Prefix Cache off, and default batch behavior.
The optimized path uses Case Capsule, required fields only, and Prefix Cache.
The parameter matrix covers `gpu_memory_utilization` 0.80/0.85/0.90/0.95,
batch tokens 8192/16384/32768, and 16K/32K context. The final interactive
configuration is 0.95 GPU memory utilization, 8,192 batch tokens, 16K context,
and Prefix Cache enabled.

## 11. Performance Results

| Metric | Baseline | Optimized |
|---|---:|---:|
| Input tokens | 11,808 | 5,795 |
| TTFT p50 / p95 | 9.003 / 9.007 s | 0.113 / 0.113 s |
| TPOT p50 | 0.040 s/token | 0.039 s/token |
| Latency p95 | 23.407 s | 15.228 s |
| Output throughput | 15.417 tok/s | 25.689 tok/s |
| Mean GPU utilization | 99.533% | 100.000% |
| Peak VRAM | 44,246 MB | 43,984 MB |
| Success / OOM | 100% / 0 | 100% / 0 |
| Quality score | 93.571 | 96.364 |
| ProtectedField retention | 100% | 100% |

Concurrency 1, 2, and 4 each executed 20 semantic requests. Throughput was
25.667, 49.323, and 89.478 tok/s; every group completed 20/20 requests with
100% business Verifier pass rate and zero OOM events.

The stability run lasted 1,809.493 seconds and completed 298/298 requests with
zero OOM. The vLLM PID, UI/API, and SQLite `quick_check` remained stable. Mean
GPU utilization was 99.626%, peak VRAM was 46,744 MB, and peak hotspot
temperature was 61 C.

The fixed short-output performance and stability workloads do not contain the
full business ID list, so their Verifier value is not used as a semantic quality
claim. Full semantic concurrency results provide the business-quality gate.

## 12. Deployment

Model inference, Agents, legal index, case files, checkpoints, and logs reside
on the same Radeon Cloud instance. vLLM listens only on
`127.0.0.1:8000`; the UI listens on `127.0.0.1:7860`. A private SSH tunnel is
used for remote demonstration, and no public model port is exposed.

The validated remote evaluation path is:

`Mac Chrome (127.0.0.1:7860) -> SSH Tunnel -> Radeon Cloud Gradio (127.0.0.1:7860) -> LangGraph Agent -> local vLLM (127.0.0.1:8000) -> AMD Radeon GPU`

Only `-L 7860:127.0.0.1:7860` is required. The Radeon Jupyter interface is not
used to render the UI, port 8000 is not forwarded, and no Cloud Proxy is part
of the approved path.

Mock mode requires Python and locked dependencies. Local vLLM mode first runs
the endpoint doctor and stops if the co-located model is unavailable. The
README records installation, launch, Golden Case, testing, and recovery steps.

## 13. Future Commercialization

The first controlled pilots can target insurance-claim assistance and vehicle
owner rights services within one jurisdiction and accident type, using
synthetic or de-identified historical cases. The immediate value is not to
replace liability determination. It is to reduce evidence-sorting effort,
surface missing materials and deadlines, make responsibility and payment
discussions explainable, and give a human reviewer a reproducible case record.

A credible insurer pilot should start with one team and one workflow. Baseline
the current first-review time, evidence-gap rate, rework, missed-window events,
and handoff volume; run redacted cases through the Agent while retaining the
insurer's existing approval roles; then compare operational results before any
wider deployment. Adoption is earned with measured savings and auditability,
not with an accuracy claim that the evidence does not support.

Production deployment requires tenant isolation, identity and RBAC, encryption
and KMS, queueing and rate limits, metrics and alerts, model/rule version
governance, backup and recovery, malicious-file sandboxing, and jurisdictional
rule packages. Human authority over every external action remains a permanent
design requirement.

## Evidence and Limitations

All performance values are taken from Radeon Cloud JSON/CSV under
`benchmarks/results/`. Functional results come from `tests/` and the 2026-08-03
release-candidate rerun. Demo materials are synthetic. The project does not
provide legal advice or guarantee review, litigation, appraisal, or insurance
outcomes.

See `amd_optimization.md` for the complete parameter evidence,
`privacy_security.md` for the local-data boundary, and `model_license.md` for
model and license provenance.
