"""
rosetta_text_bridge.py — Ollama-Compatible Rosetta Soft Prompt
==============================================================
The pragmatic path: instead of injecting raw float tensors into llama-cpp,
project the Rosetta hidden state back to the nearest tokens in the vocabulary
and prepend those tokens as a real text prompt.

Lossy? Yes. Works with every inference backend including Ollama? Also yes.

Pipeline:
  source_model hidden state [seq, d_src]
    → Rosetta encoder → rosetta_space [seq, 4096]
    → Rosetta decoder → target_space [seq, d_tgt]
    → token_approximator: cosine-nearest-neighbour over embedding table
    → k token strings  (the "text approximation")
    → "<|rosetta|> tok1 tok2 … tokK\n" prepended to real prompt
    → standard ollama.chat() call — no custom endpoints, no llama-cpp

No forks. No PRs. Works today.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import torch

log = logging.getLogger("rosetta_bridge")

# ── Ollama REST client (stdlib only, no extra deps) ───────────────────────────
import json as _json
import urllib.request


def _ollama_generate(
    model: str,
    prompt: str,
    host: str = "http://localhost:11434",
    timeout: int = 120,
    options: dict | None = None,
) -> str:
    """Thin wrapper around POST /api/generate — no third-party lib required."""
    payload = _json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            **({"options": options} if options else {}),
        }
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = _json.loads(resp.read())
    return data.get("response", "")


# ── Embedding table loader ────────────────────────────────────────────────────

_EMB_CACHE: dict[str, torch.Tensor] = {}


def _get_embedding_table(
    model_name: str, host: str = "http://localhost:11434"
) -> torch.Tensor | None:
    """
    Pull the embedding table from Ollama via /api/embed on synthetic vocab probes.

    Sends all probes in ONE batched request (or chunked batches of 50 on failure)
    so the total cost is 1 Ollama call, not 250 sequential ones.
    Table is normalised and cached to disk after first build.
    """
    cache_key = f"{host}:{model_name}"
    if cache_key in _EMB_CACHE:
        return _EMB_CACHE[cache_key]

    cache_path = (
        Path.home()
        / ".determinex"
        / "rosetta"
        / "emb_tables"
        / f"{hashlib.md5(cache_key.encode()).hexdigest()}.pt"
    )
    if cache_path.exists():
        log.info("[bridge] Loading embedding table from disk cache: %s", cache_path.name)
        _EMB_CACHE[cache_key] = torch.load(str(cache_path), map_location="cpu", weights_only=True)
        return _EMB_CACHE[cache_key]

    log.info("[bridge] Building embedding table for %s (single batched call)…", model_name)

    # Probe token set — deduped, order preserved
    probes: list[str] = list(
        dict.fromkeys(
            [chr(i) for i in range(32, 127)]
            + [f" {chr(i)}" for i in range(65, 91)]
            + [f" {chr(i)}" for i in range(97, 123)]
            + [
                " def",
                " class",
                " return",
                " import",
                " if",
                " else",
                " for",
                " while",
                " fn",
                " let",
                " mut",
                " pub",
                " use",
                " struct",
                " impl",
                " trait",
                " func",
                " var",
                " type",
                " interface",
                " package",
                " const",
                " self",
                " None",
                " True",
                " False",
                " async",
                " await",
                " int",
                " str",
                " bool",
                " float",
                " list",
                " dict",
                "0",
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
                "7",
                "8",
                "9",
                "(",
                ")",
                "{",
                "}",
                "[",
                "]",
                ":",
                ",",
                ".",
                "=",
                "+",
                "-",
                "*",
                "/",
                "//",
                "->",
                "=>",
                "::",
                "!=",
                "==",
                "<=",
                ">=",
                "&&",
                "||",
                "\n",
                "\t",
                "    ",
            ]
        )
    )

    def _embed_batch(batch: list[str], timeout: int = 30) -> list[list[float]]:
        """POST a batch to /api/embed, return list of embedding vectors."""
        payload = _json.dumps({"model": model_name, "input": batch}).encode()
        req = urllib.request.Request(
            f"{host}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read())
        embs = data.get("embeddings") or data.get("embedding") or []
        # Normalise shape: [[vec], [vec], …] or [vec] (single input)
        if embs and not isinstance(embs[0], list):
            embs = [embs]
        return embs

    vecs: list[list[float]] = []
    tokens_list: list[str] = []

    # ── Try one big batch first (fastest) ────────────────────────────────────
    try:
        log.info("[bridge] Sending %d probes in one batch…", len(probes))
        all_vecs = _embed_batch(probes, timeout=60)
        if len(all_vecs) == len(probes):
            vecs = all_vecs
            tokens_list = probes
            log.info(
                "[bridge] Batch embed OK — %d vectors × %d dims",
                len(vecs),
                len(vecs[0]) if vecs else 0,
            )
        else:
            log.warning(
                "[bridge] Batch returned %d / %d — falling through to chunked",
                len(all_vecs),
                len(probes),
            )
    except Exception as e:
        log.warning("[bridge] Single-batch embed failed (%s) — chunking into 50-token batches", e)

    # ── Chunked fallback (50 at a time, 30s each) ─────────────────────────────
    if not vecs:
        CHUNK = 50
        for i in range(0, len(probes), CHUNK):
            chunk = probes[i : i + CHUNK]
            try:
                chunk_vecs = _embed_batch(chunk, timeout=30)
                for tok, vec in zip(chunk, chunk_vecs):
                    vecs.append(vec)
                    tokens_list.append(tok)
                log.info("[bridge]   chunk %d–%d OK", i, i + len(chunk))
            except Exception as exc:
                log.warning("[bridge]   chunk %d–%d failed: %s — skipping", i, i + len(chunk), exc)

    if not vecs:
        log.warning("[bridge] Could not build embedding table — Ollama embed API unavailable")
        return None

    table = torch.tensor(vecs, dtype=torch.float32)  # [N, d_embed]
    table = torch.nn.functional.normalize(table, dim=-1)  # L2-normalise for cosine via dot

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(table, str(cache_path))
    cache_path.with_suffix(".tokens.json").write_text(_json.dumps(tokens_list))

    _EMB_CACHE[cache_key] = table
    _EMB_CACHE[cache_key + ":tokens"] = tokens_list  # type: ignore[assignment]
    log.info(
        "[bridge] Embedding table cached: %d tokens × %d dims", len(tokens_list), table.shape[-1]
    )
    return table


def _load_token_list(model_name: str, host: str = "http://localhost:11434") -> list[str]:
    cache_key = f"{host}:{model_name}:tokens"
    if cache_key in _EMB_CACHE:
        return _EMB_CACHE[cache_key]  # type: ignore[return-value]
    cache_path = (
        Path.home()
        / ".determinex"
        / "rosetta"
        / "emb_tables"
        / f"{hashlib.md5(f'{host}:{model_name}'.encode()).hexdigest()}.tokens.json"
    )
    if cache_path.exists():
        tokens = _json.loads(cache_path.read_text())
        _EMB_CACHE[cache_key] = tokens  # type: ignore[assignment]
        return tokens
    return []


# ── Core approximation ────────────────────────────────────────────────────────


class RosettaTextBridge:
    """
    Converts a Rosetta-projected hidden state into a text prefix that any
    Ollama-served model can consume as a standard prompt string.

    Usage:
        bridge = RosettaTextBridge(model_name="determinex-engineer", stone=stone)
        prompt = bridge.build_soft_prompt(
            source_h=leviathan_hidden,   # [seq, 2048]
            source_arch="deepseek2",
            target_arch="qwen2",
            user_prompt="Implement the merge function…",
            k=8,
        )
        response = bridge.generate(prompt)
    """

    # Sentinel that the receiving model knows to treat as Rosetta context
    ROSETTA_TAG = "<|rosetta_ctx|>"
    ROSETTA_END = "<|/rosetta_ctx|>"

    def __init__(
        self,
        model_name: str,
        stone,  # RosettaStone instance
        host: str = "http://localhost:11434",
        ollama_options: dict | None = None,
    ):
        self.model_name = model_name
        self.stone = stone
        self.host = host
        self.ollama_options = ollama_options or {"temperature": 0, "num_ctx": 4096}
        self._table: torch.Tensor | None = None
        self._tokens: list[str] = []

    def _ensure_table(self) -> bool:
        if self._table is not None:
            return True
        self._table = _get_embedding_table(self.model_name, self.host)
        self._tokens = _load_token_list(self.model_name, self.host)
        return self._table is not None

    # ── Approximation core ────────────────────────────────────────────────

    def project_to_rosetta(
        self,
        source_h: torch.Tensor,  # [seq, d_src]
        source_arch: str,
        target_arch: str,
    ) -> torch.Tensor:
        """Run through the two Rosetta MLPs: src → rosetta → tgt."""
        if source_h.dim() == 1:
            source_h = source_h.unsqueeze(0)
        if source_h.dtype == torch.bfloat16:
            source_h = source_h.float()
        return self.stone.project(source_h, source_arch, target_arch)

    def hidden_to_tokens(
        self,
        projected: torch.Tensor,  # [seq, d_tgt]
        k: int = 8,
    ) -> list[str]:
        """
        Find the k most cosine-similar vocabulary entries to the mean-pooled
        projected state.  Returns token strings in similarity order.

        If the embedding table dimensions don't match (model uses a different
        embed dim than the probe queries), we project with a simple PCA-like
        whitening to align dims.  This is lossy but keeps the bridge alive.
        """
        if not self._ensure_table() or not self._tokens:
            log.warning("[bridge] No embedding table — returning empty token list")
            return []

        # Mean-pool over sequence dim → [d_tgt]
        h_mean = projected.mean(dim=0).detach().cpu().float()

        table = self._table  # [N, d_embed]
        d_h, d_t = h_mean.shape[0], table.shape[1]

        if d_h != d_t:
            # Dim mismatch: linear interpolation / truncation to align
            if d_h > d_t:
                # chunk-average down
                factor = d_h // d_t
                h_mean = h_mean[: factor * d_t].reshape(d_t, factor).mean(dim=-1)
            else:
                # zero-pad
                pad = torch.zeros(d_t - d_h)
                h_mean = torch.cat([h_mean, pad])

        h_norm = torch.nn.functional.normalize(h_mean.unsqueeze(0), dim=-1)  # [1, d_t]
        sims = (table @ h_norm.T).squeeze(-1)  # [N]
        topk = torch.topk(sims, min(k, len(self._tokens)))

        return [self._tokens[i] for i in topk.indices.tolist()]

    def build_soft_prompt(
        self,
        source_h: torch.Tensor,
        source_arch: str,
        target_arch: str,
        user_prompt: str,
        k: int = 8,
    ) -> str:
        """
        Full pipeline: hidden state → Rosetta projection → nearest tokens →
        tagged prefix string prepended to user_prompt.

        The returned string is a standard text prompt — pass directly to any
        Ollama /api/generate call.

        Format:
            <|rosetta_ctx|>
            [LATENT CONTEXT — projected from {source_arch}]
            tok1 tok2 tok3 tok4 tok5 tok6 tok7 tok8
            <|/rosetta_ctx|>

            {user_prompt}
        """
        t0 = time.perf_counter()
        projected = self.project_to_rosetta(source_h, source_arch, target_arch)
        approx_tokens = self.hidden_to_tokens(projected, k=k)
        t1 = time.perf_counter()

        if approx_tokens:
            token_str = " ".join(approx_tokens)
            prefix = (
                f"{self.ROSETTA_TAG}\n"
                f"[LATENT CONTEXT — projected from {source_arch}]\n"
                f"{token_str}\n"
                f"{self.ROSETTA_END}\n\n"
            )
            log.info(
                "[bridge] Soft prompt built in %.1fms — %d tokens: %r",
                (t1 - t0) * 1000,
                len(approx_tokens),
                token_str[:60],
            )
        else:
            prefix = ""
            log.warning("[bridge] No approximation tokens — falling back to bare prompt")

        return prefix + user_prompt

    def generate(
        self,
        prompt: str,
        timeout: int = 120,
    ) -> str:
        """Send the assembled prompt to Ollama and return the response string."""
        return _ollama_generate(
            model=self.model_name,
            prompt=prompt,
            host=self.host,
            timeout=timeout,
            options=self.ollama_options,
        )

    def generate_with_rosetta(
        self,
        source_h: torch.Tensor,
        source_arch: str,
        target_arch: str,
        user_prompt: str,
        k: int = 8,
        timeout: int = 120,
    ) -> str:
        """
        End-to-end convenience method:
            hidden_state + user_prompt → Ollama response string.

        Equivalent to:
            prompt = bridge.build_soft_prompt(...)
            return bridge.generate(prompt)
        """
        prompt = self.build_soft_prompt(source_h, source_arch, target_arch, user_prompt, k=k)
        return self.generate(prompt, timeout=timeout)


# ── Parallel broadcast (Oracle → all roles) ───────────────────────────────────


def broadcast_to_roles(
    source_h: torch.Tensor,
    source_arch: str,
    stone,  # RosettaStone
    roles: dict[str, RosettaTextBridge],  # {role_name: bridge}
    user_prompts: dict[str, str],  # {role_name: prompt}
    k: int = 8,
) -> dict[str, str]:
    """
    Oracle hidden state → simultaneously build soft prompts for all active roles.
    Each role has its own model and RosettaTextBridge.

    Returns {role_name: assembled_prompt} — callers pass these to Ollama.
    This is the Hive Mind broadcast topology without needing any custom endpoints.
    """
    results: dict[str, str] = {}
    for role, bridge in roles.items():
        prompt = user_prompts.get(role, "")
        if not prompt:
            continue
        try:
            target_arch = _infer_arch_from_model(bridge.model_name)
            results[role] = bridge.build_soft_prompt(
                source_h=source_h,
                source_arch=source_arch,
                target_arch=target_arch,
                user_prompt=prompt,
                k=k,
            )
        except Exception as exc:
            log.warning(
                "[bridge] Broadcast failed for role '%s': %s — using bare prompt", role, exc
            )
            results[role] = prompt
    return results


def _infer_arch_from_model(model_name: str) -> str:
    """Best-effort arch guess from Ollama model name.

    Registry FIRST — if the model is known to rosetta.model_registry, return
    its SIZE-SPECIFIC arch (e.g. qwen2_1b5, qwen2_7b). Only fall back to the
    bare family label when nothing in the registry matches. Bare "qwen2" is
    dangerous (qwen2 covers 4 different hidden_dims) and is kept only for
    legacy code paths; new code should resolve through model_registry directly.
    """
    try:
        from rosetta.model_registry import resolve_model

        m = resolve_model(model_name)
        if m is not None:
            return m.rosetta_arch  # SIZE-SPECIFIC, e.g. qwen2_1b5
    except ImportError:
        pass

    name = model_name.lower()
    if "mistral" in name:
        return "mistral_7b"  # promoted from "mistral"
    if "qwen" in name:
        return "qwen2"  # legacy — caller should validate dim
    if "phi" in name:
        return "phi3"
    if "deepseek" in name:
        return "deepseek2"
    return "llama"  # safe default


# ── Warm-up helper ────────────────────────────────────────────────────────────


def warmup_bridge(
    model_name: str,
    host: str = "http://localhost:11434",
) -> bool:
    """
    Pre-build and cache the embedding approximation table for model_name.
    Call once at startup so the first generate_with_rosetta() call is fast.
    Returns True if table was built successfully.
    """
    log.info("[bridge] Warming up embedding table for %s…", model_name)
    table = _get_embedding_table(model_name, host)
    return table is not None


# ── Standalone smoke test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="RosettaTextBridge smoke test")
    ap.add_argument("--model", default="determinex-engineer", help="Ollama model name")
    ap.add_argument("--source-arch", default="deepseek2", help="Source hidden state arch")
    ap.add_argument("--target-arch", default="qwen2", help="Target arch (must match --model)")
    ap.add_argument("--k", type=int, default=8, help="Number of approximation tokens")
    ap.add_argument(
        "--warmup-only", action="store_true", help="Just build the embed table, don't generate"
    )
    ap.add_argument("--host", default="http://localhost:11434")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # ── 1. Load Rosetta Stone ─────────────────────────────────────────────
    from determinex_rosetta import load_latest_rosetta

    stone = load_latest_rosetta(verify=False)
    if stone is None:
        print("ERROR: no rosetta_v*.pt found in ~/.determinex/rosetta/")
        sys.exit(1)
    print(f"Loaded: {stone}")

    # ── 2. Build bridge ───────────────────────────────────────────────────
    bridge = RosettaTextBridge(model_name=args.model, stone=stone, host=args.host)

    if args.warmup_only:
        ok = warmup_bridge(args.model, args.host)
        print("Warmup:", "OK" if ok else "FAILED — Ollama embed API not available")
        sys.exit(0 if ok else 1)

    # ── 3. Synthetic source hidden state (random, just tests the pipeline) ─
    src_dim = stone.dims.get(args.source_arch, 2048)
    fake_h = torch.randn(4, src_dim)  # [4 tokens, src_dim]

    print(f"\nSource arch : {args.source_arch}  hidden [{fake_h.shape[0]}, {src_dim}]")
    print(f"Target arch : {args.target_arch}")
    print(f"Approximation k: {args.k}")

    prompt = bridge.build_soft_prompt(
        source_h=fake_h,
        source_arch=args.source_arch,
        target_arch=args.target_arch,
        user_prompt="Write a Rust function that returns the sum of a slice of i32.",
        k=args.k,
    )

    print("\n" + "-" * 60)
    print("ASSEMBLED PROMPT:")
    print(prompt)
    print("-" * 60 + "\n")

    print("Sending to Ollama…")
    response = bridge.generate(prompt)
    print("RESPONSE:")
    print(response)
