# Local-first training and free-cloud upgrade contract

Date: 2026-08-02

## Decision

ProofLaunch trains and validates the product-critical bounded router locally first. Existing local weights are inventoried before any acquisition; an absent runtime dependency is not permission to download a duplicate model. Cloud APIs and free GPU notebooks are optional teachers, critics, evaluators, or upgrade environments. They cannot become a hidden dependency of the competition core or substitute for the required Radeon-local key inference.

## Observed local execution

- Host: Apple arm64 with local Ollama/Metal runtime.
- Reused base model: `bge-m3:latest`, digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`, 566.70M parameters, F16, 1,024-dimensional embeddings.
- Download performed: false. Cloud calls: 0.
- Corpus: 15,000 rights-verified, training-allowed GTM episodes; completions and direct `Stage:` labels are excluded from the model input.
- Frozen V3 split: 12,004 train / 1,498 validation / 1,498 final test using per-stage SHA-256 ordering and a fresh seed.
- Model: 14-node Graph route head combining local BGE semantic prototypes with train-only output-contract likelihoods.
- Safety acceptance: an output contract must be recognized, unambiguous, and independently corroborated by the dense semantic head. No automatic external action is enabled.
- Frozen final result: Accuracy 1.0000, Macro-F1 1.0000, accepted coverage 0.64552737, accepted accuracy 1.0000. The model remains `promoted=false`; passing an offline gate does not authorize automatic product release.
- Live local probe: a B2B launch request with `smp, rtb, offer` routed to `strategy` at confidence 0.95054003 with every acceptance gate true.
- Existing local generator: `qwen2.5-coder:1.5b`, digest `d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668`, Q4_K_M. A 14-node frozen JSON baseline produced 14/14 valid JSON objects, 10/14 complete contracts on the first pass, and 14/14 after four bounded repair calls plus two deterministic complete-wrapper normalizations. This is an inference/Harness result; `training_observed=false` remains explicit.
- Current no-download cache discovery covers 10/10 execution roles: semantic memory, structured text, image generation/editing, text-to-video, image-to-video, video restoration, speech/voice design, audio generation, and OCR. It found 2 Ollama models and 22 Hugging Face model caches; discovery does not claim that every cached weight has passed license, runtime, or quality admission.

### Eight-scenario local creative benchmark

The first full-JSON version made the 1.5B local model reproduce a mostly locked
candidate object with a 768-token decoding allowance. A real run passed its
preflight but completed zero candidates within the bounded first-case window.
The corrected path assigns the model a small but explicit role: select four
creative-nucleus dimensions under a closed enum schema. A deterministic
compiler then binds those selections to the exact approved proof, CTA,
audience context, two channel drafts, specialist gate and human-release
boundary. The unchanged downstream validator still checks semantic depth,
context anchors, exact-proof occurrence, claim safety, channel distinction and
cross-territory Jaccard limits. Invalid nuclei fail closed before candidate use.

The V5 observed run completed 8/8 representative cases, 24/24 localhost model
calls and 24/24 mechanically validated candidates. Coverage includes B2B and
B2C, pre-PMF/launch/growth/mature stages, zero/small/scaled budgets, and both
standard and high-regulation paths. Maximum per-call decode allowance fell
from 768 to 96 tokens without reducing the candidate or portfolio quality
contracts. The run downloaded nothing, made zero cloud calls and enabled no
external action. Its receipt is
`artifacts/local-gtm-creative-benchmark-v11/benchmark-receipt.json`.

This is real local inference and Harness compilation, not fine-tuning. The
outputs are unreviewed candidates: 100% mechanical contract completion does
not establish human preference, 4A quality, campaign effect, revenue, Radeon
execution or Top-1 standing.

### Cross-scenario human-effect gate

The nine completed cases are compiled into 54 randomized, role-hidden
candidate-versus-baseline pairs and 270 empty assignments: six pairs per case,
five named independent reviewers per pair. Public packets expose neither
candidate role, provider nor model. Private mappings are independently hash
bound, stored with mode `0600`, and never referenced from the public packet.
Randomization secrets are discarded rather than persisted.

Portfolio promotion requires all 270 immutable reviews and all nine valid
case aggregates. At least six cases must yield an eligible recommendation,
including at least three of four B2B cases, three of four B2C cases, both
high-regulation cases and three of four zero-budget cases. Each recommended
territory retains the existing per-case requirements: at least eight eligible
comparisons, preference rate at least 60%, Wilson 95% lower bound above 50%,
and zero critical failures. One favorable case cannot promote the portfolio.

The current status is `0/270`: the infrastructure is executable, but no human
preference exists. See
`artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2/portfolio-blind-review-public.json`
and `evidence/v10/local-gtm-portfolio-blind-review-status.json`.

The production server now exposes this frozen queue through
`GET /v1/portfolio-blind-review/status`, invitation-bound
`GET /v1/portfolio-blind-review/tasks?slot=N`, and immutable
`POST /v1/portfolio-blind-review/reviews`. The browser Training control defaults
to this 9-case scope and can switch to the focused 30-review campaign scope.
Submissions are content-hash verified, idempotent, persisted per case, and
recovered after restart. No partial case recommendation is returned before all
270 reviews exist, and the portfolio route has no automatic selection or
publication endpoint.

The 100% classification result applies only to this structured 14-node route benchmark. It does not prove open-ended generation quality, 4A creative quality, multimodal training, business lift, or Radeon execution.

### Local Gemma 3 12B strategy probe

The already cached `mlx-community/gemma-3-12b-it-4bit` revision
`86cc6a8dedbc456dd0e4af01a9d09f396f77e558` was executed offline on Apple
Metal with no model download and no cloud call. The first bounded strategy
draft was valid JSON but failed the GTM Harness: it optimized workspace
engagement rather than qualified design-partner conversations, supplied no
comparable baseline or observation window, used a generic organic-sharing
loop, and omitted a named approve-or-reject release gate. A single
failure-feedback repair then ended before closing its JSON object and was also
rejected.

This observation narrows the local model's role to candidate generation. It
does not justify local LLM fine-tuning, automatic release, or a 4A-quality
claim. Only the failed frozen cases should be escalated to a flagship cloud
teacher or critic; the returned candidate must still pass the same local
Harness. The receipt is
`evidence/v10/local-gemma3-12b-gtm-strategy-probe.json`.

### Gemma 3 12B zero-budget strategy challenger v2

The same immutable cached revision was subsequently re-run through a stricter,
versioned Harness with a 640-token draft limit and at most one 768-token repair.
The evaluation exposed and corrected three false-positive classes: unsupported
performance language outside the rejected-claims list, historical or
cross-community baselines presented as comparable controls, and
vanity-engagement loops without a qualified-conversation ledger. The final
hash-bound candidate passes only after binding the same eligible account pool
to a 50/50 randomized same-window treatment/holdout, a 14-day window, a minimum
25-qualified-conversation decision threshold, a reusable roadmap diagnostic,
two earned-distribution mechanisms, and a named Product Marketing Manager
approve-or-reject artifact.

This is real offline Apple Metal inference from the already cached 12B model;
network downloads and cloud calls are zero. It remains candidate generation,
not model training, Radeon execution, independent human preference, causal
effect, revenue, 4A quality, or Top-1 evidence. The implementation and receipt
are `src/prooflaunch_remix/gtm_strategy_challenger.py`,
`scripts/run_local_gemma3_strategy_challenger.py`, and
`evidence/v10/local-gemma3-12b-strategy-challenger-v2.json`.

### Gemma 3 12B cross-scenario strategy portfolio v1

The single-case challenger is now complemented by eight real offline Apple
Metal generations covering B2B and B2C, pre-PMF through mature lifecycles,
standard and high-regulation work, eight industries and five markets. A
deterministic context router assigns exactly two cases each to LinkedIn,
community, partner and owned zero-paid-media lanes; the model must reproduce
the complete scenario binding and justify the selected lane. Each case still
has only one draft and one bounded repair, requires a same-pool randomized
same-window holdout, a qualified-conversation ledger and named human review,
and rejects unobserved outcome language.

All eight cases passed the per-case contract. The independent portfolio audit
also passed with eight unique strategies, a balanced 2/2/2/2 channel
distribution and maximum cross-case token-set Jaccard of `0.23494` against a
`0.60` ceiling. This is a deterministic anti-collapse test, not a human
creative judgment. Network downloads and cloud calls were zero and the model
was loaded once. No training, Radeon execution, production effect, 4A quality,
Top-1 standing or universal-industry claim is enabled.

The frozen cases, runtime receipt and quality audit are:

- `config/local-gemma3-zero-budget-strategy-portfolio-v1.json`
- `evidence/v10/local-gemma3-12b-strategy-portfolio-v1.json`
- `evidence/v10/local-gemma3-12b-strategy-portfolio-quality-v1.json`

## Observed local multimodal qualification

On 2026-08-02 the no-download path executed two cached models offline on Apple
Metal. Qwen3-TTS VoiceDesign produced a 14.72-second original synthetic voice
candidate; the delivery copy was normalized to 48 kHz, stereo, 24-bit PCM. It
has not passed transcript verification or named-human listening review. LTX-2.3
produced two 384×256, 1.04-second audio-video candidates. The distilled result
was rejected because the requested subject was not recognizable. A single
bounded one-stage repair made the evidence-card subject recognizable, but the
result still failed duration, resolution, blind-review and license gates. No
candidate entered product production. The content-addressed receipt is
`evidence/v10/local-multimodal-qualification.json`.

## Cloud inference lanes

All cloud lanes accept only public or synthetic qualification inputs until their data-processing and provider-output training rights are reviewed. Credentials come only from environment variables and are never written to receipts.

| Lane | Verified free boundary | Intended use | Current state |
|---|---|---|---|
| AMD Radeon Token Factory | sponsored daily account quota, not a generic free API | official competition advisory and later flagship comparison | no usable environment credential in the current local process |
| Groq Free Plan | model-specific RPM/RPD/TPM/TPD limits | fast same-input Agent/JSON qualification | adapter ready; key absent |
| OpenRouter `:free` | 50 requests/day without purchased credits; availability is dynamic | broad successive-halving evaluator panel | adapter ready; key absent |
| NVIDIA NIM | Developer Program endpoints are free for prototyping/research/testing | DeepSeek/Nemotron/Kimi flagship critic | adapter ready; key absent; not production licensed |
| Google AI Studio | Gemini API free tier; OpenAI-compatible endpoint available | multimodal/structured-output challenger | adapter ready; key absent |
| Cloudflare Workers AI | 10,000 shared neurons/day, reset 00:00 UTC; chat plus model-specific image/audio endpoints | GPT-OSS structured Agent challenger and Gemma 4 text/image/video understanding; separate image/audio production probes | chat adapter ready; token and account ID absent; non-chat adapters remain gated separately |
| Cerebras Inference | $5 trial credit after adding a verified payment method; expires after 30 days | optional structured-output and long-context trial challenger | classified as developer credit, excluded from the automatic zero-cost sprint |
| GitHub Models | fully retired for every customer on 2026-07-30 | none | fail-closed; playground, catalog, inference API and BYOK are excluded |
| SambaNova Free Tier | rate-limited free models | Agent and long-context challenger | adapter ready; key absent |
| Mistral Studio Free mode | rate-limited no-card mode | independent text critic | adapter ready; key absent |
| Lightning Model APIs | 30M free tokens/month; Free plan is 15 RPM/120K TPM; OpenAI-compatible | Nemotron 3 Ultra long-context critic | adapter ready; key absent; additionally requires `LIGHTNING_FREE_ONLY_ACK=1` to prevent accidental paid spill |
| Cohere | evaluation keys are free; Command A+ is limited to 20 RPM and trial keys to 1,000 calls/month | independent structured GTM challenger/rubric judge | adapter ready; evaluation key absent; non-production only |
| Hugging Face Inference Providers | $0.10 monthly credit for free accounts | fixed `openai/gpt-oss-120b` smoke test only, not a durable free route | developer-credit adapter ready; token absent; hard-stop before paid continuation |
| Alibaba Cloud Model Studio | China/Beijing new-user quota is normally 1M tokens per model for 90 days; real-time inference only | `qwen3.7-max` long-context critic | developer-credit adapter ready; key absent; execute only after enabling Free Quota Only |

Direct DeepSeek V4 and MiniMax M3/H3 hosted APIs remain pay-as-you-go and are not described as free. Free consumer chat, open weights, sponsored credits, and hosted API rights are separate facts.

## Free GPU lanes

| Resource | Official boundary | Admission decision |
|---|---|---|
| Lightning AI Studio | 15 free credits/month; current pricing guidance advertises about 80 interruptible GPU hours, subject to verification, region, supply and GPU pricing | first training lane because one account exposes model APIs, persistent storage and single-GPU training; checkpoint before every four-hour free-session restart |
| Modal Starter | $30 compute credit/month; per-second serverless GPU billing and up to 10 GPU concurrency | second lane for programmable batch evaluation, teacher generation and bounded parallel jobs; mount content-addressed checkpoints |
| Kaggle Notebooks | P100; normally 30 GPU hours/week or sometimes more depending on demand | capacity fallback for bounded LoRA/SFT with checkpoint export; quota and hardware remain demand dependent |
| Google Colab Free | free GPU/TPU access, but availability and limits are not guaranteed and fluctuate | short reproduction probe only |
| Hugging Face ZeroGPU | free account 5 minutes/day; shared 48GB/96GB Blackwell allocation | inference/demo kernels, not sustained training |
| NVIDIA LaunchPad | free guided labs/development sandbox subject to program access | NIM evaluation/reproduction, not represented as unrestricted rental |
| Amazon SageMaker Studio Lab | existing accounts receive up to 4 GPU hours/24h, in sessions up to 4 hours | existing-account fallback only; AWS closed new customer access on 2026-07-30 |

Every ephemeral runtime must begin by restoring a content-addressed checkpoint and end by exporting the adapter, tokenizer/config, optimizer state when resumability is required, metrics, split manifest, environment lock, and SHA-256 receipt. Destroying or switching an instance before export is a hard failure.

## Execution order

1. Run local route inference and local generative baselines with installed models.
2. Execute the zero-cost API sprint only when one of its environment credentials is present; 31 zero-cost candidates are discoverable, while a fixed 29-candidate cohort is capped at 47 calls. The dynamic `openrouter/free` resolver and held-back Laguna fallback stay outside the frozen cohort. GitHub Models is globally retired and Cerebras is a payment-method-backed trial, so neither enters this cohort.
3. Use the winning cloud model for evaluation/critique. Do not admit its outputs into training until model-specific output-training rights pass review.
4. Use Lightning first for a bounded trainable-adapter experiment when local tooling is insufficient; one authenticated account can cover both a long-context critic and a checkpointed Studio.
5. Use Modal second for programmatic batch workloads and Kaggle as a capacity fallback; keep Colab/ZeroGPU as short probes and never split one optimizer state across unrelated ephemeral providers.
6. Use paid DeepSeek/MiniMax or other flagship cloud training only after the free panel establishes an expected quality gain and a finite budget is approved.

## Actual activation decision on 2026-08-02

The latest read-only inventory found 10/10 local production roles already
covered, including Gemma 3 text, BGE-M3 retrieval, Flux/Qwen image, Wan/LTX
video, Qwen/Ming speech, LongCat audio and PaddleOCR resources. No download was
performed. The current process exposes no free-provider API key, no Lightning
or Modal session and no Kaggle token, so live cloud calls and cloud weight
training remain truthfully blocked.

When user-controlled credentials are added, activate only this bounded bundle:

1. `GROQ_API_KEY` for structured Agent drafts and schema qualification.
2. `GEMINI_API_KEY` for multimodal understanding on the same frozen cases.
3. `OPENROUTER_API_KEY` for fixed-model long-context and safety challengers;
   keep `openrouter/free` exploration outside frozen promotion.
4. Add Cloudflare and SambaNova only as independent resilience providers, not
   as simultaneous quota-burning defaults.
5. Use `LIGHTNING_API_KEY` for the first checkpointed LoRA/SFT workspace;
   Modal is second and Kaggle is third. Never split one optimizer state across
   providers.

API inference produces drafts, critiques and candidate supervision only. It is
not a weight update. Training begins only in an admitted GPU workspace, and
provider output enters a training corpus only after model-specific output-rights
review. The plan never persists secret values or falls through to a paid route.

## 2026-08-02 official-source routing decision

The current free-provider audit keeps the product local-first and makes the
cloud lane additive:

1. **Groq Free Plan** is the first text/Agent qualification route because its
   official account-level limits are explicit and cached prompt tokens do not
   consume the rate limit. Use it for identical frozen JSON cases, never as a
   hidden production dependency.
2. **Cloudflare Workers AI** is the second independent route. The official
   free allocation is 10,000 neurons per day and resets at 00:00 UTC; stop on
   exhaustion rather than enabling paid overflow.
3. **Gemini free tier** is the multimodal challenger only after the account's
   live project quota is inspected, because limits are model- and
   project-specific and preview limits are more restrictive.
4. **GitHub Models is retired**: GitHub's current notice states that the
   playground, catalog, inference API and BYOK ended for every customer on
   2026-07-30. Historical routes remain negative evidence and are never retried.
5. **Cerebras is trial credit, not standing free**: the official FAQ requires a
   verified payment method for $5 of credits expiring after 30 days. It remains
   an explicitly activated developer-credit route, outside automatic free use.
6. **OpenRouter free** remains exploration-only: the official default is 50
   requests/day and the `openrouter/free` resolver may select different models,
   so its responses cannot enter a frozen model-to-model comparison.
7. **Lightning** is the first free training workspace because one account can
   provide a rate-limited model API, persistent storage and checkpointed GPU
   training (15 monthly credits and advertised free-hour equivalents).
   **Modal Starter** is the second, programmable batch lane ($30 monthly compute
   credit), and **Kaggle** is the demand-dependent capacity fallback.
   **Colab Free** is only a reproduction probe because hardware and limits are
   explicitly unguaranteed and variable.

Credential presence is re-probed at execution time and only boolean presence is
written to evidence. If no user-controlled key or authenticated GPU session is
present, the planner performs zero cloud calls and does not silently create
accounts, accept terms, upload data, or consume GPU quotas. The adapters and
successive-halving budget are executable through
`scripts/run_v10_frontier_free_api_sprint.py`; until a credential is present,
the existing local models cover the product roles without a download.

The executable V2 planner now turns those routes into a composite pipeline
instead of treating providers as an undifferentiated model list:

- structured Agent drafts: Groq/Cloudflare/Cohere/SambaNova, with at most two
  independent providers;
- long-context red team: Lightning/NVIDIA/OpenRouter/SambaNova;
- multimodal understanding: Gemini/OpenRouter/Cloudflare/NVIDIA/SambaNova;
- safety critic: an independently routed safety model;
- trainable adapter updates: exactly one checkpointed Kaggle, Lightning or
  Modal workspace, selected in that order when an authenticated session is
  actually observed.

The planner fails closed on absent credentials, caps the successive-halving
request plan at the computed 47-call ceiling, requires both the Cloudflare
token and account ID, and requires `LIGHTNING_FREE_ONLY_ACK=1` before a
Lightning Model API call can be selected. It never stores secret values. API
outputs remain advisory and cannot enter training until the exact provider and
model output-rights review passes; actual weight updates occur only in the
selected GPU workspace. Lightning's official pages describe the allocation as
15 monthly credits but publish different hour equivalents depending on the
machine and spot assumptions, so the pipeline budgets credits rather than
claiming a guaranteed number of GPU hours.

## Primary official sources

- Google Gemini pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini OpenAI compatibility: <https://ai.google.dev/gemini-api/docs/openai>
- Groq Free Plan limits: <https://console.groq.com/docs/rate-limits>
- Cloudflare Workers AI pricing: <https://developers.cloudflare.com/workers-ai/platform/pricing/>
- Cloudflare OpenAI compatibility: <https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/>
- OpenRouter free-route limits: <https://openrouter.ai/docs/faq>
- OpenRouter live model catalog: <https://openrouter.ai/api/v1/models?output_modalities=all>
- Cerebras Free-tier limits: <https://inference-docs.cerebras.ai/support/rate-limits>
- Hugging Face Inference Providers pricing: <https://huggingface.co/docs/inference-providers/en/pricing>
- Cohere evaluation-key limits: <https://docs.cohere.com/v2/docs/rate-limits>
- Cohere OpenAI compatibility: <https://docs.cohere.com/docs/compatibility-api>
- Alibaba Model Studio free quota: <https://help.aliyun.com/en/model-studio/new-free-quota>
- Alibaba Model Studio OpenAI-compatible base URLs: <https://help.aliyun.com/en/model-studio/base-url>
- NVIDIA NIM developer access: <https://docs.api.nvidia.com/nim/docs/product>
- GitHub Models retirement notice: <https://docs.github.com/en/github-models>
- Kaggle GPU quota guidance: <https://www.kaggle.com/docs/efficient-gpu-usage>
- Lightning AI Studio free credits: <https://lightning.ai/docs/overview/ai-studio/>
- Lightning Model APIs and free limits: <https://lightning.ai/docs/platform/inference/model-apis>
- Lightning OpenAI-compatible endpoint: <https://lightning.ai/docs/litai/features/granular-billing>
- Modal Starter compute credits: <https://modal.com/pricing>
- Google Colab FAQ: <https://research.google.com/colaboratory/faq.html>
- Hugging Face ZeroGPU: <https://huggingface.co/docs/hub/main/en/spaces-zerogpu>
- Amazon SageMaker Studio Lab availability and GPU limits: <https://docs.aws.amazon.com/sagemaker/latest/dg/studio-lab-overview.html>

## Reproduction

```bash
node scripts/train_local_gtm_route_head.mjs --batch-size 64
node --test tests/test_local_gtm_route_head.mjs tests/test_local_gtm_route_runtime.mjs
node --test tests/test_local_gtm_generative_baseline.mjs
node scripts/run_local_gtm_generative_baseline.mjs
node scripts/run_local_gtm_route_head.mjs --text \
  'Build a differentiated B2B launch strategy. Return outputs: smp, rtb, offer.'
.venv/bin/python scripts/build_v10_frontier_api_panel.py
.venv/bin/python scripts/compile_v10_free_cloud_execution_plan.py
.venv/bin/python scripts/run_v10_frontier_free_api_sprint.py
.venv/bin/python scripts/discover_local_first_model_resources.py
.venv/bin/python scripts/run_local_gtm_creative_benchmark.py
.venv/bin/python scripts/compile_local_gtm_portfolio_blind_review.py
```

After adding at least one user-controlled free credential to the process
environment, recompile the plan and execute only synthetic or public cases:

```bash
.venv/bin/python scripts/compile_v10_free_cloud_execution_plan.py
.venv/bin/python scripts/run_v10_frontier_free_api_sprint.py \
  --execute --data-class synthetic
```

The runner never enables paid routes, never persists credential values, and
stops at the frozen 47-call execution ceiling under the separate 50-call hard
daily cap. A successful inference receipt is still
advisory evidence, not permission to train on provider output or proof of GPU
weight updates.

The training script fails if the pinned local model is absent. It never pulls a replacement.

## Five-human blind-review operation

The v14 local mission's three generated territories passed candidate-level and portfolio-level semantic distinction gates and are packaged into six randomized, role-hidden candidate-versus-baseline pairs and 30 empty review tasks. A real result requires five distinct invited humans, six immutable submissions per person, the exact independence attestation, and the predeclared Wilson lower-bound gate. Contract tests exercise the mechanics only and are never reported as human evidence.

Create the private invitations once; the command refuses to overwrite an existing file and never echoes token values:

```bash
.venv/bin/python scripts/create_blind_review_invitations.py
PROOFLAUNCH_APPROVAL_TOKEN='operator-secret-at-least-24-characters' \
  .venv/bin/python scripts/serve_v10_submission_api.py --port 8765
```

Open `http://127.0.0.1:8765/control/training`. Give each named reviewer exactly one slot token from `.prooflaunch-secrets/blind-review-invitations.json`; do not share any private mapping. The control surface can switch among the 30-label focused-campaign gate, the 270-label nine-case portfolio gate, and the 300-label judge-calibration gate. It loads only the invitation-bound assignment, computes the canonical digest in-browser, and submits an immutable record. The calibration scope shows the exact binary criterion but never the model prediction, provider, private mapping, or another human label.

Only after 30/30 integrity-valid records can the server deblind and expose a recommendation. A named operator must then explicitly admit that recommendation as a content-addressed prompt seed. The server immediately compiles the selected territory into deterministic image, video, original-music, and speech lanes, including workflow IDs or explicit missing-workflow blockers, bounded values, and hash-derived seeds. Both receipts still have `gpu_execution_authorized=false`, `spend_authorized=false`, `external_publish_authorized=false`, and `effect_claim_eligible=false`; later GPU production, craft review, release, and measured outcome gates remain separate.
