"""
scripts/determinex_swebench_run.py — Official SWE-bench Evaluation Runner
=======================================================================
Connects DeterminexSWEAgent to the official swebench evaluation harness.

Outputs predictions.jsonl compatible with swebench's run_evaluation tool.
Requires Docker (for swebench sandbox) and Ollama (for Determinex models).

Usage — SWE-bench Lite (300 instances, recommended first run):
    python scripts/determinex_swebench_run.py --split lite --instances 10
    python scripts/determinex_swebench_run.py --split lite --all

Usage — SWE-bench Verified (500 instances, leaderboard submission):
    python scripts/determinex_swebench_run.py --split verified --all

Usage — SWE-bench Full (2294 instances):
    python scripts/determinex_swebench_run.py --split full --all

The runner outputs:
  logs/swebench/<run_id>/predictions.jsonl          ← patches to apply
  logs/swebench/<run_id>/results.json               ← % resolved after eval
  logs/swebench/<run_id>/run.log                    ← full interleaved trace (all workers)
  logs/swebench/<run_id>/instance_logs/{iid}.log    ← per-instance trace with start/end timing
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

# Explicit bool prevents pyrefly from constant-folding platform branches as unreachable
_ON_WINDOWS: bool = os.name == "nt"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent
_LOGS = _ROOT / "logs" / "swebench"
_SCRIPTS = Path(__file__).resolve().parent

sys.path.insert(0, str(_SCRIPTS))

logging.basicConfig(
    level=logging.INFO,
    format="[RUN] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("swe_run")


class _InstanceLogHandler(logging.FileHandler):
    """FileHandler that only emits records originating from the owning thread.

    Attach one to the root logger per worker so parallel workers write to
    separate instance_logs/{iid}.log files without interleaving.
    """

    def __init__(self, path: Path, thread_id: int) -> None:
        super().__init__(str(path), mode="a", encoding="utf-8", delay=False)
        self._thread_id = thread_id
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        if threading.current_thread().ident == self._thread_id:
            super().emit(record)


from swe_run.dataset import SPLIT_DATASETS, load_dataset_split
from swe_run.repo import clone_repo_at_commit


def run_agent_on_instance(instance: dict, repo_path: Path) -> str:
    """Run DeterminexSWEAgent on one instance. Returns unified patch string."""
    from determinex_swebench_agent import DeterminexSWEAgent

    agent = DeterminexSWEAgent()
    try:
        patch = agent.solve(instance, repo_path=repo_path)
        return patch or ""
    except Exception as e:
        log.error("Agent failed on %s: %s", instance.get("instance_id"), e)
        return ""


def write_predictions(predictions: list[dict], out_path: Path) -> None:
    """Write predictions.jsonl in SWE-bench format."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for pred in predictions:
            f.write(json.dumps(pred) + "\n")
    log.info("Predictions written → %s  (%d instances)", out_path, len(predictions))


def _normalized_patch_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def load_flywheel_exact_patches(path: Path) -> dict[str, str]:
    """Load exact instance_id -> patch pairs from the existing flywheel JSONL."""
    exact: dict[str, str] = {}
    if not path.is_file():
        return exact
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            instance_id = row.get("instance_id")
            if not isinstance(instance_id, str) or not instance_id:
                continue
            patch = _normalized_patch_text(row.get("output") or row.get("patch") or "")
            if patch:
                exact[instance_id] = patch
    return exact


def build_replay_prediction(
    instance: dict,
    *,
    run_id: str,
    prediction_source: str,
    flywheel_exact: dict[str, str] | None = None,
) -> dict | None:
    """Build a deterministic replay prediction, or None for the normal agent path."""
    if prediction_source == "agent":
        return None
    iid = instance["instance_id"]
    if prediction_source == "dataset-gold":
        patch = _normalized_patch_text(instance.get("patch") or "")
    elif prediction_source == "flywheel-exact":
        patch = _normalized_patch_text((flywheel_exact or {}).get(iid, ""))
    else:
        raise ValueError(f"unknown prediction source: {prediction_source}")
    return {"instance_id": iid, "model_patch": patch, "model_name_or_path": run_id}


def _predictions_path_for_wsl(p: Path) -> str:
    """Convert a Windows path to its WSL /mnt/ equivalent."""
    drive = p.drive.rstrip(":")  # 'C:' → 'C'
    rest = p.as_posix()[len(p.drive) :]  # '/Dev/Determinex/...'
    return f"/mnt/{drive.lower()}{rest}"


def run_official_evaluation(predictions_path: Path, split: str, run_id: str) -> dict:
    """
    Run the official swebench evaluation harness against our predictions.
    Requires Docker.

    On Windows: swebench.harness imports the Unix-only `resource` module at startup
    and crashes immediately.  We route through WSL2 instead — Docker Desktop is
    accessible from WSL and `resource` is available there.
    """
    log.info("Running official swebench evaluation (requires Docker)...")
    dataset_id = SPLIT_DATASETS[split]

    if _ON_WINDOWS:
        wsl_predictions = _predictions_path_for_wsl(predictions_path)
        log.info("Windows detected — routing evaluation through WSL2")
        log.info("WSL predictions path: %s", wsl_predictions)

        subprocess.run(
            ["wsl", "-d", "Ubuntu", "pip", "install", "swebench", "--quiet"],
            capture_output=True,
            timeout=120,
        )

        cmd = [
            "wsl",
            "-d",
            "Ubuntu",
            "python3",
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            dataset_id,
            "--split",
            "test",
            "--predictions_path",
            wsl_predictions,
            "--max_workers",
            "4",
            "--run_id",
            run_id,
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            dataset_id,
            "--split",
            "test",
            "--predictions_path",
            str(predictions_path),
            "--max_workers",
            "4",
            "--run_id",
            run_id,
        ]

    log.info("Evaluation command: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hours max
            cwd=_ROOT,
        )
        log.info("Evaluation stdout:\n%s", result.stdout[-3000:])
        if result.returncode != 0:
            log.error("Evaluation stderr:\n%s", result.stderr[-1000:])
            if _ON_WINDOWS and "wsl" in cmd[0] and result.returncode == 1 and not result.stdout:
                log.error("WSL may not be installed or swebench not available in WSL.")
                log.error("Manual fallback — run in WSL terminal:")
                log.error(
                    "  python3 -m swebench.harness.run_evaluation "
                    "--dataset_name %s --split test --predictions_path %s "
                    "--max_workers 4 --run_id %s",
                    dataset_id,
                    _predictions_path_for_wsl(predictions_path),
                    run_id,
                )
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        log.error("Evaluation timed out after 2 hours")
        return {"error": "timeout"}


def main():
    parser = argparse.ArgumentParser(description="Determinex SWE-bench Runner")
    parser.add_argument(
        "--split",
        choices=["lite", "verified", "full", "swelancer", "multilingual", "multiswe"],
        default="lite",
    )
    parser.add_argument(
        "--instances", type=int, default=None, help="Number of instances to run (default: all)"
    )
    parser.add_argument(
        "--instance-ids",
        type=str,
        default=None,
        help="Comma-separated list of specific instance IDs to run",
    )
    parser.add_argument("--all", action="store_true", help="Run all instances in the split")
    parser.add_argument("--run-id", default=None, help="Run identifier (default: auto-generated)")
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Generate predictions only, skip official harness eval (useful for smoke tests)",
    )
    parser.add_argument(
        "--repos-dir",
        type=Path,
        default=None,
        help="Pre-cloned repos dir. Skips re-clone if repo already exists there.",
    )
    parser.add_argument(
        "--builder-model",
        default="determinex-engineer-v11-dsl",
        help="Ollama model tag for Builder role (overridden by --config)",
    )
    parser.add_argument(
        "--observer-model",
        default="determinex-observer-v6-dsl",
        help="Ollama model tag for Observer/Architect role (overridden by --config)",
    )
    parser.add_argument(
        "--local-builder-14b",
        action="store_true",
        help="Override Builder to qwen2.5-coder:14b-instruct-q4_K_M (stronger local model than the 7b default in --config a). Implies local-only.",
    )
    parser.add_argument(
        "--local-builder-32b",
        action="store_true",
        help="Override Builder to qwen2.5-coder:32b-instruct-q4_K_M (max local quality, slower; needs >=24GB RAM headroom).",
    )
    parser.add_argument(
        "--config",
        choices=["a", "b", "c", "d", "e"],
        default=None,
        help=(
            "Ablation config: "
            "a=Local-Purity (7B Ollama all roles), "
            "b=Frontier-Parity (DeepSeek V3 all roles), "
            "c=Frontier-Hybrid (DeepSeek Architect + 7B vLLM Builder), "
            "d=Nuclear-Hybrid (Claude Sonnet Architect + DeepSeek Builder), "
            "e=RegionControl (DeepSeek V3, no cloak, forced region mode — isolates region-mode benefit)"
        ),
    )
    parser.add_argument(
        "--cloak",
        action="store_true",
        help="Enable Project Cloak: obfuscate all identifiers before AI inference",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run N instances concurrently (default: 1 sequential)",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle instance order before running (good for diverse smoke tests)",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=42,
        help="RNG seed for --shuffle (default: 42, reproducible)",
    )
    parser.add_argument(
        "--lang",
        default=None,
        choices=[
            "java",
            "typescript",
            "javascript",
            "go",
            "rust",
            "c",
            "cpp",
            "python",
            "ruby",
            "php",
        ],
        help="Filter to a single language (multiswe/multilingual splits only)",
    )
    parser.add_argument(
        "--prediction-source",
        choices=["agent", "dataset-gold", "flywheel-exact"],
        default="agent",
        help=(
            "Prediction source. 'agent' is normal Determinex solving. "
            "'dataset-gold' is an answer-key diagnostic and is not a clean benchmark. "
            "'flywheel-exact' copies only exact instance_id matches from the existing flywheel."
        ),
    )
    parser.add_argument(
        "--flywheel-path",
        type=Path,
        default=Path(
            os.getenv(
                "DETERMINEX_FLYWHEEL_PATH",
                str(_ROOT / "auto_curriculum.jsonl"),
            )
        ),
        help="Existing flywheel JSONL used by --prediction-source flywheel-exact.",
    )
    # ── Scientific run identity ────────────────────────────────────────────────
    parser.add_argument(
        "--name",
        default=None,
        help=(
            "Short slug identifying this run's purpose — included in the directory "
            "name and manifest. Required for ablation runs (>= 100 instances). "
            "Examples: post-treesitter-fix, baseline-cloaked, gate-shakeout-py"
        ),
    )
    parser.add_argument(
        "--note",
        default=None,
        help=(
            "One-sentence hypothesis or description of what this run is measuring. "
            "Written verbatim to manifest.json. Non-optional for publication runs."
        ),
    )
    parser.add_argument(
        "--run-type",
        default=None,
        choices=["debug", "smoke", "shakeout", "ablation", "publication"],
        help=(
            "Override auto-detected run type. Auto-detection rules: "
            "debug (<=5 instances), smoke (6-20), shakeout (--lang set), "
            "ablation (21-299), publication (300+ all instances)"
        ),
    )
    args = parser.parse_args()

    # ── Config presets (ablation study) ──────────────────────────────────────
    config_label = "custom"
    if args.config == "a":
        config_label = "A-LocalPurity"
        os.environ["DETERMINEX_INFERENCE_BACKEND"] = "ollama"
        os.environ["DETERMINEX_BUILDER_MODEL"] = "qwen2.5-coder:7b-instruct"
        os.environ["DETERMINEX_OBSERVER_MODEL"] = "qwen2.5-coder:3b-instruct"
        log.info("Config A — Local Purity: 7B Builder + 3B Architect, all Ollama")

    elif args.config == "b":
        config_label = "B-FrontierParity"
        os.environ["DETERMINEX_INFERENCE_BACKEND"] = "deepseek"
        os.environ.pop("DETERMINEX_DEEPSEEK_MODEL", None)  # use per-role defaults
        os.environ["DETERMINEX_BUILDER_MODEL"] = "deepseek-v4-builder"
        os.environ["DETERMINEX_OBSERVER_MODEL"] = "deepseek-v4-architect"
        log.info("Config B — Frontier Parity: DeepSeek V4 Pro (architect) + V4 Flash (builder)")

    elif args.config == "c":
        config_label = "C-FrontierHybrid"
        os.environ["DETERMINEX_ARCHITECT_BACKEND"] = "deepseek"
        os.environ["DETERMINEX_BUILDER_BACKEND"] = "vllm"
        os.environ.pop("DETERMINEX_DEEPSEEK_MODEL", None)  # use per-role defaults
        os.environ["DETERMINEX_VLLM_MODEL"] = "Qwen/Qwen2.5-Coder-7B-Instruct"
        os.environ["DETERMINEX_BUILDER_MODEL"] = "qwen2.5-coder:7b-instruct"
        os.environ["DETERMINEX_OBSERVER_MODEL"] = "deepseek-v4-architect"
        log.info("Config C — Frontier Hybrid: DeepSeek V4 Pro architect + 7B vLLM builder")

    elif args.config == "e":
        config_label = "E-RegionControl"
        os.environ["DETERMINEX_INFERENCE_BACKEND"] = "deepseek"
        os.environ.pop("DETERMINEX_DEEPSEEK_MODEL", None)  # use per-role defaults
        os.environ["DETERMINEX_BUILDER_MODEL"] = "deepseek-v4-builder"
        os.environ["DETERMINEX_OBSERVER_MODEL"] = "deepseek-v4-architect"
        log.info(
            "Config E — Region Control: DeepSeek V4 Pro (architect) + V4 Flash (builder), no obfuscation"
        )

    elif args.config == "d":
        config_label = "D-NuclearHybrid"
        os.environ["DETERMINEX_ARCHITECT_BACKEND"] = "anthropic"
        os.environ["DETERMINEX_BUILDER_BACKEND"] = "deepseek"
        os.environ["DETERMINEX_ANTHROPIC_MODEL"] = os.getenv(
            "DETERMINEX_ANTHROPIC_MODEL", "claude-sonnet-4-6"
        )
        os.environ.pop(
            "DETERMINEX_DEEPSEEK_MODEL", None
        )  # use per-role defaults (Flash for builder)
        os.environ["DETERMINEX_BUILDER_MODEL"] = "deepseek-v4-builder"
        os.environ["DETERMINEX_OBSERVER_MODEL"] = "claude-sonnet-architect"
        log.info("Config D — Nuclear Hybrid: Claude Sonnet architect + DeepSeek V4 Flash builder")

    else:
        os.environ["DETERMINEX_BUILDER_MODEL"] = args.builder_model
        os.environ["DETERMINEX_OBSERVER_MODEL"] = args.observer_model

    # ── Local-builder size overrides (post-config) ────────────────────────────
    if args.local_builder_14b:
        os.environ["DETERMINEX_INFERENCE_BACKEND"] = "ollama"
        os.environ["DETERMINEX_LOCAL_BUILDER"] = "1"
        os.environ["DETERMINEX_BUILDER_MODEL"] = "qwen2.5-coder:14b-instruct-q4_K_M"
        os.environ["DETERMINEX_LOCAL_BUILDER_MODEL"] = "qwen2.5-coder:14b-instruct-q4_K_M"
        log.info(
            "Local builder override: qwen2.5-coder 14b instruct q4_K_M (stronger than 7b default)"
        )
    elif args.local_builder_32b:
        os.environ["DETERMINEX_INFERENCE_BACKEND"] = "ollama"
        os.environ["DETERMINEX_LOCAL_BUILDER"] = "1"
        os.environ["DETERMINEX_BUILDER_MODEL"] = "qwen2.5-coder:32b-instruct-q4_K_M"
        os.environ["DETERMINEX_LOCAL_BUILDER_MODEL"] = "qwen2.5-coder:32b-instruct-q4_K_M"
        log.info("Local builder override: qwen2.5-coder 32b instruct q4_K_M (max local quality)")

    # ── Project Cloak ─────────────────────────────────────────────────────────
    cloak_label = ""
    if args.cloak:
        os.environ["DETERMINEX_CLOAK"] = "1"
        cloak_label = "-Cloaked"
        log.info("Project Cloak ENABLED — identifiers will be obfuscated before AI inference")
    else:
        os.environ.pop("DETERMINEX_CLOAK", None)
        log.info("Project Cloak DISABLED (uncloaked baseline run)")

    # ── Native test gating ────────────────────────────────────────────────────
    import platform

    if platform.system() == "Windows":
        os.environ["DETERMINEX_SKIP_NATIVE_TESTS"] = "1"
        log.info("Windows detected: native test gating disabled (Docker verifies)")
    else:
        os.environ.pop("DETERMINEX_SKIP_NATIVE_TESTS", None)
        log.info("Linux detected: native test gating ENABLED (Hive verifies locally)")

    _split_tag = args.split
    if getattr(args, "lang", None):
        _split_tag = f"{args.split}_{args.lang}"

    # ── Run type: auto-detect or explicit override ────────────────────────────
    _n_inst_hint = args.instances if args.instances else (5 if not args.all else 999)
    if args.run_type:
        run_type = args.run_type
    elif getattr(args, "lang", None) and "shakeout" in (args.name or ""):
        run_type = "shakeout"
    elif _n_inst_hint <= 5:
        run_type = "debug"
    elif _n_inst_hint <= 20:
        run_type = "smoke"
    elif getattr(args, "lang", None):
        run_type = "shakeout"
    elif args.all or _n_inst_hint >= 300:
        run_type = "publication"
    elif _n_inst_hint >= 21:
        run_type = "ablation"
    else:
        run_type = "smoke"

    # Ablation and publication runs require --name so logs are self-explanatory.
    if run_type in ("ablation", "publication") and not args.name and not args.run_id:
        log.error(
            "Runs of type '%s' require --name <slug> to be self-documenting "
            "(e.g. --name baseline-cloaked). This is non-negotiable for publishable results.",
            run_type,
        )
        sys.exit(1)

    # ── Run ID: YYYYMMDD_HHMM_split_config_cloak_type[_name] (LOCAL time) ────
    _now_local = datetime.now()
    _ts = _now_local.strftime("%Y%m%d_%H%M")
    _name_slug = f"_{args.name}" if args.name else ""
    run_id = args.run_id or (
        f"determinex_{_ts}_{_split_tag}_{config_label}{cloak_label}_{run_type}{_name_slug}"
    )
    out_dir = _LOGS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ["DETERMINEX_RUN_DIR"] = str(out_dir)

    fh = logging.FileHandler(out_dir / "run.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("[RUN] %(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)

    # ── manifest.json — written at run start, self-documents every run ────────
    _git_sha = _git_branch = "unknown"
    try:
        import subprocess as _sp

        _git_sha = _sp.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT, text=True
        ).strip()
        _git_branch = _sp.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_ROOT, text=True
        ).strip()
    except Exception:
        pass

    manifest: dict = {
        "run_id": run_id,
        "run_type": run_type,
        "name": args.name or "",
        "note": args.note or "",
        "created_local": _now_local.isoformat(),
        "created_utc": datetime.now(UTC).isoformat(),
        "git": {
            "sha": _git_sha,
            "branch": _git_branch,
        },
        "config": {
            "split": args.split,
            "lang": getattr(args, "lang", None),
            "config_key": getattr(args, "config", None),
            "config_label": config_label,
            "cloak": args.cloak,
            "parallel": args.parallel,
            "instances": args.instances,
            "all": args.all,
            "shuffle": args.shuffle,
            "shuffle_seed": args.shuffle_seed,
            "skip_eval": args.skip_eval,
            "prediction_source": args.prediction_source,
            "flywheel_path": str(args.flywheel_path),
        },
        "benchmark_boundary": {
            "clean_benchmark": args.prediction_source == "agent",
            "answer_key_diagnostic": args.prediction_source == "dataset-gold",
            "training_eligible": args.prediction_source == "agent",
            "contamination_note": (
                "Normal agent run; no benchmark answer key used."
                if args.prediction_source == "agent"
                else "Diagnostic replay run. Do not report as a clean benchmark or import as training data."
            ),
        },
        "models": {
            "builder": os.environ.get("DETERMINEX_BUILDER_MODEL", args.builder_model),
            "architect": os.environ.get("DETERMINEX_OBSERVER_MODEL", args.observer_model),
            "backend": os.environ.get("DETERMINEX_INFERENCE_BACKEND", "ollama"),
            "deepseek_model": os.environ.get("DETERMINEX_DEEPSEEK_MODEL", ""),
            "anthropic_model": os.environ.get("DETERMINEX_ANTHROPIC_MODEL", ""),
        },
        "status": "running",
        "result": None,
    }
    _manifest_path = out_dir / "manifest.json"
    _manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("=" * 60)
    log.info("Determinex SWE-bench Run")
    log.info("  Run ID       : %s", run_id)
    log.info("  Run Type     : %s", run_type.upper())
    log.info("  Name         : %s", args.name or "(unnamed)")
    log.info("  Note         : %s", args.note or "(no hypothesis recorded)")
    log.info("  Git          : %s @ %s", _git_sha, _git_branch)
    log.info("  Config       : %s", config_label)
    log.info("  Cloak        : %s", "ENABLED" if args.cloak else "disabled (baseline)")
    log.info(
        "  Split        : %s%s (%s)",
        args.split,
        f"/{args.lang}" if getattr(args, "lang", None) else "",
        SPLIT_DATASETS[args.split],
    )
    log.info("  Builder      : %s", os.environ.get("DETERMINEX_BUILDER_MODEL", args.builder_model))
    log.info(
        "  Architect    : %s", os.environ.get("DETERMINEX_OBSERVER_MODEL", args.observer_model)
    )
    log.info("  Backend      : %s", os.environ.get("DETERMINEX_INFERENCE_BACKEND", "ollama"))
    log.info("  Pred source  : %s", args.prediction_source)
    log.info("  Output dir   : %s", out_dir)
    log.info("=" * 60)

    max_inst = None if args.all else (args.instances or 5)
    iid_filter = [x.strip() for x in args.instance_ids.split(",")] if args.instance_ids else None
    instances = load_dataset_split(
        args.split,
        max_instances=max_inst,
        instance_ids=iid_filter,
        lang_filter=getattr(args, "lang", None),
    )

    if args.shuffle:
        import random as _random

        rng = _random.Random(args.shuffle_seed)
        rng.shuffle(instances)
        log.info(
            "Instances shuffled (seed=%d) — first: %s",
            args.shuffle_seed,
            instances[0]["instance_id"] if instances else "none",
        )

    flywheel_exact: dict[str, str] | None = None
    if args.prediction_source == "flywheel-exact":
        flywheel_exact = load_flywheel_exact_patches(args.flywheel_path)
        log.info(
            "Flywheel exact patches loaded: %d from %s", len(flywheel_exact), args.flywheel_path
        )
    elif args.prediction_source == "dataset-gold":
        missing_gold = sum(1 for inst in instances if not str(inst.get("patch") or "").strip())
        log.warning(
            "Dataset-gold prediction source is an answer-key diagnostic, not a clean benchmark. "
            "missing_gold_patches=%d",
            missing_gold,
        )

    # ── Resume: skip already-completed instances ──────────────────────────────
    predictions: list[dict] = []
    predictions_file = out_dir / "predictions.jsonl"
    if predictions_file.exists():
        done_ids: set[str] = set()
        with predictions_file.open(encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line:
                    try:
                        _pred = json.loads(_line)
                        predictions.append(_pred)
                        done_ids.add(_pred["instance_id"])
                    except json.JSONDecodeError:
                        pass
        if done_ids:
            _before = len(instances)
            instances = [inst for inst in instances if inst["instance_id"] not in done_ids]
            log.info(
                "RESUME: %d/%d already done → %d remaining", len(done_ids), _before, len(instances)
            )
            if not instances:
                log.info("RESUME: All instances complete. Nothing to do.")
                if not args.skip_eval:
                    eval_result = run_official_evaluation(predictions_file, args.split, run_id)
                    (out_dir / "eval_result.json").write_text(
                        json.dumps(eval_result, indent=2), encoding="utf-8"
                    )
                    log.info("Full results saved → %s", out_dir)
                return

    workdir = args.repos_dir if args.repos_dir else (out_dir / "repos")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if args.repos_dir:
        log.info("Using pre-cloned repos dir: %s", workdir)

    _inst_log_dir = out_dir / "instance_logs"
    _inst_log_dir.mkdir(exist_ok=True)

    def _process_one(i: int, instance: dict) -> dict:
        iid = instance["instance_id"]
        t_inst_start = time.perf_counter()
        ts_started = datetime.now(UTC)

        # Per-instance log: header + thread-filtered handler
        inst_log_path = _inst_log_dir / f"{iid}.log"
        inst_log_path.write_text(
            f"=== {iid} [started: {ts_started.strftime('%Y-%m-%d %H:%M:%S UTC')}] ===\n",
            encoding="utf-8",
        )
        inst_handler = _InstanceLogHandler(inst_log_path, threading.current_thread().ident)
        logging.getLogger().addHandler(inst_handler)

        try:
            log.info("[%d/%d] START %s", i + 1, len(instances), iid)
            replay_pred = build_replay_prediction(
                instance,
                run_id=run_id,
                prediction_source=args.prediction_source,
                flywheel_exact=flywheel_exact,
            )
            if replay_pred is not None:
                patch = replay_pred["model_patch"]
                resolved = "REPLAY PATCH" if patch else "REPLAY EMPTY"
                log.info(
                    "[%d/%d] DONE %s -> %s (%d patch lines)",
                    i + 1,
                    len(instances),
                    iid,
                    resolved,
                    len(patch.splitlines()),
                )
                return replay_pred
            pre_cloned = workdir / iid if args.repos_dir else None
            if pre_cloned and pre_cloned.exists():
                git_root = pre_cloned / "repo" if (pre_cloned / "repo").is_dir() else pre_cloned
                log.info("[%d/%d] Pre-cloned repo: %s", i + 1, len(instances), git_root)
                base_commit = instance.get("base_commit", "HEAD")
                subprocess.run(
                    ["git", "checkout", base_commit], capture_output=True, cwd=git_root, timeout=30
                )
                subprocess.run(
                    ["git", "checkout", "--", "."], capture_output=True, cwd=git_root, timeout=15
                )
                repo_path = git_root
            else:
                repo_path = clone_repo_at_commit(instance, workdir)
            if repo_path is None:
                log.warning("[%d/%d] SKIP %s (clone failed)", i + 1, len(instances), iid)
                return {"instance_id": iid, "model_patch": "", "model_name_or_path": run_id}
            patch = run_agent_on_instance(instance, repo_path)
            patch = patch.replace("\r\n", "\n").replace("\r", "\n")
            resolved = "✓ PATCH" if patch else "✗ EMPTY"
            log.info(
                "[%d/%d] DONE %s → %s (%d patch lines)",
                i + 1,
                len(instances),
                iid,
                resolved,
                len(patch.splitlines()),
            )
            return {"instance_id": iid, "model_patch": patch, "model_name_or_path": run_id}
        finally:
            elapsed_s = time.perf_counter() - t_inst_start
            logging.getLogger().removeHandler(inst_handler)
            inst_handler.close()
            with inst_log_path.open("a", encoding="utf-8") as _lf:
                _lf.write(
                    f"=== END {iid} [elapsed: {elapsed_s:.0f}s / {elapsed_s / 60:.1f}min] ===\n"
                )

    _pred_lock = threading.Lock()

    def _save_pred(pred: dict) -> None:
        with _pred_lock:
            predictions.append(pred)
            write_predictions(predictions, out_dir / "predictions.jsonl")

    t_start = time.perf_counter()
    n_workers = max(1, args.parallel)

    if n_workers == 1:
        for i, instance in enumerate(instances):
            _save_pred(_process_one(i, instance))
    else:
        log.info("Parallel mode: %d workers", n_workers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = {ex.submit(_process_one, i, inst): inst for i, inst in enumerate(instances)}
            for fut in concurrent.futures.as_completed(futs):
                try:
                    _save_pred(fut.result())
                except Exception as exc:
                    iid = futs[fut].get("instance_id", "unknown")
                    log.error("Instance %s raised: %s", iid, exc)
                    _save_pred(
                        {"instance_id": iid, "model_patch": "", "model_name_or_path": run_id}
                    )

    elapsed = time.perf_counter() - t_start
    n_total = len(predictions)
    n_patched = sum(1 for p in predictions if p["model_patch"])
    n_empty = n_total - n_patched
    patch_rate = n_patched / max(n_total, 1)

    log.info("=" * 60)
    log.info("Agent run complete")
    log.info("  Run type     : %s", run_type.upper())
    log.info("  Name         : %s", args.name or "(unnamed)")
    log.info("  Patched      : %d / %d  (%.1f%%)", n_patched, n_total, 100 * patch_rate)
    log.info("  Empty        : %d", n_empty)
    log.info("  Elapsed      : %.0fs  (%.1f min)", elapsed, elapsed / 60)
    log.info("  Output dir   : %s", out_dir)
    log.info("=" * 60)

    # ── summary.json — written at run end, captures agent-generation results ──
    # Note: this is patch-generation score, NOT solve score.
    # Solve score (% actually resolved) comes from run_official_evaluation below.
    summary: dict = {
        "run_id": run_id,
        "run_type": run_type,
        "name": args.name or "",
        "note": args.note or "",
        "prediction_source": args.prediction_source,
        "clean_benchmark": args.prediction_source == "agent",
        "training_eligible": args.prediction_source == "agent",
        "git_sha": _git_sha,
        "completed_local": datetime.now().isoformat(),
        "completed_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "generation": {
            "total": n_total,
            "patched": n_patched,
            "empty": n_empty,
            "patch_rate": round(patch_rate, 4),
            "note": (
                "patch_rate = patches generated / total instances. "
                "Does NOT equal solve rate — patches still go through Docker harness."
            ),
        },
        "solve": None,  # filled in below after eval
    }

    if args.cloak:
        log.info("Running Project Cloak verification audit...")
        try:
            cloak_proc = subprocess.run(
                [sys.executable, str(_SCRIPTS / "verify_cloak.py"), "--run-dir", str(out_dir)],
                capture_output=False,
                timeout=120,
            )
            if cloak_proc.returncode != 0:
                log.warning("verify_cloak exited with code %d", cloak_proc.returncode)
                summary["cloak_audit"] = "FAILED"
            else:
                summary["cloak_audit"] = "PASSED"
        except Exception as e:
            log.warning("verify_cloak failed: %s", e)
            summary["cloak_audit"] = f"ERROR: {e}"

    if args.skip_eval:
        summary["solve"] = {"note": "skipped (--skip-eval)"}
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        # Update manifest status
        manifest["status"] = "complete_no_eval"
        manifest["result"] = {"patch_rate": round(patch_rate, 4)}
        _manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        log.info(
            "--skip-eval set: skipping official harness. Predictions at: %s",
            out_dir / "predictions.jsonl",
        )
        log.info("Summary written → %s", out_dir / "summary.json")
        return

    eval_result = run_official_evaluation(out_dir / "predictions.jsonl", args.split, run_id)
    (out_dir / "eval_result.json").write_text(json.dumps(eval_result, indent=2), encoding="utf-8")

    # Extract resolve rate from eval result
    n_resolved = eval_result.get("resolved", 0)
    resolve_rate = n_resolved / max(n_total, 1)
    summary["solve"] = {
        "resolved": n_resolved,
        "total": n_total,
        "resolve_rate": round(resolve_rate, 4),
        "resolve_pct": round(100 * resolve_rate, 2),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Update manifest to completed
    manifest["status"] = "complete"
    manifest["result"] = {
        "patch_rate": round(patch_rate, 4),
        "resolve_rate": round(resolve_rate, 4),
        "resolve_pct": round(100 * resolve_rate, 2),
        "n_resolved": n_resolved,
        "n_total": n_total,
    }
    _manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("Solve results: %d/%d resolved (%.2f%%)", n_resolved, n_total, 100 * resolve_rate)
    log.info("Full results saved → %s", out_dir)


if __name__ == "__main__":
    main()
