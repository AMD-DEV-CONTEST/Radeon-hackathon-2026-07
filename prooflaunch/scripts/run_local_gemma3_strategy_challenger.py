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
from prooflaunch_remix.gtm_strategy_challenger import (  # noqa: E402
    compile_strategy_challenger_receipt,
    extract_strategy_candidate,
    strategy_candidate_failures,
    validate_strategy_challenger_receipt,
)


MODEL_ID = "mlx-community/gemma-3-12b-it-4bit"
SYSTEM_PROMPT = (
    "You are the bounded strategy node inside a production GTM workflow. "
    "Output exactly one compact JSON object and no markdown. Do not state measured "
    "effects, guaranteed outcomes, revenue, ROI, conversion, improvement, reduction, "
    "or percentage claims outside unsupported_claims. Every field is mandatory."
)
TASK_PROMPT = """Design a zero-paid-media B2B launch experiment for ProofLaunch Cortex-X, an evidence-bound multimodal GTM workspace.

Return exactly these seven top-level fields:
- strategy: 80-600 characters; name the ICP and a product characteristic differentiator, without an effect claim.
- primary_channel: exactly one of LinkedIn, community, partner, owned.
- channel_rationale: 48-500 characters; describe observed audience behavior, not performance.
- zero_budget_loop: exactly four 40-420 character steps. Include at least two concrete earned mechanisms, a reusable evidence/diagnostic/checklist/benchmark/template/teardown/worksheet/proof artifact, and explicit qualified-conversation logging. No paid distribution, vanity-only final step, or case-study performance claim.
- experiment: object with exactly treatment, comparable_baseline, observation_window_days, primary_metric, decision_rule. The baseline must explicitly say that the same eligible account pool is randomly split 50/50 into a same-window treatment and holdout; comparing different communities or historical traffic is invalid. Use 7-30 days and primary_metric exactly qualified_conversations. The rule must preregister a non-zero minimum sample threshold but may not report an achieved effect.
- human_gate: object with exactly role, decision, artifact; decision exactly approve_or_reject, role must be named, and artifact must include the qualified-conversation ledger.
- unsupported_claims: array containing 1-8 claims the team explicitly rejects.

The experiment must be preregistered, rights-safe, executable without paid media, and must not imply that any result has already occurred."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _model_manifest(snapshot: Path) -> tuple[str, str]:
    required = (
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "model.safetensors.index.json",
    )
    missing = [name for name in required if not (snapshot / name).is_file()]
    shards = sorted(snapshot.glob("model-*.safetensors"))
    if missing or not shards:
        raise SystemExit(f"local model snapshot is incomplete: missing={missing}, shards={len(shards)}")
    entries = []
    for path in sorted(path for path in snapshot.iterdir() if path.is_file()):
        resolved = path.resolve(strict=True)
        entries.append(
            {
                "name": path.name,
                "bytes": resolved.stat().st_size,
                "blob_identity": resolved.name,
            }
        )
    manifest_sha256 = hashlib.sha256(_canonical(entries).encode("utf-8")).hexdigest()
    revision = snapshot.name
    if len(revision) < 7:
        raise SystemExit("model snapshot directory must expose an immutable revision")
    return revision, manifest_sha256


def _verified_prior_candidate(prior: object) -> tuple[dict[str, Any], str]:
    if not isinstance(prior, dict) or prior.get("schema") != "ProofLaunchLocalStrategyChallengerReceiptV1":
        raise SystemExit("--repair-from receipt schema is invalid")
    unsigned = dict(prior)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest():
        raise SystemExit("--repair-from receipt digest is invalid")
    execution = prior.get("execution")
    if not isinstance(execution, dict) or execution.get("network_download_performed") is not False:
        raise SystemExit("--repair-from receipt execution boundary is invalid")
    for field in (
        "automatic_release_authority",
        "automatic_training_admission",
        "four_a_claim_eligible",
        "top1_claim_eligible",
        "causal_effect_claim_eligible",
    ):
        if prior.get(field) is not False:
            raise SystemExit("--repair-from receipt authority boundary is invalid")
    candidate = prior.get("accepted_candidate")
    if isinstance(candidate, dict):
        if candidate.get("schema") != "ProofLaunchZeroBudgetStrategyCandidateV1":
            raise SystemExit("--repair-from accepted candidate schema is invalid")
        candidate_unsigned = dict(candidate)
        candidate_digest = candidate_unsigned.pop("content_sha256", None)
        if candidate_digest != hashlib.sha256(_canonical(candidate_unsigned).encode("utf-8")).hexdigest():
            raise SystemExit("--repair-from candidate digest is invalid")
        candidate_unsigned.pop("schema", None)
    else:
        attempts = prior.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise SystemExit("--repair-from receipt has no candidate snapshot")
        candidate_snapshot = attempts[-1].get("candidate_snapshot")
        if not isinstance(candidate_snapshot, dict):
            raise SystemExit("--repair-from receipt has no candidate snapshot")
        candidate_unsigned = dict(candidate_snapshot)
    return candidate_unsigned, str(supplied)


def _prompt(tokenizer: Any, user_prompt: str) -> str:
    rendered = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tokenize=False,
        add_generation_prompt=True,
    )
    return rendered + "{"


def _generate(model: Any, tokenizer: Any, user_prompt: str, *, max_tokens: int) -> dict[str, Any]:
    import mlx.core as mx
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    mx.random.seed(42)
    started = time.monotonic()
    continuation = generate(
        model,
        tokenizer,
        prompt=_prompt(tokenizer, user_prompt),
        max_tokens=max_tokens,
        sampler=make_sampler(temp=0.0),
        verbose=False,
    )
    raw_output = "{" + continuation.lstrip()
    elapsed = time.monotonic() - started
    try:
        generated_tokens = len(tokenizer.encode(raw_output))
    except Exception:
        generated_tokens = 0
    return {
        "raw_output": raw_output,
        "elapsed_seconds": elapsed,
        "generated_token_count": generated_tokens,
    }


def _repair_prompt(raw_output: str, failures: tuple[str, ...]) -> str:
    return (
        TASK_PROMPT
        + "\n\nThe draft failed the deterministic Harness for exactly these reasons:\n- "
        + "\n- ".join(failures)
        + "\n\nRewrite the full JSON from scratch. Preserve no unsupported performance claim. "
        + "The previous draft was:\n"
        + raw_output[:6_000]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a two-attempt offline MLX Gemma 3 strategy challenger."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--repair-from",
        help="Optional prior challenger receipt whose accepted candidate is re-evaluated under the current Harness.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/local-gemma3-12b-strategy-challenger-v2.json"),
    )
    args = parser.parse_args()
    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    if not snapshot.is_dir():
        raise SystemExit("--model-path must be a local snapshot directory")
    revision, manifest_sha256 = _model_manifest(snapshot)
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    attempts: list[dict[str, Any]] = []
    if args.repair_from:
        prior_path = Path(args.repair_from).expanduser().resolve(strict=True)
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        candidate, prior_digest = _verified_prior_candidate(prior)
        attempts.append(
            {
                "raw_output": json.dumps(candidate, ensure_ascii=False),
                "elapsed_seconds": 0.0,
                "generated_token_count": 0,
                "source": f"prior_receipt:{prior_digest}",
            }
        )
    else:
        from mlx_lm import load

        model, tokenizer = load(str(snapshot), lazy=False)
        attempt = _generate(model, tokenizer, TASK_PROMPT, max_tokens=640)
        attempt["source"] = "fresh_generation"
        attempts.append(attempt)
    try:
        parsed = extract_strategy_candidate(attempts[0]["raw_output"])
        failures = strategy_candidate_failures(parsed)
    except Exception as error:
        failures = (str(error),)
    if failures:
        if "model" not in locals():
            from mlx_lm import load

            model, tokenizer = load(str(snapshot), lazy=False)
        attempts.append(
            _generate(
                model,
                tokenizer,
                _repair_prompt(attempts[0]["raw_output"], failures),
                max_tokens=768,
            )
        )
        attempts[-1]["source"] = "bounded_repair"

    receipt = compile_strategy_challenger_receipt(
        model_id=MODEL_ID,
        model_revision=revision,
        model_manifest_sha256=manifest_sha256,
        device_family="Apple Metal",
        attempts=attempts,
    )
    validate_strategy_challenger_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "accepted": receipt["accepted"],
                "attempt_count": len(receipt["attempts"]),
                "content_sha256": receipt["content_sha256"],
                "network_download_performed": False,
                "cloud_api_calls": 0,
                "training_observed": False,
                "radeon_local_inference_observed": False,
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
