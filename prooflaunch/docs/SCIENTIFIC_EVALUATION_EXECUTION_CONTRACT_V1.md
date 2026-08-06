# Scientific Evaluation Execution Contract V1

This layer freezes evaluation before additional model work. It extends the
existing Competition 2X runner and Cortex-X V10 quality contract; it does not
replace either one.

## Frozen protocol

The project-owned mechanical seed contains eighteen sealed cases, two in each
of nine partitions: entity product, AI-agent product, long document,
multi-image, video, audio, tool trajectory, memory, and integrated 4A
campaign. Every case has a content hash, expected-schema hash, rights label,
sealed-test split, training prohibition, and partition-specific leakage
canary. Two PCM WAV files provide real hash-bound audio inputs. Video cases
currently bind owned UHD boundary-frame sequences; they are not encoded or
model-generated videos.

The image, video, and GTM-agent baseline choices were frozen before candidate
results using exact upstream revisions. Selection is not execution: all three
still require the same input, hardware, budget, and tools before comparison.

## Denominator-safe metrics

The formula layer accepts raw confusion counts or raw pass/eligible counts for
exactly thirteen preregistered metrics: Claim precision and recall, schema
validity, Agent success, tool error, trajectory accuracy, failure attribution,
memory precision, stale recall, image identity, video identity, temporal
consistency, and A/V alignment. Zero or impossible denominators fail closed.
Wilson lower bounds reuse `quality_contract.wilson_lower_bound`; the project
does not maintain a second statistical implementation.

The checked formula fixture uses controlled counts only. Its values are not
model performance and cannot satisfy a quality threshold.

## Evidence still missing

The scientific report remains planned because none of the twelve runtime arms
has a matched result, no five human reviewers have been calibrated, no 1,500
human ratings exist, no reliability alpha or 4A/publishability/preference
result exists, and no Agency Critic TPR/TNR has been measured. Consequently,
no complete ablation, Scientific Report, or Top-3 Evidence is frozen, and any
Top-3 claim remains prohibited.
