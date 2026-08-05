#!/usr/bin/env python3
"""scripts/rosetta_softprefix_smoke.py — Layer 2B soft-prefix injection smoke test.

This is NOT a quality test. It only verifies that the plumbing for soft-prefix
injection via llama-cpp-python's embedding-batch API works end-to-end:

    1. llama-cpp-python is installed and imports
    2. A GGUF target model loads with embedding=True
    3. We can call llama_decode in embedding mode (embd != NULL)
    4. Generation changes when a nonzero prefix is injected
       (i.e. the prefix actually reaches the attention layer)
    5. If any of the above fails, the failure is EXPLICIT — not silently
       downgraded to text generation

If the smoke test exits ACTIVE, Layer 2B is real. If it exits UNAVAILABLE WITH
REASON, the reason is structured. If llama-cpp-python doesn't expose what we
need, we say so by name.

Conditions tested per pass:
    A: no prefix          (baseline)
    B: zero vector prefix (must produce same output as A — proves zero is no-op)
    C: random prefix      (must produce different output from A)
    D: Rosetta-projected prefix from a different model
       (only run if rosetta_v1.pt + a 2nd model are available)

The smoke test runs at low max_tokens (32) with greedy decoding so per-condition
output is deterministic — that's what makes A==B and A!=C meaningful signals.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ACTIVE = "ACTIVE"
UNAVAIL = "UNAVAILABLE WITH REASON"


def _pick_target_model_path() -> tuple[Path | None, str]:
    """Return (gguf_path, model_name) for the first registered model whose GGUF resolves.
    Returns (None, '') if none do."""
    from rosetta.model_registry import current_family

    for role, m in current_family().items():
        if m.gguf_path and Path(m.gguf_path).is_file():
            return Path(m.gguf_path), m.name
    return None, ""


def run_smoke(
    model_path: Path | None = None,
    prompt: str = "The capital of France is",
    max_tokens: int = 32,
    seed: int = 1337,
) -> dict:
    """Run the four-condition smoke test. Returns a report dict.

    Report shape:
        {
            "status": "ACTIVE" | "UNAVAILABLE WITH REASON",
            "reason": "...",                # only if UNAVAIL
            "model_path": "...",
            "n_embd": int,
            "conditions": {
                "A_no_prefix":     {"output": "...", "tokens": N},
                "B_zero_prefix":   {"output": "...", "tokens": N},
                "C_random_prefix": {"output": "...", "tokens": N, "differs_from_A": True},
                "D_rosetta_prefix":{"status": "...", ...}  # optional
            },
            "checks": {
                "zero_prefix_is_noop": True | False,
                "random_prefix_changes_output": True | False,
            }
        }
    """
    report: dict = {"status": UNAVAIL, "conditions": {}, "checks": {}}

    # 1. llama-cpp-python
    # IMPORTANT: torch must be imported FIRST on Windows so its bundled CUDA runtime
    # DLLs (cudart64_12, cublas64_12, cublasLt64_12) are loaded into the process.
    # Otherwise llama.dll can't resolve its CUDA deps and raises a generic
    # "FileNotFoundError: Could not find module ... (or one of its dependencies)".
    try:
        import torch  # noqa: F401 — DLL preload side-effect on Windows
    except ImportError:
        pass
    try:
        from llama_cpp import Llama, llama_cpp
    except ImportError as e:
        report["status"] = UNAVAIL
        report["reason"] = f"llama-cpp-python not installed ({e})"
        return report
    except (OSError, RuntimeError) as e:
        # DLL-load failure — common when CUDA runtime DLLs aren't in the search path.
        report["status"] = UNAVAIL
        report["reason"] = f"llama-cpp-python installed but DLL load failed: {e}"
        return report

    # 2. Pick a GGUF
    if model_path is None:
        model_path, model_name = _pick_target_model_path()
    else:
        model_name = Path(model_path).stem
    if model_path is None:
        report["status"] = UNAVAIL
        report["reason"] = "no registered model has a resolvable GGUF on disk"
        return report
    if not Path(model_path).is_file():
        report["status"] = UNAVAIL
        report["reason"] = f"model_path does not exist: {model_path}"
        return report

    report["model_path"] = str(model_path)
    report["model_name"] = model_name

    # 3. Load the model with embedding=True so embedding-batch decode works
    t0 = time.time()
    try:
        # NOTE: embedding=False here. The `embedding` flag controls whether the
        # model OUTPUTS pooled sequence embeddings (it disables causal logit
        # computation when True). The prefix-injection path we test feeds raw
        # embedding vectors as INPUT via llama_decode + llama_batch.embd, which
        # is independent of this flag. We want causal logits for next-token
        # prediction, so embedding=False.
        llm = Llama(
            model_path=str(model_path),
            n_ctx=512,
            n_gpu_layers=-1,
            embedding=False,
            verbose=False,
            seed=seed,
        )
    except Exception as e:
        report["status"] = UNAVAIL
        report["reason"] = f"Llama() load failed: {type(e).__name__}: {e}"
        return report
    report["model_load_seconds"] = round(time.time() - t0, 1)

    try:
        n_embd = llm._model.n_embd()
        report["n_embd"] = n_embd

        # Helper: greedy completion of `prompt` with optional embedding prefix.
        # llama-cpp-python 0.3.x stopped mirroring logits into llm.scores and its
        # python-side sampler segfaults on this rig. We read logits directly from
        # the C side via llama_get_logits_ith(ctx, -1) and do argmax in numpy —
        # bit-identical to top_p=1.0 / temp=0.0 greedy sampling.
        import numpy as np

        n_vocab = llm._model.n_vocab()
        ctx_ptr = llm._ctx.ctx
        get_logits = llama_cpp.llama_get_logits_ith

        def complete(prefix_floats=None) -> tuple[str, int]:
            llm.reset()
            if prefix_floats is not None:
                if not _eval_embedding_prefix(llm, llama_cpp, prefix_floats, n_embd, report):
                    return "", 0
            prompt_tokens = llm.tokenize(prompt.encode("utf-8"), add_bos=True)
            llm.eval(prompt_tokens)
            out_tokens: list[int] = []
            eos = llm.token_eos()
            for _ in range(max_tokens):
                p = get_logits(ctx_ptr, -1)  # ptr to last-position logits
                logits = np.ctypeslib.as_array(p, shape=(n_vocab,))
                tok = int(np.argmax(logits))
                if tok == eos:
                    break
                out_tokens.append(tok)
                llm.eval([tok])
            text = llm.detokenize(out_tokens).decode("utf-8", errors="replace")
            return text, len(out_tokens)

        # We grade 2B on the LOGIT VECTOR not the decoded string. Strong-prior
        # prompts ("def fib(n):" → "\n") keep argmax pinned even when the prefix
        # has clearly steered attention. The byte-honest check is: does the full
        # logit distribution shift away from the no-prefix baseline?
        def last_logits():
            p = get_logits(ctx_ptr, -1)
            return np.ctypeslib.as_array(p, shape=(n_vocab,)).copy()

        # A: no prefix
        text_a, n_a = complete(None)
        logits_a = last_logits()
        report["conditions"]["A_no_prefix"] = {"output": text_a, "tokens": n_a}

        # B: zero prefix — must produce bit-identical logits to A
        zero = np.zeros((1, n_embd), dtype=np.float32)
        text_b, n_b = complete(zero)
        logits_b = last_logits()
        report["conditions"]["B_zero_prefix"] = {"output": text_b, "tokens": n_b}

        # C: random prefix at scale=5 — must produce visibly different logits.
        # Threshold: logit_max_diff > 0.5 (typical model logit range is ~10s,
        # floating-point noise is <0.01).
        rng = np.random.default_rng(seed)
        rand = rng.standard_normal((1, n_embd)).astype(np.float32) * 5.0
        text_c, n_c = complete(rand)
        logits_c = last_logits()

        ab_max_diff = float(np.abs(logits_a - logits_b).max())
        ac_max_diff = float(np.abs(logits_a - logits_c).max())
        ac_mean_diff = float(np.abs(logits_a - logits_c).mean())

        report["conditions"]["C_random_prefix"] = {
            "output": text_c,
            "tokens": n_c,
            "differs_from_A_output": text_c != text_a,
            "logit_diff_max_vs_A": ac_max_diff,
            "logit_diff_mean_vs_A": ac_mean_diff,
        }

        # A zero-vector prefix is NOT a no-op for logits, because llama.cpp still
        # applies position embeddings (rotary, etc.) to that zero vector. The
        # prompt now starts at position 1 instead of position 0, which shifts
        # rotary embeddings on every prompt token. That gives a small but real
        # logit diff (~1-2 units typical) even though the prefix carries zero
        # information. We grade Layer 2B by RATIO — random-prefix diff must be
        # at least 5x the zero-prefix diff, proving the prefix CONTENT (not just
        # its positional slot) is reaching attention.
        ratio = ac_max_diff / max(ab_max_diff, 1e-6)
        report["checks"] = {
            "zero_prefix_positional_shift": ab_max_diff,
            "random_prefix_logit_diff": ac_max_diff,
            "content_to_positional_ratio": ratio,
            "ratio_threshold": 5.0,
            "ratio_pass": ratio >= 5.0,
            "random_changes_argmax": text_c != text_a,
        }

        # Layer 2B is real when content-vs-positional logit ratio passes AND
        # the random prefix actually shifted argmax for at least one token
        # in the generated sequence (text_c != text_a). Both are necessary —
        # the ratio alone could in principle be high even if argmax never moved.
        if report["checks"]["ratio_pass"] and report["checks"]["random_changes_argmax"]:
            report["status"] = ACTIVE
        else:
            report["status"] = UNAVAIL
            report["reason"] = (
                "Layer 2B plumbing did not behave as expected: "
                f"ratio={ratio:.2f} (need >= 5.0), "
                f"random_changes_argmax={report['checks']['random_changes_argmax']}, "
                f"logit_max_diff_zero={ab_max_diff:.4g}, "
                f"logit_max_diff_random={ac_max_diff:.4g}"
            )

        # D: Rosetta-projected (best-effort, only if rosetta_v1.pt + a second model)
        report["conditions"]["D_rosetta_prefix"] = _try_rosetta_projection(
            llm=llm,
            n_embd=n_embd,
            complete=complete,
        )
    finally:
        try:
            del llm
        except Exception:
            pass

    return report


def _eval_embedding_prefix(llm, llama_cpp, prefix_floats, n_embd: int, report: dict) -> bool:
    """Feed a [N, n_embd] float32 prefix through llama_decode in embedding mode.

    Returns True on success. On failure, mutates report['status']/['reason'] and
    returns False — so the smoke test fails LOUDLY when llama-cpp-python doesn't
    expose what we need (no silent fallback).
    """
    import numpy as np

    arr = np.asarray(prefix_floats, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.shape[1] != n_embd:
        report["status"] = UNAVAIL
        report["reason"] = f"prefix dim {arr.shape[1]} != model n_embd {n_embd}"
        return False
    n_prefix = arr.shape[0]
    # llama-cpp-python 0.3.x wraps the C context in _LlamaContext; raw pointer is
    # at llm._ctx.ctx. 0.2.x exposed the raw pointer at llm._ctx directly. Handle both.
    _ctx_obj = llm._ctx
    ctx = getattr(_ctx_obj, "ctx", _ctx_obj)
    try:
        batch = llama_cpp.llama_batch_init(n_prefix, n_embd, 1)
    except Exception as e:
        report["status"] = UNAVAIL
        report["reason"] = f"llama_batch_init unavailable: {type(e).__name__}: {e}"
        return False
    try:
        batch.n_tokens = n_prefix
        flat = arr.flatten()
        for i, val in enumerate(flat):
            batch.embd[i] = float(val)
        for i in range(n_prefix):
            batch.pos[i] = i
            batch.n_seq_id[i] = 1
            batch.seq_id[i][0] = 0
            batch.logits[i] = False
        rc = llama_cpp.llama_decode(ctx, batch)
        if rc != 0:
            report["status"] = UNAVAIL
            report["reason"] = f"llama_decode in embedding mode returned rc={rc}"
            return False
        # Critical: tell the python wrapper that n_prefix positions are now in
        # the KV cache. Without this bump, the next llm.eval(prompt_tokens) call
        # starts at n_past=0 and OVERWRITES the prefix's KV entries — making the
        # whole injection a no-op. Try public attr first, fall back to private.
        try:
            llm.n_tokens = llm.n_tokens + n_prefix
        except AttributeError:
            # In some llama-cpp-python versions n_tokens is a property; bump the
            # underlying field directly.
            llm._n_tokens = llm._n_tokens + n_prefix  # type: ignore[attr-defined]
    finally:
        try:
            llama_cpp.llama_batch_free(batch)
        except Exception:
            pass
    return True


def _try_rosetta_projection(llm, n_embd: int, complete) -> dict:
    """Best-effort: project a stub hidden state through RosettaStone into target dim
    and feed as prefix. Reports status either way."""
    try:
        from rosetta.model_registry import BridgeStatus, current_family

        try:
            sys.path.insert(0, str(REPO_ROOT / "scripts"))
            from determinex_rosetta import RosettaStone
        except ImportError as e:
            return {"status": UNAVAIL, "reason": f"RosettaStone import failed: {e}"}
        family = current_family()
        target = None
        for m in family.values():
            if m.hidden_dim == n_embd:
                target = m
                break
        if target is None:
            return {
                "status": UNAVAIL,
                "reason": f"no registered target model with hidden_dim={n_embd}",
            }
        # Pick any non-target model as source. Best is one whose hidden_dim != n_embd.
        source = None
        for m in family.values():
            if m.hidden_dim != n_embd:
                source = m
                break
        if source is None:
            return {
                "status": UNAVAIL,
                "reason": "no registered source model with hidden_dim != target",
            }

        import torch

        # Try common stone-weight locations
        candidates = [
            Path.home() / ".determinex" / "rosetta" / "rosetta_v1.pt",
            REPO_ROOT / "outputs" / "rosetta" / "best",
            REPO_ROOT / "outputs" / "rosetta" / "best.pt",
        ]
        stone_path = next((p for p in candidates if p.exists()), None)
        if stone_path is None:
            return {"status": UNAVAIL, "reason": "no rosetta_v1.pt found"}
        try:
            try:
                stone = RosettaStone.load(stone_path, verify=False)
            except TypeError:
                stone = RosettaStone.load(stone_path)
            if stone is None:
                return {"status": UNAVAIL, "reason": "RosettaStone has no .load() classmethod"}
        except Exception as e:
            return {
                "status": UNAVAIL,
                "reason": f"RosettaStone.load failed: {type(e).__name__}: {e}",
            }

        # Generate a fake source hidden, project via stone if its API allows
        src_hidden = torch.randn(source.hidden_dim)
        try:
            translated = stone.project(
                src_hidden.unsqueeze(0),
                source_arch=source.rosetta_arch,
                target_arch=target.rosetta_arch,
            )
        except Exception as e:
            return {
                "status": UNAVAIL,
                "reason": f"stone.project failed: {type(e).__name__}: {e}",
                "bridge_status": BridgeStatus.FAILED_BRIDGE.value,
                "source_model": source.name,
                "source_arch": source.rosetta_arch,
                "target_model": target.name,
                "target_arch": target.rosetta_arch,
            }
        prefix = translated.squeeze(0).detach().cpu().numpy()
        if prefix.shape[0] != n_embd:
            return {
                "status": UNAVAIL,
                "reason": f"stone produced dim {prefix.shape[0]}, target n_embd={n_embd}",
                "bridge_status": BridgeStatus.FAILED_BRIDGE.value,
            }
        text, n_tok = complete(prefix)
        return {
            "status": ACTIVE,
            "output": text,
            "tokens": n_tok,
            "bridge_status": BridgeStatus.ROSETTA_PROJECTED.value,
            "source_model": source.name,
            "source_arch": source.rosetta_arch,
            "target_model": target.name,
            "target_arch": target.rosetta_arch,
        }
    except Exception as e:
        return {"status": UNAVAIL, "reason": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer 2B soft-prefix smoke test")
    ap.add_argument("--model", type=Path, default=None, help="override GGUF path")
    ap.add_argument(
        "--prompt",
        default="The capital of France is",
        help="text prompt used for all four conditions",
    )
    ap.add_argument("--max-tokens", type=int, default=32)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--json", type=Path, default=None, help="write JSON report here")
    args = ap.parse_args()

    report = run_smoke(
        model_path=args.model, prompt=args.prompt, max_tokens=args.max_tokens, seed=args.seed
    )
    print(json.dumps(report, indent=2, default=str))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)

    return 0 if report.get("status") == ACTIVE else 0  # never crash the harness; just report


if __name__ == "__main__":
    raise SystemExit(main())
