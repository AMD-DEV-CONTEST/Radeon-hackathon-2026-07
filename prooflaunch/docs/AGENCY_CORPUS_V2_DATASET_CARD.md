# ProofLaunch Agency Corpus V2 — Dataset Card

Version: `2.0.0-pre-human-gold`  
Status: **Published locally as a pre-release; not frozen for training promotion.**

## What is actually present

| Component | Observed count |
|---|---:|
| Rights-bound source records | 2,000 |
| CPT tokens | 15,000,000 |
| SFT episodes | 15,000 |
| Contract-negative preference pairs | 5,000 |
| Mechanical region preference pairs | 2,000 |
| Visible source-bound trajectories | 1,000 |
| Repair episodes | 500 |
| Gold brief candidates | 300 |
| Gold campaign candidates | 150 |
| Planned five-person reviews | 2,250 |
| Observed human reviews | 0 |

## Promotion boundary

The 300 briefs and 150 campaigns are candidates only. Five independent human reviewers must complete all 2,250 assignments. Promotion requires overall mean >= 4.7, every dimension mean >= 4.5, publishable rate >= 95%, exact case/hash binding, and no imputed ratings. Current human mean is `null`.

## Rights and provenance

Every admitted training record is source- and revision-bound. Trademark holds fail closed. Provider model outputs and public 4A campaign assets are excluded from the training corpus unless separate output/asset rights are proven. This card is not legal advice.

## Intended use

- rights-aware CPT/SFT and visible trajectory research after separate runtime admission;
- source-bound GTM instruction, preference, and repair experiments;
- held-out five-person evaluation after the review packet is completed.

## Prohibited or unsupported use

- copying protected agency work, autonomous publication/spend/outreach, or claims of 4A/business parity;
- treating metadata-only multimodal examples as observed image/audio/video content;
- claiming training, adapter lift, multi-GPU performance, or Radeon execution from these files.

## Known limitations

- Media payloads are unobserved in most SFT records.
- Region preferences are mechanical crop scores, not aesthetic judgments.
- Human review count is zero; rendered 4K quality and business outcomes are unobserved.
- Coverage is English-first and does not establish global cultural adequacy.

## Reproducibility

The machine-readable card at `data/v10_agency_corpus_v2/dataset-card.json` binds every component manifest, the five-human review gate, counts, limitations, and SHA-256 values. Card SHA-256: `e6819a6664067491ae7e8ce1a64b3c4386ead80e75d3109e12d05fb77bd5165a`.

## Truth boundary

Publication of this Dataset Card proves disclosure and component binding, not final corpus promotion, training, 4A quality, five-person review, or Radeon execution.
