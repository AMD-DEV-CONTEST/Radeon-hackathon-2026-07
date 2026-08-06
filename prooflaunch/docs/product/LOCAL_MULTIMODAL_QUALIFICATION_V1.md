# Local multimodal qualification v1

ProofLaunch now has direct local model evidence instead of only workflow
blueprints. The run used already-cached weights, `HF_HUB_OFFLINE=1`, Apple
Metal, zero cloud calls and zero downloads.

## Speech lane

`mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16` generated an original
14.72-second English proof-first script without reference audio, voice cloning,
a named person or celebrity resemblance. The source WAV is 24 kHz mono 16-bit;
the bounded delivery master is 48 kHz stereo 24-bit PCM. The base model card is
Apache-2.0. Technical delivery format passed, while semantic transcription and
named-human listening review remain unobserved.

## Video lane

`dgrauet/ltx-2.3-mlx`, an MLX conversion of `Lightricks/LTX-2.3`, generated two
fixed-seed candidates. The first decode attempt failed because ffmpeg was not on
PATH; the existing bundled binary fixed that packaging defect without an
install. The distilled candidate was rejected because the subject was not
recognizable. One bounded one-stage repair made a single translucent evidence
card recognizable. It remains only 384×256 and 1.04 seconds.

LTX-2.3 uses the LTX-2 Community License. Its paid-license threshold depends on
entity revenue, which has not been verified for the operator, so production
rights remain fail-closed. The candidate is neither distributable production
creative nor training material.

## Admission decision

Local inference: observed. Product admission: failed. 4A/Top-1 claim: ineligible.
Radeon-local inference: not observed. Business effect: not observed. The
machine-readable receipt hashes every output and records every failed gate at
`evidence/v10/local-multimodal-qualification.json`.
