r"""
rebuild_corpus.py — Rebuild combined_training.jsonl from all sources.

Sources:
  1. T: drive corpus (1.1M examples, 43 languages) — stratified at T_CAP per lang
  2. C:\Dev\Determinex\data\  — Determinex-specific specialized files

Output: data/combined_training.jsonl  (up to MAX_TOTAL examples, shuffled)
"""

import collections
import glob
import json
import os
import random
from pathlib import Path

T_CAP = 2000  # max examples per language from T: drive
MAX_TOTAL = 100_000  # hard cap (dsl_finetune also caps at 100K, but be explicit)

DATA_DIR = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).parent.parent)) / "data"
OUT_FILE = DATA_DIR / "combined_training.jsonl"

# T: drive corpus directories (all contain instruction/output/system examples)
#
# These were four literal strings containing the *shell* expression
# "${DETERMINEX_MODELS_DIR:-~/determinex-models}". Python does not expand shell syntax, so
# every path here resolved to a directory whose name was the source text -- this script
# scanned four folders that cannot exist and reported finding nothing, without erroring.
# Resolved the way sh would, using the same env-var pattern already on line 20 of this file.
_MODELS_DIR = Path(
    os.path.expanduser(os.environ.get("DETERMINEX_MODELS_DIR", "~/determinex-models"))
)
T_DIRS = [
    str(_MODELS_DIR / "corpus" / "real_scale") + "/",
    str(_MODELS_DIR / "corpus" / "augmented") + "/",
    str(_MODELS_DIR / "corpus" / "antigravity") + "/",
    str(_MODELS_DIR / "corpus") + "/",
]

# Languages that aren't useful for code generation training
SKIP_LANGS = {
    "html",
    "yaml",
    "hcl",
    "cobol",
    "fortran",
    "language",
    "json",
    "toml",
    "css",
    "graphql",
    "dockerfile",
    "redis",
}

# Files in data/ to skip when reading local sources
SKIP_FILES = {
    "combined_training.jsonl",
    "rosetta_training.jsonl",
    "rosetta_train.jsonl",
    "lora_train.jsonl",
}

random.seed(42)

# ── Phase 1: T: drive — stratified by language ───────────────────────────────
print("=== Phase 1: Loading T: drive corpus ===")
by_lang: dict[str, list] = collections.defaultdict(list)

for d in T_DIRS:
    for f in sorted(glob.glob(f"{d}*.jsonl")):
        try:
            with open(f, encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if "instruction" not in obj or "output" not in obj:
                            continue
                        lang = (obj.get("meta") or {}).get("lang", "general")
                        if lang in SKIP_LANGS:
                            continue
                        by_lang[lang].append(obj)
                    except Exception:
                        pass
        except Exception as e:
            print(f"  WARN: could not read {f}: {e}")

print(
    f"  Loaded {sum(len(v) for v in by_lang.values()):,} T: examples across {len(by_lang)} languages"
)

t_examples = []
for lang in sorted(by_lang.keys()):
    pool = by_lang[lang]
    random.shuffle(pool)
    taken = pool[:T_CAP]
    t_examples.extend(taken)
    print(f"  {lang:<20s} {len(pool):7,} avail  {len(taken):4d} taken")

print(f"  T: drive total (stratified): {len(t_examples):,}")

# ── Phase 2: Local data/ specialized files ────────────────────────────────────
print("\n=== Phase 2: Loading local data/ files ===")
local_examples = []

# Languages already well-covered by T: drive — skip gap_gen to avoid duplicate templates
# Include everything else (DSL, builder steps, compiler fixes, arc_mutex, etc.)
t_langs_set = set(by_lang.keys())

for f in sorted(DATA_DIR.glob("*.jsonl")):
    name = f.name
    if name in SKIP_FILES:
        continue
    # gap_gen_*_2k.jsonl = template data for langs already in T: drive — skip
    if name.startswith("gap_gen_") and name.endswith("_2k.jsonl"):
        continue
    try:
        with open(f, encoding="utf-8", errors="replace") as fp:
            exs = []
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # Accept any valid format
                    has_msgs = "messages" in obj
                    has_alpaca = "instruction" in obj or "output" in obj
                    has_pcomp = "prompt" in obj and ("completion" in obj or "response" in obj)
                    if has_msgs or has_alpaca or has_pcomp:
                        exs.append(obj)
                except Exception:
                    pass
        local_examples.extend(exs)
        print(f"  {name:<50s} {len(exs):5d} examples")
    except Exception as e:
        print(f"  WARN: {name}: {e}")

print(f"  Local specialized total: {len(local_examples):,}")

# Also include lora_train.jsonl (frontier model, prompt/response format)
lora_path = DATA_DIR / "lora_train.jsonl"
if lora_path.exists():
    lora_exs = []
    with open(lora_path, encoding="utf-8", errors="replace") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "prompt" in obj and "response" in obj:
                    lora_exs.append(obj)
            except Exception:
                pass
    print(f"  lora_train.jsonl (frontier quality):  {len(lora_exs):5d} examples")
    local_examples.extend(lora_exs)

# ── Phase 3: Combine + shuffle + cap ─────────────────────────────────────────
print("\n=== Phase 3: Combining ===")
all_examples = t_examples + local_examples
random.shuffle(all_examples)

if len(all_examples) > MAX_TOTAL:
    all_examples = all_examples[:MAX_TOTAL]
    print(f"  Capped at {MAX_TOTAL:,} (had {len(t_examples) + len(local_examples):,})")

print(f"  Final corpus: {len(all_examples):,} examples")

# ── Write ─────────────────────────────────────────────────────────────────────
with open(OUT_FILE, "w", encoding="utf-8", errors="replace") as f:
    for ex in all_examples:
        try:
            f.write(json.dumps(ex, ensure_ascii=True) + "\n")
        except Exception:
            pass

print(f"\nWrote: {OUT_FILE}  ({OUT_FILE.stat().st_size / 1e6:.1f} MB)")
print(f"Examples: {len(all_examples):,}")
print(f"Steps/epoch (eff_batch=8): {len(all_examples) // 8:,}")
print(f"Total steps (3 epochs):    {len(all_examples) // 8 * 3:,}")
