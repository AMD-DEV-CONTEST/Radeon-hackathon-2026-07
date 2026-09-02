"""
patch_retrain_whitelists.py
============================
LESSON LEARNED (2026-04-14):
  All three retrain scripts used DATA_DIR.glob("*.jsonl") which loaded
  EVERY jsonl in /workspace/data/ into EVERY model's training run.
  This caused cross-contamination:
    - Engineer got Observer-specific + Sentinel-specific gap data
    - Observer got Sentinel-specific + Engineer-only gap data
    - Sentinel got Observer-specific data
  Result: catastrophic forgetting across all three models (Engineer dropped 60% -> 18%).

FIX: Each model now has an explicit whitelist of ONLY the files it should see.
LOCK: Never use glob("*.jsonl") for model training. Always explicit whitelists.
"""

from pathlib import Path

# =============================================================================
# CANONICAL PER-MODEL DATA WHITELISTS
# =============================================================================
# RULE: When adding new gap curriculum files, explicitly add them to ONLY the
#       model(s) they target. Never add to all three blindly.
# RULE: General distillation files (claude, gemini) go to ALL models.
# RULE: distilled_observer.jsonl is Rust-only curriculum -- Engineer + Observer only.
# RULE: targeted_gaps.jsonl is general multi-language -- Engineer + Sentinel only.
#
# FILE OWNERSHIP MAP:
#   determinex_v1_distilled_claude.jsonl    -> ALL  (general multi-language)
#   determinex_v1_distilled_gemini.jsonl    -> ALL  (general multi-language)
#   determinex_v1_distilled_observer.jsonl  -> Observer ONLY (330 Rust-specific samples)
#   determinex_v1_targeted_gaps.jsonl       -> Engineer, Sentinel (multi-lang gap fixes)
#   gap_v3_arc_mutex.jsonl               -> ALL  (shared Rust concurrency gap)
#   gap_v3_go_panic.jsonl                -> Engineer ONLY (Go-specific gap)
#   gap_v4_observer_specific.jsonl       -> Observer ONLY (refcell, first_even, go_panic fmt)
#   gap_v4_sentinel_specific.jsonl       -> Sentinel ONLY (refcell rename, planning gaps)
# =============================================================================

WHITELISTS = {
    "/workspace/fix_retrain_engineer.py": [
        "determinex_v1_distilled_claude.jsonl",  # general multi-language distillation
        "determinex_v1_distilled_gemini.jsonl",  # general multi-language distillation
        "determinex_v1_targeted_gaps.jsonl",  # multi-lang gap fixes for codegen
        "gap_v3_arc_mutex.jsonl",  # shared: Rust arc/mutex concurrency
        "gap_v3_go_panic.jsonl",  # Engineer-only: Go panic/recover
        # EXCLUDED: determinex_v1_distilled_observer.jsonl -- 330 Rust-only samples, skews language balance
        # EXCLUDED: gap_v4_observer_specific.jsonl -- critique/review format, wrong signal for codegen
        # EXCLUDED: gap_v4_sentinel_specific.jsonl -- planning format, wrong signal for codegen
    ],
    "/workspace/fix_retrain_observer.py": [
        "determinex_v1_distilled_claude.jsonl",  # general multi-language distillation
        "determinex_v1_distilled_gemini.jsonl",  # general multi-language distillation
        "determinex_v1_distilled_observer.jsonl",  # Observer-specific: 330 Rust curriculum samples
        "gap_v3_arc_mutex.jsonl",  # shared: Rust arc/mutex concurrency
        "gap_v4_observer_specific.jsonl",  # Observer-only: refcell, first_even, go_panic fmt
        # EXCLUDED: determinex_v1_targeted_gaps.jsonl -- codegen format, wrong signal for critique model
        # EXCLUDED: gap_v3_go_panic.jsonl -- codegen format, not critique examples
        # EXCLUDED: gap_v4_sentinel_specific.jsonl -- planning format, wrong for Observer
    ],
    "/workspace/fix_retrain_sentinel.py": [
        "determinex_v1_distilled_claude.jsonl",  # general multi-language distillation
        "determinex_v1_distilled_gemini.jsonl",  # general multi-language distillation
        "determinex_v1_targeted_gaps.jsonl",  # multi-lang gap fixes, planning-compatible
        "gap_v3_arc_mutex.jsonl",  # shared: Rust arc/mutex concurrency
        "gap_v4_sentinel_specific.jsonl",  # Sentinel-only: refcell rename, planning patterns
        # EXCLUDED: determinex_v1_distilled_observer.jsonl -- Rust-only, skews Sentinel language balance
        # EXCLUDED: gap_v3_go_panic.jsonl -- codegen format, wrong signal for planner
        # EXCLUDED: gap_v4_observer_specific.jsonl -- critique format, wrong for Sentinel
    ],
}

# The exact glob line in all three scripts that caused the contamination
BAD_GLOB = 'for f in sorted(DATA_DIR.glob("*.jsonl")):'


def patch_script(script_path: str, whitelist: list):
    p = Path(script_path)
    if not p.exists():
        print(f"[SKIP] Not found locally: {script_path}")
        return False

    src = p.read_text(encoding="utf-8")

    if BAD_GLOB not in src:
        print(f"[WARN] Bad glob pattern not found in {p.name} -- already patched?")
        return False

    # Build safe whitelist loader replacing the glob
    wl_lines = "\n".join(f'        "{f}",' for f in whitelist)
    new_loader = f"""# LOCKED WHITELIST -- do NOT replace with glob("*.jsonl").
    # Adding a new gap file? Add it to patch_retrain_whitelists.py and document ownership above.
    WHITELIST = [
{wl_lines}
    ]
    for fname in WHITELIST:
        f = DATA_DIR / fname
        if not f.exists():
            print(f"  [WARN] Whitelist file not found: {{f}}", flush=True)
            continue"""

    src = src.replace(BAD_GLOB, new_loader)
    p.write_text(src, encoding="utf-8")
    print(f"[OK] Patched {p.name} with {len(whitelist)}-file whitelist")
    return True


if __name__ == "__main__":
    # Patch local copies in scripts/ if they exist,
    # otherwise just print the patch content for manual SCP
    local_map = {
        "/workspace/fix_retrain_engineer.py": Path("scripts/fix_retrain_engineer.py"),
        "/workspace/fix_retrain_observer.py": Path("scripts/fix_retrain_observer.py"),
        "/workspace/fix_retrain_sentinel.py": Path("scripts/fix_retrain_sentinel.py"),
    }

    for pod_path, whitelist in WHITELISTS.items():
        local = local_map[pod_path]
        if local.exists():
            patch_script(str(local), whitelist)
        else:
            print(f"[INFO] {local} not found locally -- will patch on pod via SCP")

    print(
        "\nDone. Next: SCP patched scripts to pod, then retrain in order: Engineer -> Observer -> Sentinel"
    )
    print("SAFE RETRAIN ORDER:")
    print("  1. Engineer (1.5B Qwen, ~45 min) -- clear only Qwen cache before start")
    print("  2. Observer (3B Llama, ~60 min)  -- clear Qwen cache, keep Llama")
    print("  3. Sentinel (7B Mistral, ~90 min) -- clear Llama cache, keep or re-dl Mistral")
    print("\nPRE-RETRAIN CHECKLIST (run before EACH model):")
    print("  [ ] df -h / -- root must have >10GB free")
    print("  [ ] df -h /tmp -- must have >8GB free")
    print("  [ ] ps aux | grep python3 -- no other training running")
    print("  [ ] EVAL OLD GGUF BEFORE OVERWRITING -- never rm old model before comparing scores")
