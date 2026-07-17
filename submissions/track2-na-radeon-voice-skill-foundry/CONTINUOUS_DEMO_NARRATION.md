# Continuous Demo Narration

The final continuous-operation demo uses AIDP
`gemini-3.1-flash-tts-preview`, voice `Kore`. It is a single browser recording
of the enhanced local workflow. Radeon measurements and proof values remain
those of the independently validated Radeon Cloud run.

## Open the Workbench

This is one continuous operating session of Radeon Voice Skill Foundry. The
workbench starts with a clean local data directory. The blue status badge shows
how many trusted compile runs have been durably stored.

## Upload the Spoken SOP

I upload the same twenty-point-three-nine second spoken procedure used for the
Radeon validation. Voice Evidence version zero point two measures level,
clipping, silence, noise floor, estimated signal-to-noise ratio, crest factor,
dropout ratio, and source integrity. No acoustic diagnostic is triggered, and
the source receives a one-hundred-out-of-one-hundred pass.

## Compile Voice into Policy

Next, the transcript and aligned action trace are compiled into typed rules.
The policy retrieves local evidence, keeps P-zero and P-one findings, redacts
compensation data, requires confirmation for missing ownership, and denies
automatic email sending. The trusted compile run is written to disk rather
than kept only in process memory.

## Run Adversarial Verification

The verifier executes seven positive and adversarial fixtures. The unsafe
paths are tested before promotion. All seven pass, mail dot send remains
denied, BLOCK and REVIEW receipts are issued, and the proof bundle receives a
compatibility manifest for the verifier, runtime, tools, policy, skill, and
voice evidence schema.

## Save and Reuse the Verified Skill

The verified proof is saved into procedural memory with its original action
contract. Exact reuse loads the proven skill without regenerating policy or
fixtures. The reuse counter and measured retrieval latency update immediately.

## Restart and Recover Durable Runs

Now the application service is restarted. The browser stays in the same
session. After reload, the saved skill and trusted proof are still available.
The durable-run count survives because voice evidence, compile runs, and
verification results are atomically persisted on disk.

## Change Runtime and Invalidate Proof

I restart the service again with a different runtime model identity. The saved
proof is no longer silently trusted. The skill changes to revalidation
required and explains that the model, GPU, ROCm, or runtime contract changed.
The Reuse command becomes Revalidate.

## Revalidate and Download Proof

Revalidation creates a new child run bound to the current runtime, reruns all
seven fixtures, and produces a new compatible proof. The skill returns to
verified status. Finally, I download the proof package containing the skill,
policy, fixtures, receipts, local evidence, voice evidence, and compatibility
manifest. This completes the full lifecycle from voice to policy to proof,
through restart, invalidation, and recovery.
