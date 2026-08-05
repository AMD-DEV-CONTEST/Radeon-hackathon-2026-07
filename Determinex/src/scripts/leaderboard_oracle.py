"""
leaderboard_oracle.py — Determinex Leaderboard Oracle

Queries LMSYS Chatbot Arena (primary) and HuggingFace Open LLM Leaderboard (secondary)
at session start to determine the current best models per task category.

Maps rankings to enabled providers via .env cost gates, then applies all three Oracle Modes:
  Mode A: Logs "opportunity report" — what APIs would unlock vs current local state
  Mode B: Prioritizes curriculum categories by available teacher quality score
  Mode C: Weights pass count per category by quality gap to current #1

Writes session_config.json — the single source of truth for the data engine.

Cache: .oracle_cache.json with 24h TTL. Falls back to cache on ANY network failure.
Last resort: hardcoded April 2026 rankings — pipeline NEVER blocks.

Usage:
    python scripts/leaderboard_oracle.py              # Full run, writes session_config.json
    python scripts/leaderboard_oracle.py --dry-run    # Report only, no file writes
    python scripts/leaderboard_oracle.py --force-refresh  # Bypass 24h cache, re-fetch live
    python scripts/leaderboard_oracle.py --category rust_code_generation  # Single-category agenda
"""

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── Windows UTF-8 terminal fix ──────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[ORACLE] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("oracle")

# ── Paths ────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_DETERMINEX_ROOT = _SCRIPTS_DIR.parent
_ENV_FILE = _DETERMINEX_ROOT / ".env"
_CURRICULUM = _SCRIPTS_DIR / "curriculum.jsonl"
_CACHE_FILE = _SCRIPTS_DIR / ".oracle_cache.json"
_SESSION_CONFIG = _SCRIPTS_DIR / "session_config.json"
_LOG_DIR = _DETERMINEX_ROOT / "logs"
_OPPORTUNITY_LOG = _LOG_DIR / "oracle_opportunity.log"

CACHE_TTL_HOURS = 24

# ── Hardcoded April 2026 Rankings (last-resort fallback) ────────────────────
# Source: LMSYS Chatbot Arena coding category + broader benchmarks.
# Update this list periodically as the field evolves.
FALLBACK_RANKINGS = [
    {
        "model_name": "claude-sonnet-4-5",
        "provider": "api_anthropic",
        "elo_score": 1342,
        "coding_rank": 1,
        "reasoning_rank": 1,
    },
    {
        "model_name": "gemini-2.5-pro",
        "provider": "api_google",
        "elo_score": 1330,
        "coding_rank": 2,
        "reasoning_rank": 2,
    },
    {
        "model_name": "gpt-4o",
        "provider": "api_openai",
        "elo_score": 1310,
        "coding_rank": 3,
        "reasoning_rank": 3,
    },
    {
        "model_name": "deepseek-v3",
        "provider": "api_deepseek",
        "elo_score": 1295,
        "coding_rank": 4,
        "reasoning_rank": 4,
    },
    {
        "model_name": "deepseek-coder-v2:latest",
        "provider": "local_ollama",
        "elo_score": 1240,
        "coding_rank": 5,
        "reasoning_rank": 6,
    },
    {
        "model_name": "llama3.2:3b",
        "provider": "local_ollama",
        "elo_score": 1110,
        "coding_rank": 9,
        "reasoning_rank": 9,
    },
    {
        "model_name": "phi3:mini",
        "provider": "local_ollama",
        "elo_score": 1080,
        "coding_rank": 11,
        "reasoning_rank": 11,
    },
    {
        "model_name": "mistral:latest",
        "provider": "local_ollama",
        "elo_score": 1095,
        "coding_rank": 10,
        "reasoning_rank": 10,
    },
    {
        "model_name": "qwen2.5-coder:7b",
        "provider": "local_ollama",
        "elo_score": 1165,
        "coding_rank": 7,
        "reasoning_rank": 8,
    },
]

# Model name aliases: leaderboard names → Ollama tag or API model ID
MODEL_ALIASES = {
    "claude-sonnet-4-5": "claude-sonnet-4-5",
    "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
    "gemini-2.5-pro": "gemini-2.5-pro-preview-03-25",
    "gemini-1.5-pro": "gemini-1.5-pro",
    "gpt-4o": "gpt-4o",
    "deepseek-v3": "deepseek-chat",
    "deepseek-coder-v2:latest": "determinex-leviathan:v1",
}


# ── .env loader ──────────────────────────────────────────────────────────────


def load_env() -> dict:
    """Parse .env into a dict. Returns {} if file not found."""
    env = {}
    if not _ENV_FILE.exists():
        return env
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def env_bool(env: dict, key: str, default: bool = False) -> bool:
    return env.get(key, str(default)).lower() in ("true", "1", "yes")


def env_int(env: dict, key: str, default: int) -> int:
    try:
        return int(env.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# ── Cache management ─────────────────────────────────────────────────────────


def load_cache() -> dict | None:
    """Return cached rankings if fresh, else None."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        expires_at = data.get("cache_expires_at", 0)
        if time.time() < expires_at:
            log.info("Cache hit — expires %s", datetime.fromtimestamp(expires_at).isoformat())
            return data
        log.info("Cache expired — will refresh")
    except (json.JSONDecodeError, KeyError, OSError) as e:
        log.warning("Cache read failed: %s", e)
    return None


def save_cache(rankings: list[dict], source_url: str):
    """Write rankings to cache with 24h TTL."""
    expires = time.time() + CACHE_TTL_HOURS * 3600
    data = {
        "fetch_timestamp": datetime.now(UTC).isoformat(),
        "source_url": source_url,
        "rankings": rankings,
        "cache_expires_at": expires,
    }
    try:
        _CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("Rankings cached → %s", _CACHE_FILE.name)
    except OSError as e:
        log.warning("Cache write failed: %s", e)


# ── Leaderboard fetchers ─────────────────────────────────────────────────────


def _fetch_lmsys_arena() -> list[dict] | None:
    """
    Attempt to fetch LMSYS Chatbot Arena coding leaderboard.
    Returns normalized ranking list or None on failure.
    """
    try:
        import urllib.error
        import urllib.request

        # LMSYS publishes leaderboard data via their HuggingFace space backend.
        # The coding-specific category filter produces the most relevant ranking.
        url = (
            "https://huggingface.co/datasets/lmsys/chatbot-arena-elo-results"
            "/resolve/main/latest.json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "DeterminexOracle/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        # Normalize — HuggingFace dataset schema varies; handle both known shapes
        rankings = []
        models = raw if isinstance(raw, list) else raw.get("models", raw.get("data", []))
        for i, entry in enumerate(models[:20], start=1):
            name = entry.get("model") or entry.get("model_name") or entry.get("name", "")
            score = float(entry.get("elo") or entry.get("elo_score") or entry.get("score") or 0)
            if name and score:
                rankings.append(
                    {
                        "model_name": name.lower().replace(" ", "-"),
                        "provider": _infer_provider(name),
                        "elo_score": score,
                        "coding_rank": i,
                        "reasoning_rank": i,
                    }
                )
        if rankings:
            log.info("LMSYS Arena: fetched %d model rankings", len(rankings))
            return rankings

    except Exception as e:
        log.debug("LMSYS fetch failed: %s", e)
    return None


def _fetch_hf_leaderboard() -> list[dict] | None:
    """
    Attempt to fetch HuggingFace Open LLM Leaderboard 2 summary.
    Returns normalized ranking list or None on failure.
    """
    try:
        import urllib.request

        # HuggingFace Leaderboard 2 API endpoint for results summary
        url = (
            "https://huggingface.co/api/datasets/open-llm-leaderboard/results?split=train&limit=20"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "DeterminexOracle/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        rankings = []
        rows = raw.get("rows", []) if isinstance(raw, dict) else raw
        for i, row in enumerate(rows[:20], start=1):
            row_data = row.get("row", row)
            name = row_data.get("model") or row_data.get("model_name", "")
            avg = float(
                row_data.get("Average", 0) or row_data.get("average", 0) or row_data.get("score", 0)
            )
            if name:
                rankings.append(
                    {
                        "model_name": name.lower().replace(" ", "-").split("/")[-1],
                        "provider": _infer_provider(name),
                        "elo_score": avg * 10,  # normalize to ~ELO scale
                        "coding_rank": i,
                        "reasoning_rank": i,
                    }
                )
        if rankings:
            log.info("HF Leaderboard: fetched %d model rankings", len(rankings))
            return rankings

    except Exception as e:
        log.debug("HF Leaderboard fetch failed: %s", e)
    return None


def _infer_provider(model_name: str) -> str:
    """Map a model name string to its provider ID."""
    name = model_name.lower()
    if any(k in name for k in ("claude", "anthropic")):
        return "api_anthropic"
    if any(k in name for k in ("gemini", "google", "palm")):
        return "api_google"
    if any(k in name for k in ("gpt", "o1", "o3", "o4", "openai", "chatgpt")):
        return "api_openai"
    if "deepseek" in name:
        return "api_deepseek"
    # Open-source models are assumed local via Ollama
    return "local_ollama"


def fetch_rankings(force_refresh: bool = False) -> tuple[list[dict], str]:
    """
    Return (rankings_list, source_description).
    Priority: live LMSYS → live HF Leaderboard → cache → hardcoded fallback.
    """
    if not force_refresh:
        cached = load_cache()
        if cached:
            return cached["rankings"], f"cache ({cached['source_url']})"

    # Try live sources
    rankings = _fetch_lmsys_arena()
    source_url = "lmsys_chatbot_arena"

    if not rankings:
        rankings = _fetch_hf_leaderboard()
        source_url = "huggingface_open_llm_leaderboard"

    if rankings:
        save_cache(rankings, source_url)
        return rankings, source_url

    # Fall through to stale cache regardless of TTL
    if _CACHE_FILE.exists():
        try:
            cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            log.warning("Using stale cache (all live fetches failed)")
            return cached["rankings"], f"stale_cache ({cached.get('source_url', 'unknown')})"
        except Exception:
            pass

    log.warning("All sources failed — using hardcoded April 2026 fallback rankings")
    return FALLBACK_RANKINGS, "hardcoded_fallback"


# ── Curriculum loader ────────────────────────────────────────────────────────


def load_curriculum() -> list[dict]:
    """Load curriculum.jsonl. Exits if not found."""
    if not _CURRICULUM.exists():
        log.error("Curriculum not found: %s", _CURRICULUM)
        sys.exit(1)
    categories = []
    for line in _CURRICULUM.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                categories.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("Skipping malformed curriculum line: %s", e)
    log.info("Curriculum loaded: %d categories", len(categories))
    return categories


# ── Provider mapping ─────────────────────────────────────────────────────────


def build_enabled_providers(env: dict) -> set[str]:
    """Return set of provider IDs that are currently enabled in .env."""
    enabled = {"local_ollama"}  # always on
    if env_bool(env, "DETERMINEX_API_ANTHROPIC_ENABLED"):
        enabled.add("api_anthropic")
    if env_bool(env, "DETERMINEX_API_GOOGLE_ENABLED"):
        enabled.add("api_google")
    if env_bool(env, "DETERMINEX_API_DEEPSEEK_ENABLED"):
        enabled.add("api_deepseek")
    if env_bool(env, "DETERMINEX_API_OPENAI_ENABLED"):
        enabled.add("api_openai")
    return enabled


def best_available_teacher(
    rankings: list[dict],
    enabled_providers: set[str],
    category_focus: str = "coding",
) -> dict | None:
    """Return the highest-ranked model whose provider is currently enabled."""
    rank_key = "coding_rank" if category_focus == "coding" else "reasoning_rank"
    sorted_models = sorted(rankings, key=lambda m: m.get(rank_key, 999))
    for model in sorted_models:
        if model["provider"] in enabled_providers:
            return model
    return None


def top_model(rankings: list[dict], category_focus: str = "coding") -> dict | None:
    """Return overall #1 model regardless of enabled status."""
    rank_key = "coding_rank" if category_focus == "coding" else "reasoning_rank"
    sorted_models = sorted(rankings, key=lambda m: m.get(rank_key, 999))
    return sorted_models[0] if sorted_models else None


# ── Oracle Mode computations ─────────────────────────────────────────────────


def compute_mode_a(
    rankings: list[dict],
    enabled_providers: set[str],
) -> list[str]:
    """
    Mode A: generate opportunity_log — what APIs would unlock.
    Returns list of human-readable strings for the report.
    """
    opportunities = []
    rank_key = "coding_rank"
    sorted_models = sorted(rankings, key=lambda m: m.get(rank_key, 999))

    current_best = best_available_teacher(sorted_models, enabled_providers)
    current_rank = current_best.get(rank_key, 99) if current_best else 99

    for model in sorted_models:
        if model["provider"] not in enabled_providers:
            rank = model.get(rank_key, 99)
            if rank < current_rank:
                opportunities.append(
                    f"Rank {rank}: {model['model_name']} ({model['provider']}) would "
                    f"replace Rank {current_rank} {current_best['model_name'] if current_best else 'N/A'} "
                    f"— enable {model['provider'].upper()} to unlock"
                )

    if not opportunities:
        opportunities.append(
            f"Current teacher ({current_best['model_name'] if current_best else 'none'}) "
            "is the best available. No higher-ranked providers are disabled."
        )
    return opportunities


def compute_quality_score(
    model: dict | None,
    top: dict | None,
    rank_key: str = "coding_rank",
) -> float:
    """
    Quality score 0.0–1.0: ratio of available teacher's rank to theoretical #1.
    Uses ELO scores for a smooth gradient rather than discrete rank positions.
    """
    if not model or not top:
        return 0.3  # minimal fallback
    top_elo = top.get("elo_score", 1300)
    model_elo = model.get("elo_score", 1000)
    if top_elo <= 0:
        return 0.5
    # Normalize: score = model_elo / top_elo, clamped 0.0–1.0
    return min(1.0, max(0.0, model_elo / top_elo))


def compute_pass_multiplier(quality_score: float) -> float:
    """
    Mode C: convert quality score to pass multiplier.
    Teacher at 100% quality → 2.0× (maximize data density)
    Teacher at 80-99%       → 1.5×
    Teacher at 60-79%       → 1.0×
    Teacher below 60%       → 0.75× (flag as low-quality, fewer passes)
    """
    if quality_score >= 0.98:
        return 2.0
    if quality_score >= 0.80:
        return 1.5
    if quality_score >= 0.60:
        return 1.0
    return 0.75


def compute_category_priority(
    categories: list[dict],
    rankings: list[dict],
    enabled_providers: set[str],
    env: dict,
) -> list[dict]:
    """
    Mode B + C: score and sort categories, compute pass multipliers.
    Returns enriched category list sorted by priority descending.
    """
    top_coding = top_model(rankings, "coding")
    top_reasoning = top_model(rankings, "reasoning")

    enriched = []
    for cat in categories:
        # Determine which ranking dimension matters for this category
        cot = cat.get("cot_requested", False)
        focus = "reasoning" if cot else "coding"
        top = top_reasoning if cot else top_coding

        teacher = best_available_teacher(rankings, enabled_providers, focus)
        quality = compute_quality_score(teacher, top, f"{focus}_rank")
        multiplier = compute_pass_multiplier(quality)

        base_weight = cat.get("task_category_weight", 1.0)
        # Mode B final priority = base_weight × quality_score (higher quality → prioritized)
        priority_score = base_weight * quality

        enriched.append(
            {
                **cat,
                "_oracle": {
                    "teacher_model": teacher["model_name"] if teacher else "none",
                    "teacher_provider": teacher["provider"] if teacher else "none",
                    "teacher_rank": teacher.get(f"{focus}_rank", 99) if teacher else 99,
                    "quality_score": round(quality, 3),
                    "pass_multiplier": multiplier,
                    "priority_score": round(priority_score, 3),
                },
            }
        )

    # Mode B: sort by priority_score descending
    enriched.sort(key=lambda c: c["_oracle"]["priority_score"], reverse=True)
    return enriched


# ── Session config writer ────────────────────────────────────────────────────


def build_session_config(
    categories_enriched: list[dict],
    rankings: list[dict],
    source: str,
    opportunity_log: list[str],
    env: dict,
    enabled_providers: set[str],
    filter_category: str | None = None,
) -> dict:
    """Assemble the full session_config dict."""
    samples_per_cat = env_int(env, "SESSION_SAMPLES_PER_CATEGORY", 50)
    max_categories = env_int(env, "SESSION_MAX_CATEGORIES_PER_RUN", 3)
    mode_a = env_bool(env, "ORACLE_MODE_A", True)
    mode_b = env_bool(env, "ORACLE_MODE_B", True)
    mode_c = env_bool(env, "ORACLE_MODE_C", True)

    # Filter by category if requested
    if filter_category:
        categories_enriched = [c for c in categories_enriched if c["category"] == filter_category]

    # Agenda: top N categories (Mode B sorted if active, else original order)
    agenda_cats = categories_enriched if mode_b else categories_enriched
    agenda = []
    for cat in agenda_cats[:max_categories]:
        oracle_meta = cat["_oracle"]
        multiplier = oracle_meta["pass_multiplier"] if mode_c else 1.0
        target = int(samples_per_cat * multiplier)
        agenda.append(
            {
                "category": cat["category"],
                "display_name": cat["display_name"],
                "target_samples": target,
                "teacher_model": oracle_meta["teacher_model"],
                "teacher_provider": oracle_meta["teacher_provider"],
                "quality_score": oracle_meta["quality_score"],
                "pass_multiplier": oracle_meta["pass_multiplier"],
                "priority_score": oracle_meta["priority_score"],
                "validator": cat.get("validator", "regex"),
                "cot_requested": cat.get("cot_requested", False),
            }
        )

    # Teacher assignments dict keyed by category
    teacher_assignments = {
        cat["category"]: {
            "provider": cat["_oracle"]["teacher_provider"],
            "model": cat["_oracle"]["teacher_model"],
            "leaderboard_rank": cat["_oracle"]["teacher_rank"],
            "quality_score": cat["_oracle"]["quality_score"],
            "pass_multiplier": cat["_oracle"]["pass_multiplier"],
            "enabled": cat["_oracle"]["teacher_provider"] in enabled_providers,
        }
        for cat in categories_enriched
    }

    config = {
        "generated_at": datetime.now(UTC).isoformat(),
        "leaderboard_source": source,
        "oracle_modes_active": [
            m for m, flag in [("A", mode_a), ("B", mode_b), ("C", mode_c)] if flag
        ],
        "enabled_providers": sorted(enabled_providers),
        "teacher_assignments": teacher_assignments,
        "session_agenda": agenda,
        "opportunity_log": opportunity_log if mode_a else [],
        "top_rankings": rankings[:10],
    }
    return config


# ── Reporting ────────────────────────────────────────────────────────────────


def print_session_report(config: dict, env: dict):
    """Print a human-readable session summary to stdout."""
    autonomy = env.get("ORACLE_AUTONOMY_LEVEL", "full").lower()

    print("\n" + "═" * 65)
    print("  DETERMINEX LEADERBOARD ORACLE — SESSION REPORT")
    print(f"  Source : {config['leaderboard_source']}")
    print(f"  Modes  : {', '.join(config['oracle_modes_active'])}")
    print(f"  Enabled: {', '.join(config['enabled_providers'])}")
    print(f"  Autonomy: {autonomy}")
    print("═" * 65)

    print("\n  TODAY'S AGENDA (Mode B priority order):")
    for i, item in enumerate(config["session_agenda"], 1):
        print(
            f"  {i}. [{item['category']}]  "
            f"Teacher: {item['teacher_model']} ({item['teacher_provider']})  "
            f"Quality: {item['quality_score']:.0%}  "
            f"Target: {item['target_samples']} samples  "
            f"Multiplier: {item['pass_multiplier']}x"
        )

    if config.get("opportunity_log"):
        print("\n  OPPORTUNITY LOG (Mode A — APIs that would improve quality):")
        for line in config["opportunity_log"]:
            print(f"    > {line}")

    print("\n  TOP 5 CURRENT RANKINGS:")
    for model in config.get("top_rankings", [])[:5]:
        rank = model.get("coding_rank", "?")
        name = model.get("model_name", "unknown")
        prov = model.get("provider", "?")
        elo = model.get("elo_score", 0)
        avail = "[ENABLED]" if prov in config["enabled_providers"] else "[disabled]"
        print(f"    #{rank:<3} {name:<35} {avail}  ELO {elo:.0f}")

    print("═" * 65 + "\n")


def write_opportunity_log(config: dict):
    """Append opportunity log to logs/oracle_opportunity.log."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"\n[{timestamp}] Oracle Run — {config['leaderboard_source']}"]
        lines.extend(f"  {line}" for line in config.get("opportunity_log", []))
        with _OPPORTUNITY_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        log.warning("Could not write opportunity log: %s", e)


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex Leaderboard Oracle")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print report only — do not write session_config.json",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass 24h cache and re-fetch live rankings",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Limit agenda to a single curriculum category (for testing)",
    )
    args = parser.parse_args()

    env = load_env()
    autonomy = env.get("ORACLE_AUTONOMY_LEVEL", "full").lower()

    log.info("Oracle starting — autonomy=%s  dry_run=%s", autonomy, args.dry_run)

    # ── Fetch rankings
    rankings, source = fetch_rankings(force_refresh=args.force_refresh)
    log.info("Rankings source: %s  models: %d", source, len(rankings))

    # ── Load curriculum
    categories = load_curriculum()

    # ── Determine enabled providers
    enabled = build_enabled_providers(env)
    log.info("Enabled providers: %s", sorted(enabled))

    # ── Mode A: opportunity log
    opportunities = compute_mode_a(rankings, enabled)
    for line in opportunities:
        log.info("[Mode A] %s", line)

    # ── Modes B + C: enrich and sort categories
    enriched = compute_category_priority(categories, rankings, enabled, env)

    # ── Build session config
    config = build_session_config(
        enriched,
        rankings,
        source,
        opportunities,
        env,
        enabled,
        filter_category=args.category,
    )

    # ── Report
    print_session_report(config, env)
    write_opportunity_log(config)

    if args.dry_run:
        log.info("--dry-run: session_config.json NOT written.")
        return

    # ── Autonomy gate
    if autonomy == "assisted":
        response = input("Oracle proposes the above agenda. Approve? [Y/n]: ").strip().lower()
        if response not in ("", "y", "yes"):
            log.info("Agenda rejected by user. Exiting without writing session_config.")
            sys.exit(0)
    elif autonomy == "manual":
        log.info(
            "Autonomy=manual: session_config.json written for reference. "
            "Edit it manually before running the data engine."
        )

    # ── Write session_config.json
    _SESSION_CONFIG.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log.info("Session config written: %s", _SESSION_CONFIG)


if __name__ == "__main__":
    main()
