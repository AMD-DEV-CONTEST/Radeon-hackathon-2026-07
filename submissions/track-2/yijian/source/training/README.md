# Public training and evaluation source

This directory contains the reproducible code contracts for YIJIAN's data, training, evaluation, and release pipeline. Restricted rows are intentionally absent.

## Included

- gold-unit schemas, reviewer binding, canonical hashes, and source-chain validation;
- creator video-level split and symmetry leakage checks;
- deterministic 720-record Agent SFT projection and task-mix validation;
- Qwen3-14B tokenizer audit with no silent answer truncation;
- BF16 LoRA smoke, micro, full, adapter freeze, and hash manifests;
- formal Agent/runtime evaluation, blind-review packaging, sealed access controls, and release gates;
- synthetic fixtures and public unit tests.

## Excluded

Creator-authorized text, raw video/audio, private games, reviewer comments, authorization screenshots, sealed cases, model weights, and adapters are not public. Aggregate counts and immutable hashes are published in the submission evidence directory.

## Public test path

From `source/`:

```bash
python -m pytest -q training/tests
```

The tests construct temporary synthetic artifacts and cover candidate selection, reviewer trust, source-chain hashes, legal PV replay, explicit split isolation, task proportions, adapter freezing, runtime plans, coexistence summaries, and sealed-test protections.

## Authorized full replay

The fixed base is Qwen3-14B revision `40c069824f4251a91eefaf281ebe4c544efd3e18`. The private manifest must contain exactly 720 train records with the 216 / 288 / 144 / 72 task mix and must pass tokenizer, license, hash, and leakage gates before training.

The v3 configuration is BF16, seed `20260803`, batch size 1, gradient accumulation 16, learning rate `3e-5`, LoRA rank 8 / alpha 16 / dropout 0.10, attention projection targets, and exactly two epochs. Smoke, micro, and full start independently from the original base. Failure at any stage restores the stable 27B service and quarantines the candidate.

KataGo and the rules engine remain authoritative; the LoRA is an explanation and planning layer, never the source of board legality, coordinates, win rate, score lead, or life-and-death facts.
