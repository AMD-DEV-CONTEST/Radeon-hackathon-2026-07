"""
scripts/codebase_explorer.py — Enterprise Codebase Explorer
============================================================
Loads an existing codebase, maps its structure, runs shadow compilation
across multiple languages, identifies issues, and generates targeted fixes.

This is the "Repo-to-Patch" adapter that bridges SWE-bench-style repository
exploration into Determinex's Hive Mind. Unlike the Idea/Concept Lab (which builds
from scratch), this module explores, diagnoses, and patches existing code.

Architecture:
  1. WorkspaceLoader  — Scans a directory, builds a file tree, filters noise
  2. ShadowCompiler   — Runs the project's native test/build commands before changes
  3. IssueLocalizer   — Uses keyword extraction + traceback analysis to find targets
  4. PatchPipeline    — Generates, applies and validates patches via the Builder model
  5. DiagnosticReport — Summarizes findings as structured JSON for the UI

Usage (CLI):
    python scripts/codebase_explorer.py explore --workspace /path/to/repo
    python scripts/codebase_explorer.py diagnose --workspace /path/to/repo --issue "describe the bug"
    python scripts/codebase_explorer.py fix --workspace /path/to/repo --issue "describe the bug" --out patch.diff

Usage (Python API):
    from codebase_explorer import CodebaseExplorer
    explorer = CodebaseExplorer("/path/to/repo")
    report = explorer.explore()
    patch = explorer.fix("The login endpoint returns 500 on empty payload")
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[EXPLORER] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("codebase_explorer")

_ROOT = Path(__file__).resolve().parent.parent

# ── Configuration ─────────────────────────────────────────────────────────────
# Defaults sourced from the config spine (determinex_settings) so the
# current-generation ids (v11/v6/v5) are the only baseline. The previous
# v10/v5 hard-coded defaults were stale per CLAUDE.md role assignments and
# the MODEL_ROUTER_LOCK_001 stale-id catalogue.
BUILDER_MODEL = os.getenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl")
OBSERVER_MODEL = os.getenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl")
MAX_RETRIES = int(os.getenv("DETERMINEX_MAX_RETRIES", "5"))
MAX_FILES = int(os.getenv("DETERMINEX_MAX_FILES", "12"))
CTX_LINES = int(os.getenv("DETERMINEX_CTX_LINES", "120"))
TEST_TIMEOUT = int(os.getenv("DETERMINEX_TEST_TIMEOUT", "60"))

# ── SSRF guard ────────────────────────────────────────────────────────────────
import urllib.parse as _urlparse

_OLLAMA_URL_RAW = os.getenv("DETERMINEX_OLLAMA_URL", "http://localhost:11434")
_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_parsed_host = _urlparse.urlparse(_OLLAMA_URL_RAW).hostname or ""
if _parsed_host not in _ALLOWED_HOSTS:
    raise ValueError(
        f"DETERMINEX_OLLAMA_URL host '{_parsed_host}' is not allowed. "
        "Only localhost/127.0.0.1 are permitted to prevent SSRF."
    )
OLLAMA_URL = _OLLAMA_URL_RAW

# ── Noise filters ────────────────────────────────────────────────────────────

# Directories to always skip when scanning a workspace
SKIP_DIRS = frozenset(
    {
        # Package managers / dependency caches
        "node_modules",
        "site-packages",
        "bower_components",
        "Pods",
        "vendor",
        ".yarn",
        ".pnp",
        # Version control
        ".git",
        ".svn",
        ".hg",
        # Python caches
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".eggs",
        # Virtual environments
        "venv",
        ".venv",
        "env",
        ".env",
        # Build artifacts
        "build",
        "dist",
        "target",
        "out",
        "bin",
        "obj",
        "cmake-build-debug",
        "cmake-build-release",
        # IDE / editor
        ".idea",
        ".vs",
        ".vscode",
        # Framework caches
        ".next",
        ".nuxt",
        ".cargo",
        ".gradle",
        ".terraform",
        ".serverless",
        # Coverage / test output
        "coverage",
        ".nyc_output",
        "htmlcov",
        # Heavy data / log directories (common in ML/AI repos)
        "logs",
        "log",
        "data",
        "datasets",
        "checkpoints",
        "weights",
        "models",
        "artifacts",
        "outputs",
        "results",
        "eval_results",
        "cloud_outputs",
        "fine_tuning",
        "swebench",
        "evals",
        "ab_eval",
        "run_evaluation",
        "archive_streamlit",
        ".determinex_staging",
    }
)

# Hard cap: never scan more than this many files to prevent hanging
MAX_SCAN_FILES = 5000

# File extensions we care about for code analysis
CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".rs",
        ".go",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".m",
        ".scala",
        ".ex",
        ".exs",
        ".hs",
        ".ml",
        ".fs",
        ".clj",
        ".erl",
        ".dart",
    }
)

# Config/doc extensions — lower priority but still relevant
CONFIG_EXTENSIONS = frozenset(
    {
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".xml",
        ".ini",
        ".cfg",
        ".md",
        ".rst",
        ".txt",
        ".sql",
        ".sh",
        ".bat",
        ".ps1",
        ".dockerfile",
        ".tf",
        ".hcl",
    }
)

# Secrets — never read, never index
SECRET_FILES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
        "secrets.json",
        "credentials.json",
        "service_account.json",
        ".netrc",
        "vault.key",
    }
)
SECRET_EXTENSIONS = frozenset(
    {
        ".pem",
        ".key",
        ".pfx",
        ".p12",
        ".crt",
        ".cer",
        ".der",
    }
)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    path: str  # relative to workspace root
    extension: str
    size_bytes: int
    line_count: int
    category: str  # "source", "test", "config", "other"
    language: str  # detected language


@dataclass
class DiagnosticFinding:
    severity: str  # "error", "warning", "info"
    file: str  # relative path
    line: int  # 0 if whole-file
    message: str
    category: str  # "compilation", "test_failure", "lint", "structure"


@dataclass
class WorkspaceReport:
    workspace_path: str
    total_files: int
    source_files: int
    test_files: int
    config_files: int
    languages: dict  # language -> file count
    build_system: str  # "cargo", "go", "pip", "npm", "gradle", "maven", etc.
    test_framework: str  # "pytest", "jest", "cargo test", "go test", etc.
    findings: list  # list of DiagnosticFinding dicts
    shadow_output: str  # raw shadow compilation output
    health_score: float  # 0.0 - 1.0


@dataclass
class PatchResult:
    success: bool
    patch_diff: str
    files_modified: list  # list of relative file paths
    tests_passed: bool
    attempts: int
    error: str


# ── Inference helpers ────────────────────────────────────────────────────────


def _ollama(model: str, prompt: str, system: str = "", temperature: float = 0.1) -> str:
    """Local Ollama inference. SSRF-guarded above."""
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": (
                f"<|im_start|>system\n{system or 'You are an expert software engineer.'}"
                f"<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            ),
            "stream": False,
            "options": {
                "num_ctx": 16384,
                "temperature": temperature,
                "num_predict": 16384,
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except Exception as e:
        log.error("Ollama call failed: %s", e)
        return ""


def _infer(model: str, prompt: str, system: str = "", temperature: float = 0.1) -> str:
    """Route to Ollama. Extensible to vLLM/DeepSeek via env vars."""
    return _ollama(model, prompt, system, temperature)


# ── Language Detection ────────────────────────────────────────────────────────

_EXT_TO_LANG = {
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".fs": "fsharp",
    ".clj": "clojure",
    ".erl": "erlang",
    ".dart": "dart",
    ".m": "objective-c",
}


def detect_language(ext: str) -> str:
    return _EXT_TO_LANG.get(ext.lower(), "unknown")


# ── Build System Detection ───────────────────────────────────────────────────


def detect_build_system(root: Path) -> tuple[str, str]:
    """
    Returns ``(build_system, test_framework)`` for the workspace.

    As of BUILD_ADAPTER_REGISTRY_LOCK_001 this delegates to
    ``intake.build_adapter_registry.default_registry().select(root)`` and
    returns the primary adapter's ``(build_system_id, test_framework_id)``.
    The historical return shape and concrete string identifiers
    (``"pip"``/``"cargo"``/``"go"``/``"npm"``/``"maven"``/``"gradle"``/
    ``"unknown"``) are preserved so existing callers and the rung-1 smoke
    fixtures continue to pass without modification.

    Adapters not yet migrated from the legacy if-ladder (bundler, composer,
    mix, make, cmake) fall through to ``("unknown", "unknown")`` for now and
    will be added in a follow-up rung; that is a deliberate scope cut, not
    a regression — none of the smoke fixtures exercise them.
    """
    try:
        from intake.build_adapter_registry import default_registry
        from intake.build_adapters import NodeAdapter
    except ImportError:
        # Defensive: if the intake package can't be imported, fail to "unknown"
        # rather than silently returning a stale value.
        return "unknown", "unknown"

    sel = default_registry().select(root)
    primary = sel.primary
    build_id = primary.build_system_id
    test_id = primary.test_framework_id
    if build_id == "unknown":
        return "unknown", "unknown"
    # Preserve historical npm test-framework refinement: vitest/mocha/jest
    # detected from package.json devDependencies. NodeAdapter encapsulates
    # this so the call stays one line.
    if primary is NodeAdapter:
        test_id = NodeAdapter.refine_test_framework_id(root)
    return build_id, test_id


# ── File Classification ─────────────────────────────────────────────────────


def _is_test_file(path: Path) -> bool:
    """True if this looks like a test file."""
    name = path.stem.lower()
    if name.startswith("test_") or name.endswith("_test"):
        return True
    if name in ("tests", "conftest", "test", "spec"):
        return True
    # Check if inside a tests/ or test/ or spec/ directory
    parts_lower = [p.lower() for p in path.parts]
    return (
        "tests" in parts_lower
        or "test" in parts_lower
        or "spec" in parts_lower
        or "__tests__" in parts_lower
    )


def _is_secret_file(path: Path) -> bool:
    """True if this file might contain secrets."""
    name = path.name.lower()
    if name in SECRET_FILES or name.startswith(".env"):
        return True
    ext = path.suffix.lower()
    return ext in SECRET_EXTENSIONS


def _should_skip_dir(name: str) -> bool:
    return name.lower() in SKIP_DIRS or name.startswith(".")


# ── Core: Workspace Loader ───────────────────────────────────────────────────


class WorkspaceLoader:
    """
    Scans a workspace directory and builds a structured file map.
    Respects .gitignore, skips noise directories, never touches secrets.
    """

    def __init__(self, workspace_path: Path, max_depth: int = 10):
        self.root = workspace_path.resolve()
        self.max_depth = max_depth
        self.files: list[FileInfo] = []
        self.languages: dict[str, int] = {}

    def scan(self) -> list[FileInfo]:
        """Walk the workspace and classify every file."""
        log.info("Scanning workspace: %s", self.root)

        if not self.root.exists():
            log.error("Workspace path does not exist: %s", self.root)
            return []

        self.files = []
        self.languages = {}

        self._walk(self.root, depth=0)

        log.info(
            "Scan complete: %d files (%d source, %d test, %d config)",
            len(self.files),
            sum(1 for f in self.files if f.category == "source"),
            sum(1 for f in self.files if f.category == "test"),
            sum(1 for f in self.files if f.category == "config"),
        )
        log.info("Languages: %s", dict(sorted(self.languages.items(), key=lambda x: -x[1])))

        return self.files

    def _walk(self, directory: Path, depth: int) -> None:
        if depth > self.max_depth:
            return
        if len(self.files) >= MAX_SCAN_FILES:
            return

        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if len(self.files) >= MAX_SCAN_FILES:
                return
            if entry.is_dir():
                if _should_skip_dir(entry.name):
                    continue
                self._walk(entry, depth + 1)
            elif entry.is_file():
                if _is_secret_file(entry):
                    continue
                self._classify_file(entry)

    def _classify_file(self, path: Path) -> None:
        ext = path.suffix.lower()
        try:
            rel = str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return

        # Determine category
        if ext in CODE_EXTENSIONS:
            category = "test" if _is_test_file(path) else "source"
        elif ext in CONFIG_EXTENSIONS:
            category = "config"
        else:
            return  # Skip binary/unknown files

        lang = detect_language(ext)

        try:
            size = path.stat().st_size
            # Quick line count for reasonably sized files
            if size < 5_000_000:  # 5MB cap
                content = path.read_text(encoding="utf-8", errors="ignore")
                lines = content.count("\n") + 1
            else:
                lines = -1  # Too large to count
        except Exception:
            size = 0
            lines = 0

        info = FileInfo(
            path=rel,
            extension=ext,
            size_bytes=size,
            line_count=lines,
            category=category,
            language=lang,
        )
        self.files.append(info)

        if lang != "unknown" and category in ("source", "test"):
            self.languages[lang] = self.languages.get(lang, 0) + 1

    def get_source_files(self) -> list[FileInfo]:
        return [f for f in self.files if f.category == "source"]

    def get_test_files(self) -> list[FileInfo]:
        return [f for f in self.files if f.category == "test"]


# ── Core: Shadow Compiler ────────────────────────────────────────────────────


class ShadowCompiler:
    """
    Runs the project's native build/test commands on UNMODIFIED code.
    Captures tracebacks and errors to inject into the Architect prompt.
    """

    def __init__(self, workspace: Path, build_system: str, test_framework: str):
        self.workspace = workspace
        self.build_system = build_system
        self.test_framework = test_framework

    def compile(self) -> tuple[bool, str]:
        """Run the build step. Returns (success, output)."""
        log.info("Shadow compile: %s build system", self.build_system)

        commands = {
            "cargo": [["cargo", "check", "--message-format=short"]],
            "go": [["go", "build", "./..."]],
            "pip": [[sys.executable, "-m", "py_compile"]],  # per-file
            "npm": [["npm", "run", "build", "--if-present"]],
            "maven": [["mvn", "compile", "-q"]],
            "gradle": [["gradle", "compileJava", "-q"]],
            "cmake": [["cmake", "--build", "."]],
        }

        cmd_list = commands.get(self.build_system)
        if not cmd_list:
            log.info("No build command known for '%s' — skipping", self.build_system)
            return True, ""

        # Special case: pip (Python) — use py_compile on each .py file
        if self.build_system == "pip":
            return self._shadow_compile_python()

        # Every subprocess invocation below routes through the hardened
        # intake runner (HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001):
        # workspace-scoped cwd, scrubbed env, no Docker, no shell=True,
        # structured failure (never raises).
        from intake.hardened_runner import run as _hardened_run

        for cmd in cmd_list:
            r = _hardened_run(
                cmd,
                workspace=self.workspace,
                timeout=TEST_TIMEOUT * 2,
                extra_env={"PYTHONWARNINGS": "ignore"},
            )
            if r.tool_missing:
                log.info("Build tool not found: %s", cmd[0])
                return True, f"Build tool '{cmd[0]}' not installed"
            if r.timed_out:
                return False, "Build timed out"
            if r.blocked:
                log.warning("Shadow compile blocked: %s", r.reason)
                return False, f"hardened runner blocked: {r.reason}"
            output = self._format_output(r.stdout, r.stderr)
            if r.exit_code != 0:
                log.info("Shadow compile FAILED: %s", output[:200])
                return False, output

        log.info("Shadow compile: PASS")
        return True, ""

    def _shadow_compile_python(self) -> tuple[bool, str]:
        """Check syntax of all Python files via the hardened runner."""
        from intake.hardened_runner import run as _hardened_run

        errors = []
        py_files = list(self.workspace.rglob("*.py"))
        py_files = [f for f in py_files if not any(skip in str(f) for skip in SKIP_DIRS)]

        for f in py_files[:200]:  # Cap at 200 files
            r = _hardened_run(
                [sys.executable, "-m", "py_compile", str(f)],
                workspace=self.workspace,
                timeout=10,
            )
            if r.tool_missing:
                # Interpreter itself missing — surface once and stop.
                errors.append(f"py_compile tool missing: {r.stderr}")
                break
            if r.timed_out or r.blocked:
                continue
            if r.exit_code != 0:
                rel = str(f.relative_to(self.workspace))
                errors.append(f"{rel}: {r.stderr.strip()}")

        if errors:
            return False, "\n".join(errors[:20])
        return True, ""

    def run_tests(self) -> tuple[bool, str]:
        """Run the test suite. Returns (success, output)."""
        log.info("Shadow test: %s framework", self.test_framework)

        commands = {
            "pytest": [sys.executable, "-m", "pytest", "-x", "--tb=short", "-q", "--no-header"],
            "cargo test": ["cargo", "test", "--", "--test-threads=1"],
            "go test": ["go", "test", "./...", "-count=1", "-short"],
            "jest": ["npx", "jest", "--bail", "--silent"],
            "vitest": ["npx", "vitest", "run", "--reporter=verbose"],
            "maven test": ["mvn", "test", "-q"],
            "gradle test": ["gradle", "test", "-q"],
            "rspec": ["bundle", "exec", "rspec", "--fail-fast"],
            "mix test": ["mix", "test"],
            "make test": ["make", "test"],
        }

        cmd = commands.get(self.test_framework)
        if not cmd:
            log.info("No test command known for '%s' — skipping", self.test_framework)
            return True, ""

        from intake.hardened_runner import run as _hardened_run

        r = _hardened_run(
            cmd,
            workspace=self.workspace,
            timeout=TEST_TIMEOUT * 3,
            extra_env={"PYTHONWARNINGS": "ignore"},
        )
        if r.tool_missing:
            log.info("Test tool not found: %s", cmd[0])
            return True, f"Test tool '{cmd[0]}' not installed"
        if r.timed_out:
            log.warning("Test suite timed out")
            return False, "Test suite timed out — possible infinite loop"
        if r.blocked:
            log.warning("Shadow test blocked: %s", r.reason)
            return False, f"hardened runner blocked: {r.reason}"
        output = self._format_output(r.stdout, r.stderr)
        if r.exit_code == 0:
            log.info("Shadow test: PASS")
            return True, output
        log.info("Shadow test: FAIL (%d chars output)", len(output))
        return False, output

    @staticmethod
    def _format_output(stdout: str, stderr: str) -> str:
        raw = (stdout + "\n" + stderr).strip()
        lines = raw.splitlines()
        # Filter out noise
        relevant = [
            l for l in lines if not any(x in l for x in ("DeprecationWarning", "site-packages"))
        ]
        return "\n".join(relevant[-60:])[:3000]


# ── Core: Issue Localizer ────────────────────────────────────────────────────


class IssueLocalizer:
    """
    Given an issue description (and optional traceback), identifies the
    most likely files and functions to investigate.
    """

    # Words too common to be useful as search keywords
    _NOISE = frozenset(
        {
            "error",
            "issue",
            "should",
            "would",
            "could",
            "please",
            "count",
            "stdout",
            "stdin",
            "stderr",
            "sys",
            "os",
            "path",
            "test",
            "tests",
            "assert",
            "format",
            "print",
            "write",
            "read",
            "open",
            "true",
            "false",
            "none",
            "self",
            "args",
            "kwargs",
            "return",
            "raise",
            "import",
            "from",
            "with",
            "file",
            "data",
            "value",
            "result",
            "output",
            "input",
            "name",
            "type",
            "class",
            "object",
            "string",
            "list",
            "dict",
            "tuple",
            "bool",
            "function",
            "method",
            "module",
            "package",
            "library",
            "version",
            "exception",
            "traceback",
            "stack",
            "trace",
            "debug",
        }
    )

    def __init__(self, workspace: Path, files: list[FileInfo]):
        self.workspace = workspace
        self.files = files

    def locate(self, issue_text: str, shadow_trace: str = "") -> list[Path]:
        """
        Find the top N files most likely to contain the bug.
        Uses LLM keyword extraction + traceback analysis + content grep.
        """
        log.info("Localizing issue across %d files...", len(self.files))

        # Step 1: Extract keywords via LLM
        keywords = self._extract_keywords(issue_text)

        # Step 2: Parse traceback for file references
        trace_files = self._parse_traceback(shadow_trace)

        # Step 3: Score all source files
        scores: dict[str, float] = {}

        # Traceback files get highest priority
        for tf in trace_files:
            scores[tf] = scores.get(tf, 0) + 15.0

        # Keyword search across source files
        source_files = [f for f in self.files if f.category == "source"]
        for fi in source_files:
            full_path = self.workspace / fi.path
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                for kw in keywords:
                    if f"def {kw}" in content or f"class {kw}" in content:
                        scores[fi.path] = scores.get(fi.path, 0) + 6.0
                    elif f"fn {kw}" in content or f"func {kw}" in content:
                        scores[fi.path] = scores.get(fi.path, 0) + 6.0
                    elif kw in content:
                        scores[fi.path] = scores.get(fi.path, 0) + 2.0
            except Exception:
                pass

        if not scores:
            # Fallback: return largest source files (most likely to contain logic)
            source_files.sort(key=lambda f: -f.size_bytes)
            return [self.workspace / f.path for f in source_files[:MAX_FILES]]

        # Sort by score (desc), then by path length (prefer shorter paths)
        ranked = sorted(scores.items(), key=lambda x: (-x[1], len(x[0])))
        result = [self.workspace / path for path, _ in ranked[:MAX_FILES]]

        log.info("Top targets: %s", [str(r.relative_to(self.workspace)) for r in result[:5]])
        return result

    def _extract_keywords(self, issue_text: str) -> list[str]:
        """Use the Observer model to extract code identifiers from the issue."""
        prompt = (
            "Extract 5-10 specific code identifiers, function names, class names, "
            "variable names, or module names from this bug report. "
            "Return ONLY a JSON list of strings, nothing else.\n\n"
            f"Bug report:\n{issue_text[:2000]}"
        )
        resp = _infer(
            OBSERVER_MODEL,
            prompt,
            system="You extract code identifiers from bug reports. Return only JSON.",
        )

        keywords: list[str] = []
        try:
            m = re.search(r"\[.*?\]", resp, re.DOTALL)
            if m:
                keywords = json.loads(m.group())
        except Exception:
            pass

        # Filter noise
        keywords = [k for k in keywords if len(k) >= 3 and k.lower() not in self._NOISE]

        # Fallback: regex extraction from issue text
        if not keywords:
            keywords = [
                w
                for w in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", issue_text)
                if w.lower() not in self._NOISE
            ][:10]

        log.info("Keywords: %s", keywords[:8])
        return keywords[:10]

    def _parse_traceback(self, trace: str) -> list[str]:
        """Extract file paths from a stack traceback."""
        if not trace:
            return []

        files = []
        # Python: File "path/to/file.py", line N
        for m in re.finditer(r'File\s+"([^"]+)"', trace):
            path = m.group(1).replace("\\", "/")
            # Make relative if possible
            try:
                rel = str(Path(path).relative_to(self.workspace)).replace("\\", "/")
                files.append(rel)
            except (ValueError, TypeError):
                # Try just the filename
                name = Path(path).name
                for fi in self.files:
                    if fi.path.endswith(name):
                        files.append(fi.path)
                        break

        # Rust: --> src/main.rs:42:5
        for m in re.finditer(r"-->\s+([^\s:]+\.rs):\d+", trace):
            files.append(m.group(1))

        # Go: filename.go:42
        for m in re.finditer(r"([^\s]+\.go):\d+", trace):
            files.append(m.group(1))

        return list(dict.fromkeys(files))  # deduplicate, preserve order


# ── Core: Patch Pipeline ─────────────────────────────────────────────────────


class PatchPipeline:
    """
    Generates targeted patches for identified issues.
    Reuses the proven fix logic from determinex_swebench_agent.py.
    """

    _REGION_THRESHOLD = int(os.getenv("DETERMINEX_REGION_THRESHOLD", "400"))
    _REGION_CONTEXT = int(os.getenv("DETERMINEX_REGION_CONTEXT", "80"))

    def __init__(self, workspace: Path, build_system: str, test_framework: str):
        self.workspace = workspace
        self.build_system = build_system
        self.test_framework = test_framework
        self.shadow = ShadowCompiler(workspace, build_system, test_framework)

    def fix(
        self,
        issue_text: str,
        target_files: list[Path],
        shadow_trace: str = "",
    ) -> PatchResult:
        """
        Generate a patch to fix the described issue.
        Tries up to MAX_RETRIES, validating each attempt against the compiler/tests.
        """
        log.info("Patch pipeline: %d target files, %d max retries", len(target_files), MAX_RETRIES)

        # Plan the fix using the Architect (Observer model)
        steps = self._plan_fix(issue_text, target_files, shadow_trace)
        if not steps:
            return PatchResult(
                success=False,
                patch_diff="",
                files_modified=[],
                tests_passed=False,
                attempts=0,
                error="Could not generate a fix plan",
            )

        # Execute each step
        all_patches = []
        total_attempts = 0

        for step in steps[:3]:
            target = self.workspace / step["file"]
            if not target.exists():
                log.warning("Target not found: %s", target)
                continue

            original = target.read_text(encoding="utf-8", errors="replace")
            last_error = ""

            for attempt in range(1, MAX_RETRIES + 1):
                total_attempts += 1
                log.info(
                    "Step %s attempt %d/%d: %s",
                    step.get("step", "?"),
                    attempt,
                    MAX_RETRIES,
                    step.get("description", "")[:60],
                )

                fixed = self._generate_fix(step, issue_text, last_error, attempt, shadow_trace)
                if not fixed:
                    continue

                # Write the fix
                target.write_text(fixed, encoding="utf-8")

                # Validate
                compile_ok, compile_out = self.shadow.compile()
                if not compile_ok:
                    last_error = compile_out
                    target.write_text(original, encoding="utf-8")
                    continue

                # Targeted tests
                test_ok, test_out = self.shadow.run_tests()
                if not test_ok:
                    last_error = test_out
                    target.write_text(original, encoding="utf-8")
                    continue

                # Success! Generate the diff
                patch = self._make_diff(step["file"], original, fixed)
                if patch:
                    all_patches.append(patch)
                    log.info("Step %s FIXED on attempt %d", step.get("step", "?"), attempt)
                    break
            else:
                # All retries exhausted — restore original
                target.write_text(original, encoding="utf-8")
                log.warning("Step %s exhausted all retries", step.get("step", "?"))

        if all_patches:
            combined = "\n".join(all_patches)
            files_modified = [
                step.get("file", "")
                for step in steps
                if any(step.get("file", "") in p for p in all_patches)
            ]
            return PatchResult(
                success=True,
                patch_diff=combined,
                files_modified=files_modified,
                tests_passed=True,
                attempts=total_attempts,
                error="",
            )

        return PatchResult(
            success=False,
            patch_diff="",
            files_modified=[],
            tests_passed=False,
            attempts=total_attempts,
            error="All fix attempts exhausted",
        )

    def _plan_fix(self, issue_text: str, target_files: list[Path], shadow_trace: str) -> list[dict]:
        """Architect: decompose the fix into 1-3 atomic steps."""
        file_summaries = []
        for f in target_files[:4]:
            try:
                rel = str(f.relative_to(self.workspace)).replace("\\", "/")
                content = f.read_text(encoding="utf-8", errors="replace")
                all_lines = content.splitlines()
                total = len(all_lines)

                if total <= 200:
                    # Small file: show the whole thing
                    numbered = "\n".join(f"{i + 1:4d}: {l}" for i, l in enumerate(all_lines))
                    file_summaries.append(f"=== {rel} ({total} lines) ===\n{numbered}")
                else:
                    # Large file: signature index + targeted region
                    # 1) Extract function/class signatures as a map
                    sigs = []
                    for i, line in enumerate(all_lines):
                        stripped = line.lstrip()
                        if re.match(
                            r"(?:pub\s+)?(?:async\s+)?(?:def|fn|func|fun|class|struct|impl|trait|interface|type)\s+\w+",
                            stripped,
                        ):
                            sigs.append(f"  L{i + 1:4d}: {stripped[:100]}")
                    sig_block = "\n".join(sigs[:40]) if sigs else "  (no signatures found)"

                    # 2) Find traceback anchor lines in this file
                    fname = Path(rel).name
                    anchor_lines = set()
                    if shadow_trace:
                        for m in re.finditer(rf"(?:{re.escape(fname)})[^\d]*?(\d+)", shadow_trace):
                            anchor_lines.add(int(m.group(1)))

                    # 3) Build targeted region: show 30 lines around each anchor
                    region_parts = []
                    shown = set()
                    for anchor in sorted(anchor_lines)[:3]:
                        start = max(0, anchor - 16)
                        end = min(total, anchor + 15)
                        if any(i in shown for i in range(start, end)):
                            continue  # avoid duplicates
                        for i in range(start, end):
                            shown.add(i)
                        region = "\n".join(f"{i + 1:4d}: {all_lines[i]}" for i in range(start, end))
                        region_parts.append(f"  [lines {start + 1}–{end}]\n{region}")

                    # 4) If no anchors, show first 40 + last 20 lines
                    if not region_parts:
                        head = "\n".join(f"{i + 1:4d}: {l}" for i, l in enumerate(all_lines[:40]))
                        tail = "\n".join(
                            f"{total - 20 + i + 1:4d}: {l}" for i, l in enumerate(all_lines[-20:])
                        )
                        region_parts.append(f"  [head: lines 1–40]\n{head}")
                        region_parts.append(f"  [tail: lines {total - 19}–{total}]\n{tail}")

                    regions = "\n".join(region_parts)
                    file_summaries.append(
                        f"=== {rel} ({total} lines) ===\n"
                        f"[SIGNATURES]\n{sig_block}\n\n"
                        f"[RELEVANT REGIONS]\n{regions}"
                    )
            except Exception:
                pass

        trace_section = ""
        if shadow_trace:
            trace_section = (
                f"\n\n[PRE-CHANGE TRACEBACK — captured before any edits]\n{shadow_trace[:1500]}\n"
            )

        prompt = (
            f"You are a senior software engineer. Analyze this bug report and the "
            f"relevant source files.\n"
            f"Produce a minimal fix plan: 1-3 atomic steps, each modifying one file.\n\n"
            f"Bug report:\n{issue_text[:2000]}\n"
            f"{trace_section}\n\n"
            f"Relevant files:\n{'---'.join(file_summaries[:2])}\n\n"
            f"Return ONLY a JSON array of steps:\n"
            f'[{{"step": 1, "file": "path/to/file", "action": "modify", '
            f'"description": "Fix the X function to handle Y edge case"}}]\n'
            f"RULES: Use relative paths from the project root. Maximum 3 steps. "
            f"Minimal targeted changes.\n"
            f"NEVER target test files. Only modify SOURCE files."
        )

        resp = _infer(
            OBSERVER_MODEL,
            prompt,
            system="You plan minimal code fixes. Return only JSON arrays.",
        )

        steps: list[dict] = []
        try:
            m = re.search(r"\[.*?\]", resp, re.DOTALL)
            if m:
                steps = json.loads(m.group())
        except Exception:
            pass

        # Heal template paths
        for step in steps:
            file_val = step.get("file", "")
            if "path/to" in file_val and target_files:
                src_files = [f for f in target_files if not _is_test_file(f)]
                fallback = (src_files or target_files)[0]
                step["file"] = str(fallback.relative_to(self.workspace)).replace("\\", "/")

        if not steps and target_files:
            src = target_files[0]
            rel = str(src.relative_to(self.workspace)).replace("\\", "/")
            steps = [
                {
                    "step": 1,
                    "file": rel,
                    "action": "modify",
                    "description": "Fix the bug described in the issue",
                }
            ]

        log.info("Fix plan: %d step(s)", len(steps))
        return steps

    def _generate_fix(
        self, step: dict, issue_text: str, last_error: str, attempt: int, shadow_trace: str
    ) -> str:
        """Builder: generate the actual code fix."""
        target = self.workspace / step["file"]
        if not target.exists():
            return ""

        original = target.read_text(encoding="utf-8", errors="replace")
        lines = original.splitlines(keepends=True)

        retry_ctx = ""
        if last_error:
            retry_ctx = (
                f"\n\nAttempt #{attempt - 1} FAILED:\n{last_error[:600]}\n"
                "Fix that error. Return ONLY the corrected code."
            )

        if len(lines) > self._REGION_THRESHOLD:
            # Region mode: only show the relevant section
            r_start, r_end = self._extract_target_region(
                [l.rstrip("\n") for l in lines],
                step.get("description", ""),
                shadow_trace,
                step["file"],
            )
            region = [l.rstrip("\n") for l in lines[r_start:r_end]]
            numbered = "\n".join(f"{r_start + i + 1:4d} | {line}" for i, line in enumerate(region))
            prompt = (
                f"Fix this section of the file to resolve the bug.\n\n"
                f"Bug:\n{issue_text[:1500]}\n\n"
                f"Fix: {step.get('description', 'Fix the bug')}\n\n"
                f"File: {step['file']} ({len(lines)} lines total)\n"
                f"Showing lines {r_start + 1}–{r_end}:\n"
                f"```\n{numbered}\n```\n"
                f"{retry_ctx}\n\n"
                f"Return ONLY the corrected lines {r_start + 1}–{r_end}.\n"
                f"No line numbers. No markdown fences. No explanations."
            )
        else:
            plain = [l.rstrip("\n") for l in lines]
            numbered = "\n".join(f"{i + 1:4d} | {l}" for i, l in enumerate(plain))
            prompt = (
                f"Fix this file to resolve the bug.\n\n"
                f"Bug:\n{issue_text[:1500]}\n\n"
                f"Fix: {step.get('description', 'Fix the bug')}\n\n"
                f"File ({step['file']}):\n```\n{numbered}\n```\n"
                f"{retry_ctx}\n\n"
                f"Return ONLY the complete corrected file. "
                f"No line numbers. No markdown fences. No explanations."
            )

        raw = _infer(
            BUILDER_MODEL,
            prompt,
            system="You are an expert developer. Output ONLY correct code. No markdown fences.",
            temperature=0.1 + (attempt * 0.03),
        )

        # Clean up
        raw = re.sub(r"^```\w*\s*\n?", "", raw.strip())
        raw = re.sub(r"\n?```\s*$", "", raw).strip()

        # Strip echoed line numbers
        cleaned = []
        for line in raw.splitlines():
            m = re.match(r"^\s*\d+\s*\|\s?(.*)", line)
            cleaned.append(m.group(1) if m else line)
        raw = "\n".join(cleaned)

        if len(lines) > self._REGION_THRESHOLD:
            # Splice region back
            region_lines = raw.splitlines(keepends=True)
            if region_lines and not region_lines[-1].endswith("\n"):
                region_lines[-1] += "\n"
            rebuilt = lines[:r_start] + region_lines + lines[r_end:]
            return "".join(rebuilt)

        return raw

    def _extract_target_region(
        self, lines: list[str], desc: str, trace: str, file_path: str
    ) -> tuple[int, int]:
        """Find the anchor point in a large file."""
        anchor = -1
        fname = Path(file_path).name

        # 1. Traceback line
        for m in re.finditer(rf"(?:{re.escape(fname)})[^\d]*?(\d+)", trace):
            candidate = int(m.group(1)) - 1
            if 0 <= candidate < len(lines):
                anchor = candidate
                break

        # 2. Named function from description
        if anchor < 0:
            for m in re.finditer(r'[`\'"](\\w+)\s*\(', desc):
                name = m.group(1)
                if len(name) < 3:
                    continue
                for i, line in enumerate(lines):
                    if re.match(
                        rf"\s*(?:async\s+)?(?:def|fn|func|fun)\s+{re.escape(name)}\s*[\(]", line
                    ):
                        anchor = i
                        break
                if anchor >= 0:
                    break

        # 3. Fallback
        if anchor < 0:
            anchor = min(50, len(lines) - 1)

        half = self._REGION_CONTEXT
        start = max(0, anchor - half)
        end = min(len(lines), anchor + half)
        return start, end

    @staticmethod
    def _make_diff(file_path: str, original: str, fixed: str) -> str:
        """Generate a unified diff."""
        import difflib

        rel = Path(file_path).as_posix()
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                fixed.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        if not diff_lines:
            return ""
        patch = f"diff --git a/{rel} b/{rel}\n" + "".join(diff_lines)
        if not patch.endswith("\n"):
            patch += "\n"
        return patch


# ── Main: CodebaseExplorer ───────────────────────────────────────────────────


class CodebaseExplorer:
    """
    Top-level API. Wraps WorkspaceLoader + ShadowCompiler + IssueLocalizer + PatchPipeline.

    Usage:
        explorer = CodebaseExplorer("/path/to/repo")
        report = explorer.explore()         # Scan + diagnose
        patch = explorer.fix("Bug desc")    # Locate + fix
    """

    def __init__(self, workspace_path: str | Path):
        self.workspace = Path(workspace_path).resolve()
        self.loader = WorkspaceLoader(self.workspace)
        self.build_system, self.test_framework = detect_build_system(self.workspace)
        self.shadow = ShadowCompiler(self.workspace, self.build_system, self.test_framework)
        self.files: list[FileInfo] = []

    def explore(self) -> WorkspaceReport:
        """
        Full workspace scan + shadow compilation + diagnostics.
        Returns a structured report suitable for the UI.
        """
        log.info("=" * 60)
        log.info("EXPLORE: %s", self.workspace)
        log.info("=" * 60)

        # 1. Scan files
        self.files = self.loader.scan()
        languages = dict(self.loader.languages)

        # 2. Shadow compile
        compile_ok, compile_out = self.shadow.compile()

        # 3. Shadow tests
        test_ok, test_out = self.shadow.run_tests()

        # 4. Generate findings
        findings: list[dict] = []

        if not compile_ok:
            for line in compile_out.splitlines()[:10]:
                findings.append(
                    asdict(
                        DiagnosticFinding(
                            severity="error",
                            file="",
                            line=0,
                            message=line.strip(),
                            category="compilation",
                        )
                    )
                )

        if not test_ok:
            for line in test_out.splitlines()[:10]:
                if "FAILED" in line or "Error" in line or "error" in line:
                    findings.append(
                        asdict(
                            DiagnosticFinding(
                                severity="error",
                                file="",
                                line=0,
                                message=line.strip(),
                                category="test_failure",
                            )
                        )
                    )

        # Health score: simple heuristic
        health = 1.0
        if not compile_ok:
            health -= 0.4
        if not test_ok:
            health -= 0.3
        if not self.files:
            health -= 0.3
        health = max(0.0, health)

        shadow_combined = ""
        if compile_out:
            shadow_combined += f"[COMPILATION]\n{compile_out}\n\n"
        if test_out:
            shadow_combined += f"[TESTS]\n{test_out}"

        report = WorkspaceReport(
            workspace_path=str(self.workspace),
            total_files=len(self.files),
            source_files=len([f for f in self.files if f.category == "source"]),
            test_files=len([f for f in self.files if f.category == "test"]),
            config_files=len([f for f in self.files if f.category == "config"]),
            languages=languages,
            build_system=self.build_system,
            test_framework=self.test_framework,
            findings=findings,
            shadow_output=shadow_combined[:5000],
            health_score=health,
        )

        log.info("Explore complete: health=%.1f, %d findings", health, len(findings))
        return report

    def diagnose(self, issue_text: str) -> dict:
        """
        Given a user-described issue, locate the relevant files and
        return a diagnosis with suggested targets.
        """
        if not self.files:
            self.files = self.loader.scan()

        # Shadow compile to get traceback
        _, shadow_trace = self.shadow.compile()
        if not shadow_trace:
            _, shadow_trace = self.shadow.run_tests()

        localizer = IssueLocalizer(self.workspace, self.files)
        targets = localizer.locate(issue_text, shadow_trace)

        # Read context from target files
        file_contexts = []
        for t in targets[:5]:
            try:
                rel = str(t.relative_to(self.workspace)).replace("\\", "/")
                content = t.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()
                file_contexts.append(
                    {
                        "file": rel,
                        "lines": len(lines),
                        "preview": "\n".join(lines[:30]),
                    }
                )
            except Exception:
                pass

        return {
            "issue": issue_text,
            "targets": [str(t.relative_to(self.workspace)) for t in targets],
            "file_contexts": file_contexts,
            "shadow_trace": shadow_trace[:2000],
            "build_system": self.build_system,
            "test_framework": self.test_framework,
        }

    def fix(self, issue_text: str, out_path: str | Path | None = None) -> PatchResult:
        """
        End-to-end: locate the bug, generate a fix, validate it.
        """
        if not self.files:
            self.files = self.loader.scan()

        # Shadow compilation for traceback
        _, shadow_trace = self.shadow.compile()
        if not shadow_trace:
            _, shadow_trace = self.shadow.run_tests()

        # Locate targets
        localizer = IssueLocalizer(self.workspace, self.files)
        targets = localizer.locate(issue_text, shadow_trace)

        # Generate and validate the fix
        pipeline = PatchPipeline(self.workspace, self.build_system, self.test_framework)
        result = pipeline.fix(issue_text, targets, shadow_trace)

        # Optionally write patch to file
        if result.success and out_path:
            Path(out_path).write_text(result.patch_diff, encoding="utf-8")
            log.info("Patch saved: %s", out_path)

        return result


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Determinex Enterprise Codebase Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # explore — scan and diagnose a workspace
    p_explore = sub.add_parser("explore", help="Scan and diagnose a codebase")
    p_explore.add_argument(
        "--workspace", "-w", type=Path, required=True, help="Path to the project root"
    )
    p_explore.add_argument("--json", action="store_true", help="Output as JSON")

    # diagnose — locate files relevant to a bug
    p_diag = sub.add_parser("diagnose", help="Locate files relevant to a bug")
    p_diag.add_argument("--workspace", "-w", type=Path, required=True)
    p_diag.add_argument(
        "--issue", "-i", type=str, required=True, help="Description of the bug or issue"
    )

    # fix — generate a patch
    p_fix = sub.add_parser("fix", help="Generate a patch to fix a bug")
    p_fix.add_argument("--workspace", "-w", type=Path, required=True)
    p_fix.add_argument("--issue", "-i", type=str, required=True)
    p_fix.add_argument(
        "--out", "-o", type=Path, default=None, help="Path to save the generated patch"
    )

    args = parser.parse_args()

    explorer = CodebaseExplorer(args.workspace)

    if args.cmd == "explore":
        report = explorer.explore()
        if args.json:
            print(json.dumps(asdict(report), indent=2, default=str))
        else:
            print(f"\n{'=' * 60}")
            print(f"WORKSPACE REPORT: {report.workspace_path}")
            print(f"{'=' * 60}")
            print(
                f"Files:     {report.total_files} total "
                f"({report.source_files} source, {report.test_files} test, "
                f"{report.config_files} config)"
            )
            print(f"Build:     {report.build_system}")
            print(f"Tests:     {report.test_framework}")
            print(f"Health:    {report.health_score:.0%}")
            print(f"Languages: {report.languages}")
            if report.findings:
                print(f"\nFindings ({len(report.findings)}):")
                for f in report.findings[:10]:
                    print(f"  [{f['severity'].upper()}] {f['message'][:100]}")
            if report.shadow_output:
                print(f"\nShadow output:\n{report.shadow_output[:500]}")

    elif args.cmd == "diagnose":
        result = explorer.diagnose(args.issue)
        print(json.dumps(result, indent=2, default=str))

    elif args.cmd == "fix":
        result = explorer.fix(args.issue, args.out)
        if result.success:
            print(f"\nPATCH GENERATED ({result.attempts} attempts)")
            print(f"Files modified: {result.files_modified}")
            if args.out:
                print(f"Saved to: {args.out}")
            else:
                print(result.patch_diff)
        else:
            print(f"\nFIX FAILED after {result.attempts} attempts: {result.error}")
            sys.exit(1)


if __name__ == "__main__":
    main()
