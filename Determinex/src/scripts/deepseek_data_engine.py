"""
deepseek_data_engine.py -- Determinex Behavioral Cloning Data Engine

Reads the Oracle's session_config.json to determine today's agenda and teacher
assignments, then generates validated training samples for each curriculum category.

Despite the legacy name, this engine is provider-agnostic -- it dispatches to
whichever teacher the Oracle designated (local Ollama, Claude, Gemini, etc.).

Validated samples are written to the existing JSONL paths that train_unsloth.py
already reads. Zero changes to the training pipeline -- just better data.

Usage:
    python scripts/deepseek_data_engine.py                    # Run full Oracle agenda
    python scripts/deepseek_data_engine.py --category rust_code_generation
    python scripts/deepseek_data_engine.py --category rust_code_generation --n 20
    python scripts/deepseek_data_engine.py --dry-run          # Generate but do not write JSONL
    python scripts/deepseek_data_engine.py --run-oracle       # Re-run Oracle first, then engine

Output JSONL format (matches train_unsloth.py expectation):
    {"system": "...", "user": "...", "assistant": "..."}
"""

import argparse
import json
import logging
import random
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ── UTF-8 terminal fix (Windows) ────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[ENGINE] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("engine")

# ── Paths ────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_DETERMINEX_ROOT = _SCRIPTS_DIR.parent
_SRC_TAURI = _DETERMINEX_ROOT / "frontend" / "src-tauri"
_SESSION_CONFIG = _SCRIPTS_DIR / "session_config.json"
_CURRICULUM = _SCRIPTS_DIR / "curriculum.jsonl"
_LOG_DIR = _DETERMINEX_ROOT / "logs"
_ENV_FILE = _DETERMINEX_ROOT / ".env"

# JSONL output files -- match exactly what train_unsloth.py reads
_JSONL_MAP = {
    "api_anthropic": _SRC_TAURI / "determinex_v1_distilled_claude.jsonl",
    "api_google": _SRC_TAURI / "determinex_v1_distilled_gemini.jsonl",
    "local_ollama": _SRC_TAURI / "determinex_v1_distilled_observer.jsonl",
    "api_deepseek": _SRC_TAURI
    / "determinex_v1_distilled_observer.jsonl",  # routes to observer file
    "api_openai": _SRC_TAURI / "determinex_v1_distilled_claude.jsonl",  # routes to claude file
}
_DEFAULT_JSONL = _SRC_TAURI / "determinex_v1_distilled_observer.jsonl"

# Token limit guard (must match train_unsloth.py MAX_SEQ_LENGTH)
_MAX_TOKEN_ESTIMATE = 2000  # chars / 4 ≈ tokens; conservative 8000 char ceiling
_MAX_CHARS = 8000


# ── .env loader ──────────────────────────────────────────────────────────────


def load_env() -> dict:
    env = {}
    if not _ENV_FILE.exists():
        return env
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


# ── Session config loader ────────────────────────────────────────────────────


def load_session_config() -> dict:
    if not _SESSION_CONFIG.exists():
        log.error(
            "session_config.json not found at %s\n"
            "Run: python scripts/leaderboard_oracle.py  first.",
            _SESSION_CONFIG,
        )
        sys.exit(1)
    try:
        return json.loads(_SESSION_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("session_config.json is malformed: %s", e)
        sys.exit(1)


# ── Curriculum loader ────────────────────────────────────────────────────────


def load_curriculum(path: Path | None = None) -> dict[str, dict]:
    """Return curriculum indexed by category name. Uses _CURRICULUM by default."""
    curriculum_path = path or _CURRICULUM
    if not curriculum_path.exists():
        log.error("curriculum not found: %s", curriculum_path)
        sys.exit(1)
    cats = {}
    for line in curriculum_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                cat = json.loads(line)
                cats[cat["category"]] = cat
            except (json.JSONDecodeError, KeyError) as e:
                log.warning("Skipping malformed curriculum line: %s", e)
    log.info("Curriculum loaded: %d categories from %s", len(cats), curriculum_path.name)
    return cats


# ── Provider dispatch ────────────────────────────────────────────────────────


def dispatch(provider: str, model: str, system: str, user: str, cot: bool) -> str | None:
    """
    Route generation to the correct provider adapter.
    Falls back to local_ollama if the requested provider fails.
    """
    from scripts.providers import PROVIDER_MAP

    fn = PROVIDER_MAP.get(provider)
    if fn is None:
        log.error("Unknown provider '%s' -- falling back to local_ollama", provider)
        fn = PROVIDER_MAP["local_ollama"]
        model = "determinex-leviathan:v1"

    result = fn(system=system, user=user, model=model, cot=cot)

    # Fallback to local Ollama if primary provider fails
    if result is None and provider != "local_ollama":
        log.warning("Provider '%s' failed -- falling back to local Ollama", provider)
        fallback_fn = PROVIDER_MAP["local_ollama"]
        result = fallback_fn(
            system=system,
            user=user,
            model="determinex-leviathan:v1",
            cot=cot,
        )

    return result


# ── Validation dispatch ──────────────────────────────────────────────────────


def run_validator(
    output: str,
    task_meta: dict,
    validator_type: str,
) -> tuple[bool, str]:
    """Dispatch to the correct validator module."""
    from scripts.validators import VALIDATOR_MAP

    fn = VALIDATOR_MAP.get(validator_type)
    if fn is None:
        log.warning(
            "Unknown validator '%s' -- skipping validation (PASS by default)", validator_type
        )
        return True, f"Unknown validator '{validator_type}' -- passed by default"

    try:
        return fn(output=output, task_meta=task_meta)
    except Exception as e:
        log.error("Validator '%s' crashed: %s", validator_type, e)
        return False, f"Validator error: {e}"


# ── Token pre-check ──────────────────────────────────────────────────────────


def passes_token_check(system: str, user: str, assistant: str) -> tuple[bool, int]:
    """
    Estimate token count for the full formatted sample.
    Rough heuristic: 1 token per 4 characters (conservative).
    Returns (passes, estimated_token_count).
    """
    full_text = (
        f"<|begin_of_text|>"
        f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
        f"<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>"
        f"<|start_header_id|>assistant<|end_header_id|>\n\n{assistant}<|eot_id|>"
    )
    char_count = len(full_text)
    est_tokens = char_count // 4
    return est_tokens <= _MAX_TOKEN_ESTIMATE, est_tokens


# ── JSONL writer ─────────────────────────────────────────────────────────────


def write_sample(provider: str, system: str, user: str, assistant: str, dry_run: bool) -> Path:
    """
    Append a validated sample to the appropriate JSONL file.
    Returns the path written to (or would write to, in dry_run mode).
    """
    target = _JSONL_MAP.get(provider, _DEFAULT_JSONL)
    sample = json.dumps(
        {"system": system, "user": user, "assistant": assistant}, ensure_ascii=False
    )
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(sample + "\n")
    return target


# ── Generation report ────────────────────────────────────────────────────────


class SessionReport:
    """Accumulates stats for a generation run and writes generation_report.json."""

    def __init__(self, session_id: str, category: str, teacher_model: str, provider: str):
        self.session_id = session_id
        self.category = category
        self.teacher_model = teacher_model
        self.provider = provider
        self.start_time = datetime.now(UTC).isoformat()
        self.attempted = 0
        self.validated = 0
        self.rejected = 0
        self.token_overflow = 0
        self.rejection_reasons: list[str] = []
        self._start_ts = time.time()

        # Rough cost estimate per token (USD) -- update as pricing changes
        _COST_PER_TOKEN = {
            "api_anthropic": 0.000003,  # ~$3/M input+output blended
            "api_google": 0.000001,  # ~$1/M blended
            "api_deepseek": 0.00000027,  # ~$0.27/M
            "api_openai": 0.000005,  # ~$5/M blended
            "local_ollama": 0.0,
        }
        self._cost_per_token = _COST_PER_TOKEN.get(provider, 0.0)
        self.estimated_cost = 0.0
        self._total_chars = 0

    def record_attempt(self, output_chars: int = 0):
        self.attempted += 1
        self._total_chars += output_chars
        self.estimated_cost = (self._total_chars / 4) * self._cost_per_token

    def record_validated(self):
        self.validated += 1

    def record_rejected(self, reason: str):
        self.rejected += 1
        self.rejection_reasons.append(reason[:200])

    def record_token_overflow(self):
        self.token_overflow += 1
        self.rejection_reasons.append("token_overflow")

    def to_dict(self) -> dict:
        elapsed = round(time.time() - self._start_ts, 1)
        rejection_rate = self.rejected / max(self.attempted, 1)
        return {
            "session_id": self.session_id,
            "category": self.category,
            "teacher_model": self.teacher_model,
            "provider": self.provider,
            "start_time": self.start_time,
            "end_time": datetime.now(UTC).isoformat(),
            "elapsed_seconds": elapsed,
            "samples_attempted": self.attempted,
            "samples_validated": self.validated,
            "samples_rejected": self.rejected,
            "token_overflow_count": self.token_overflow,
            "rejection_rate": round(rejection_rate, 3),
            "rejection_reasons": self.rejection_reasons[:20],
            "estimated_cost_usd": round(self.estimated_cost, 4),
        }

    def write(self, dry_run: bool = False):
        if dry_run:
            return
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _LOG_DIR / f"generation_report_{self.category}_{self.session_id[:8]}.json"
        report_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        log.info("Report written: %s", report_path.name)


# ── Category runner ──────────────────────────────────────────────────────────


def run_category(
    agenda_item: dict,
    curriculum: dict[str, dict],
    dry_run: bool = False,
    max_samples: int | None = None,
) -> SessionReport:
    """
    Generate and validate samples for one curriculum category.
    Returns a SessionReport with counts and stats.
    """
    category = agenda_item["category"]
    target = max_samples or agenda_item.get("target_samples", 50)
    provider = agenda_item.get("teacher_provider", "local_ollama")
    model = agenda_item.get("teacher_model", "determinex-leviathan:v1")
    validator_type = agenda_item.get("validator", "regex")
    cot = agenda_item.get("cot_requested", False)

    cat_def = curriculum.get(category)
    if not cat_def:
        log.error("Category '%s' not in curriculum -- skipping", category)
        report = SessionReport(str(uuid.uuid4()), category, model, provider)
        return report

    system_prompt = cat_def.get("system_prompt", "You are a helpful assistant.")
    templates = cat_def.get("prompt_templates", [])

    if not templates:
        log.error("Category '%s' has no prompt templates -- skipping", category)
        report = SessionReport(str(uuid.uuid4()), category, model, provider)
        return report

    session_id = str(uuid.uuid4())
    report = SessionReport(session_id, category, model, provider)

    log.info(
        "\n[ENGINE] === Category: %s ===\n"
        "  Teacher : %s (%s)\n"
        "  Target  : %d samples\n"
        "  Validator: %s\n"
        "  CoT     : %s",
        category,
        model,
        provider,
        target,
        validator_type,
        cot,
    )

    validated_count = 0
    attempt_count = 0
    max_attempts = target * 4  # allow up to 4x attempts to hit target (rejection tolerance)

    # Shuffle templates so we don't always use the same ones first
    shuffled_templates = templates.copy()
    random.shuffle(shuffled_templates)
    template_cycle = shuffled_templates * ((max_attempts // len(shuffled_templates)) + 1)

    for i, user_prompt in enumerate(template_cycle[:max_attempts]):
        if validated_count >= target:
            break

        attempt_count += 1
        log.info(
            "[ENGINE] Attempt %d/%d  (validated: %d/%d)",
            attempt_count,
            max_attempts,
            validated_count,
            target,
        )

        # ── Generate ────────────────────────────────────────────────────────
        output = dispatch(provider, model, system_prompt, user_prompt, cot)
        report.record_attempt(len(output) if output else 0)

        if output is None or len(output.strip()) < 10:
            reason = "Empty or too-short response from teacher"
            log.warning("[ENGINE] %s", reason)
            report.record_rejected(reason)
            time.sleep(1)  # back off before retry
            continue

        # ── Token pre-check ──────────────────────────────────────────────────
        passes, est_tokens = passes_token_check(system_prompt, user_prompt, output)
        if not passes:
            # Truncate assistant response rather than discard outright
            # Keep the first _MAX_CHARS chars of output
            output = output[:_MAX_CHARS]
            passes, est_tokens = passes_token_check(system_prompt, user_prompt, output)
            if not passes:
                log.warning("[ENGINE] Token overflow even after truncation -- discarding")
                report.record_token_overflow()
                continue

        # ── Validate ─────────────────────────────────────────────────────────
        task_meta_with_prompt = {**cat_def, "_task_prompt": user_prompt}
        passed, reason = run_validator(output, task_meta_with_prompt, validator_type)

        if not passed:
            log.warning("[ENGINE] Validation FAIL: %s", reason[:120])
            report.record_rejected(reason)
            time.sleep(0.5)
            continue

        # ── Write sample ─────────────────────────────────────────────────────
        jsonl_path = write_sample(provider, system_prompt, user_prompt, output, dry_run)
        report.record_validated()
        validated_count += 1

        mode_tag = "[DRY RUN]" if dry_run else ""
        log.info(
            "[ENGINE] VALIDATED %s --> %s  (est. %d tokens)",
            mode_tag,
            jsonl_path.name,
            est_tokens,
        )

    # ── Summary ──────────────────────────────────────────────────────────────
    rejection_pct = 100 * report.rejected / max(report.attempted, 1)
    log.info(
        "\n[ENGINE] Category '%s' complete:\n"
        "  Attempted  : %d\n"
        "  Validated  : %d / %d target\n"
        "  Rejected   : %d (%.0f%%)\n"
        "  Est. cost  : $%.4f",
        category,
        report.attempted,
        report.validated,
        target,
        report.rejected,
        rejection_pct,
        report.estimated_cost,
    )

    if rejection_pct > 40:
        log.warning(
            "[ENGINE] High rejection rate (%.0f%%) for '%s' -- "
            "consider refining prompt templates or system prompt.",
            rejection_pct,
            category,
        )

    return report


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex Data Engine")
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Run only this category (e.g., rust_code_generation). Default: run full agenda.",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        help="Override target sample count for the run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and validate samples but do NOT write to JSONL files.",
    )
    parser.add_argument(
        "--run-oracle",
        action="store_true",
        help="Re-run the Leaderboard Oracle to refresh session_config.json first.",
    )
    parser.add_argument(
        "--curriculum",
        type=str,
        default=None,
        help="Path to a curriculum JSONL file. Defaults to scripts/curriculum.jsonl. "
        "Use scripts/micro_curriculum.jsonl for a focused micro-test.",
    )
    args = parser.parse_args()

    curriculum_path = Path(args.curriculum) if args.curriculum else None

    # ── Optionally re-run Oracle ─────────────────────────────────────────────
    if args.run_oracle:
        import subprocess

        oracle_script = _SCRIPTS_DIR / "leaderboard_oracle.py"
        log.info("Running Oracle before engine...")
        result = subprocess.run(
            [sys.executable, str(oracle_script)],
            cwd=str(_DETERMINEX_ROOT),
        )
        if result.returncode != 0:
            log.warning("Oracle returned non-zero exit -- proceeding with existing session_config")

    # ── Load session config ──────────────────────────────────────────────────
    config = load_session_config()
    agenda = config.get("session_agenda", [])
    curriculum = load_curriculum(curriculum_path)

    if not agenda:
        log.error("No agenda in session_config.json -- run leaderboard_oracle.py first")
        sys.exit(1)

    # ── Filter agenda if --category specified ────────────────────────────────
    if args.category:
        agenda = [item for item in agenda if item["category"] == args.category]
        if not agenda:
            # Category might not be in today's agenda -- pull from full config
            assignments = config.get("teacher_assignments", {})
            if args.category in assignments:
                assignment = assignments[args.category]
                cat_def = curriculum.get(args.category, {})
                agenda = [
                    {
                        "category": args.category,
                        "display_name": cat_def.get("display_name", args.category),
                        "target_samples": args.n or 50,
                        "teacher_model": assignment.get("model", "determinex-leviathan:v1"),
                        "teacher_provider": assignment.get("provider", "local_ollama"),
                        "quality_score": assignment.get("quality_score", 0.5),
                        "pass_multiplier": assignment.get("pass_multiplier", 1.0),
                        "priority_score": 0.0,
                        "validator": cat_def.get("validator", "regex"),
                        "cot_requested": cat_def.get("cot_requested", False),
                    }
                ]
            else:
                log.error("Category '%s' not found in curriculum or session config", args.category)
                sys.exit(1)

    dry_tag = " [DRY RUN]" if args.dry_run else ""
    log.info(
        "\n%s\n  DETERMINEX DATA ENGINE STARTING%s\n  Source  : %s\n  Agenda  : %d categories\n%s",
        "=" * 60,
        dry_tag,
        config.get("leaderboard_source", "unknown"),
        len(agenda),
        "=" * 60,
    )

    all_reports = []
    total_validated = 0
    total_cost = 0.0

    for agenda_item in agenda:
        report = run_category(
            agenda_item,
            curriculum,
            dry_run=args.dry_run,
            max_samples=args.n,
        )
        report.write(dry_run=args.dry_run)
        all_reports.append(report.to_dict())
        total_validated += report.validated
        total_cost += report.estimated_cost

    # ── Final summary ────────────────────────────────────────────────────────
    log.info(
        "\n%s\n  ENGINE RUN COMPLETE%s\n"
        "  Categories : %d\n"
        "  Total validated samples : %d\n"
        "  Estimated total cost    : $%.4f\n%s",
        "=" * 60,
        dry_tag,
        len(agenda),
        total_validated,
        total_cost,
        "=" * 60,
    )

    if total_validated == 0:
        log.warning(
            "Zero samples validated. Check:\n"
            "  1. Ollama is running: ollama list\n"
            "  2. Leviathan model exists: ollama list | findstr leviathan\n"
            "  3. Provider API keys are set if APIs are enabled\n"
            "  4. rustc is on PATH for rust_* categories"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
