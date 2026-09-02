"""
scripts/hive/workspace.py — Workspace management and Builder context assembly
==============================================================================
Moved from determinex_hive.py (lines ~703-789, ~1044-1229).
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import shutil
import tempfile
from pathlib import Path

from hive.compiler import get_toolchain_version  # L5-B
from hive.concurrent_guard import WorkspaceLock  # #28
from hive.manifest import StepRecord
from hive.rag_guard import is_binary_file, is_oversized_file  # #14 OOM guard

log = logging.getLogger("hive")

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE_BASE = Path(tempfile.gettempdir()) / "determinex_workspaces"
_WORKSPACE_BASE = WORKSPACE_BASE  # legacy alias

# ── Signature index limits ────────────────────────────────────────────────────
SIG_INDEX_REGION_LINES = 60
MAX_FILE_LINES_BEFORE_SIG = 200

# ── #11 Snapshot / hash exclusion list ───────────────────────────────────────
# These directories contain compiler artifacts, vendored dependencies, or
# generated build outputs. Copying them into per-step snapshots causes Inode
# exhaustion on the host SSD (Rust target/ alone creates 40,000+ files).
_SNAPSHOT_EXCLUDE_DIRS = frozenset(
    [
        "target",  # Rust/Cargo compilation artifacts
        "node_modules",  # npm / yarn dependencies
        "vendor",  # Go vendored packages
        "dist",  # TypeScript/bundler output
        ".git",  # Git object store
        ".venv",  # Python virtual environment
        "__pycache__",  # Python bytecode
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    ]
)


def _is_excluded_path(path: Path, workspace: Path) -> bool:
    """Return True if path is inside a snapshot-excluded directory (#11)."""
    try:
        rel = path.relative_to(workspace)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in _SNAPSHOT_EXCLUDE_DIRS


# ── Workspace path safety (symlink escape prevention) ─────────────────────────


def resolve_workspace_path(path: Path, workspace: Path) -> Path:
    """
    Resolve *path* and verify it stays inside *workspace*.

    Follows symlinks via Path.resolve() then checks containment.
    Blocks: symlink escapes, junction escapes (Windows), and `../` traversal
    that crosses the workspace boundary.

    Raises ValueError if the resolved path escapes the workspace.
    """
    try:
        resolved = path.resolve()
        workspace_resolved = workspace.resolve()
    except OSError as exc:
        raise ValueError(f"Path resolution failed for '{path}': {exc}") from exc

    try:
        resolved.relative_to(workspace_resolved)
    except ValueError:
        raise ValueError(
            f"Path escape detected: '{path}' resolves to '{resolved}' "
            f"which is outside workspace '{workspace_resolved}'"
        )
    return resolved


def assert_inside_workspace(path: Path, workspace: Path) -> None:
    """Raise ValueError if *path* resolves to a location outside *workspace*."""
    resolve_workspace_path(path, workspace)


# ── #27 Secret key absolute denylist ─────────────────────────────────────────
# .gitignore is insufficient because users make mistakes. These patterns are
# enforced at the file I/O layer — before content reaches the embedding model,
# the Vanguard Vault, or any LLM prompt.
_SECRET_NAME_RE = re.compile(
    r"(\.env$|\.env\.|\.pem$|\.key$|\.pfx$|\.p12$"
    r"|id_rsa|id_ed25519|id_ecdsa"
    r"|secrets?\.(json|yaml|yml|toml|txt)|credentials"
    r"|auth_token|\.netrc)",
    re.IGNORECASE,
)
_KEY_PREFIX_RE = re.compile(
    r"(AKIA[0-9A-Z]{16}"  # AWS access key
    r"|\bAIza[0-9A-Za-z\-_]{35}\b"  # GCP API key
    r"|ghp_[A-Za-z0-9]{36}"  # GitHub personal token
    r"|ghs_[A-Za-z0-9]{36}"  # GitHub app token
    r"|sk-[A-Za-z0-9]{48}"  # OpenAI secret key
    r"|xoxb-[0-9A-Za-z\-]+"  # Slack bot token
    r")"
)
_SECRET_ENTROPY_THRESHOLD = (
    5.0  # G22: raised from 4.5 → 5.0 to reduce false positives on base64/binary content
)
_SECRET_SCAN_BYTES = 4096  # only scan first 4KB


def _shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string in bits per character."""
    if not data:
        return 0.0
    freq: dict[str, int] = {}
    for ch in data:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


_CODE_EXTENSIONS = frozenset({".py", ".rs", ".go", ".ts", ".js", ".c", ".cpp", ".h"})


def _is_sensitive_file(path: Path) -> bool:
    """#27: Return True if the file should be blocked from RAG/embedding.

    Matches on filename patterns AND scans the first 4KB for known key prefixes
    and high-entropy strings. Applied before any file content is read by the
    embedding model or written to the training vault.

    Note: entropy check is skipped for code files (.py, .rs, .go, etc.) because
    generated code legitimately has high Shannon entropy — false positive rate is too high.
    """
    if _SECRET_NAME_RE.search(path.name):
        log.warning("Secret denylist: blocked sensitive filename '%s'", path.name)
        return True
    is_code_file = path.suffix.lower() in _CODE_EXTENSIONS
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:_SECRET_SCAN_BYTES]
        if _KEY_PREFIX_RE.search(head):
            log.warning("Secret denylist: key pattern detected in '%s'", path)
            return True
        if not is_code_file:
            for line in head.splitlines():
                stripped = line.strip()
                if (
                    len(stripped) >= 50 and _shannon_entropy(stripped) > _SECRET_ENTROPY_THRESHOLD
                ):  # G22: min length 40→50
                    log.warning(
                        "Secret denylist: high-entropy content in '%s' — "
                        "blocking to prevent credential leakage",
                        path,
                    )
                    return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


# ── #SEC-4 Corpus Integrity — HMAC signing wrappers ──────────────────────────
#
# Every verdict corpus entry must be HMAC-signed before being written to disk
# and verified before being ingested into any retraining pipeline.
#
# Signing prevents corpus poisoning: a manually crafted (error→fix) pair that
# passes the compiler oracle but introduces a backdoor would be blocked at
# ingest time if it lacks a valid signature from the issuing process.
#
# Delegates to determinex_safety.SafetyEngine for the actual HMAC logic (BLAKE2b).
# Key is loaded from DETERMINEX_CORPUS_HMAC_KEY env var; falls back to ephemeral
# session key if not set (sufficient for in-process tamper detection).


def sign_corpus_entry(entry: dict) -> None:
    """#SEC-4: HMAC-sign a corpus entry dict in-place (adds '_sig' key)."""
    try:
        from determinex_safety import sign_corpus_entry as _sign

        _sign(entry)
    except ImportError:
        log.warning("[SEC-4] determinex_safety unavailable — corpus entry not signed")


def verify_corpus_entry(entry: dict) -> bool:
    """#SEC-4: Verify HMAC signature on a corpus entry. Raises CorpusTamperError if invalid.

    An unavailable verifier is NOT a valid signature. This returned True when
    `determinex_safety` could not be imported -- so on any machine where that import failed,
    every corpus entry verified, including a tampered one. The log line said "verify
    skipped" while the return value said "verified", and callers see return values.

    Found 2026-08-02 by an AST scan for the shape `except ...: return <success>`, after the
    same shape was found by hand in four other places that day. Signature checking is where
    fail-open costs the most: the corpus is training data, and Layer 6 exists specifically to
    catch tampering with signed corpus data.

    Raising is correct rather than returning False: False means "this entry is forged", which
    is also a claim we cannot support. "We could not check" is its own answer.
    """
    try:
        from determinex_safety import verify_corpus_entry as _verify
    except ImportError as e:
        log.error("[SEC-4] determinex_safety unavailable — corpus entry CANNOT be verified")
        raise RuntimeError(
            "corpus HMAC verification is unavailable (determinex_safety could not be "
            "imported); refusing to report an unverified entry as valid"
        ) from e
    return _verify(entry)


# ── Workspace management ──────────────────────────────────────────────────────


def create_workspace(session_id: str, lang: str) -> tuple[Path, WorkspaceLock]:
    """
    Create a per-session temp workspace directory and acquire an exclusive
    file lock on it (#28 workspace lock).

    Returns (workspace_path, lock). The caller MUST call lock.release() when
    the session completes or use it as a context manager.

    Raises WorkspaceLockError if another Determinex process holds the lock.
    """
    workspace = _WORKSPACE_BASE / session_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "src").mkdir(exist_ok=True)
    (workspace / "steps").mkdir(exist_ok=True)
    # #28: Acquire exclusive hardware file lock before any compiler writes.
    lock = WorkspaceLock(session_id, workspace, timeout=10.0)
    lock.acquire()
    log.info("Workspace created and locked: %s", workspace)
    return workspace, lock


def release_workspace(lock: WorkspaceLock) -> None:
    """Release the workspace file lock acquired by create_workspace (#28)."""
    lock.release()


def scaffold_rust_project(
    workspace: Path, package_name: str, dependencies: dict | None = None, binary: bool = True
) -> str:
    """Write Cargo.toml + placeholder src/main.rs to workspace. Returns Cargo.toml content.

    For a binary project (binary=True, the default): creates src/main.rs placeholder.
    For a library project (binary=False): creates src/lib.rs placeholder + [lib] section.
    """
    # Rust package names cannot start with a digit — prefix with 'pkg_' if needed
    if package_name and package_name[0].isdigit():
        package_name = "pkg_" + package_name

    deps_lines = ""
    if dependencies:
        # Values in _RUST_KNOWN_CRATES already include correct TOML syntax:
        # simple versions as '"1"' (with quotes), inline tables as '{ version = "1", ... }'.
        # Use f'{k} = {v}' — no extra quote wrapping.
        deps_lines = "\n".join(f"{k} = {v}" for k, v in dependencies.items())

    (workspace / "src").mkdir(parents=True, exist_ok=True)

    if binary:
        cargo_content = f"""\
[package]
name = "{package_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
{deps_lines}
"""
        # Placeholder binary so `cargo check` passes on empty project
        main_rs = workspace / "src" / "main.rs"
        if not main_rs.exists():
            main_rs.write_text("fn main() {}\n", encoding="utf-8")
    else:
        cargo_content = f"""\
[package]
name = "{package_name}"
version = "0.1.0"
edition = "2021"

[dependencies]
{deps_lines}

[lib]
name = "{package_name}"
path = "src/lib.rs"
"""
        lib_rs = workspace / "src" / "lib.rs"
        if not lib_rs.exists():
            lib_rs.write_text("// placeholder\n", encoding="utf-8")

    (workspace / "Cargo.toml").write_text(cargo_content, encoding="utf-8")
    log.info("Scaffolded Cargo.toml for package '%s' (binary=%s)", package_name, binary)
    return cargo_content


def scaffold_go_module(workspace: Path, module_name: str, go_version: str = "1.21") -> str:
    """Write go.mod to workspace. Returns content."""
    content = f"module {module_name}\ngo {go_version}\n"
    (workspace / "go.mod").write_text(content, encoding="utf-8")
    (workspace / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    log.info("Scaffolded go.mod for module '%s'", module_name)
    return content


def scaffold_python_project(
    workspace: Path, package_name: str, requirements: list | None = None
) -> str:
    """Write pyproject.toml and requirements.txt. Returns requirements content."""
    reqs = "\n".join(requirements or [])
    (workspace / "requirements.txt").write_text(reqs, encoding="utf-8")
    pyproject = f"""\
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "{package_name}"
version = "0.1.0"
"""
    (workspace / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    log.info("Scaffolded pyproject.toml for package '%s'", package_name)
    return reqs


def cleanup_workspace(session_id: str, project_root: Path | None = None) -> None:
    """Remove the workspace directory for a completed session.

    G34: accepts explicit project_root so callers that set a non-default
    workspace path don't silently clean the wrong directory.
    """
    workspace = Path(project_root) if project_root else _WORKSPACE_BASE / session_id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
        log.info("Workspace cleaned up: %s", workspace)


# ── Workspace file hashing ────────────────────────────────────────────────────


def hash_workspace_files(workspace: Path, lang: str) -> dict[str, str]:
    """
    Compute SHA256 hashes for all source files in the workspace.
    Used by session resume protocol to detect manual edits between sessions.

    #11: Excludes snapshot-bloating directories (target/, node_modules/, etc.).
    #27: Skips files matching the secret key denylist.
    """
    exts = {"rust": [".rs"], "go": [".go"], "python": [".py"]}.get(
        lang.lower(), [".rs", ".go", ".py"]
    )
    hashes: dict[str, str] = {}
    for ext in exts:
        for f in sorted(workspace.rglob(f"*{ext}")):
            # #11: skip compiler artifacts and vendored deps
            if _is_excluded_path(f, workspace):
                continue
            # #27: skip sensitive files before their content is read
            if _is_sensitive_file(f):
                continue
            # #14: skip binary artifacts that share a source extension (e.g. .o → .go)
            if is_binary_file(f) or is_oversized_file(f):
                log.debug("hash_workspace: skipping binary/oversized file '%s'", f)
                continue
            rel = str(f.relative_to(workspace)).replace("\\", "/")
            h = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
            hashes[rel] = h
    return hashes


# ── Signature index (Builder context for large files) ────────────────────────


def build_signature_index(file_path: Path, lang: str) -> tuple[str, str]:
    """
    Extract function/struct signatures from a source file for Builder context.
    Returns (index_text, parse_mode) where parse_mode is "normal" or "degraded".
    """
    if not file_path.exists():
        return "(file not yet created)", "normal"

    content = file_path.read_text(encoding="utf-8")

    ts_result = _try_tree_sitter_index(file_path, content, lang)
    if ts_result is not None:
        return ts_result, "normal"

    log.debug("Signature index: tree-sitter unavailable — using regex (degraded)")
    return _regex_signature_index(content, lang), "degraded"


def _try_tree_sitter_index(file_path: Path, content: str, lang: str) -> str | None:
    """
    Attempt tree-sitter parse using the Python tree-sitter bindings.
    Returns a signature index string on success, None if tree-sitter is not
    installed (caller falls back to regex).

    Requires: pip install tree-sitter tree-sitter-rust tree-sitter-go tree-sitter-python
    These are listed as optional in hive/requirements.txt.
    """
    lang_module_map = {
        "rust": "tree_sitter_rust",
        "go": "tree_sitter_go",
        "python": "tree_sitter_python",
    }
    lang_key = lang.lower()
    mod_name = lang_module_map.get(lang_key)
    if not mod_name:
        return None

    try:
        import importlib

        from tree_sitter import Language, Parser

        lang_module = importlib.import_module(mod_name)
        ts_lang = Language(lang_module.language())
        parser = Parser(ts_lang)
        tree = parser.parse(content.encode("utf-8"))

        # Fail fast if AST is mostly error nodes (broken syntax from prior step).
        error_count = sum(1 for node in _iter_nodes(tree.root_node) if node.type == "ERROR")
        total_count = sum(1 for _ in _iter_nodes(tree.root_node))
        if total_count > 0 and error_count / total_count > 0.20:
            return None  # degraded AST — let caller use regex fallback

        sigs: list[str] = []
        if lang_key == "rust":
            _extract_rust_sigs(tree.root_node, content, sigs)
        elif lang_key == "go":
            _extract_go_sigs(tree.root_node, content, sigs)
        elif lang_key == "python":
            _extract_python_sigs(tree.root_node, content, sigs)

        return "\n".join(sigs) if sigs else None
    except Exception:
        return None


def _iter_nodes(node):
    """DFS traversal of a tree-sitter node tree."""
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _node_first_line(node, content_bytes: bytes) -> str:
    """Return the first line of source for a tree-sitter node."""
    start_byte = node.start_byte
    end_byte = min(node.end_byte, len(content_bytes))
    chunk = content_bytes[start_byte:end_byte].decode("utf-8", errors="backslashreplace")
    return chunk.split("\n")[0].strip()


def _extract_rust_sigs(root, content: str, sigs: list[str]) -> None:
    cb = content.encode("utf-8")
    target_types = {
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "type_item",
    }
    for node in _iter_nodes(root):
        if node.type in target_types:
            sigs.append(_node_first_line(node, cb))


def _extract_go_sigs(root, content: str, sigs: list[str]) -> None:
    cb = content.encode("utf-8")
    for node in _iter_nodes(root):
        if node.type in {"function_declaration", "method_declaration", "type_declaration"}:
            sigs.append(_node_first_line(node, cb))


def _extract_python_sigs(root, content: str, sigs: list[str]) -> None:
    cb = content.encode("utf-8")
    for node in _iter_nodes(root):
        if node.type in {"function_definition", "class_definition"}:
            sigs.append(_node_first_line(node, cb))


def _regex_signature_index(content: str, lang: str) -> str:
    """
    Regex-based signature extractor. Extracts function/struct/class names + first line.
    Language-aware patterns.
    """
    lang = lang.lower()
    lines = content.splitlines()
    sigs: list[str] = []

    if "rust" in lang:
        patterns = [
            r"^(pub\s+)?(async\s+)?fn\s+\w+.*",
            r"^(pub\s+)?struct\s+\w+.*",
            r"^(pub\s+)?enum\s+\w+.*",
            r"^(pub\s+)?trait\s+\w+.*",
            r"^impl(\s+\w+)?\s+for\s+\w+.*",
            r"^impl\s+\w+.*",
        ]
    elif "go" in lang:
        patterns = [
            r"^func\s+\w+\(.*",
            r"^type\s+\w+\s+(struct|interface).*",
        ]
    elif "python" in lang:
        patterns = [
            r"^(async\s+)?def\s+\w+\(.*",
            r"^class\s+\w+.*",
        ]
    else:
        patterns = [r"^(func|def|class|fn|pub)\s+\w+.*"]

    combo = re.compile("|".join(patterns))
    for i, line in enumerate(lines):
        stripped = line.strip()
        if combo.match(stripped):
            sig_line = stripped.rstrip("{").rstrip(":")[:120]
            sigs.append(f"L{i + 1}: {sig_line}")

    if not sigs:
        return "(no signatures found — file may be empty or unstructured)"
    return "\n".join(sigs)


def get_target_region(
    file_path: Path, step: StepRecord, region_lines: int = SIG_INDEX_REGION_LINES
) -> str:
    """
    Extract the target region from the file: N lines before and after the insertion point.
    Used when a file is too large to fit in Builder's context window.
    """
    if not file_path.exists():
        return "(target file not yet created)"

    lines = file_path.read_text(encoding="utf-8").splitlines()

    # Mole-116: scale context window with file size so the LLM isn't blind to
    # global state in large files.  The fixed 60-line window was designed for
    # small scaffolded files; 5 000-line Rust modules need far more context.
    file_len = len(lines)
    if region_lines == SIG_INDEX_REGION_LINES:
        if file_len > 2000:
            region_lines = 200
        elif file_len > 1000:
            region_lines = 120
        elif file_len > 500:
            region_lines = 80

    if not step.target_region:
        if len(lines) <= region_lines * 2:
            return "\n".join(lines)
        return "\n".join(lines[-region_lines:])

    target = step.target_region
    center_line = 0
    for i, line in enumerate(lines):
        if target.lower() in line.lower():
            center_line = i
            break

    start = max(0, center_line - region_lines)
    end = min(len(lines), center_line + region_lines)
    region_content = "\n".join(lines[start:end])

    if start > 0:
        region_content = f"... (lines 1–{start} omitted) ...\n" + region_content
    if end < len(lines):
        region_content += f"\n... (lines {end + 1}–{len(lines)} omitted) ..."

    return region_content


def assemble_builder_context(
    workspace: Path,
    step: StepRecord,
    lang: str,
    last_compiler_error: str = "",
    parse_mode_override: str | None = None,
) -> str:
    """
    Assemble Builder's full context window for a step.
    """
    target_file = workspace / step.target_file if step.target_file else None
    parts: list[str] = []

    parts.append(f"STEP {step.id}: {step.instruction}")
    if step.dsl_context:
        parts.append(f"\nDSL CONTEXT:\n{step.dsl_context}")

    # L5-B: Inject the ACTUAL installed compiler version so the model targets the
    # host toolchain instead of guessing from its training cutoff.
    tc_ver = get_toolchain_version(lang)
    if tc_ver:
        parts.append(
            f"\nTOOLCHAIN VERSION (host): {tc_ver}\nWrite code compatible with this version."
        )

    # Inject Cargo.toml [dependencies] so the Builder knows which crates are available.
    # Without this, 1.5B models hallucinate crates not in Cargo.toml (lazy_static, etc.)
    if lang == "rust":
        cargo_toml = workspace / "Cargo.toml"
        if cargo_toml.exists():
            cargo_text = cargo_toml.read_text(encoding="utf-8")
            # Extract just the [dependencies] section
            dep_match = re.search(r"\[dependencies\](.*?)(?:\[|\Z)", cargo_text, re.DOTALL)
            if dep_match:
                dep_section = dep_match.group(1).strip()
                if dep_section:
                    parts.append(
                        f"\nAVAILABLE CRATES (Cargo.toml [dependencies]):\n{dep_section}\nOnly use these crates. Do not import anything else."
                    )
                else:
                    parts.append(
                        "\nAVAILABLE CRATES: NONE. No external crates are in Cargo.toml. Use ONLY std:: — no serde, no tokio, no rand, no anyhow, nothing else."
                    )

    # For main.rs steps: inject lib.rs as a library context so the model knows
    # what types are already defined and how to import them.
    if lang == "rust" and step.target_file and "main.rs" in step.target_file:
        lib_rs = workspace / "src" / "lib.rs"
        if lib_rs.exists():
            lib_content = lib_rs.read_text(encoding="utf-8")
            if lib_content.strip() and lib_content.strip() != "// placeholder":
                # Extract package name from Cargo.toml for the use statement
                pkg_name = ""
                cargo_toml = workspace / "Cargo.toml"
                if cargo_toml.exists():
                    m = re.search(
                        r'^name\s*=\s*"([^"]+)"',
                        cargo_toml.read_text(encoding="utf-8"),
                        re.MULTILINE,
                    )
                    if m:
                        pkg_name = m.group(1)
                use_hint = (
                    f"\nImport types with: `use {pkg_name}::*;` or `use {pkg_name}::{{TypeName}};`"
                    if pkg_name
                    else ""
                )
                parts.append(
                    f"\nLIBRARY FILE (src/lib.rs — types are defined here, import them in main.rs):{use_hint}\n"
                    f"<untrusted_file_content>\n```rust\n{lib_content}\n```\n</untrusted_file_content>"
                )

    if target_file and target_file.exists():
        file_lines = target_file.read_text(encoding="utf-8").splitlines()
        if len(file_lines) > MAX_FILE_LINES_BEFORE_SIG:
            region = get_target_region(target_file, step)
            sig_index, parse_mode = build_signature_index(target_file, lang)
            actual_mode = parse_mode_override or parse_mode
            parts.append(
                f"\nCURRENT FILE (target region — full file is {len(file_lines)} lines):\n<untrusted_file_content>\n```\n{region}\n```\n</untrusted_file_content>"
            )
            sig_note = (
                " [DEGRADED — tree-sitter failed, may be incomplete]"
                if actual_mode == "degraded"
                else ""
            )
            parts.append(
                f"\nFILE SIGNATURE INDEX{sig_note}:\n<untrusted_file_content>\n{sig_index}\n</untrusted_file_content>"
            )
        else:
            content = "\n".join(file_lines)
            parts.append(
                f"\nCURRENT FILE ({step.target_file}):\n<untrusted_file_content>\n```\n{content}\n```\n</untrusted_file_content>"
            )
    elif step.target_file:
        parts.append(
            f"\nTARGET FILE: {step.target_file} (does not exist yet — use write_mode: new_file)"
        )

    harness_path = getattr(step, "_session_correctness_test_harness", "")
    if harness_path:
        harness = workspace / harness_path
        if harness.is_file() and not _is_sensitive_file(harness):
            harness_text = harness.read_text(encoding="utf-8", errors="ignore")[:2000]
            parts.append(
                f"\nCORRECTNESS TEST HARNESS ({harness_path}):\n"
                f"<untrusted_file_content>\n```{lang}\n{harness_text}\n```\n</untrusted_file_content>"
            )

    if last_compiler_error:
        parts.append(f"\nLAST COMPILER ERROR:\n{last_compiler_error[:1500]}")

    return "\n".join(parts)
