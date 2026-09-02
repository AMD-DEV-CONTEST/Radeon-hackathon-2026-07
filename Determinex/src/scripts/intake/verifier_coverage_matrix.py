"""scripts/intake/verifier_coverage_matrix.py — Honest coverage matrix.

Maps (language × build_system_id × test_framework_id) onto a coverage
status: ``backed`` | ``partial`` | ``missing`` | ``unknown``.

Locked under ``locks/sentinel/VERIFIER_COVERAGE_MATRIX_LOCK_001.json``.

Honesty rules (enforced by the lock + tests):

  * A row is **backed** ONLY if there is a deterministic verifier/oracle
    wired end-to-end: detection in the BuildAdapter registry, plus a
    shadow build path, plus a test-execution path, plus a corpus/repair
    pipeline that operates on real outputs from that toolchain.
  * A row is **partial** if SOMETHING is wired but the path is
    incomplete (e.g. the shadow build is a no-op script, or the adapter
    detects the manifest but the test framework is not wired, or the
    adapter compiles a related language only).
  * A row is **missing** when the (language, build, test) combination is
    a known target but no deterministic verifier path exists in this
    repo today.
  * Any combination NOT in ``COVERAGE_MATRIX`` returns ``UNKNOWN`` via
    ``lookup()``. There is no implicit fallback to **partial** or
    **backed** — unsupported combinations fail closed.

The existence of a validator under ``scripts/validators/`` is NOT, by
itself, sufficient for **backed** — those modules are DATA ENGINE ONLY
(see ``scripts/validators/__init__.py`` lines 1-9). The matrix tracks
the inference-side verifier, not the corpus-side filter.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CoverageStatus(str, Enum):
    BACKED = "backed"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CoverageEntry:
    language: str
    build_system_id: str
    test_framework_id: str
    oracle_path: str
    status: CoverageStatus
    notes: str = ""


# ---------------------------------------------------------------------------
# The canonical matrix.
#
# Order: backed first, then partial, then missing, then unknown. Within each
# tier, alphabetical by language for stable doc generation.
# ---------------------------------------------------------------------------

COVERAGE_MATRIX: tuple[CoverageEntry, ...] = (
    # ── backed ────────────────────────────────────────────────────────────
    CoverageEntry(
        language="Python",
        build_system_id="pip",
        test_framework_id="pytest",
        oracle_path=(
            "PythonAdapter.run_shadow_build (py_compile) + "
            "ShadowCompiler.run_tests (pytest) + "
            "PythonRepairPipeline (PYTHON_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.BACKED,
        notes="End-to-end: syntax compile + pytest execution + signed repair corpus.",
    ),
    CoverageEntry(
        language="Rust",
        build_system_id="cargo",
        test_framework_id="cargo test",
        oracle_path=(
            "RustAdapter.run_shadow_build (cargo check) + "
            "ShadowCompiler.run_tests (cargo test) + "
            "RustRepairPipeline (RUST_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.BACKED,
        notes="End-to-end: cargo check + cargo test + signed repair corpus.",
    ),
    CoverageEntry(
        language="Go",
        build_system_id="go",
        test_framework_id="go test",
        oracle_path=(
            "GoAdapter.run_shadow_build (go build ./...) + "
            "ShadowCompiler.run_tests (go test ./...) + "
            "GoRepairPipeline (GO_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.BACKED,
        notes="End-to-end: go build + go test + signed repair corpus.",
    ),
    CoverageEntry(
        language="Java",
        build_system_id="maven",
        test_framework_id="maven test",
        oracle_path=(
            "JavaMavenAdapter.run_shadow_build (mvn compile -q) + "
            "ShadowCompiler.run_tests (mvn test -q) + "
            "JavaRepairPipeline (JAVA_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.BACKED,
        notes="End-to-end: mvn compile + mvn test + JavaRepairPipeline.",
    ),
    CoverageEntry(
        language="Java",
        build_system_id="gradle",
        test_framework_id="gradle test",
        oracle_path=(
            "JavaGradleAdapter.run_shadow_build (gradle compileJava -q) + "
            "ShadowCompiler.run_tests (gradle test -q) + "
            "JavaRepairPipeline (JAVA_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.BACKED,
        notes="Gradle adapter compiles Java; Kotlin via Gradle is a separate row.",
    ),
    # ── partial ───────────────────────────────────────────────────────────
    CoverageEntry(
        language="Kotlin",
        build_system_id="gradle",
        test_framework_id="junit",
        oracle_path=(
            "JavaGradleAdapter detects build.gradle.kts but compiles Java "
            "(gradle compileJava), not Kotlin (gradle compileKotlin); JUnit "
            "run via ShadowCompiler.run_tests (gradle test -q) works"
        ),
        status=CoverageStatus.PARTIAL,
        notes="Detection routes through JavaGradleAdapter; Kotlin-specific compile target NOT wired.",
    ),
    CoverageEntry(
        language="TypeScript",
        build_system_id="npm",
        test_framework_id="jest",
        oracle_path=(
            "NodeAdapter.run_shadow_build (npm run build --if-present) + "
            "ShadowCompiler.run_tests (npx jest --bail --silent) + "
            "TypeScriptRepairPipeline (TYPESCRIPT_REPAIR_LOCK_001)"
        ),
        status=CoverageStatus.PARTIAL,
        notes="Build oracle relies on package.json having a 'build' script — not a true tsc gate. Test execution wired.",
    ),
    CoverageEntry(
        language="TypeScript",
        build_system_id="npm",
        test_framework_id="vitest",
        oracle_path=(
            "NodeAdapter.run_shadow_build (npm run build --if-present) + "
            "ShadowCompiler.run_tests (npx vitest run)"
        ),
        status=CoverageStatus.PARTIAL,
        notes="Build oracle weak (same as jest path); vitest execution wired.",
    ),
    # ── missing ───────────────────────────────────────────────────────────
    CoverageEntry(
        language="C/C++",
        build_system_id="cmake",
        test_framework_id="ctest",
        oracle_path=(
            "No CMake adapter in registry; scripts/validators/cpp_validator.py "
            "exists but is DATA ENGINE ONLY; NATIVE_C_CPP_REPAIR_LOCK_001 "
            "covers corpus pipeline, not inference"
        ),
        status=CoverageStatus.MISSING,
        notes="Falls through to UnknownAdapter today.",
    ),
    CoverageEntry(
        language="C/C++",
        build_system_id="make",
        test_framework_id="make test",
        oracle_path=(
            "No Make adapter in registry; ShadowCompiler.run_tests has 'make test' "
            "entry but no adapter is migrated"
        ),
        status=CoverageStatus.MISSING,
        notes="Adapter not migrated from legacy if-ladder; falls through to UnknownAdapter.",
    ),
    CoverageEntry(
        language="Elixir",
        build_system_id="mix",
        test_framework_id="exunit",
        oracle_path=(
            "No Mix adapter in registry; ShadowCompiler.run_tests has 'mix test' "
            "entry but no adapter is migrated"
        ),
        status=CoverageStatus.MISSING,
        notes="Adapter not migrated from legacy if-ladder.",
    ),
    CoverageEntry(
        language=".NET",
        build_system_id="dotnet",
        test_framework_id="xunit",
        oracle_path="No .NET adapter; no oracle path wired",
        status=CoverageStatus.MISSING,
        notes="No detection, no oracle wiring, no repair pipeline.",
    ),
    CoverageEntry(
        language="PHP",
        build_system_id="composer",
        test_framework_id="phpunit",
        oracle_path="No PHP adapter; ShadowCompiler.run_tests has no 'phpunit' entry",
        status=CoverageStatus.MISSING,
        notes="No detection, no oracle wiring.",
    ),
    CoverageEntry(
        language="Ruby",
        build_system_id="bundler",
        test_framework_id="rspec",
        oracle_path=(
            "No Ruby adapter; ShadowCompiler.run_tests has 'rspec' entry but no adapter is migrated"
        ),
        status=CoverageStatus.MISSING,
        notes="Falls through to UnknownAdapter today.",
    ),
    CoverageEntry(
        language="Scala",
        build_system_id="sbt",
        test_framework_id="scalatest",
        oracle_path="No Scala adapter; no oracle path wired",
        status=CoverageStatus.MISSING,
        notes="No detection, no oracle wiring, no repair pipeline.",
    ),
    CoverageEntry(
        language="Swift",
        build_system_id="swiftpm",
        test_framework_id="XCTest",
        oracle_path="No Swift adapter; no oracle path wired",
        status=CoverageStatus.MISSING,
        notes="No detection, no oracle wiring, no repair pipeline.",
    ),
    CoverageEntry(
        language="TypeScript",
        build_system_id="npm",
        test_framework_id="mocha",
        oracle_path=(
            "NodeAdapter.discover_tests returns 'mocha --bail' when "
            "package.json devDeps has mocha, but ShadowCompiler.run_tests "
            "has no 'mocha' entry — execution path not wired"
        ),
        status=CoverageStatus.MISSING,
        notes="Adapter recognizes mocha; oracle/test-runner wiring is absent.",
    ),
    # ── unknown ───────────────────────────────────────────────────────────
    CoverageEntry(
        language="(any)",
        build_system_id="unknown",
        test_framework_id="unknown",
        oracle_path="UnknownAdapter — explicit registry fallback when no manifest detected",
        status=CoverageStatus.UNKNOWN,
        notes="Registry assigns UnknownAdapter when no manifest detected; no verifier path applies.",
    ),
)


# ---------------------------------------------------------------------------
# Lookup / classification helpers
# ---------------------------------------------------------------------------


def lookup(language: str, build_system_id: str, test_framework_id: str) -> CoverageEntry:
    """Return the coverage entry for ``(build_system_id, test_framework_id)``.

    Matching is on (build_system_id, test_framework_id) because those are the
    canonical strings the adapter contract exposes. ``language`` is
    informational. Unsupported combinations return a synthetic UNKNOWN entry
    — never **backed** or **partial**.
    """
    for e in COVERAGE_MATRIX:
        if e.build_system_id == build_system_id and e.test_framework_id == test_framework_id:
            return e
    return CoverageEntry(
        language=language or "(unknown)",
        build_system_id=build_system_id,
        test_framework_id=test_framework_id,
        oracle_path="no entry in coverage matrix",
        status=CoverageStatus.UNKNOWN,
        notes="Unsupported combination; fails closed (no implicit fallback).",
    )


def classify_for_build_test(build_system_id: str, test_framework_id: str) -> CoverageStatus:
    """Shortcut: return only the coverage status for the (build, test) pair
    an adapter exposes."""
    return lookup("", build_system_id, test_framework_id).status


def summary() -> dict[str, int]:
    """Count entries by status. Stable for the lock manifest + evidence."""
    out: dict[str, int] = {s.value: 0 for s in CoverageStatus}
    for e in COVERAGE_MATRIX:
        out[e.status.value] += 1
    return out


def entries_by_status(status: CoverageStatus) -> list[CoverageEntry]:
    return [e for e in COVERAGE_MATRIX if e.status == status]


# ---------------------------------------------------------------------------
# Markdown emission (docs/VERIFIER_COVERAGE_MATRIX.md is regenerated from
# this function — the test suite asserts docs and matrix agree byte-for-byte)
# ---------------------------------------------------------------------------

_MARKDOWN_PREAMBLE = """# Verifier Coverage Matrix

> Generated from `scripts/intake/verifier_coverage_matrix.COVERAGE_MATRIX`.
> Locked under `locks/sentinel/VERIFIER_COVERAGE_MATRIX_LOCK_001.json`.
> Do not edit this file by hand. Regenerate via:
>
> ```
> python -m scripts.intake.verifier_coverage_matrix --emit-md docs/VERIFIER_COVERAGE_MATRIX.md
> ```

Coverage classification:

- **backed** — deterministic verifier/oracle exists AND is wired end-to-end (detection + shadow build + test execution + repair-corpus path).
- **partial** — detection works but the verifier path is incomplete (weak build oracle, missing repair path, partial language support inside a generic adapter, etc.).
- **missing** — the language/build/test combination is a known target but no deterministic verifier path exists in this repo today.
- **unknown** — no adapter detected the workspace; UnknownAdapter fallback.

Honesty rules:

- A row is **backed** ONLY if there is a deterministic verifier/oracle wired end-to-end. Existence of a validator under `scripts/validators/` is NOT sufficient — those modules are DATA ENGINE ONLY (`scripts/validators/__init__.py` lines 1-9).
- Detection alone (a BuildAdapter that recognizes the manifest) does NOT make a row **backed**; the oracle path must also exist.
- Unsupported (language, build, test) tuples return `UNKNOWN` via `verifier_coverage_matrix.lookup()`. There is no implicit fallback to **partial** or **backed**.
"""


def to_markdown() -> str:
    counts = summary()
    lines: list[str] = [_MARKDOWN_PREAMBLE.rstrip(), ""]
    lines.append(
        f"**Counts as of lock issue date:** "
        f"backed={counts['backed']} · partial={counts['partial']} "
        f"· missing={counts['missing']} · unknown={counts['unknown']}"
    )
    lines.append("")
    lines.append(
        "| Language | build_system_id | test_framework_id | Status | Oracle path | Notes |"
    )
    lines.append("|---|---|---|---|---|---|")
    for e in COVERAGE_MATRIX:
        lines.append(
            f"| {e.language} | `{e.build_system_id}` | `{e.test_framework_id}` "
            f"| **{e.status.value}** | {e.oracle_path} | {e.notes} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Related: `locks/sentinel/BUILD_ADAPTER_REGISTRY_LOCK_001.json`, "
        "`locks/sentinel/CODEBASE_EXPLORER_SMOKE_LOCK_001.json`, "
        "`docs/CLOAK_THREAT_MODEL.md`.*"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--emit-md",
        type=str,
        default=None,
        help="Write the human-readable matrix to this Markdown file",
    )
    ap.add_argument(
        "--summary",
        action="store_true",
        help="Print status counts as JSON to stdout",
    )
    ap.add_argument(
        "--lookup",
        nargs=3,
        metavar=("LANG", "BUILD", "TEST"),
        help="Print the coverage entry for (lang, build, test) as JSON",
    )
    args = ap.parse_args(argv)

    if args.emit_md:
        out = Path(args.emit_md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_markdown(), encoding="utf-8")
        print(f"wrote {out}")

    if args.summary:
        print(json.dumps(summary(), indent=2))

    if args.lookup:
        lang, build, test = args.lookup
        e = lookup(lang, build, test)
        print(
            json.dumps(
                {
                    "language": e.language,
                    "build_system_id": e.build_system_id,
                    "test_framework_id": e.test_framework_id,
                    "status": e.status.value,
                    "oracle_path": e.oracle_path,
                    "notes": e.notes,
                },
                indent=2,
            )
        )

    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
