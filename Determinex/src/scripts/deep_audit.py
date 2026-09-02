#!/usr/bin/env python3
"""
DEEP CORPUS AUDIT — Analyzes every example in real_scale/
Reports: diversity, bloat, gaps, structural patterns, content quality signals
"""

import glob
import hashlib
import json
import os
import os as _os
from collections import Counter, defaultdict
from pathlib import Path as _Path

DIR = str(
    _Path(_os.environ.get("DETERMINEX_MODELS_DIR", str(_Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)
OUTPUT = str(_Path(__file__).parent / "audit_output.txt")

all_examples = []
seen_hashes = set()
dupes = 0

# Load everything
for fpath in sorted(glob.glob(os.path.join(DIR, "*.jsonl"))):
    fname = os.path.basename(fpath)
    for lineno, line in enumerate(open(fpath, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            k = hashlib.md5(
                (obj.get("instruction", "") + obj.get("output", ""))[:600].encode()
            ).hexdigest()
            if k in seen_hashes:
                dupes += 1
                continue
            seen_hashes.add(k)
            obj["_source_file"] = fname
            obj["_hash"] = k
            all_examples.append(obj)
        except (KeyError, TypeError, ValueError):
            pass

print(f"Loaded {len(all_examples)} unique examples ({dupes} cross-file dupes skipped)")

# ============================================================
# 1. LANGUAGE DISTRIBUTION
# ============================================================
lang_counts = Counter()
for ex in all_examples:
    lang = ex.get("meta", {}).get("lang", "unknown")
    lang_counts[lang] += 1

# ============================================================
# 2. TYPE DISTRIBUTION (code_gen, bug_fix, anti_pattern, etc.)
# ============================================================
type_counts = Counter()
for ex in all_examples:
    typ = ex.get("meta", {}).get("type", "unknown")
    type_counts[typ] += 1

# ============================================================
# 3. SOURCE DISTRIBUTION (which generator produced what)
# ============================================================
source_counts = Counter()
for ex in all_examples:
    src = ex.get("meta", {}).get("source", "unknown")
    source_counts[src] += 1

# ============================================================
# 4. TOPIC DIVERSITY per language
# ============================================================
lang_topics = defaultdict(set)
for ex in all_examples:
    lang = ex.get("meta", {}).get("lang", "unknown")
    topic = ex.get("meta", {}).get("topic", "")
    if topic:
        lang_topics[lang].add(topic)

# ============================================================
# 5. INSTRUCTION ANALYSIS — diversity of prompts
# ============================================================
lang_instr_prefixes = defaultdict(Counter)
lang_instr_lengths = defaultdict(list)
for ex in all_examples:
    lang = ex.get("meta", {}).get("lang", "unknown")
    instr = ex.get("instruction", "")
    # First 50 chars as "prefix fingerprint"
    prefix = instr[:50].strip()
    lang_instr_prefixes[lang][prefix] += 1
    lang_instr_lengths[lang].append(len(instr))

# ============================================================
# 6. OUTPUT ANALYSIS — code quality signals
# ============================================================
lang_output_lengths = defaultdict(list)
lang_output_line_counts = defaultdict(list)
lang_has_comments = defaultdict(int)
lang_has_error_handling = defaultdict(int)
lang_has_imports = defaultdict(int)
lang_has_tests = defaultdict(int)
lang_has_bad_good = defaultdict(int)  # Has both BAD and GOOD sections

COMMENT_PATTERNS = {
    "//": [
        "typescript",
        "solidity",
        "java",
        "kotlin",
        "csharp",
        "cpp",
        "c",
        "swift",
        "go",
        "rust",
        "scala",
        "dart",
    ],
    "#": ["python", "ruby", "bash", "powershell", "r", "elixir", "yaml", "hcl"],
    "--": ["haskell", "lua", "sql"],
    "/*": ["php", "html"],
}

for ex in all_examples:
    lang = ex.get("meta", {}).get("lang", "unknown")
    output = ex.get("output", "")
    lang_output_lengths[lang].append(len(output))
    lang_output_line_counts[lang].append(output.count("\n") + 1)

    out_lower = output.lower()

    # Comments present?
    has_comment = False
    for pat, langs in COMMENT_PATTERNS.items():
        if lang in langs and pat in output:
            has_comment = True
            break
    if has_comment:
        lang_has_comments[lang] += 1

    # Error handling?
    error_keywords = [
        "error",
        "throw",
        "catch",
        "try",
        "revert",
        "require",
        "assert",
        "raise",
        "die",
        "panic",
        "except",
        "rescue",
        "tryCatch",
        "stop(",
    ]
    if any(kw in out_lower for kw in error_keywords):
        lang_has_error_handling[lang] += 1

    # Imports?
    import_keywords = [
        "import ",
        "require(",
        "use ",
        "from ",
        "library(",
        "include",
        "using ",
        "#include",
        "open ",
        "module ",
    ]
    if any(kw in output for kw in import_keywords):
        lang_has_imports[lang] += 1

    # Tests?
    test_keywords = ["test", "assert", "expect", "describe", "it(", "should", "spec"]
    if any(kw in out_lower for kw in test_keywords):
        lang_has_tests[lang] += 1

    # BAD/GOOD pair?
    if ("BAD" in output or "BUGGY" in output or "anti-pattern" in out_lower) and (
        "GOOD" in output or "FIXED" in output or "refactor" in out_lower
    ):
        lang_has_bad_good[lang] += 1

# ============================================================
# 7. STRUCTURAL PATTERN ANALYSIS — what kinds of code
# ============================================================
pattern_signals = {
    "class/struct/type definitions": [
        "class ",
        "struct ",
        "type ",
        "data class",
        "case class",
        "dataclass",
        "record ",
        "defstruct",
        "typedef",
    ],
    "functions/methods": ["function ", "func ", "def ", "fn ", "fun ", "method ", "sub ", "proc "],
    "async/concurrency": [
        "async ",
        "await ",
        "goroutine",
        "channel",
        "mutex",
        "lock",
        "thread",
        "parallel",
        "concurrent",
        "coroutine",
        "Task",
        "Future",
        "Promise",
    ],
    "database/SQL ops": [
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE TABLE",
        "psql",
        "query",
        "migration",
        "schema",
    ],
    "HTTP/API": [
        "http",
        "REST",
        "API",
        "endpoint",
        "GET ",
        "POST ",
        "curl",
        "fetch",
        "request",
        "response",
        "route",
    ],
    "file I/O": [
        "read_file",
        "write_file",
        "open(",
        "File.",
        "fopen",
        "readFile",
        "writeFile",
        "read_csv",
        "to_csv",
    ],
    "testing": ["test", "assert", "expect", "mock", "stub", "fixture", "spec", "describe"],
    "CLI/args": ["argparse", "getopts", "flag.", "cobra", "clap", "OptionParser", "Commander"],
    "data structures": [
        "HashMap",
        "Dict",
        "Map",
        "Vector",
        "Array",
        "List",
        "Queue",
        "Stack",
        "Tree",
        "Graph",
        "Heap",
        "Trie",
    ],
    "design patterns": [
        "Factory",
        "Singleton",
        "Observer",
        "Strategy",
        "Adapter",
        "Decorator",
        "Proxy",
        "Builder",
        "Command",
        "Iterator",
    ],
    "security": [
        "encrypt",
        "decrypt",
        "hash",
        "token",
        "auth",
        "password",
        "credential",
        "secret",
        "certificate",
        "TLS",
        "SSL",
    ],
    "deployment/infra": [
        "deploy",
        "container",
        "docker",
        "kubernetes",
        "terraform",
        "ansible",
        "CI/CD",
        "pipeline",
        "helm",
    ],
    "math/science": [
        "matrix",
        "vector",
        "linear",
        "regression",
        "optimize",
        "gradient",
        "probability",
        "statistics",
        "numpy",
        "scipy",
    ],
    "ML/AI": [
        "model",
        "train",
        "predict",
        "neural",
        "layer",
        "embedding",
        "transformer",
        "loss",
        "optimizer",
        "epoch",
    ],
}

lang_patterns = defaultdict(lambda: Counter())
for ex in all_examples:
    lang = ex.get("meta", {}).get("lang", "unknown")
    combined = (ex.get("instruction", "") + " " + ex.get("output", "")).lower()
    for pattern_name, keywords in pattern_signals.items():
        if any(kw.lower() in combined for kw in keywords):
            lang_patterns[lang][pattern_name] += 1

# ============================================================
# 8. BLOAT DETECTION — overly similar outputs
# ============================================================
# Check how many outputs share the same first 200 chars (template bloat)
output_prefix_200 = Counter()
for ex in all_examples:
    prefix = ex.get("output", "")[:200].strip()
    output_prefix_200[prefix] += 1

bloated_prefixes = [(p, c) for p, c in output_prefix_200.most_common(100) if c > 20]

# ============================================================
# 9. SYSTEM PROMPT DIVERSITY
# ============================================================
system_prompts = Counter()
for ex in all_examples:
    sys_prompt = ex.get("system", "")[:100]
    system_prompts[sys_prompt] += 1

# ============================================================
# 10. IDENTIFY MISSING COVERAGE
# ============================================================
# What a "complete coding corpus" should cover
IDEAL_COVERAGE = {
    # Languages
    "languages": {
        "systems": ["rust", "cpp", "c", "go"],
        "backend": ["python", "java", "kotlin", "csharp", "scala", "ruby", "php", "elixir"],
        "frontend": ["typescript", "html", "dart"],
        "scripting": ["bash", "powershell", "lua"],
        "functional": ["haskell", "scala", "elixir"],
        "scientific": ["r", "julia", "python"],
        "infra": ["hcl", "yaml"],  # terraform, k8s, ansible
        "blockchain": ["solidity"],
        "data": ["sql"],
        "mobile": ["swift", "kotlin", "dart"],
    },
    # Task types every coding AI needs
    "task_types": [
        "code_generation",
        "code_explanation",
        "code_review",
        "bug_fixing",
        "refactoring",
        "performance_optimization",
        "security_audit",
        "test_writing",
        "documentation",
        "API_design",
        "database_design",
        "system_design",
        "debugging",
        "code_translation",
        "code_completion",
    ],
    # Cross-cutting concepts
    "concepts": [
        "error_handling",
        "concurrency",
        "data_structures",
        "algorithms",
        "design_patterns",
        "security",
        "testing",
        "performance",
        "accessibility",
        "internationalization",
        "logging_observability",
        "configuration_management",
        "dependency_injection",
        "event_driven",
        "streaming",
        "caching",
        "rate_limiting",
        "pagination",
        "authentication",
        "authorization",
        "serialization",
        "validation",
        "migrations",
        "deployment",
        "monitoring",
    ],
}

# ============================================================
# WRITE REPORT
# ============================================================
with open(OUTPUT, "w", encoding="utf-8") as f:

    def w(s=""):
        f.write(s + "\n")

    w("=" * 80)
    w("  DETERMINEX CORPUS DEEP AUDIT")
    w(f"  Total unique examples: {len(all_examples):,}")
    w(f"  Cross-file duplicates skipped: {dupes:,}")
    w(f"  Source directory: {DIR}")
    w("=" * 80)

    # --- LANGUAGE DISTRIBUTION ---
    w("\n\n### 1. LANGUAGE DISTRIBUTION ###")
    w(f"{'Language':<20} {'Count':>8} {'%':>7} {'Topics':>8} {'Bar'}")
    w("-" * 70)
    max_count = max(lang_counts.values())
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / len(all_examples)
        topic_count = len(lang_topics.get(lang, set()))
        bar = "█" * int(40 * count / max_count)
        w(f"{lang:<20} {count:>8,} {pct:>6.1f}% {topic_count:>8} {bar}")

    # --- TYPE DISTRIBUTION ---
    w("\n\n### 2. EXAMPLE TYPE DISTRIBUTION ###")
    w(f"{'Type':<25} {'Count':>8} {'%':>7}")
    w("-" * 45)
    for typ, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / len(all_examples)
        w(f"{typ:<25} {count:>8,} {pct:>6.1f}%")

    # --- SOURCE FILES ---
    w("\n\n### 3. SOURCE GENERATOR DISTRIBUTION (top 30) ###")
    w(f"{'Source':<40} {'Count':>8}")
    w("-" * 52)
    for src, count in source_counts.most_common(30):
        w(f"{src:<40} {count:>8,}")

    # --- CODE QUALITY SIGNALS per language ---
    w("\n\n### 4. CODE QUALITY SIGNALS PER LANGUAGE ###")
    w(
        f"{'Language':<15} {'Total':>7} {'Has Comments':>14} {'Error Handling':>16} {'Imports':>10} {'Tests':>8} {'Bad→Good':>10}"
    )
    w("-" * 85)
    for lang in sorted(lang_counts.keys(), key=lambda x: -lang_counts[x]):
        total = lang_counts[lang]
        comm = lang_has_comments.get(lang, 0)
        err = lang_has_error_handling.get(lang, 0)
        imp = lang_has_imports.get(lang, 0)
        tst = lang_has_tests.get(lang, 0)
        bg = lang_has_bad_good.get(lang, 0)
        w(
            f"{lang:<15} {total:>7,} {comm:>8,} ({100 * comm // max(total, 1):>3}%) {err:>8,} ({100 * err // max(total, 1):>3}%) {imp:>8,} ({100 * imp // max(total, 1):>3}%) {tst:>6,} ({100 * tst // max(total, 1):>3}%) {bg:>6,} ({100 * bg // max(total, 1):>3}%)"
        )

    # --- OUTPUT SIZE STATS ---
    w("\n\n### 5. OUTPUT SIZE STATISTICS ###")
    w(f"{'Language':<15} {'Avg chars':>10} {'Avg lines':>10} {'Min chars':>10} {'Max chars':>10}")
    w("-" * 60)
    for lang in sorted(lang_counts.keys(), key=lambda x: -lang_counts[x]):
        lengths = lang_output_lengths.get(lang, [0])
        lines = lang_output_line_counts.get(lang, [0])
        w(
            f"{lang:<15} {sum(lengths) // max(len(lengths), 1):>10,} {sum(lines) // max(len(lines), 1):>10} {min(lengths):>10,} {max(lengths):>10,}"
        )

    # --- STRUCTURAL PATTERN COVERAGE ---
    w("\n\n### 6. STRUCTURAL PATTERN COVERAGE PER LANGUAGE ###")
    all_patterns = list(pattern_signals.keys())
    w(f"{'Language':<15} " + " ".join(f"{p[:8]:>9}" for p in all_patterns))
    w("-" * (15 + 9 * len(all_patterns) + len(all_patterns)))
    for lang in sorted(lang_counts.keys(), key=lambda x: -lang_counts[x]):
        vals = []
        for p in all_patterns:
            count = lang_patterns[lang][p]
            pct = 100 * count // max(lang_counts[lang], 1)
            vals.append(f"{pct:>7}%")
        w(f"{lang:<15} " + "  ".join(vals))

    # --- INSTRUCTION DIVERSITY ---
    w("\n\n### 7. INSTRUCTION DIVERSITY ###")
    w(
        f"{'Language':<15} {'Total':>7} {'Unique Prefixes':>18} {'Prefix Ratio':>14} {'Avg Instr Len':>15}"
    )
    w("-" * 75)
    for lang in sorted(lang_counts.keys(), key=lambda x: -lang_counts[x]):
        total = lang_counts[lang]
        unique_pfx = len(lang_instr_prefixes.get(lang, {}))
        ratio = unique_pfx / max(total, 1)
        avg_len = sum(lang_instr_lengths.get(lang, [0])) // max(
            len(lang_instr_lengths.get(lang, [1])), 1
        )
        w(f"{lang:<15} {total:>7,} {unique_pfx:>18,} {ratio:>13.3f} {avg_len:>15,}")

    # --- BLOAT DETECTION ---
    w("\n\n### 8. BLOAT DETECTION — Repeated Output Prefixes (>20 occurrences) ###")
    if bloated_prefixes:
        w(
            f"Found {len(bloated_prefixes)} bloated prefixes (same first 200 chars across >20 examples):"
        )
        for prefix, count in bloated_prefixes[:30]:
            safe = prefix[:100].replace("\n", "\\n")
            w(f"  [{count:>5}x] {safe}")
    else:
        w("No significant bloat detected.")

    # --- SYSTEM PROMPT DIVERSITY ---
    w("\n\n### 9. SYSTEM PROMPT DIVERSITY ###")
    w(f"Unique system prompts: {len(system_prompts)}")
    for sp, count in system_prompts.most_common(20):
        safe = sp.replace("\n", " ")[:80]
        w(f"  [{count:>6,}x] {safe}")

    # --- GAP ANALYSIS ---
    w("\n\n### 10. GAP ANALYSIS — WHAT'S MISSING ###")

    # Missing task types
    w("\n--- Missing Task Types ---")
    covered_types = set(type_counts.keys())
    all_content = " ".join(ex.get("meta", {}).get("type", "") for ex in all_examples).lower()
    for task in IDEAL_COVERAGE["task_types"]:
        found = task.lower().replace("_", " ") in all_content or task.lower() in all_content
        # Also check instructions for this concept
        instr_matches = sum(
            1
            for ex in all_examples
            if task.lower().replace("_", " ") in ex.get("instruction", "").lower()
        )
        status = (
            f"✓ {instr_matches:,} examples"
            if instr_matches > 50
            else f"⚠ WEAK ({instr_matches})"
            if instr_matches > 0
            else "✗ MISSING"
        )
        w(f"  {task:<30} {status}")

    # Missing concepts
    w("\n--- Missing Cross-Cutting Concepts ---")
    for concept in IDEAL_COVERAGE["concepts"]:
        hits = sum(
            1
            for ex in all_examples
            if concept.lower().replace("_", " ")
            in (ex.get("instruction", "") + " " + ex.get("output", "")).lower()
        )
        status = f"✓ {hits:,}" if hits > 100 else f"⚠ WEAK ({hits})" if hits > 0 else "✗ MISSING"
        w(f"  {concept:<30} {status}")

    # SQL bloat warning
    w("\n--- Bloat Warnings ---")
    sql_pct = 100.0 * lang_counts.get("sql", 0) / len(all_examples)
    w(f"  SQL: {lang_counts.get('sql', 0):,} examples = {sql_pct:.1f}% of corpus")
    if sql_pct > 30:
        w(
            f"  ⚠ SQL is {sql_pct:.0f}% of corpus — STRONGLY recommend capping at 40,000 during merge"
        )
        w("    Without cap: model will be biased toward SQL generation")
        w("    With 40k cap: SQL drops to ~26% which is still dominant but more balanced")

    # Per-language type coverage
    w("\n--- Per-Language Good/Bad/Fix Coverage ---")
    lang_type_matrix = defaultdict(Counter)
    for ex in all_examples:
        lang = ex.get("meta", {}).get("lang", "unknown")
        typ = ex.get("meta", {}).get("type", "unknown")
        lang_type_matrix[lang][typ] += 1

    for lang in sorted(lang_counts.keys(), key=lambda x: -lang_counts[x]):
        types = lang_type_matrix[lang]
        has_good = any("good" in t or "code_gen" in t for t in types)
        has_bad = any("bad" in t or "anti" in t for t in types)
        has_fix = any("bug" in t or "fix" in t for t in types)
        has_perf = any("perf" in t or "advanced" in t for t in types)
        markers = []
        if has_good:
            markers.append("✓good")
        else:
            markers.append("✗good")
        if has_bad:
            markers.append("✓bad")
        else:
            markers.append("✗bad")
        if has_fix:
            markers.append("✓fix")
        else:
            markers.append("✗fix")
        if has_perf:
            markers.append("✓adv")
        else:
            markers.append("✗adv")
        w(
            f"  {lang:<15} {' | '.join(markers)}  ({', '.join(f'{t}:{c}' for t, c in types.most_common(5))})"
        )

print(f"\nAudit written to: {OUTPUT}")
print("Loading into summary...")

# Print summary to console too
with open(OUTPUT, encoding="utf-8") as f:
    for line in f:
        print(line, end="")
