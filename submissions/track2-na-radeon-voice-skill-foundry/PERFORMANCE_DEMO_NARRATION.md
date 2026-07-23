# Performance Demo Narration

The narration is AI-generated with AIDP
`gemini-3.1-flash-tts-preview`, male voice `Charon`. The product workflow is
recorded from the public Cloudflare deployment and executes against the W7900
runtime.

## Open the Live Product

Radeon Voice Skill Foundry runs as a public full-stack product, not a static
mockup. Cloudflare Pages hosts the interface. An authenticated same-origin
gateway forwards API actions to an AMD Radeon Pro W7900 running ROCm 7.2.1.
The product turns a private spoken procedure into a governed, reusable Agent
Skill before risky actions are allowed.

## Capture Source-Bound Voice

The Voice module uploads the twenty-point-three-nine second synthetic Chinese
procedure used in the Radeon validation. Qwen3-ASR transcribes the audio on the
W7900. Voice Evidence measures source integrity, level, clipping, silence,
signal-to-noise ratio, dropout, and multi-frame burst loss. The sample passes at
one hundred out of one hundred, and the server binds the original transcript
hash to the skill.

## Compile on Radeon

The Radeon model adapter compiles the spoken procedure. Qwen3-4B-Instruct
combines the transcript, aligned action trace, and retrieved local policy
evidence. The interface keeps the compiling state visible during the real model
call. The footage is not accelerated and a cached policy does not replace
generation. Deterministic safety guardrails are merged ahead of the model
result.

## Inspect Enforced Policy

The no-send instruction becomes a must-not rule and `mail.send` is denied.
Salary data becomes a redaction rule. Missing ownership opens human review.
Calendar holds remain conditional on a due date. Seven tests cover voice
integrity, the happy path, automatic sending, sensitive data, missing context,
conditional scope, and unapproved network writes.

## Prove Unsafe Paths

Verification executes unsafe paths before promotion. The server resolves the
authoritative compile run rather than trusting client-side permissions. All
seven fixtures pass. Automatic email sending is blocked before tool execution,
sensitive data is removed, and governance receipts record the review and block
decisions.

## Save and Reuse Memory

The verified result is saved into local procedural memory and reused without
regenerating its policy or fixtures. Compatibility remains bound to the active
runtime, verifier, tool contract, policy, skill definition, and Voice Evidence
schema.

## Show W7900 Evidence

At concurrency eight, vLLM graph serving reaches two hundred fifty-seven point
six five aggregate output tokens per second, twelve point four seven times the
serialized Transformers path. Native Qwen3-ASR batching reaches eighty-five
point three five times aggregate real-time and is six point six six times faster
than sequential inference. The recorded performance revision passes
thirty-five out of thirty-five tests.

## Close

The public path is Cloudflare, authenticated gateway, W7900 speech recognition,
local policy retrieval, Radeon model compilation, least-privilege enforcement,
adversarial proof, and procedural memory. Actions capture what happened. Voice
captures why, when, exceptions, and what must never happen.
