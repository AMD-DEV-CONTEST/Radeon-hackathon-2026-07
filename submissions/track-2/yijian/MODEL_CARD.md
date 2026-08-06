# Model Card — YIJIAN LoRA v3

## Model

- Base: Qwen3-14B BF16
- Fixed revision: `40c069824f4251a91eefaf281ebe4c544efd3e18`
- Adapter: YIJIAN LoRA v3, rank 8, alpha 16, dropout 0.10
- Target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`
- Intended runtime: vLLM on AMD Radeon PRO W7900 / ROCm
- Status: trained and frozen experimental candidate; the completed blind review failed, so the competition alias remains on the stable 27B rollback

## Intended use

The adapter produces bounded Go teaching plans, evidence-grounded explanations, and follow-up questions inside the YIJIAN Agent. It is not a standalone Go engine. It must be used with server-side plan validation, goboard, KataGo, source-labelled retrieval, answer validators, and deterministic fallback.

## Training

Training used 720 SFT records with an exact mix of 216 planner, 288 answer, 144 follow-up, and 72 memory/privacy records. The creator portion comes from 48 human-signed, authorized train units; eight creator units form dev and eight remain sealed. The adapter completed exactly 2 epochs / 90 optimizer steps in BF16. Dev loss improved from 3.1131 to 1.6685, all three measured task groups improved, and peak reserved memory was 38.643 GiB.

Training used learning rate `3e-5`, batch 1, gradient accumulation 16, maximum supervised length 1,536, and seed `20260803`. All stages start from the fixed base rather than chaining from an earlier adapter.

## Data and licensing

Creator-authorized material is restricted to non-commercial research and competition demonstration. Project-original and public-domain sources are tracked separately. The public repository contains code, schemas, aggregate manifests, hashes, and synthetic examples—not restricted text, videos, review comments, sealed content, weights, or the adapter.

## Safety design

- the planner cannot emit coordinates or numeric board facts;
- tools are server-whitelisted;
- current-position facts come from goboard and KataGo;
- RAG is labelled as heuristic or source material;
- memory writes require a separate explicit user action;
- unsupported coordinates, values, and status claims trigger rejection or fallback;
- release requires zero severe coordinate, best-move, win-rate, score-lead, side-to-play, and life/death contradictions.

## Evaluation status

The formal runtime suite passed 220/220 plan cases and 24/24 failure/privacy cases. The unseen-position suite achieved 39/40 structured, evidence-faithful outputs (97.5%), with zero severe contradictions and zero fabricated sources. In the completed 30-question anonymous human comparison, the stable 27B scored 4.6133, base 14B scored 2.8500, and YIJIAN LoRA scored 2.5400. The LoRA was marked with five severe contradictions, failed all three release gates, and therefore did not unlock the sealed test. It must not be labelled the released competition model.

## Limitations

The adapter cannot calculate Go strength independently. A 128-visit KataGo query has uncertainty and is not proof. Explanations may still be stylistically incomplete, and one of 40 unseen-position responses was not valid JSON. Small-board instructional cases do not automatically transfer to full-board play. Commercial use of creator-derived data is outside the documented authorization.

## Reproduction and retention

The private local archive contains 11 files / 57,880,245 bytes and matches frozen adapter tree SHA-256 `9de29915ef28dfe66ee3b3239bc9ff70f5ee8a53176a09d918ac425c8cb90ff0`. The optional local F16 GGUF has SHA-256 `f409779aa3cd206ef43c7f389a719d5ecf1ae3bafba60cbf80efe7de28d81c97`. The 14B base can be fetched again at the fixed revision. The adapter can also be retrained from the frozen gold/SFT manifests in a compatible W7900 environment.
