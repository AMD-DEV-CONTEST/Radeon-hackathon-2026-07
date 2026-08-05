"""swe_run/dataset.py — Dataset constants + loading for all SWE-bench splits."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("swe_run")

# Dataset IDs per split
SPLIT_DATASETS = {
    "lite": "princeton-nlp/SWE-bench_Lite",
    "verified": "princeton-nlp/SWE-bench_Verified",
    "full": "princeton-nlp/SWE-bench",
    "swelancer": "princeton-nlp/SWE-lancer",
    # Multi-language benchmarks (real GitHub issue resolution)
    "multilingual": "SWE-bench/SWE-bench_Multilingual",  # 300 tasks, 9 langs
    "multiswe": "ByteDance-Seed/Multi-SWE-bench",  # 1632 tasks, 7 langs
}

# Multi-SWE-bench per-language config names
_MULTISWE_CONFIGS = ["java", "typescript", "javascript", "go", "rust", "c", "cpp"]

# SWE-bench Multilingual has no 'language' field — detect from repo owner/name.
# Maps repo-name prefix (lowercase) → canonical language tag.
_MULTILINGUAL_REPO_LANG: dict[str, str] = {
    # Java
    "apache__druid": "java",
    "google__gson": "java",
    "javaparser__javaparser": "java",
    "projectlombok__lombok": "java",
    "reactivex__rxjava": "java",
    # Rust
    "astral-sh__ruff": "rust",
    "burntsushi__ripgrep": "rust",
    "sharkdp__bat": "rust",
    "tokio-rs__axum": "rust",
    "nushell__nushell": "rust",
    "uutils__coreutils": "rust",
    # Go
    "gin-gonic__gin": "go",
    "gohugoio__hugo": "go",
    "hashicorp__terraform": "go",
    "prometheus__prometheus": "go",
    "caddyserver__caddy": "go",
    # TypeScript
    "babel__babel": "typescript",
    "facebook__docusaurus": "typescript",
    "vuejs__core": "typescript",
    "preactjs__preact": "typescript",
    # JavaScript
    "axios__axios": "javascript",
    "immutable-js__immutable-js": "javascript",
    "mrdoob__three.js": "javascript",
    # Ruby
    "faker-ruby__faker": "ruby",
    "jekyll__jekyll": "ruby",
    "fastlane__fastlane": "ruby",
    "jordansissel__fpm": "ruby",
    "rubocop__rubocop": "ruby",
    "fluent__fluentd": "ruby",
    # PHP
    "laravel__framework": "php",
    "phpoffice__phpspreadsheet": "php",
    "php-cs-fixer__php-cs-fixer": "php",
    "briannesbitt__carbon": "php",
    # C
    "jqlang__jq": "c",
    "redis__redis": "c",
    "valkey-io__valkey": "c",
    # C++
    "fmtlib__fmt": "cpp",
    "nlohmann__json": "cpp",
    # Go (extras)
    "micropython__micropython": "c",
}


# Local repo cache roots, searched in order.
# Primary: DETERMINEX_REPO_CACHE — colon-separated (Unix) or semicolon-separated (Windows) list.
# Fallback: any of the legacy default T: paths that actually exist on this machine.
def _build_cache_roots() -> list[Path]:
    roots: list[Path] = []
    env_val = os.environ.get("DETERMINEX_REPO_CACHE", "")
    if env_val:
        sep = ";" if os.name == "nt" and ";" in env_val else os.pathsep
        for p in env_val.split(sep):
            p = p.strip()
            if p:
                roots.append(Path(p))
    # Legacy defaults — included only if they exist on this machine.
    for legacy in [
        r"T:\determinex-swebench-full",
        r"T:\determinex-swebench-ml",
        r"T:\determinex-swebench",
    ]:
        p = Path(legacy)
        if p.exists() and p not in roots:
            roots.append(p)
    return roots


_T_CACHE_ROOTS = _build_cache_roots()


def _normalize_instance(inst: dict, dataset_id: str) -> dict:
    """Normalize field names across different dataset formats."""
    # Multi-SWE-bench uses f2p_tests / p2p_tests instead of FAIL_TO_PASS / PASS_TO_PASS
    if "ByteDance-Seed" in dataset_id:
        if "FAIL_TO_PASS" not in inst and "f2p_tests" in inst:
            inst = dict(inst)
            inst["FAIL_TO_PASS"] = inst.get("f2p_tests", "[]")
            inst["PASS_TO_PASS"] = inst.get("p2p_tests", "[]")
        # Synthesize instance_id if missing
        if not inst.get("instance_id") and inst.get("repo") and inst.get("base_commit"):
            inst = dict(inst)
            inst["instance_id"] = f"{inst['repo'].replace('/', '__')}__{inst['base_commit'][:8]}"
    return inst


def _load_multiswe_bench(
    max_instances: int | None,
    instance_ids: list[str] | None,
    lang_filter: str | None,
) -> list[dict]:
    """Load Multi-SWE-bench. Tries per-language configs first; falls back to 'default'."""
    from datasets import load_dataset  # type: ignore[import-untyped]

    dataset_id = SPLIT_DATASETS["multiswe"]
    all_instances: list[dict] = []
    id_set = set(instance_ids) if instance_ids else None

    # Try per-language configs first (original layout)
    configs = [lang_filter] if lang_filter else _MULTISWE_CONFIGS
    loaded_any = False
    for lang in configs:
        try:
            ds = load_dataset(dataset_id, lang, split="test")
            for row in ds:
                inst = _normalize_instance(dict(row), dataset_id)
                if id_set and inst.get("instance_id") not in id_set:
                    continue
                if lang_filter and inst.get("language", "").lower() != lang_filter.lower():
                    continue
                all_instances.append(inst)
                if max_instances and len(all_instances) >= max_instances:
                    return all_instances
            log.info("  Multi-SWE-bench %s: %d instances so far", lang, len(all_instances))
            loaded_any = True
        except Exception as e:
            log.warning("  Multi-SWE-bench lang=%s failed: %s", lang, e)

    if loaded_any:
        return all_instances

    # Fallback: dataset ships as single 'default' config with a 'language' field
    log.info("  Multi-SWE-bench per-lang configs unavailable — loading 'default' config")
    try:
        ds = load_dataset(dataset_id, "default", split="test")
    except Exception:
        ds = load_dataset(dataset_id, split="test")
    for row in ds:
        inst = _normalize_instance(dict(row), dataset_id)
        if id_set and inst.get("instance_id") not in id_set:
            continue
        if lang_filter and inst.get("language", "").lower() != lang_filter.lower():
            continue
        all_instances.append(inst)
        if max_instances and len(all_instances) >= max_instances:
            break
    log.info("  Multi-SWE-bench default config: %d instances", len(all_instances))
    return all_instances


def load_dataset_split(
    split: str,
    max_instances: int | None = None,
    instance_ids: list[str] | None = None,
    lang_filter: str | None = None,
) -> list[dict]:
    """Load SWE-bench instances. Supports all split variants including multilingual."""
    from datasets import load_dataset  # type: ignore[import-untyped]

    dataset_id = SPLIT_DATASETS[split]
    log.info("Loading dataset: %s", dataset_id)

    if split == "multiswe":
        instances = _load_multiswe_bench(max_instances, instance_ids, lang_filter)
    else:
        try:
            dataset = load_dataset(dataset_id, split="test")
        except Exception:
            dataset = load_dataset(dataset_id, split="test", trust_remote_code=False)
        instances = [_normalize_instance(dict(row), dataset_id) for row in dataset]

        # SWE-bench Multilingual has no 'language' field — apply repo-name mapping
        if split == "multilingual" and lang_filter:

            def _ml_lang(inst: dict) -> str:
                repo_key = inst.get("repo", "").replace("/", "__").lower()
                return _MULTILINGUAL_REPO_LANG.get(repo_key, "")

            pre = len(instances)
            instances = [i for i in instances if _ml_lang(i) == lang_filter.lower()]
            log.info(
                "Multilingual lang filter '%s': %d → %d instances", lang_filter, pre, len(instances)
            )
        elif lang_filter and split in ("multiswe",):
            instances = [
                i for i in instances if (i.get("language") or "").lower() == lang_filter.lower()
            ]

    log.info("Loaded %d instances", len(instances))
    if instance_ids:
        id_set = set(instance_ids)
        instances = [inst for inst in instances if inst["instance_id"] in id_set]
        log.info("Filtered to %d instances by --instance-ids", len(instances))
    elif max_instances:
        instances = instances[:max_instances]
        log.info("Capped to %d instances for this run", max_instances)
    return instances
