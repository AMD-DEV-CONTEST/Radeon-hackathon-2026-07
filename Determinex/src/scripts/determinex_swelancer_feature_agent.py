"""
scripts/determinex_swelancer_feature_agent.py — SWE-lancer Feature Task Agent

SWE-lancer has two task types:
  1. IC (Individual Contractor) bug-fix — identical format to SWE-bench.
     Route through determinex_swebench_run.py --split swelancer

  2. Feature tasks — write new code from a spec. Handled here.
     Uses the Hive's new-session pipeline (write-from-scratch mode).

Feature task format:
    {
        "instance_id": "...",
        "repo": "owner/repo",
        "problem_statement": "...",
        "base_commit": "...",
        "FAIL_TO_PASS": ["test_..."],
        "task_type": "feature"   ← distinguishes from bug-fix
    }

Usage:
    python scripts/determinex_swelancer_feature_agent.py \\
        --split feature --instances 50 --workers 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="[SWL] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("determinex_swelancer")

_ANTHROPIC_KEY = os.getenv("DETERMINEX_ANTHROPIC_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
_ANTHROPIC_MODEL = os.getenv("DETERMINEX_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_REPOS_BASE = Path(os.getenv("DETERMINEX_SWEBENCH_REPOS", "T:/determinex-swebench"))
_LOGS_BASE = Path("logs/swelancer")


# ── Hive integration helpers ───────────────────────────────────────────────────


def _spec_from_instance(instance: dict, repo_language: str = "python") -> str:
    """Convert a SWE-lancer feature task instance to a Determinex spec."""
    problem = instance.get("problem_statement", "")
    repo = instance.get("repo", "unknown/repo")
    tests = instance.get("FAIL_TO_PASS", [])

    test_section = ""
    if tests:
        test_list = "\n".join(f"- {t}" for t in tests[:10])
        test_section = f"\n## Tests That Must Pass\n{test_list}\n"

    return (
        f"# Feature Implementation Task\n\n"
        f"## Repository\n{repo}\n\n"
        f"## Goal\n{problem}\n"
        f"{test_section}\n"
        f"## Language\n{repo_language}\n\n"
        f"## Constraints\n"
        f"- Must not break existing tests\n"
        f"- Implement the minimal feature described above\n"
        f"- Follow the existing code style and conventions in the repo\n"
    )


def _run_hive_session(
    spec: str, repo_path: Path, instance_id: str, repo_language: str = "python"
) -> str | None:
    """
    Run a Hive new-session for a feature task. Returns the unified diff or None.

    For feature tasks we use the Hive's write-from-scratch pipeline:
      new-session → generate-dag → run-session → collect patch
    """
    spec_path: str | None = None
    try:
        import tempfile as _tf

        with _tf.NamedTemporaryFile(
            suffix=".md",
            mode="w",
            delete=False,
            prefix="swelancer_spec_",
            encoding="utf-8",
        ) as f:
            f.write(spec)
            spec_path = f.name

        hive = _SCRIPTS_DIR / "determinex_hive.py"
        if not hive.exists():
            log.error("determinex_hive.py not found — cannot run Hive session")
            return None

        # new-session
        r1 = subprocess.run(
            [
                sys.executable,
                str(hive),
                "new-session",
                "--spec",
                spec_path,
                "--lang",
                repo_language,
                "--repo",
                str(repo_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        session_id_m = re.search(r"session[:\s]+([a-f0-9\-]{8,})", r1.stdout + r1.stderr, re.I)
        if not session_id_m:
            log.warning("[%s] new-session: could not extract session ID", instance_id)
            log.debug("stdout: %s", r1.stdout[:300])
            return None
        session_id = session_id_m.group(1)
        log.info("[%s] session: %s", instance_id, session_id)

        # generate-dag
        subprocess.run(
            [sys.executable, str(hive), "generate-dag", "--session", session_id],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # run-session
        r3 = subprocess.run(
            [sys.executable, str(hive), "run-session", "--session", session_id, "--export-patch"],
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Extract patch from output
        patch_m = re.search(r"diff --git.*", r3.stdout + r3.stderr, re.DOTALL)
        if patch_m:
            return patch_m.group(0)

        # Check for exported patch file
        patch_file = repo_path / f".determinex_patch_{session_id}.diff"
        if patch_file.exists():
            patch = patch_file.read_text(encoding="utf-8")
            patch_file.unlink(missing_ok=True)
            return patch if patch.strip() else None

        log.warning("[%s] run-session: no patch found in output", instance_id)
        return None

    except subprocess.TimeoutExpired as e:
        log.error("[%s] Hive session timed out: %s", instance_id, e)
        return None
    except Exception as e:
        log.error("[%s] Hive session error: %s", instance_id, e)
        return None
    finally:
        if spec_path:
            try:
                os.unlink(spec_path)
            except Exception:
                pass


# ── Direct fallback (no Hive) ─────────────────────────────────────────────────


def _direct_feature_fallback(
    instance: dict, repo_path: Path, repo_language: str = "python"
) -> str | None:
    """
    Bypass Hive entirely. Ask Claude to implement the feature directly as a diff.
    Used when Hive is unavailable or returns nothing.
    """
    import urllib.request

    if not _ANTHROPIC_KEY:
        log.warning("ANTHROPIC_API_KEY not set — cannot use direct fallback")
        return None

    problem = instance.get("problem_statement", "")
    tests = instance.get("FAIL_TO_PASS", [])

    # Language → file extension map for source file discovery
    _lang_globs = {
        "python": ["*.py"],
        "go": ["*.go"],
        "rust": ["*.rs"],
        "java": ["*.java"],
        "javascript": ["*.js"],
        "typescript": ["*.ts"],
        "ruby": ["*.rb"],
        "php": ["*.php"],
        "c": ["*.c", "*.h"],
        "cpp": ["*.cpp", "*.cc", "*.hpp", "*.h"],
    }
    _skip = {
        "test",
        "tests",
        "__tests__",
        "spec",
        "specs",
        "vendor",
        "node_modules",
        "site-packages",
        "__pycache__",
        "target",
        "build",
    }
    globs = _lang_globs.get(repo_language, ["*.py"])
    src_files: list[Path] = []
    for pattern in globs:
        for f in sorted(repo_path.rglob(pattern)):
            if any(p in f.parts for p in _skip):
                continue
            src_files.append(f)
            if len(src_files) >= 3:
                break
        if len(src_files) >= 3:
            break

    lang_fence = repo_language if repo_language not in ("cpp",) else "cpp"
    file_context = ""
    for f in src_files:
        try:
            rel = f.relative_to(repo_path)
            content = f.read_text(encoding="utf-8", errors="replace")[:1500]
            file_context += f"\n### {rel}\n```{lang_fence}\n{content}\n```\n"
        except Exception:
            pass

    lang_display = repo_language.capitalize()
    ext = globs[0].lstrip("*") if globs else ".py"
    test_list = "\n".join(f"- {t}" for t in tests[:5])
    prompt = (
        f"You are implementing a new feature in a {lang_display} repository.\n\n"
        f"TASK:\n{problem}\n\n"
        f"TESTS THAT MUST PASS:\n{test_list}\n\n"
        f"RELEVANT SOURCE FILES:\n{file_context}\n\n"
        f"Generate a unified diff implementing this feature.\n"
        f"Output ONLY a valid `git diff` format patch. No explanation. No prose.\n"
        f"```diff\n"
        f"diff --git a/path/to/file{ext} b/path/to/file{ext}\n"
        f"...\n"
        f"```\n"
    )

    body = {
        "model": _ANTHROPIC_MODEL,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": f"You are a battle-hardened {lang_display} engineer. Output only unified diffs.",
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        _ANTHROPIC_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": _ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            response = data["content"][0]["text"].strip()

        # Extract diff
        m = re.search(r"```diff\s*(.*?)```", response, re.DOTALL)
        if m:
            patch = m.group(1).strip()
            if patch.startswith("diff --git"):
                return patch

        # Maybe no fences
        if "diff --git" in response:
            idx = response.index("diff --git")
            return response[idx:].strip()

        return None
    except Exception as e:
        log.error("Direct fallback API call failed: %s", e)
        return None


# ── Single instance solver ────────────────────────────────────────────────────

_LANG_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
}
_LANG_PRIMARY_FILES: dict[str, list[str]] = {
    "go": ["go.mod"],
    "rust": ["Cargo.toml"],
    "java": ["pom.xml", "build.gradle"],
    "javascript": ["package.json"],
    "typescript": ["tsconfig.json", "package.json"],
    "ruby": ["Gemfile"],
    "php": ["composer.json"],
    "c": ["Makefile", "CMakeLists.txt"],
    "cpp": ["CMakeLists.txt", "Makefile"],
}
_LANG_SKIP_DIRS = {
    "node_modules",
    "vendor",
    "target",
    "build",
    ".gradle",
    "__pycache__",
    "site-packages",
    ".git",
}


def _detect_instance_language(instance: dict, repo_path: Path) -> str:
    """Detect repo language: instance field → manifest file → extension frequency."""
    lang = (instance.get("language") or instance.get("repo_language") or "").lower().strip()
    if lang:
        return lang

    if repo_path.exists():
        # Check manifest files
        for candidate_lang, markers in _LANG_PRIMARY_FILES.items():
            for marker in markers:
                if (repo_path / marker).exists():
                    return candidate_lang

        # Count source file extensions
        counts: dict[str, int] = {}
        for f in repo_path.rglob("*"):
            if any(p in f.parts for p in _LANG_SKIP_DIRS):
                continue
            ext = f.suffix.lower()
            if ext in _LANG_EXT_MAP:
                counts[_LANG_EXT_MAP[ext]] = counts.get(_LANG_EXT_MAP[ext], 0) + 1
        if counts:
            return max(counts, key=lambda k: counts[k])

    return "python"


def solve_feature_instance(
    instance: dict,
    repos_base: Path = _REPOS_BASE,
) -> dict:
    """Solve a single SWE-lancer feature task."""
    instance_id = instance.get("instance_id", "unknown")
    repo_name = instance.get("repo", "").replace("/", "__")

    # Locate repo
    repo_path = repos_base / repo_name
    if not repo_path.exists():
        # Try alternate naming
        for candidate in repos_base.glob(f"*{repo_name.split('__')[-1]}*"):
            if candidate.is_dir():
                repo_path = candidate
                break
        else:
            log.warning("[%s] repo not found: %s", instance_id, repo_path)
            return {
                "instance_id": instance_id,
                "model_patch": "",
                "model_name_or_path": "determinex_swelancer_feature",
                "error": f"repo not found: {repo_name}",
            }

    # Detect language before any cloak/hive work
    repo_language = _detect_instance_language(instance, repo_path)
    log.info("[%s] detected language: %s", instance_id, repo_language)

    # Reset repo to base commit
    base_commit = instance.get("base_commit", "")
    if base_commit:
        r = subprocess.run(
            ["git", "checkout", base_commit, "--", "."],
            cwd=repo_path,
            capture_output=True,
        )
        if r.returncode != 0:
            log.warning(
                "[%s] git checkout %s failed: %s",
                instance_id,
                base_commit[:8],
                r.stderr.decode(errors="replace")[:200],
            )

    spec = _spec_from_instance(instance, repo_language)
    patch = _run_hive_session(spec, repo_path, instance_id, repo_language)

    if not patch:
        log.warning("[%s] Hive returned nothing — trying direct fallback", instance_id)
        patch = _direct_feature_fallback(instance, repo_path, repo_language)

    if not patch:
        log.error("[%s] Both Hive and direct fallback failed", instance_id)
        patch = ""

    return {
        "instance_id": instance_id,
        "model_patch": patch,
        "model_name_or_path": "determinex_swelancer_feature",
    }


# ── Dataset loader ────────────────────────────────────────────────────────────


def _load_feature_tasks(n: int) -> list[dict]:
    """Load SWE-lancer feature tasks."""
    try:
        from datasets import load_dataset  # type: ignore[import]

        ds = load_dataset("princeton-nlp/SWE-lancer", split="test", trust_remote_code=True)
        instances = [dict(row) for row in ds]
        # Filter to feature tasks only
        feature_instances = [
            inst for inst in instances if inst.get("task_type", "").lower() == "feature"
        ]
        if not feature_instances:
            log.warning("No 'feature' task_type found — using all instances")
            feature_instances = instances
        log.info("Loaded %d SWE-lancer feature tasks", len(feature_instances))
        return feature_instances[:n]
    except Exception as e:
        log.error("Failed to load SWE-lancer dataset: %s", e)
        return []


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Determinex SWE-lancer feature task agent")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--repos-dir", default=str(_REPOS_BASE))
    p.add_argument("--out", default="logs/swelancer/predictions.jsonl")
    args = p.parse_args()

    repos_base = Path(args.repos_dir)
    instances = _load_feature_tasks(args.n)

    if not instances:
        log.error("No instances loaded — exiting")
        sys.exit(1)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(solve_feature_instance, inst, repos_base): inst for inst in instances
        }
        for future in as_completed(futures):
            try:
                result = future.result(timeout=900)
                results.append(result)
                has_patch = bool(result.get("model_patch"))
                log.info(
                    "[%d/%d] %s → %s",
                    len(results),
                    len(instances),
                    result["instance_id"],
                    "patch" if has_patch else "empty",
                )
            except Exception as e:
                inst = futures[future]
                log.warning("Instance %s raised: %s", inst.get("instance_id"), e)
                results.append(
                    {
                        "instance_id": inst.get("instance_id", "unknown"),
                        "model_patch": "",
                        "model_name_or_path": "determinex_swelancer_feature",
                        "error": str(e),
                    }
                )

    with open(args.out, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    patched = sum(1 for r in results if r.get("model_patch"))
    log.info("Done: %d/%d have patches (%.0fs)", patched, len(results), time.time() - start)
    log.info("Predictions: %s", args.out)


if __name__ == "__main__":
    main()
