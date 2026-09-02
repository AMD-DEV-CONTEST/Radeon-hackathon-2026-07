"""
partition_corpus.py — Role-agnostic corpus partitioner
=======================================================
Reads all JSONL sources and classifies each example into one of four buckets:

  role_builder.jsonl       — code-domain only, zero DSL, zero critique
  role_monitor.jsonl       — code + bug-fix / anti-pattern / critique patterns
  role_architect.jsonl     — planning, decomposition, step sequencing
  rosetta_protocol.jsonl   — DSL protocol packets (INTENT:/CONSTRAINT:) -> Rosetta v2 training

Specialist corpora are also emitted (subset of Builder, used for specialist slot scoring):
  specialist_sql.jsonl
  specialist_iac.jsonl
  specialist_solidity.jsonl
  specialist_mobile.jsonl  (React/Flutter/Swift/Kotlin UI patterns)

Classification is by content scoring, not binary rules. Each example gets a score
per bucket; highest score wins. Default -> Builder.

Usage:
  python scripts/partition_corpus.py                         # uses default corpus paths
  python scripts/partition_corpus.py --corpus ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/merged/corpus_deduped.jsonl
  python scripts/partition_corpus.py --corpus a.jsonl b.jsonl --out ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/partitioned/
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_DEFAULT_SOURCES = [
    _ROOT.parent.parent / "determinex-models" / "corpus" / "merged" / "corpus_deduped.jsonl",
    _ROOT / "scripts" / "gap_v30_go_errors_v2.jsonl",
]
_DEFAULT_OUT = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus/partitioned"
)

# ── Classification signals ────────────────────────────────────────────────────

# DSL protocol — goes to Rosetta training, not model weights
_DSL_PATTERNS = re.compile(
    r"^(?:INTENT|CONSTRAINT|CONFIDENCE|CONTEXT|VERDICT):\S", re.I | re.MULTILINE
)

# Monitor: evaluation, critique, bug-fix, anti-pattern
_MONITOR_INSTRUCTION = re.compile(
    r"\b(bug|fix|refactor|anti.?pattern|bad\b|wrong|broken|memory.?leak|"
    r"critique|review|audit|diagnose|identify.?error|what.?wrong|incorrect|"
    r"deadlock|race.?condition|reentrancy|vulnerability|smell|improve)\b",
    re.I,
)
_MONITOR_OUTPUT = re.compile(
    r"(#\s*(BAD|GOOD|BEFORE|AFTER)|//\s*(BAD|GOOD|BEFORE|AFTER)|"
    r"<!--\s*(BAD|GOOD)|the.?bug.?is|the.?fix.?is|note:|warning:|"
    r"this.?will.?deadlock|this.?leaks)",
    re.I,
)

# Architect: planning, decomposition, scaffolding
_ARCHITECT_INSTRUCTION = re.compile(
    r"\b(design|plan|decompose|scaffold|outline|architect|step.?by.?step|"
    r"break.?down|dag|manifest|structure.?a|how.?to.?build|sequence|"
    r"roadmap|phase|milestone)\b",
    re.I,
)
_ARCHITECT_OUTPUT = re.compile(
    r"(step\s+\d|^\d+\.\s|phase\s+\d|depends.?on|first.{0,20}then|"
    r"^\s*[-*]\s+.*(then|next|after|before|finally))",
    re.I | re.MULTILINE,
)

# SQL specialist
_SQL_OUTPUT = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|CREATE\s+TABLE|"
    r"ALTER\s+TABLE|DROP\s+TABLE|WITH\s+\w+\s+AS|JOIN\s+\w|GROUP\s+BY|"
    r"ORDER\s+BY|HAVING|UNION|EXCEPT|INTERSECT)\b",
    re.I,
)

# IaC specialist
_IAC_OUTPUT = re.compile(
    r"(resource\s+\"|provider\s+\"|terraform\s*\{|apiVersion:|kind:\s*(Deployment|Service|"
    r"ConfigMap|StatefulSet|Ingress|Pod|Job)|FROM\s+\w|EXPOSE\s+\d|RUN\s+\w|"
    r"- name:|hosts:|tasks:|ansible)",
    re.I,
)

# Solidity specialist
_SOLIDITY_OUTPUT = re.compile(
    r"\b(pragma\s+solidity|contract\s+\w+|mapping\s*\(|emit\s+\w|"
    r"modifier\s+\w|require\s*\(|revert\s*\(|address\s+\w|uint256|"
    r"ERC20|ERC721|payable|msg\.sender|msg\.value)\b",
    re.I,
)

# Mobile UI specialist (React TSX / Flutter / Swift UI / Kotlin Compose)
_MOBILE_OUTPUT = re.compile(
    r"(StatefulWidget|StatelessWidget|BuildContext|Widget\s+build|"
    r"React\.FC|useState|useEffect|JSX|\.tsx|SwiftUI|View\s*\{|"
    r"@Composable|Scaffold\s*\{|NavigationView|VStack|HStack)",
    re.I,
)

# Code presence (Builder baseline signal)
_CODE_OUTPUT = re.compile(
    r"\b(fn\s+\w|def\s+\w|func\s+\w|class\s+\w|interface\s+\w|"
    r"struct\s+\w|impl\s+\w|public\s+(class|void|int|static)|"
    r"#include|package\s+main|import\s+\w)",
)


# Explicit type -> role mapping (used when meta.type is present)
# Types not listed here fall through to content inference.
_TYPE_TO_ROLE: dict[str, str] = {
    # Builder: code generation is the output
    "code_gen": "builder",
    "algorithm": "builder",
    "test_writing": "builder",
    "code_translation": "builder",
    "framework": "builder",
    "testing": "builder",
    "config": "builder",
    "config_scaffold": "builder",
    "observability": "builder",
    "debugging": "builder",
    "security": "builder",
    # Monitor: evaluation, critique, correction
    "bug_fix": "monitor",
    "code_review": "monitor",
    "anti_pattern": "monitor",
    "refactor": "monitor",
    "code_explanation": "monitor",
    # Architect: planning and structure
    "architecture": "architect",
    # IaC types -> builder but also specialist-tagged
    "tf_good": "builder",
    "tf_antipattern": "builder",
    "tf_bugfix": "builder",
    "tf_advanced": "builder",
    "k8s_good": "builder",
    "k8s_antipattern": "builder",
    "k8s_bugfix": "builder",
    "k8s_advanced": "builder",
    "ansible_good": "builder",
    "ansible_antipattern": "builder",
    "ansible_bugfix": "builder",
    "ansible_advanced": "builder",
    "ps_good": "builder",
    "ps_antipattern": "builder",
    "ps_bugfix": "builder",
    "ps_advanced": "builder",
    # Specialist-primary types
    "sol_good": "builder",
    "sol_antipattern": "builder",
    "sol_bugfix": "builder",
    "sol_advanced": "builder",
    "react_good": "builder",
    "react_bad": "builder",
    "react_bug": "builder",
    "react_perf": "builder",
    "flutter_good": "builder",
    "flutter_bad": "builder",
    "flutter_bug": "builder",
    "flutter_perf": "builder",
    "html_good": "builder",
    "html_bad": "builder",
    "html_bug": "builder",
    "html_perf": "builder",
    "lua_good": "builder",
    "lua_antipattern": "builder",
    "lua_bugfix": "builder",
    "lua_advanced": "builder",
    "r_good": "builder",
    "r_antipattern": "builder",
    "r_bugfix": "builder",
    "r_advanced": "builder",
    "julia_good": "builder",
    "julia_antipattern": "builder",
    "julia_bugfix": "builder",
    "julia_advanced": "builder",
}

# Types that carry an implicit specialist tag regardless of output content
_TYPE_TO_SPECIALIST: dict[str, list[str]] = {
    "tf_good": ["iac"],
    "tf_antipattern": ["iac"],
    "tf_bugfix": ["iac"],
    "tf_advanced": ["iac"],
    "k8s_good": ["iac"],
    "k8s_antipattern": ["iac"],
    "k8s_bugfix": ["iac"],
    "k8s_advanced": ["iac"],
    "ansible_good": ["iac"],
    "ansible_antipattern": ["iac"],
    "ansible_bugfix": ["iac"],
    "ansible_advanced": ["iac"],
    "ps_good": ["powershell"],
    "ps_antipattern": ["powershell"],
    "ps_bugfix": ["powershell"],
    "ps_advanced": ["powershell"],
    "sol_good": ["solidity"],
    "sol_antipattern": ["solidity"],
    "sol_bugfix": ["solidity"],
    "sol_advanced": ["solidity"],
    "react_good": ["mobile"],
    "react_bad": ["mobile"],
    "react_bug": ["mobile"],
    "react_perf": ["mobile"],
    "flutter_good": ["mobile"],
    "flutter_bad": ["mobile"],
    "flutter_bug": ["mobile"],
    "flutter_perf": ["mobile"],
    "html_good": ["mobile"],
    "html_bad": ["mobile"],
    "html_bug": ["mobile"],
    "html_perf": ["mobile"],
}


def classify(example: dict) -> tuple[str, list[str]]:
    """
    Returns (primary_bucket, specialist_tags).
    primary_bucket ∈ {builder, monitor, architect, rosetta_protocol}
    specialist_tags ⊆ {sql, iac, solidity, mobile, powershell, data_sci}

    Priority:
    1. DSL output -> rosetta_protocol always wins
    2. Explicit meta.type -> use _TYPE_TO_ROLE mapping
    3. Content inference fallback (for unlabeled examples)
    """
    instr = example.get("instruction", "") or ""
    output = example.get("output", "") or ""
    meta = example.get("meta", {}) or {}
    ex_type = (meta.get("type") or example.get("type") or "").lower().strip()

    # 1. DSL protocol -> Rosetta, never model weights
    if _DSL_PATTERNS.search(output):
        return "rosetta_protocol", []

    # 2. Explicit type label (fast path — no content regex needed)
    if ex_type and ex_type in _TYPE_TO_ROLE:
        primary = _TYPE_TO_ROLE[ex_type]
        # Start with type-implied specialist tags
        tags = list(_TYPE_TO_SPECIALIST.get(ex_type, []))
        # Still scan output for SQL (not type-labeled in most generators)
        if _SQL_OUTPUT.search(output) and "sql" not in tags:
            tags.append("sql")
        return primary, tags

    # 3. Content inference fallback (unlabeled examples)
    monitor_score = 3 * bool(_MONITOR_INSTRUCTION.search(instr)) + 2 * bool(
        _MONITOR_OUTPUT.search(output)
    )
    architect_score = 3 * bool(_ARCHITECT_INSTRUCTION.search(instr)) + bool(
        _ARCHITECT_OUTPUT.search(output)
    )

    if monitor_score > architect_score and monitor_score >= 3:
        primary = "monitor"
    elif architect_score > monitor_score and architect_score >= 3:
        primary = "architect"
    else:
        primary = "builder"

    # Content-based specialist tags
    tags = []
    if _SQL_OUTPUT.search(output):
        tags.append("sql")
    if _IAC_OUTPUT.search(output):
        tags.append("iac")
    if _SOLIDITY_OUTPUT.search(output):
        tags.append("solidity")
    if _MOBILE_OUTPUT.search(output):
        tags.append("mobile")

    return primary, tags


def partition(sources: list[Path], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load all examples
    all_examples = []
    for src in sources:
        if not src.exists():
            print(f"  [SKIP] not found: {src}")
            continue
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_examples.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        print(
            f"  [LOAD] {src.name}: {sum(1 for _ in open(src, encoding='utf-8') if _.strip())} examples"
        )

    print(f"\n  Total loaded: {len(all_examples)}")

    # Classify
    buckets: dict[str, list] = {
        "builder": [],
        "monitor": [],
        "architect": [],
        "rosetta_protocol": [],
    }
    specialists: dict[str, list] = {
        "sql": [],
        "iac": [],
        "solidity": [],
        "mobile": [],
        "powershell": [],
        "data_sci": [],
    }

    primary_counts: Counter = Counter()
    spec_counts: Counter = Counter()

    for ex in all_examples:
        primary, tags = classify(ex)
        buckets[primary].append(ex)
        primary_counts[primary] += 1
        for tag in tags:
            specialists[tag].append(ex)
            spec_counts[tag] += 1

    # Write primary buckets
    bucket_files = {
        "builder": out_dir / "role_builder.jsonl",
        "monitor": out_dir / "role_monitor.jsonl",
        "architect": out_dir / "role_architect.jsonl",
        "rosetta_protocol": out_dir / "rosetta_protocol.jsonl",
    }
    for bucket, path in bucket_files.items():
        with open(path, "w", encoding="utf-8") as f:
            for ex in buckets[bucket]:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # Write specialist corpora
    spec_files = {
        "sql": out_dir / "specialist_sql.jsonl",
        "iac": out_dir / "specialist_iac.jsonl",
        "solidity": out_dir / "specialist_solidity.jsonl",
        "mobile": out_dir / "specialist_mobile.jsonl",
        "powershell": out_dir / "specialist_powershell.jsonl",
        "data_sci": out_dir / "specialist_data_sci.jsonl",
    }
    for tag, path in spec_files.items():
        with open(path, "w", encoding="utf-8") as f:
            for ex in specialists[tag]:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # Report
    print("\n" + "=" * 60)
    print("PARTITION RESULTS")
    print("=" * 60)
    print("\n  Primary buckets:")
    for bucket, path in bucket_files.items():
        n = primary_counts[bucket]
        pct = n / len(all_examples) * 100 if all_examples else 0
        print(f"    {bucket:<20} {n:>6}  ({pct:.1f}%)  -> {path.name}")

    print("\n  Specialist corpora (subset of Builder):")
    for tag, path in spec_files.items():
        n = spec_counts[tag]
        print(f"    {tag:<20} {n:>6}            -> {path.name}")

    print(f"\n  Output directory: {out_dir}")
    print("\n  NOTE: rosetta_protocol.jsonl is Rosetta v2 training data.")
    print("        Do NOT include it in any model LoRA training run.")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Partition corpus by role")
    parser.add_argument(
        "--corpus",
        nargs="+",
        type=Path,
        default=None,
        help="Input JSONL file(s). Defaults to corpus_deduped.jsonl + gap files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output directory. Default: {_DEFAULT_OUT}",
    )
    args = parser.parse_args()

    sources = args.corpus if args.corpus else [p for p in _DEFAULT_SOURCES if p.exists()]
    if not sources:
        print("[ERROR] No source files found. Pass --corpus path/to/corpus.jsonl")
        sys.exit(1)

    print(f"\nPartitioning {len(sources)} source file(s) -> {args.out}\n")
    partition(sources, args.out)


if __name__ == "__main__":
    main()
