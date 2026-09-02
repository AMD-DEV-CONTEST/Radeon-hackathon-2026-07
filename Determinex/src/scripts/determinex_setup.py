"""
determinex_setup.py — Determinex User-Specific Setup Wizard

One-time interactive setup that:
  1. Detects your hardware (VRAM, RAM, CPU threads)
  2. Asks which models you have in Ollama
  3. Configures API access (all optional / gated)
  4. Sets GPU throttle preferences (nvidia-smi power limit)
  5. Configures training aggressiveness (batch size, epochs, seq len)
  6. Writes determinex_user_config.json  (used by all pipeline scripts)
  7. Patches .env with your model routing and API keys

Usage:
    python scripts/determinex_setup.py
    python scripts/determinex_setup.py --reconfigure      # re-run all prompts
    python scripts/determinex_setup.py --show             # print current config
    python scripts/determinex_setup.py --apply-throttle   # apply GPU power cap now
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
_CONFIG_FILE = _ROOT / "determinex_user_config.json"
_ENV_FILE = _ROOT / ".env"


# ── colour helpers ────────────────────────────────────────────────────────────
def _c(text, code):
    return f"\033[{code}m{text}\033[0m"


def green(t):
    return _c(t, "92")


def yellow(t):
    return _c(t, "93")


def cyan(t):
    return _c(t, "96")


def bold(t):
    return _c(t, "1")


def dim(t):
    return _c(t, "2")


def ask(prompt, default="", choices=None):
    """Single prompt with optional choices validation."""
    choice_str = f" [{'/'.join(choices)}]" if choices else ""
    default_str = f" (default: {default})" if default else ""
    while True:
        raw = input(f"  {cyan('?')} {prompt}{choice_str}{default_str}: ").strip()
        val = raw or default
        if choices and val.lower() not in [c.lower() for c in choices]:
            print(f"    {yellow('!')} Please enter one of: {', '.join(choices)}")
            continue
        return val


def ask_bool(prompt, default=True):
    default_str = "Y/n" if default else "y/N"
    raw = input(f"  {cyan('?')} {prompt} [{default_str}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def section(title):
    print(f"\n{bold('─' * 60)}")
    print(f"  {bold(title)}")
    print(f"{bold('─' * 60)}")


# ── Hardware detection ────────────────────────────────────────────────────────


def detect_hardware():
    hw = {"gpu_name": "Unknown", "vram_mb": 0, "ram_gb": 0, "cpu_threads": os.cpu_count() or 4}

    # GPU via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            hw["gpu_name"] = parts[0].strip()
            hw["vram_mb"] = int(parts[1].strip())
    except Exception:
        pass

    # RAM
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        mem = ctypes.c_ulonglong(0)
        kernel.GetPhysicallyInstalledSystemMemory(ctypes.byref(mem))
        hw["ram_gb"] = round(mem.value / 1024 / 1024)
    except Exception:
        try:
            result = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip().isdigit()]
            if lines:
                hw["ram_gb"] = round(int(lines[0]) / 1024 / 1024 / 1024)
        except Exception:
            pass

    return hw


def get_ollama_models():
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()[1:]  # skip header
            return [l.split()[0] for l in lines if l.strip()]
    except Exception:
        pass
    return []


def get_gpu_default_power():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.default_limit", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return round(float(result.stdout.strip()))
    except Exception:
        pass
    return 120


# ── Training profile presets ──────────────────────────────────────────────────

TRAINING_PROFILES = {
    "safe": {
        "label": "Safe (61°C max, ~40% GPU, takes 2x longer)",
        "epochs": 1,
        "batch": 1,
        "grad_accum": 8,
        "max_seq": 512,
        "power_cap": 70,
    },
    "balanced": {
        "label": "Balanced (75°C max, ~70% GPU, recommended)",
        "epochs": 1,
        "batch": 1,
        "grad_accum": 4,
        "max_seq": 1024,
        "power_cap": 90,
    },
    "full": {
        "label": "Full throttle (85°C, 98% GPU, fastest — max heat)",
        "epochs": 1,
        "batch": 1,
        "grad_accum": 4,
        "max_seq": 2048,
        "power_cap": None,  # no cap
    },
    "custom": {
        "label": "Custom — I'll enter everything manually",
        "epochs": None,
        "batch": None,
        "grad_accum": None,
        "max_seq": None,
        "power_cap": None,
    },
}

# ── .env helpers ──────────────────────────────────────────────────────────────


def load_env():
    env = {}
    if not _ENV_FILE.exists():
        return env
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def write_env_key(key, value):
    """Update or append a key=value pair in .env without disturbing other lines."""
    if not _ENV_FILE.exists():
        _ENV_FILE.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip() == f"{key}=":
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Main setup flow ────────────────────────────────────────────────────────────


def install_git_hooks() -> list[str]:
    """Install the repo's tracked git hooks (scripts/git-hooks/) into
    .git/hooks/ -- these previously only ever existed as local, untracked
    files in whoever's .git/hooks/ happened to have them by hand, so they
    silently never survived a fresh clone (found 2026-07-20 while wiring a
    post-commit hook that keeps the corpus semantic embeddings cache in
    sync: the pre-existing pre-commit integrity gate for
    corpus/programbench/eval_index.json had the exact same problem and was
    never noticed because whoever's machine had it already just kept working).
    Safe to call repeatedly -- always overwrites with the tracked version,
    never merges with anything a user hand-edited into their local hook."""
    src_dir = _SCRIPTS_DIR / "git-hooks"
    dst_dir = _ROOT / ".git" / "hooks"
    installed = []
    if not src_dir.is_dir() or not dst_dir.is_dir():
        return installed
    for src in sorted(src_dir.iterdir()):
        if not src.is_file():
            continue
        dst = dst_dir / src.name
        dst.write_bytes(src.read_bytes())
        try:
            os.chmod(dst, 0o755)
        except OSError:
            pass
        installed.append(src.name)
    return installed


def run_setup(reconfigure=False):
    existing = {}
    if _CONFIG_FILE.exists() and not reconfigure:
        try:
            existing = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    print(f"\n{bold('═' * 60)}")
    print(f"  {bold('DETERMINEX — User Setup Wizard')}")
    print("  Configures training, models, APIs, and GPU safety for YOUR hardware.")
    print(f"{bold('═' * 60)}")

    hooks = install_git_hooks()
    if hooks:
        print(f"  {green('✓')} Git hooks installed: {', '.join(hooks)}")

    # ── Section 1: Hardware ──────────────────────────────────────────────────
    section("1 / 5 — Detecting Hardware")
    hw = detect_hardware()
    print(f"  {green('✓')} GPU   : {hw['gpu_name']} ({hw['vram_mb']} MB VRAM)")
    print(f"  {green('✓')} RAM   : {hw['ram_gb']} GB")
    print(f"  {green('✓')} CPU   : {hw['cpu_threads']} logical threads")

    # Derive safe defaults from hardware
    vram_gb = hw["vram_mb"] / 1024
    default_seq = 512 if vram_gb < 6 else 1024 if vram_gb < 8 else 2048
    default_profile = "balanced" if vram_gb >= 6 else "safe"

    section("2 / 5 — Model Routing")
    print(f"  {cyan('Building local Ollama model fleet (this may take a few moments)...')}")
    try:
        subprocess.run(
            [
                "ollama",
                "create",
                "determinex-engineer",
                "-f",
                "rosetta/modelfiles/Modelfile.engineer",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "ollama",
                "create",
                "determinex-observer",
                "-f",
                "rosetta/modelfiles/Modelfile.observer",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "ollama",
                "create",
                "determinex-sentinel",
                "-f",
                "rosetta/modelfiles/Modelfile.sentinel",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"  {yellow('!')} Failed to auto-create models: {e}")

    ollama_models = get_ollama_models()
    if ollama_models:
        print(f"  Ollama models found ({len(ollama_models)}):")
        for m in ollama_models:
            print(f"    {dim('·')} {m}")
    else:
        print(f"  {yellow('!')} No Ollama models found (is Ollama running?)")

    # Default selections from .env if they exist
    env = load_env()
    default_engineer = existing.get(
        "engineer_model", env.get("DETERMINEX_ENGINEER_MODEL", "determinex-engineer-v10-dsl")
    )
    default_observer = existing.get(
        "observer_model", env.get("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v5-dsl")
    )
    default_sentinel = existing.get(
        "sentinel_model", env.get("DETERMINEX_SENTINEL_MODEL", "determinex-sentinel-v3")
    )
    default_leviathan = existing.get(
        "leviathan_model", env.get("DETERMINEX_LEVIATHAN_MODEL", "determinex-leviathan:v1")
    )

    print()
    engineer_model = ask("Engineer model (code generation, 4-7B)", default_engineer)
    observer_model = ask("Observer model (reasoning/critique, 2-3B)", default_observer)
    sentinel_model = ask("Sentinel model (security/guard, 2B)", default_sentinel)
    leviathan_model = ask("Leviathan model (teacher, CPU RAM, 8-14B)", default_leviathan)

    # ── Section 3: Cloud APIs ────────────────────────────────────────────────
    section("3 / 5 — Cloud API Access")
    print(f"  {dim('All API keys are optional. Leave blank to stay local-only.')}")
    print(f"  {dim('Keys are stored in .env — never committed to git.')}")
    print()

    current_anthropic = env.get("ANTHROPIC_API_KEY", "")
    current_gemini = env.get("GEMINI_API_KEY", "")
    current_openai = env.get("OPENAI_API_KEY", "")

    use_anthropic = ask_bool(
        "Anthropic (Claude) API — do you have access?", default=bool(current_anthropic)
    )
    if use_anthropic:
        if current_anthropic:
            print(f"    {dim('Current key: ' + current_anthropic[:12] + '...')}")
        anthropic_key = ask("Anthropic API key (paste or press Enter to keep)", current_anthropic)
    else:
        anthropic_key = ""

    use_gemini = ask_bool("Google (Gemini) API — do you have access?", default=bool(current_gemini))
    if use_gemini:
        gemini_key = ask("Gemini API key", current_gemini)
    else:
        gemini_key = ""

    use_openai = ask_bool("OpenAI API — do you have access?", default=bool(current_openai))
    if use_openai:
        openai_key = ask("OpenAI API key", current_openai)
    else:
        openai_key = ""

    # ── Section 4: Training Profile ──────────────────────────────────────────
    section("4 / 5 — Training Profile")
    gpu_name = hw["gpu_name"]
    print(f"  {dim(f'Your GPU: {gpu_name} | {vram_gb:.1f} GB VRAM')}")
    print()
    for k, v in TRAINING_PROFILES.items():
        marker = green("→") if k == default_profile else " "
        print(f"  {marker} {bold(k):<12} {v['label']}")
    print()

    profile_key = ask(
        "Choose a training profile", default_profile, choices=list(TRAINING_PROFILES.keys())
    ).lower()
    profile = TRAINING_PROFILES[profile_key]

    if profile_key == "custom":
        epochs = int(ask("Epochs per forge run", existing.get("epochs", "1")))
        batch = int(ask("Per-device batch size", existing.get("batch_size", "1")))
        grad_acc = int(ask("Gradient accumulation steps", existing.get("grad_accum", "4")))
        max_seq = int(
            ask("Max sequence length (tokens)", existing.get("max_seq_length", str(default_seq)))
        )
        power_raw = ask("GPU power cap in watts (0 = no cap)", existing.get("power_cap_watts", "0"))
        power_cap = int(power_raw) if power_raw.isdigit() and int(power_raw) > 0 else None
    else:
        epochs = profile["epochs"]
        batch = profile["batch"]
        grad_acc = profile["grad_accum"]
        max_seq = profile["max_seq"] or default_seq
        power_cap = profile["power_cap"]

    # ── Section 5: Data Engine ───────────────────────────────────────────────
    section("5 / 5 — Data Engine Preferences")

    oracle_autonomy = ask(
        "Oracle autonomy mode",
        existing.get("oracle_autonomy", "full"),
        choices=["full", "confirm", "off"],
    )
    samples_per_run = int(
        ask("Samples to generate per category per run", str(existing.get("samples_per_run", "50")))
    )
    mix_general = ask_bool(
        "Mix Alpaca general data during training (prevents catastrophic forgetting)?",
        existing.get("mix_general", True),
    )
    curriculum_ratio = float(
        ask(
            "Curriculum-to-general data ratio (0.0-1.0)",
            str(existing.get("curriculum_ratio", "0.8")),
        )
    )

    # ── Build config ─────────────────────────────────────────────────────────
    config = {
        "schema_version": "1.0",
        "user_configured": True,
        # Hardware profile
        "hardware": hw,
        # Model routing
        "engineer_model": engineer_model,
        "observer_model": observer_model,
        "sentinel_model": sentinel_model,
        "leviathan_model": leviathan_model,
        # API access
        "api_anthropic_enabled": use_anthropic,
        "api_google_enabled": use_gemini,
        "api_openai_enabled": use_openai,
        # Training profile
        "training_profile": profile_key,
        "epochs": epochs,
        "batch_size": batch,
        "grad_accum": grad_acc,
        "max_seq_length": max_seq,
        "power_cap_watts": power_cap,
        # Data engine
        "oracle_autonomy": oracle_autonomy,
        "samples_per_run": samples_per_run,
        "mix_general": mix_general,
        "curriculum_ratio": curriculum_ratio,
    }

    # ── Write config ─────────────────────────────────────────────────────────
    _CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"\n  {green('✓')} Config saved: {_CONFIG_FILE}")

    # ── Patch .env ───────────────────────────────────────────────────────────
    write_env_key("DETERMINEX_ENGINEER_MODEL", engineer_model)
    write_env_key("DETERMINEX_OBSERVER_MODEL", observer_model)
    write_env_key("DETERMINEX_SENTINEL_MODEL", sentinel_model)
    write_env_key("DETERMINEX_LEVIATHAN_MODEL", leviathan_model)

    write_env_key("ANTHROPIC_API_KEY", anthropic_key)
    write_env_key("GEMINI_API_KEY", gemini_key)
    write_env_key("OPENAI_API_KEY", openai_key)

    # DETERMINEX_ prefix, not CITADEL_ -- the real functional consumer
    # (leaderboard_oracle.py's env_bool checks) reads DETERMINEX_API_*_ENABLED;
    # writing CITADEL_ here meant a user's provider choice during setup was
    # silently never picked up (found 2026-07-19 in a systematic rename-
    # split-brain sweep).
    write_env_key("DETERMINEX_API_ANTHROPIC_ENABLED", "true" if use_anthropic else "false")
    write_env_key("DETERMINEX_API_GOOGLE_ENABLED", "true" if use_gemini else "false")
    write_env_key("DETERMINEX_API_OPENAI_ENABLED", "true" if use_openai else "false")

    print(f"  {green('✓')} .env updated with model routing and API gate flags")

    # ── Apply GPU power cap ───────────────────────────────────────────────────
    if power_cap:
        apply = ask_bool(f"\nApply GPU power cap now? ({power_cap}W)", default=True)
        if apply:
            apply_gpu_throttle(power_cap)
    else:
        print(f"\n  {dim('No GPU power cap set. Full throttle during training.')}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{bold('═' * 60)}")
    print(f"  {green('SETUP COMPLETE')}")
    print(f"{bold('─' * 60)}")
    print(
        f"  Profile    : {bold(profile_key.upper())}  —  {TRAINING_PROFILES[profile_key]['label']}"
    )
    print(f"  Seq length : {max_seq} tokens  |  batch {batch}x{grad_acc} grad_accum")
    print(f"  GPU cap    : {f'{power_cap}W' if power_cap else 'unlimited'}")
    print(f"  APIs       : {_api_summary(use_anthropic, use_gemini, use_openai)}")
    print(f"  Oracle     : {oracle_autonomy} autonomy  |  {samples_per_run} samples/category")
    print(f"  Mix general: {'yes' if mix_general else 'no'}  |  ratio {curriculum_ratio}")
    print("\n  Run your next training session with:")
    train_cmd = _build_train_cmd(config)
    print(f"  {cyan(train_cmd)}")
    print("\n  Or use the data engine:")
    print(f"  {cyan('python -m scripts.deepseek_data_engine')}")
    print(f"{bold('═' * 60)}\n")


def _api_summary(anthropic, gemini, openai):
    parts = []
    if anthropic:
        parts.append(green("Claude"))
    if gemini:
        parts.append(green("Gemini"))
    if openai:
        parts.append(green("OpenAI"))
    if not parts:
        return yellow("local-only")
    return " + ".join(parts) + dim(" (enabled)")


def _build_train_cmd(cfg):
    args = [
        "python determinex_trainer/train_unsloth.py",
        f"--epochs {cfg['epochs']}",
        f"--max_seq_length {cfg['max_seq_length']}",
        f"--per_device_batch_size {cfg['batch_size']}",
        f"--grad_accum {cfg['grad_accum']}",
    ]
    if cfg.get("mix_general"):
        ratio = cfg.get("curriculum_ratio", 0.8)
        args.append(f"--mix-general --curriculum-ratio {ratio}")
    return " ".join(args)


# ── GPU throttle ──────────────────────────────────────────────────────────────


def apply_gpu_throttle(watts):
    try:
        result = subprocess.run(
            ["nvidia-smi", "-pl", str(watts)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"  {green('✓')} GPU power capped to {watts}W")
        else:
            print(f"  {yellow('!')} nvidia-smi failed: {result.stderr.strip()[:100]}")
            print(f"  {dim('Tip: Run PowerShell as Administrator for nvidia-smi power control')}")
    except FileNotFoundError:
        print(f"  {yellow('!')} nvidia-smi not found on PATH")


def restore_gpu_power():
    default = get_gpu_default_power()
    print(f"  Restoring GPU to default TDP ({default}W)...")
    apply_gpu_throttle(default)


# ── Show config ────────────────────────────────────────────────────────────────


def show_config():
    if not _CONFIG_FILE.exists():
        print(f"\n  {yellow('!')} No config found. Run:  python scripts/determinex_setup.py")
        return
    cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    print(f"\n{bold('═' * 60)}")
    print(f"  {bold('DETERMINEX USER CONFIG')}  —  {_CONFIG_FILE}")
    print(f"{bold('─' * 60)}")
    hw = cfg.get("hardware", {})
    print(f"  GPU         : {hw.get('gpu_name', '?')} ({hw.get('vram_mb', 0)} MB VRAM)")
    print(f"  RAM         : {hw.get('ram_gb', '?')} GB")
    print()
    print(f"  Profile     : {cfg.get('training_profile', '?').upper()}")
    print(f"  Max seq     : {cfg.get('max_seq_length', '?')} tokens")
    print(f"  Batch       : {cfg.get('batch_size', '?')} × {cfg.get('grad_accum', '?')} grad_accum")
    print(f"  Epochs      : {cfg.get('epochs', '?')}")
    print(f"  GPU cap     : {cfg.get('power_cap_watts', 'unlimited')}")
    print()
    print(f"  Engineer    : {cfg.get('engineer_model', '?')}")
    print(f"  Observer    : {cfg.get('observer_model', '?')}")
    print(f"  Sentinel    : {cfg.get('sentinel_model', '?')}")
    print(f"  Leviathan   : {cfg.get('leviathan_model', '?')}")
    print()
    print(f"  Claude API  : {'enabled' if cfg.get('api_anthropic_enabled') else 'disabled'}")
    print(f"  Gemini API  : {'enabled' if cfg.get('api_google_enabled') else 'disabled'}")
    print(f"  OpenAI API  : {'enabled' if cfg.get('api_openai_enabled') else 'disabled'}")
    print()
    print(f"  Oracle mode : {cfg.get('oracle_autonomy', '?')}")
    print(f"  Samples/run : {cfg.get('samples_per_run', '?')}")
    print(f"  Mix general : {cfg.get('mix_general', '?')}")
    print(f"  Curriculum  : {cfg.get('curriculum_ratio', '?')}")
    print()
    print("  Recommended training command:")
    print(f"  {cyan(_build_train_cmd(cfg))}")
    print(f"{bold('═' * 60)}\n")


# ── User config loader (for other scripts to import) ──────────────────────────


def load_user_config() -> dict:
    """
    Load determinex_user_config.json. Returns empty dict if not configured.
    Import this in other scripts:
        from scripts.determinex_setup import load_user_config
        cfg = load_user_config()
        max_seq = cfg.get("max_seq_length", 2048)
    """
    if not _CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Determinex User Setup Wizard")
    parser.add_argument(
        "--reconfigure", action="store_true", help="Re-run all prompts (overwrites existing config)"
    )
    parser.add_argument("--show", action="store_true", help="Print current config and exit")
    parser.add_argument(
        "--apply-throttle", action="store_true", help="Apply saved GPU power cap now and exit"
    )
    parser.add_argument(
        "--restore-power", action="store_true", help="Restore GPU to default power limit"
    )
    args = parser.parse_args()

    if args.show:
        show_config()
        return

    if args.apply_throttle:
        cfg = load_user_config()
        cap = cfg.get("power_cap_watts")
        if cap:
            apply_gpu_throttle(cap)
        else:
            print(f"  {yellow('!')} No power cap in config. Run setup first.")
        return

    if args.restore_power:
        restore_gpu_power()
        return

    # Check if already configured
    if _CONFIG_FILE.exists() and not args.reconfigure:
        cfg = load_user_config()
        if cfg.get("user_configured"):
            print(
                f"\n  {green('✓')} Already configured. Use --show to view, --reconfigure to change."
            )
            show_config()
            return

    run_setup(reconfigure=args.reconfigure)


if __name__ == "__main__":
    main()
