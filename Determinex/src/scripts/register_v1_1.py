"""
register_v1_1.py — Download GGUFs from RunPod and register C1/C3/C7 v1.1 in Ollama
=====================================================================================
Run after pod_training_launch.sh completes, or manually:
  python scripts/register_v1_1.py [--gguf-dir ${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions]
"""

from __future__ import annotations

import argparse
import json
import os as _os
import subprocess
import sys
from pathlib import Path

# The rename inserted a *shell* expansion into plain Python strings; Python does
# not expand those, so these silently became a literal directory named
# "${DETERMINEX_MODELS_DIR:-~/determinex-models}". Resolve it the way sh would.
_MODELS_DIR = _os.path.expanduser(_os.environ.get("DETERMINEX_MODELS_DIR", "~/determinex-models"))

DETERMINEX_DIR = Path(__file__).parent.parent
REGISTRY = DETERMINEX_DIR / "determinex_model_registry.json"

_GGUF_MAP = {
    "engineer": {"c_name": "C1", "full_name": "Determinex-1-Tiny", "tag": "determinex-1-tiny-v1.1"},
    "observer": {
        "c_name": "C3",
        "full_name": "Determinex-3-Medium",
        "tag": "determinex-3-medium-v1.1",
    },
    "sentinel": {
        "c_name": "C7",
        "full_name": "Determinex-7-Large",
        "tag": "determinex-7-large-v1.1",
    },
}

_SYSTEM_PROMPTS = {
    "engineer": (
        "You are Determinex-1-Tiny (C1) v1.1, a 1.5B parameter code intelligence model by "
        "Determinex.Trained on 20K compiler-verified examples with 7 task-vector "
        "LoRA adapters. You specialize in fast, precise code generation and patch application. "
        "You communicate in Semantic DSL and produce compiler-verified patches."
    ),
    "observer": (
        "You are Determinex-3-Medium (C3) v1.1, a 3B parameter code intelligence model by "
        "Determinex.Trained on 20K compiler-verified examples. You specialize in "
        "code review, error diagnosis, and Monitor-role adjudication in the Determinex Hive Mind."
    ),
    "sentinel": (
        "You are Determinex-7-Large (C7) v1.1, a 7B parameter code intelligence model by "
        "Determinex.Trained on 20K compiler-verified examples. You specialize in "
        "architectural planning, DAG decomposition, and Architect/Oracle roles in the Determinex Hive Mind."
    ),
}

_PARAMS = {
    "engineer": "PARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER top_p 0.9\nPARAMETER stop <|im_end|>",
    "observer": "PARAMETER num_ctx 4096\nPARAMETER temperature 0.2\nPARAMETER top_p 0.9\nPARAMETER stop <|im_end|>",
    "sentinel": "PARAMETER num_thread 8\nPARAMETER num_ctx 4096\nPARAMETER temperature 0.1\nPARAMETER num_gpu 19\nPARAMETER stop <|im_end|>",
}


def find_gguf(gguf_dir: Path, model: str) -> Path | None:
    for pattern in [f"*{model}*v1.1*.gguf", f"*{model}*.gguf"]:
        hits = (
            sorted((gguf_dir / model / "v1.1").glob(pattern))
            if (gguf_dir / model / "v1.1").exists()
            else []
        )
        if not hits:
            hits = sorted(gguf_dir.rglob(f"*{model}*.gguf"))
        if hits:
            return hits[-1]  # newest
    return None


def register(model: str, gguf_path: Path, dry_run: bool = False) -> bool:
    info = _GGUF_MAP[model]
    tag = info["tag"]
    mf_path = DETERMINEX_DIR / "modelfiles" / f"Modelfile.{info['c_name'].lower()}_v1_1"

    modelfile = (
        f"FROM {gguf_path.as_posix()}\n\n"
        f'SYSTEM """{_SYSTEM_PROMPTS[model]}"""\n\n'
        f"{_PARAMS[model]}\n"
    )

    if dry_run:
        print(f"[DRY-RUN] Would register {tag} from {gguf_path}")
        print(modelfile)
        return True

    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(modelfile)
    print(f"[{info['c_name']}] Creating {tag} from {gguf_path.name}...")

    result = subprocess.run(
        ["ollama", "create", tag, "-f", str(mf_path)], capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"[{info['c_name']}] {tag} registered OK")
        return True
    else:
        print(f"[{info['c_name']}] FAILED: {result.stderr.strip()}")
        return False


def update_registry(results: dict):
    if not REGISTRY.exists():
        return
    reg = json.loads(REGISTRY.read_text())
    for model, info in _GGUF_MAP.items():
        c = info["c_name"]
        if c in reg.get("models", {}) and results.get(model):
            reg["models"][c]["ollama_tag_v1_1"] = info["tag"]
    REGISTRY.write_text(json.dumps(reg, indent=2))
    print(f"Registry updated: {REGISTRY}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gguf-dir", default="" + _MODELS_DIR + "/versions")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--model", choices=["engineer", "observer", "sentinel", "all"], default="all"
    )
    args = parser.parse_args()

    gguf_dir = Path(args.gguf_dir)
    targets = list(_GGUF_MAP.keys()) if args.model == "all" else [args.model]

    results = {}
    for model in targets:
        gguf = find_gguf(gguf_dir, model)
        if not gguf:
            print(f"[{model}] No GGUF found in {gguf_dir} — skipping")
            results[model] = False
            continue
        results[model] = register(model, gguf, dry_run=args.dry_run)

    if not args.dry_run:
        update_registry(results)

    ok = sum(v for v in results.values())
    tot = len(results)
    print(f"\nRegistered {ok}/{tot} models")
    print("\nNext steps:")
    print("  python scripts/determinex_benchmark_5run.py --runs 5 --backend ollama")
    print("  python scripts/determinex_benchmark_5run.py --runs 5 --instances 50 --backend ollama")

    return 0 if ok == tot else 1


if __name__ == "__main__":
    sys.exit(main())
