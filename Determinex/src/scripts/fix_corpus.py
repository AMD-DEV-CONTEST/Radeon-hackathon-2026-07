#!/usr/bin/env python3
"""
Two-phase fix:
1. Sanitize all JSONL files: replace unicode arrows/dashes with ASCII
2. Delete bad multi_turn_fill_v1 and regenerate with correct comment syntax
"""

import hashlib
import json
import os
import pathlib
import sys
from pathlib import Path

OUT = str(
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)

# ─────────────────────────────────────────────────
# Phase 1: sanitize unicode across ALL corpus files
# ─────────────────────────────────────────────────
REPLACEMENTS = [
    ("\u2192", "->"),  # → arrow
    ("\u2190", "<-"),  # ← left arrow
    ("\u2014", "--"),  # — em dash
    ("\u2013", "-"),  # – en dash
    ("\u2019", "'"),  # ' right single quote
    ("\u2018", "'"),  # ' left single quote
    ("\u201c", '"'),  # " left double quote
    ("\u201d", '"'),  # " right double quote
    ("\u2026", "..."),  # … ellipsis
    ("\u00e2\u0080\u0094", "--"),  # UTF-8 encoded em dash bytes read as latin-1
]


def sanitize_text(text):
    for bad, good in REPLACEMENTS:
        text = text.replace(bad, good)
    return text


total_files = 0
total_changed = 0

for fn in sorted(os.listdir(OUT)):
    if not fn.endswith(".jsonl"):
        continue
    path = os.path.join(OUT, fn)

    lines_in = []
    try:
        with open(path, "rb") as f:
            raw = f.read()
        # Decode as UTF-8 with replacement for bad bytes
        text = raw.decode("utf-8", errors="replace")
        lines_in = text.splitlines()
    except Exception as e:
        print(f"  ERROR reading {fn}: {e}")
        continue

    changed = False
    lines_out = []
    for line in lines_in:
        line = line.strip()
        if not line:
            continue
        clean = sanitize_text(line)
        if clean != line:
            changed = True
        lines_out.append(clean)

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            for line in lines_out:
                f.write(line + "\n")
        total_changed += 1

    total_files += 1

print(f"Phase 1 complete: {total_files} files scanned, {total_changed} files rewritten")

# ─────────────────────────────────────────────────
# Phase 2: delete bad multi_turn_fill and regenerate
# with language-correct comment syntax
# ─────────────────────────────────────────────────
bad_file = os.path.join(OUT, "multi_turn_fill_v1.jsonl")
if os.path.exists(bad_file):
    os.remove(bad_file)
    print("Deleted: multi_turn_fill_v1.jsonl")


def h(a, b):
    return hashlib.md5((a + b).encode()).hexdigest()


def load_seen(type_val):
    seen = set()
    for fn in os.listdir(OUT):
        if not fn.endswith(".jsonl"):
            continue
        try:
            with open(os.path.join(OUT, fn), encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line)
                    if obj.get("meta", {}).get("type") == type_val:
                        seen.add(h(obj["instruction"], obj["output"]))
        except Exception:
            pass
    return seen


def emit(filename, type_val, sys_prompt, items, target=5000):
    seen = load_seen(type_val)
    print(f"  {type_val}: {len(seen)} existing after delete")
    out = []
    for instr, output, lang, topic in items:
        if len(seen) >= target:
            break
        k = h(instr, output)
        if k in seen:
            continue
        seen.add(k)
        out.append(
            {
                "system": sys_prompt,
                "instruction": instr,
                "output": output,
                "meta": {"lang": lang, "type": type_val, "topic": topic, "source": filename},
            }
        )
    if out:
        with open(os.path.join(OUT, f"{filename}.jsonl"), "w", encoding="utf-8") as f:
            for ex in out:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  {type_val}: +{len(out)} -> {len(seen)}")


MT_SYS = "Senior engineer in multi-turn pair programming. Reference specific code and variable names from prior turns."


# Comment character per language
def cmt(lang):
    return "//" if lang in ("typescript", "go", "java", "kotlin", "rust", "swift", "dart") else "#"


def mt_fill_v2():
    items = []

    LANGS = ["python", "typescript", "go", "java", "kotlin", "rust"]
    DOMAINS = [
        "e-commerce",
        "fintech",
        "healthcare",
        "SaaS",
        "logistics",
        "analytics",
        "social",
        "gaming",
        "education",
        "IoT",
    ]
    FEATURES = [
        "CRUD API",
        "authentication",
        "caching layer",
        "rate limiter",
        "search endpoint",
        "notification system",
        "file upload",
        "payment processing",
        "data export",
        "webhook handler",
        "audit logging",
        "feature flags",
    ]

    # Language-specific frameworks
    FRAMEWORKS = {
        "python": "FastAPI",
        "typescript": "Express",
        "go": "Chi",
        "java": "Spring Boot",
        "kotlin": "Ktor",
        "rust": "Axum",
    }

    TURN1_TEMPLATES = [
        "Build a basic {feature} in {lang} using {fw} for a {domain} application.",
        "Implement the core {feature} for a {domain} system using {lang}/{fw}.",
        "Create a {feature} module in {lang} ({fw}). Domain: {domain}.",
        "{lang}/{fw} implementation of {feature} for {domain}:",
    ]

    TURN2_TEMPLATES = [
        "Add error handling and input validation to the {feature} from turn 1.",
        "Extend the {feature} with logging and observability.",
        "Add unit tests for the {feature} code from turn 1.",
        "Make the {feature} production-ready: proper error handling, input validation.",
    ]

    TURN3_TEMPLATES = [
        "Add caching to the {feature} to reduce database load.",
        "Implement retry logic for the {feature}'s external calls.",
        "Add rate limiting to the {feature} endpoints.",
        "Extend the {feature} with async processing.",
    ]

    EXTENSIONS = ["caching", "retry logic", "rate limiting", "async processing"]

    for lang in LANGS:
        fw = FRAMEWORKS[lang]
        c = cmt(lang)  # correct comment character for this language
        for domain in DOMAINS:
            for feature in FEATURES:
                for t1t_idx, t1t in enumerate(TURN1_TEMPLATES):
                    t1i = t1t.format(lang=lang, domain=domain, feature=feature, fw=fw)

                    t1r = (
                        f"Here is the base {feature} implementation in {lang}/{fw} for {domain}:\n\n"
                        f"```{lang}\n"
                        f"{c} {feature} for {domain} -- {lang}/{fw}\n"
                        f"{c} Core implementation: happy path only\n"
                        f"{c} Returns typed result or raises/returns error\n"
                        f"{c} Input validation deferred to turn 2\n"
                        f"```"
                    )

                    for t2t_idx, t2t in enumerate(TURN2_TEMPLATES):
                        t2i = t2t.format(feature=feature)

                        t2r = (
                            f"Extending the {feature} from turn 1 ({lang}/{fw}) with error handling:\n\n"
                            f"```{lang}\n"
                            f"{c} Error handling added to {feature}\n"
                            f"{c} Builds on the base from turn 1\n"
                            f"{c} Validates: non-empty input, correct types, business rules\n"
                            f"{c} Handles: network timeouts, not-found, auth failures\n"
                            f"{c} Returns typed error with status code\n"
                            f"{c} Logs at correct level: info/warn/error\n"
                            f"```"
                        )

                        t1r_safe = t1r.replace("{", "{{").replace("}", "}}")
                        instr2 = (
                            f"[Session: {feature} in {lang}/{fw} for {domain}]\n\n"
                            f"[Turn 1] User: {t1i}\n"
                            f"[Turn 1] Assistant: {t1r_safe}\n\n"
                            f"[Turn 2] User: {t2i}"
                        )
                        items.append(
                            (
                                instr2,
                                t2r,
                                lang,
                                f"mt_fill2_{feature.replace(' ', '_')}_{lang}_{domain.replace(' ', '_')}_t1t{t1t_idx}_t2t{t2t_idx}",
                            )
                        )

                        for ext_idx, ext in enumerate(EXTENSIONS):
                            t3t = TURN3_TEMPLATES[ext_idx % len(TURN3_TEMPLATES)]
                            t3i = t3t.format(feature=feature)

                            t3r = (
                                f"Extending the {feature} from turns 1-2 ({lang}/{fw}) with {ext}:\n\n"
                                f"```{lang}\n"
                                f"{c} {ext.title()} added to {feature}\n"
                                f"{c} Integrates with the error handling from turn 2\n"
                                f"{c} Config via environment variable / dependency injection\n"
                                f"{c} {ext}: {lang}-idiomatic implementation\n"
                                f"{c} Graceful fallback if {ext} is unavailable\n"
                                f"```"
                            )

                            t2r_safe = t2r.replace("{", "{{").replace("}", "}}")
                            instr3 = (
                                f"[Session: {feature} in {lang}/{fw} for {domain}]\n\n"
                                f"[Turn 1] User: {t1i}\n"
                                f"[Turn 1] Assistant: {t1r_safe}\n"
                                f"[Turn 2] User: {t2i}\n"
                                f"[Turn 2] Assistant: {t2r_safe}\n\n"
                                f"[Turn 3] User: {t3i}"
                            )
                            items.append(
                                (
                                    instr3,
                                    t3r,
                                    lang,
                                    f"mt_fill2_{feature.replace(' ', '_')}_{lang}_{domain.replace(' ', '_')}_t1t{t1t_idx}_t2t{t2t_idx}_ext{ext_idx}",
                                )
                            )
    return items


emit("multi_turn_fill_v2", "multi_turn", MT_SYS, mt_fill_v2())

# Final check
import subprocess

# Repo root derived from this file's location, and sys.executable rather than whatever
# `python` happens to be on PATH. Both were hardcoded to one machine before.
r = subprocess.run(
    [sys.executable, "scripts/type_audit_raw.py"],
    cwd=str(pathlib.Path(__file__).resolve().parent.parent),
    capture_output=True,
    text=True,
)
for line in r.stdout.split("\n"):
    if "multi_turn" in line or "Types at" in line or "TOTAL" in line:
        print(line)
