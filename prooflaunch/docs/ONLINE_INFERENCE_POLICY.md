# Online inference policy

## Local-first boundary

The product-critical route is trained and evaluated locally before any online
teacher is considered. Existing local model digests are reused and automatic
model downloads are disabled. The observed V3 route-head receipt, real-time
runtime and current free-cloud matrix are documented in
`docs/product/LOCAL_FIRST_TRAINING_AND_FREE_CLOUD_V1.md`.

## Routing order

1. Every external model or Agent call first attempts the official AMD Radeon
   Token Factory endpoint.
2. The gateway tries the three currently public Radeon Cloud models in a fixed
   order and records only redacted operational metadata.
3. Third-party fallback activates only when all official attempts fail with a
   network, rate-limit, gateway, server, or response-contract error.
4. Authentication, permission, and client-validation failures do not silently
   fall through to another provider.

## Third-party admission gate

A fallback endpoint is disabled until all of the following are explicit:

- public HTTPS endpoint and model identity;
- API key supplied only by an environment variable;
- data-processing approval and license review;
- finite per-call spend cap;
- acceptance of `radeon-official-finetuning-extreme-v1`;
- auditable provider/model/route receipt with no prompt, output, or credential;
- no eligibility for the competition core path.

Allowed scopes are training-data generation, teacher distillation, evaluation,
development Agent inference, and development core workflows. The submitted
competition core remains local Radeon-only because the frozen competition
adapter forbids a closed online API dependency.

The ready-to-load Fireworks example is
`config/fireworks-fallback.example.json`. Its routing order is Kimi K2.6
(multimodal/Agent), GLM 5.1 (long-horizon Agent), DeepSeek V4 Pro
(long-context reasoning), and gpt-oss-120b (lower-cost critic). Kimi, GLM, and
gpt-oss use Fireworks Priority service where the current service supports it;
DeepSeek V4 Pro stays on its documented default tier. No route activates until
`FIREWORKS_API_KEY` exists and the admission fields remain approved.

## Evidence boundary

Official Token Factory and third-party outputs are external evidence. They may
teach, critique, rank, repair, or distill the local model, but they cannot be
reported as local Radeon execution, observed business outcomes, or competition
benchmark results. Every fallback is visible in the composite receipt.

The public AMD site terms inspected on 2026-07-30 do not provide an explicit
Token Factory output-training or redistribution grant. Raw teacher episodes
therefore remain private `external_teacher_advisory` with
`rights_review_required`; they are excluded from the rights-audited Radeon
training manifest until an exact AMD term or written authorization establishes
that permission. The fail-closed audit is
`evidence/v10/tokenfactory-output-rights.json`.

## 2026-07-31 frontier capability panel

The dated capability contract is
`config/cortex_x_v10_frontier_api_panel.json`. It separates model identity,
access economics, open-weight status, modality, and competition eligibility:

- DeepSeek's current API identifier remains `deepseek-v4-flash`; the provider
  change log identifies the 2026-07-31 post-trained release as
  DeepSeek-V4-Flash-0731. Token Factory continues to expose its own
  `DeepSeek-V4-Flash` identifier.
- MiniMax M3 is the Agentic/multimodal language candidate. Its official direct
  API ID is `MiniMax-M3`, and official weights are now published separately.
  MiniMax-H3 is the current asynchronous multimodal video candidate at
  `/v2/video_generation`: text/image/video/audio inputs, 2K output, and an
  integer duration from 4 through 15 seconds. Hailuo 2.3 remains a separate
  older-compatible video route rather than an alias for H3.
- Direct DeepSeek and MiniMax APIs are pay-as-you-go products. A free consumer
  app, an AMD sponsored daily quota, developer credits, and open weights are
  not interchangeable claims.
- MiniMax M3's official Hugging Face repository is observed, so open-weight
  availability is verified separately from its paid hosted API. That does not
  imply unrestricted redistribution or hosted-output distillation rights. H3
  and Hailuo hosted video routes are not represented as downloadable weights.

All available language/Agent candidates enter a same-input successive-halving ladder. One
cheap schema smoke case precedes two Agent-contract cases; only the two best
hard-gate passers may run five frozen GTM finals. H3 runs in the separate 2K
video lane against the same campaign brief and cross-media evidence
requirements; Hailuo 2.3 is retained as a bounded compatibility baseline.
This preserves broad model discovery without spending full quota on weak or
malformed outputs.

### Zero-cost frontier sprint

The zero-cost panel is a bounded evaluation accelerator, not an automatic
training-data source. A live 2026-08-02 OpenRouter catalog observation found
18 exact zero-cost variants among 455 catalog models. Twelve chat-compatible
variants enter the frozen challenger panel. Six speech, text/vision embedding,
visual reranking, coding-fallback or same-provider fallback variants remain in
a specialist inventory because they require different response contracts or
would exceed the frozen request budget. Every exact frozen comparison uses a
`:free` model ID;
`openrouter/free` is exploratory because its resolved model can vary.

Groq's official Free Plan contributes four additional same-input candidates:
GPT-OSS 120B, GPT-OSS 20B, Qwen3.6-27B, and Compound. The direct DeepSeek V4
and MiniMax M3/H3 routes are excluded from this zero-cost runner because
official pricing classifies them as pay-as-you-go.

Additional official free-mode providers are admitted behind separate keys:
NVIDIA NIM contributes DeepSeek V4 Pro, Nemotron 3 Ultra, Kimi K2.6 and the
text/image/video-capable `google/diffusiongemma-26b-a4b-it` free development
endpoints; SambaNova Free Tier contributes DeepSeek V3.1,
GPT-OSS 120B and preview DeepSeek V3.2/Gemma 4 31B routes; Mistral Studio Free
mode contributes a rate-limited `mistral-large-latest` route. Cerebras is kept
out of the permanent-free roster because its current new-account offer is a
time-bounded developer credit requiring a verified payment method.

The 2026-08-02 refresh adds OpenAI-compatible free routes without changing the
competition boundary: Google AI Studio `gemini-3.6-flash`, plus Cloudflare
Workers AI `@cf/openai/gpt-oss-120b` and multimodal
`@cf/google/gemma-4-26b-a4b-it`. Cloudflare requires both
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`; its free allocation is
10,000 neurons/day shared across models. They remain public/synthetic
evaluation routes until provider-output training rights are approved.

GitHub Models is not a fallback. GitHub's current service notice states that
the playground, catalog, inference API and BYOK were fully retired for every
customer on 2026-07-30. Historical HTTP 410 receipts remain preserved as
negative evidence, and no `GITHUB_MODELS_TOKEN` is read by the current runner.

OpenRouter's live catalog also contains Lyria 3 rows whose prompt/completion
token prices are zero while the product pages charge a fixed fee per song.
They are not `:free` variants and are excluded from the zero-cost text race.
Zero token price alone is therefore never used as the free-route predicate.

`scripts/run_v10_frontier_free_api_sprint.py` uses the same frozen synthetic
GTM cases and hard JSON/claim/approval gates for every candidate. Its
successive-halving maximum is 47 calls (29 smoke + 4×2 contract + 2×5 final),
kept at the conservative 50-call cross-provider sprint cap. Paid models are
disabled in this runner. A call is impossible until at least one of
`OPENROUTER_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`,
`SAMBANOVA_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`,
`CLOUDFLARE_API_TOKEN` plus `CLOUDFLARE_ACCOUNT_ID`, `LIGHTNING_API_KEY` plus
`LIGHTNING_FREE_ONLY_ACK=1`, or `COHERE_API_KEY` is
supplied through the environment;
keys are never written to disk.

Free trial endpoints receive only public or synthetic inputs. NVIDIA's free
endpoint notice says trial session data may be collected for security and
product improvement, so customer/confidential data is fail-closed. Outputs
remain evaluation-only until the exact resolved model's license and
provider-output training rights are separately approved. Open weights, free
inference and permission to distill hosted outputs are three different facts.

### Free GPU elasticity

The free-compute scheduler now enumerates all seven verified routes instead of
silently considering only the first three. It keeps workload eligibility
explicit:

- Kaggle, Lightning, Modal, Colab and qualifying legacy SageMaker Studio Lab
  sessions may run checkpointed adapter training. Kaggle is first because its
  official weekly GPU quota is materially larger; Lightning and Modal follow
  because their free allowance is credit-denominated and therefore hardware
  dependent. Colab remains a best-effort fallback because accelerator type,
  availability and duration are not guaranteed.
- Hugging Face ZeroGPU is short-inference/demo only. A free account currently
  receives five GPU minutes per day, so it cannot be selected as the weight
  training route.
- NVIDIA LaunchPad is a guided lab/reproducibility route, not an unrestricted
  persistent GPU rental, and is never selected for product weight training.

Every provider requires an authenticated session signal. A generic account
token alone does not prove that a GPU was allocated. Before stop, switch or
preemption, the selected route must export the adapter checkpoint, optimizer
state, training metrics, environment lock and SHA-256 receipt; the local frozen
regression remains authoritative after import.

## Daily quota and cache boundary

The current Radeon profile is authoritative for the active usage window. It
reports a `$10` daily hard budget, a `30 RPM` provider ceiling, an
`Asia/Shanghai` reset window, and the exact remaining spend. The client keeps
additional fail-closed controls:

- at most `24 RPM`, leaving provider headroom;
- at most six official attempts per logical completion;
- at most 4,096 generated tokens per request;
- a `$0.0001` settlement buffer while deliberately using the current window;
- a fresh profile-usage snapshot before every large batch;
- automatic stop if the reset timestamp changes or the protected reset
  boundary is reached.

`KV Hit`, `KV Hit %`, and `Cache Write` are operational counters, not
competition-eligibility gates. Zero values mean the provider did not reuse or
write a server-side prompt/KV cache entry. They do not mean authentication,
model execution, ROCm compliance, or the submitted local Radeon path failed.
Repeated prompts keep a stable system prefix so provider caching can help when
available, but no evidence claim depends on a cache hit.

The official teacher-corpus runner uses
`chat_template_kwargs.enable_thinking=false` for bulk artifact generation.
This prevents short Qwen calls from consuming the entire completion budget in
an unpersisted reasoning field. Hidden reasoning is never written to the
dataset; only the visible answer, response metadata, hashes, and redacted
usage receipt are retained.
