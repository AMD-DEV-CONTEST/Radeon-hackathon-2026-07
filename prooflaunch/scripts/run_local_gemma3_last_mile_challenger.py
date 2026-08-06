#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_last_mile_challenger import (  # noqa: E402
    challenger_failures,
    compile_receipt,
    extract_json_object,
    validate_receipt,
)


MODEL_ID = "mlx-community/gemma-3-12b-it-4bit"
SYSTEM_PROMPT = """You are an award-calibre but evidence-disciplined GTM creative director and operator. Return exactly one JSON object, no markdown. You are creating a clean-room challenger from the supplied brief, not copying any named campaign. Do not claim achieved lift, revenue, conversion, awards, 4A parity or Top-1 status. Make decisive, specific, production-ready choices. Every field is mandatory."""
TASK_PROMPT = """Create an integrated same-brief challenger for ProofLaunch Cortex-X.

Frozen brief:
- Product: governed multimodal GTM employee that binds approved evidence, generation, review, activation and learning without automatic external release.
- Audience: GTM leaders and founder-led growth teams at B2B AI software companies.
- Problem: fragmented strategy, content, approval and measurement tools slow execution and obscure accountability.
- Desired outcome: one traceable path from a rights-bound brief to review-ready GTM artifacts.
- Offer: inspect the end-to-end evidence pack, then decide whether to join the design-partner cohort.
- Budget: zero paid media for launch. Primary channel LinkedIn organic; secondary channel partner communities.
- Claim boundary: only the product characteristic above is approved. All performance statements must be framed as hypotheses to test.
- Voice: lucid, restrained, provocative, operational; no generic AI superlatives.
- Human release required for every external action.

Return exactly these top-level objects and fields:
1 integrated_gtm_strategy: diagnosis, strategic_choice, big_idea, channel_sequence, commercial_hypothesis.
2 organic_social_copy: hook, body (array of 3-6 short paragraphs), cta.
3 landing_page: headline, subhead, proof (array), objection, cta.
4 lifecycle_email: subject, preheader, body (array of 3-6 short paragraphs), cta.
5 content_schedule: sequence_logic, days (array of seven objects: day, channel, asset, learning_question).
6 seo: primary_intent, title, outline (array), internal_links (array).
7 geo: question, direct_answer, evidence_needed (array), entity_statement.
8 advertising: audience, creative_route, copy (object with headline, body, cta), test_design. This is a draft test plan only; spend remains disabled.
9 analytics: primary_metric, leading_signals (array), stop_rules (array), decision_rule.
10 employee_agent: graph (array), loop (array), harness (array), approval_points (array).
11 cross_device_memory: remember (array), retrieve, conflict_rule, privacy_rule.

Creative requirement: build one ownable campaign platform around the tension between a polished promise and inspectable proof. Make each channel native, avoid repeating the same sentence, and give an operator enough specificity to execute tomorrow."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _model_manifest(snapshot: Path) -> tuple[str, str]:
    required = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json")
    missing = [name for name in required if not (snapshot / name).is_file()]
    shards = sorted(snapshot.glob("model-*.safetensors"))
    if missing or not shards:
        raise SystemExit(f"local model snapshot is incomplete: missing={missing}, shards={len(shards)}")
    entries = []
    for path in sorted(item for item in snapshot.iterdir() if item.is_file()):
        resolved = path.resolve(strict=True)
        entries.append({"name": path.name, "bytes": resolved.stat().st_size, "blob_identity": resolved.name})
    return snapshot.name, hashlib.sha256(_canonical(entries).encode("utf-8")).hexdigest()


def _prompt(tokenizer: Any, user_prompt: str) -> str:
    rendered = tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
        tokenize=False,
        add_generation_prompt=True,
    )
    return rendered + "{"


def _generate(model: Any, tokenizer: Any, prompt: str, *, max_tokens: int) -> dict[str, Any]:
    import mlx.core as mx
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    mx.random.seed(20260802)
    started = time.monotonic()
    continuation = generate(
        model,
        tokenizer,
        prompt=_prompt(tokenizer, prompt),
        max_tokens=max_tokens,
        sampler=make_sampler(temp=0.15),
        verbose=False,
    )
    raw = "{" + continuation.lstrip()
    try:
        token_count = len(tokenizer.encode(raw))
    except Exception:
        token_count = 0
    return {"raw_output": raw, "elapsed_seconds": time.monotonic() - started, "generated_token_count": token_count}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline Gemma 3 same-brief last-mile challenger.")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", default=str(ROOT / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger.json"))
    args = parser.parse_args()
    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    output = Path(args.output).expanduser().resolve()
    output.relative_to(ROOT)
    revision, manifest_sha256 = _model_manifest(snapshot)
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})

    from mlx_lm import load

    model, tokenizer = load(str(snapshot), lazy=False)
    attempts = [_generate(model, tokenizer, TASK_PROMPT, max_tokens=3000)]
    attempts[0]["source"] = "fresh_generation"
    try:
        failures = challenger_failures(extract_json_object(attempts[0]["raw_output"]))
    except Exception as error:
        failures = (str(error),)
    if failures:
        repair = TASK_PROMPT + "\n\nThe prior draft failed for these exact reasons:\n- " + "\n- ".join(failures) + "\nRewrite the complete JSON from scratch."
        attempts.append(_generate(model, tokenizer, repair, max_tokens=3400))
        attempts[-1]["source"] = "bounded_repair"

    receipt = compile_receipt(
        model_id=MODEL_ID,
        model_revision=revision,
        model_manifest_sha256=manifest_sha256,
        attempts=attempts,
    )
    validate_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "accepted": receipt["accepted"], "lane_count": receipt["lane_count"], "attempt_count": len(attempts), "content_sha256": receipt["content_sha256"]}, sort_keys=True))
    return 0 if receipt["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
