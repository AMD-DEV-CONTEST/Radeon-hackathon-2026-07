"""Parallel Execution Layer Audit — PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001.

Static, read-only inventory of every subprocess / shell-out / direct-process
call site under ``scripts/``. Classifies each site into a closed set:

    HARDENED_COMPILER_PATH         hive/compiler.py — sandbox + Job Object + docker backend
    HIVE_SANDBOXED_PATH            other hive/* and browser/desktop subsystems
                                   that compose with hardened isolation
    LEGACY_EXEMPT_READ_ONLY        validators, dev tools, agent helpers — do
                                   not execute user payload
    LEGACY_EXEMPT_TEST_FIXTURE     tests/* — fixture-local shell-out
    MUST_MIGRATE_TO_HARDENED_RUNNER
                                   intake/repair sites that should route
                                   through hive/compiler.py's hardened runner
    BLOCKED_UNSAFE                 raw shell=True + user-controlled string,
                                   os.system, etc.
    PROGRAMBENCH_OUT_OF_SCOPE      Codex/ProgramBench artifact-trail files;
                                   not in Claude lane
    UNKNOWN_REQUIRES_REVIEW        site matched a known kind but no rule
                                   in CLASSIFICATION_RULES applied

The audit is **read-only**: it parses Python with ``ast`` and matches paths
against regexes. It never executes a discovered command, never imports the
audited module, and never mutates any file outside the explicit lock
evidence destination.

Usage::

    python scripts/dev/parallel_execution_layer_audit.py
    python scripts/dev/parallel_execution_layer_audit.py --json out.json
    python scripts/dev/parallel_execution_layer_audit.py --md out.md
    python scripts/dev/parallel_execution_layer_audit.py --strict
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


# ---------------------------------------------------------------------------
# Classification tokens — closed set
# ---------------------------------------------------------------------------

STATUS_TOKENS: frozenset[str] = frozenset(
    {
        "PARALLEL_EXECUTION_AUDIT_READY",
        "EXECUTION_SITE_FOUND",
        "HARDENED_COMPILER_PATH",
        "HIVE_SANDBOXED_PATH",
        "LEGACY_EXEMPT_READ_ONLY",
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BLOCKED_UNSAFE",
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "UNKNOWN_REQUIRES_REVIEW",
        "NEEDS_OWNER_DECISION",
        "AUDIT_READ_ONLY",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)

CLASSIFICATIONS = frozenset(
    {
        "HARDENED_COMPILER_PATH",
        "HIVE_SANDBOXED_PATH",
        "LEGACY_EXEMPT_READ_ONLY",
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BLOCKED_UNSAFE",
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "UNKNOWN_REQUIRES_REVIEW",
        "NEEDS_OWNER_DECISION",
    }
)

# Execution kinds that are unconditionally BLOCKED_UNSAFE regardless of
# the file's path-rule classification (added in
# SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001). Safety-by-default:
# shell=True and os.system / os.popen can be used to invoke arbitrary
# command lines and have no documented exemption in the Claude lane.
_ALWAYS_BLOCKED_KINDS = frozenset(
    {
        "shell=True",
        "os.system",
        "os.popen",
    }
)

# Path-rule classifications that exempt a file from the kind-aware
# BLOCKED_UNSAFE override. PROGRAMBENCH_OUT_OF_SCOPE is Codex's lane;
# Claude does not seal its shell=True sites. LEGACY_EXEMPT_TEST_FIXTURE
# preserves test scaffolding that may legitimately use shell semantics.
_KIND_OVERRIDE_EXEMPT = frozenset(
    {
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "LEGACY_EXEMPT_TEST_FIXTURE",
    }
)


# ---------------------------------------------------------------------------
# Classification rules — first match wins, priority by order
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    classification: str
    rationale: str


# Path regexes are matched against the file's path RELATIVE to repo root,
# normalised to forward slashes.
CLASSIFICATION_RULES: tuple[_Rule, ...] = (
    # ── Test fixtures ──────────────────────────────────────────────────────
    _Rule(
        re.compile(r"^tests/"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Test code; runs against fixture data only, never user payload.",
    ),
    # ── ProgramBench / Codex trail (out of Claude lane) ───────────────────
    _Rule(
        re.compile(r"^scripts/corpus/programbench/"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "ProgramBench/Codex trail — not in Claude's audit scope.",
    ),
    _Rule(
        re.compile(r"^scripts/corpus/legacy_recovery/"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "Legacy recovery is part of the ProgramBench/Codex artifact-provenance trail.",
    ),
    _Rule(
        re.compile(r"^scripts/pb_"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "pb_*-prefixed scripts belong to the Codex/ProgramBench trail.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_programbench"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "ProgramBench agent code; not in Claude lane.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_pb_taxonomy"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "ProgramBench taxonomy classifier.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_pb_"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "determinex_pb_*-prefixed scripts are the same Codex/ProgramBench trail as "
        "pb_*; naming drifted to the determinex_ prefix (2026-06) without a matching "
        "rule update. covers autodrive/churn/drive/eval/memory_conveyor/mojibake_guard/"
        "official_eval/overnight/reeval_campaign/reimpl/self_scan and future siblings.",
    ),
    _Rule(
        re.compile(r"^scripts/programbench_"),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "programbench_*-prefixed scripts belong to the Codex/ProgramBench trail.",
    ),
    _Rule(
        re.compile(
            r"^scripts/(csview_iterate|determinex_reimpl_drive|determinex_test_oracle|"
            r"determinex_test_validator|_audit_build_output|prefetch_task_images_hetzner|"
            r"push_images_to_hetzner|sync_task_images_to_hetzner)\.py$"
        ),
        "PROGRAMBENCH_OUT_OF_SCOPE",
        "ProgramBench reimpl/build/oracle/image-sync tooling — same Codex/PB trail as "
        "determinex_pb_*, just not prefixed that way. Builds and runs *candidate* code "
        "(cargo/go/gcc/docker) as part of the PB compile-oracle loop, not user payload "
        "in the Claude lane.",
    ),
    # ── Test runners / smoke harnesses ────────────────────────────────────
    _Rule(
        re.compile(r"^scripts/testing/"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Test driver / sprint smoke harness; runs against fixtures.",
    ),
    # ── Hardened compiler / intake-runner paths ───────────────────────────
    _Rule(
        re.compile(r"^scripts/hive/compiler\.py$"),
        "HARDENED_COMPILER_PATH",
        "hive/compiler.py is the documented hardened oracle "
        "(Job Object + Docker backend + WSL2 backend + sanitization).",
    ),
    _Rule(
        re.compile(r"^scripts/intake/hardened_runner\.py$"),
        "HARDENED_COMPILER_PATH",
        "intake/hardened_runner.py is the hardened intake runner "
        "(HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001): workspace-scoped cwd, "
        "scrubbed env, no Docker/network by default, structured failure).",
    ),
    # ── Hive subsystem ────────────────────────────────────────────────────
    _Rule(
        re.compile(r"^scripts/hive/"),
        "HIVE_SANDBOXED_PATH",
        "Hive subsystem module; composes with hive/compiler.py's sandboxed runner.",
    ),
    # ── Crucible (proper-method compile-oracle enforcement) ────────────────
    _Rule(
        re.compile(r"^scripts/determinex_crucible\.py$"),
        "HIVE_SANDBOXED_PATH",
        "Crucible builds/tests *candidate* code inside `docker run --rm "
        "--network none -v <workdir>:/workspace ...` — network-isolated, throwaway "
        "container, same sandboxing shape as the Hive Docker backend.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_oracle\.py$"),
        "HIVE_SANDBOXED_PATH",
        "Universal ground-truth oracle: driving docker inspect/run/exec/rm for "
        "isolated silicon kernel testing, and delegates all other verify calls "
        "to the sandboxed intake.hardened_runner.",
    ),
    # ── Agent registry (external coding-agent CLI runner) ───────────────────
    _Rule(
        re.compile(r"^scripts/determinex_agents\.py$"),
        "NEEDS_OWNER_DECISION",
        "Hosts registered coding-agent CLIs and runs them non-interactively "
        "against a workspace with an interpolated task string (subprocess.run, "
        "argv_template, no shell=True). Per CLAUDE.md: 'Real live runs mutate "
        "source + spend credits — opt-in.' This is a legitimate opt-in surface, "
        "not unreviewed — but whether the argv_template contract is tight enough "
        "to skip hardened_runner is a security-governance call, not an audit-script "
        "inference. Left flagged for that owner decision rather than silently "
        "exempted.",
    ),
    _Rule(
        re.compile(r"^scripts/dev/record_terminal_segment\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Operator-invoked screen recorder: it runs the command given on ITS OWN command line "
        "and renders that command's output to frames. Exempt because the argv comes from the "
        "operator's shell and no model- or user-supplied string reaches it -- NOT because it "
        "is read-only, which it plainly is not. Given its own rule rather than inheriting the "
        "blanket `^scripts/dev/` rationale ('read-only audit/dev tooling - no payload "
        "execution'), which is false for a file whose entire purpose is executing whatever it "
        "is handed. A bucket that says the wrong reason is how the next reader mis-files "
        "something that genuinely is dangerous.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_provider_setup\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "First-run setup helper. Its one execution site is `subprocess.run([exe, 'login'])` "
        "where `exe` is `shutil.which(option_id)` for an option_id drawn from this module's "
        "own hard-coded tuple of CLI names -- fixed argv, no shell, and no user- or "
        "model-supplied string reaches it. The spawned CLI owns its own OAuth and opens a "
        "browser; Determinex never handles the credential. Distinct from "
        "`determinex_agents.py` next door, which is NEEDS_OWNER_DECISION because it "
        "interpolates a TASK STRING into the argv -- there is no task here, only the literal "
        "subcommand `login`.",
    ),
    # ── Ops / infra utilities (fixed-argv, no user payload) ─────────────────
    _Rule(
        re.compile(r"^scripts/release/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Release packaging scripts; read-only w.r.t user payload, fixed command lines.",
    ),
    _Rule(
        re.compile(r"^scripts/publish_mirror\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Release tooling that happens to live at scripts/ root rather than under "
        "scripts/release/, so it fell through to the UNKNOWN catch-all. Both of its "
        "execution sites were read before classifying: a `run(args: list[str])` git "
        "helper and `[sys.executable, scripts/security/secret_scan.py]`. Fixed argv, "
        "no shell=True, and it never executes model-generated or user-supplied "
        "payload -- it publishes the mirror and gates on the repo's own scanner.",
    ),
    _Rule(
        re.compile(r"^scripts/claim_scanner/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Claim scanner checks compliance; no user payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_corpus_fetch\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Reconstructs a vendored corpus tool from upstream: fixed `git init` / `remote add` / "
        "`fetch --depth 1 <sha>` / `checkout <sha>` argv, no shell=True. The remote URL and the "
        "commit are read from corpus/programbench/canonical_tasks.json -- repo-controlled data "
        "committed by a human, not model output and not user input -- and the fetched tree is "
        "only ever written to disk, never executed. Reviewed 2026-07-31: the audit surfaced this "
        "as UNKNOWN_REQUIRES_REVIEW because scripts/ root has no blanket rule, which is the "
        "catch-all behaving correctly for a newly added execution site.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_orphan_reaper\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Box-hygiene utility: fixed `ps -eo ...` inventory + `kill -9 <pid>` on "
        "orphaned processes it discovers itself. No shell=True, no user-controlled "
        "command string, no payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_metrics\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Metrics/status gathering; fixed argv, no payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_notify\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Native desktop notification: powershell NotifyIcon / osascript / notify-send "
        "with FIXED argv and no shell=True. The only variable parts are the title and "
        "body TEXT, which are displayed, never executed. Both are stripped of the quote "
        "characters that could terminate the enclosing PowerShell or AppleScript string "
        "literal -- the macOS branch interpolated `title` raw until 2026-08-03, which is "
        "why this rule names the sanitization rather than asserting the argv is constant.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_code_rag\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "RAG corpus ingestion: `git clone` of a source URL for indexing. Clones "
        "text/source for embedding, never executes the cloned repository's code.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_observe\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Observation/build-probe tooling: docker run/exec/cp with fixed argv "
        "(no shell=True) to inspect candidate build artifacts; read-only w.r.t. "
        "the Claude lane, does not execute unreviewed payload outside its own "
        "throwaway containers.",
    ),
    _Rule(
        re.compile(r"^scripts/governance/overclaim_guard\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "The current canonical no-overclaim scanner (replaces the superseded "
        "day_one_public_claim_scanner.py): `git ls-files` inventory only, "
        "read-only, no payload execution. See RELEASE_AUDIT_HANDOFF_2026_06_29.md "
        "item #10 — that item is now stale, this file is the live scanner.",
    ),
    _Rule(
        re.compile(r"^scripts/spec_generator\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "IDE spec-generation bridge: the only subprocess site is fixed-argv "
        "`ollama list` model readiness discovery; it does not execute generated "
        "code, shell strings, Docker, ProgramBench, or user repositories.",
    ),
    # ── Audit / dev tools (this script, gauntlet) ─────────────────────────
    _Rule(
        re.compile(r"^scripts/dev/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only audit/dev tooling — no payload execution.",
    ),
    # ── Model router (MODEL_ROUTER_LOCK_001) ──────────────────────────────
    _Rule(
        re.compile(r"^scripts/models/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Model routing decision surface (MODEL_ROUTER_LOCK_001): produces "
        "RouteRecord only; never invokes a model, subprocess, or network.",
    ),
    # Proof-control readiness audit (DETERMINEX_PROOF_EXECUTION_AUDIT_REPAIR_LOCK_001)
    # contains one narrow subprocess site: `git status --short
    # --untracked-files=all`. It is a read-only workspace state probe used
    # only to detect whether Claude/Tauri final-state files are dirty before
    # unified status consumes them. It does not execute user payload, does not
    # use shell=True, does not invoke Docker/ProgramBench/scanners/models, and
    # grants no authority by itself.
    _Rule(
        re.compile(r"^scripts/proof/proof_control_readiness_audit\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Proof-control readiness audit read-only git status probe "
        "(DETERMINEX_PROOF_EXECUTION_AUDIT_REPAIR_LOCK_001): fixed argv "
        "`git status --short --untracked-files=all`, no shell, no payload "
        "execution, authority flags remain closed.",
    ),
    _Rule(
        re.compile(r"^scripts/proof/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Proof-control modules are evidence/authority decision surfaces; "
        "no payload execution or authority grant. Any future execution "
        "site must be separately classified or migrated.",
    ),
    _Rule(
        re.compile(r"^scripts/status/git_dirty_state\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Shared status dirty-tree probe: fixed argv `git status --short "
        "--branch --untracked-files=all`, no shell, no payload execution, "
        "no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/windows_first_local_dependency_check_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Packaging dependency status probe: bounded local `--version` checks "
        "only, shell=False, no install, no network fetch, no build, no "
        "payload execution, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/dependency_blocker_reconciliation_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Dependency blocker reconciliation probe: bounded local version, "
        "registry, and git path-risk checks only, shell=False, no install, "
        "no network fetch, no build, no payload execution, and no "
        "authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/onnxruntime_local_import_lib_generation_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "ONNX Runtime local import-library generator: bounded local dumpbin/lib "
        "argv only against the existing local wheel DLL, shell=False, no "
        "install, no network fetch, no Tauri build, no payload execution, "
        "no product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tauri_desktop_build_retry_with_local_ort_link_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Tauri no-bundle release-build proof harness: one bounded repo-internal "
        "offline build with ORT_LIB_LOCATION pointed at committed evidence, "
        "shell=False, no install, no network fetch, no untrusted payload "
        "execution, no product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/local_smoke_after_build_artifact_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local smoke probe: launches the committed Tauri build artifact "
        "with sandboxed app profile and ONNX Runtime on PATH, shell=False, "
        "no install, no network fetch, no untrusted payload execution, no "
        "product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/local_smoke_after_fastembed_binding_retry_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local rebuild and smoke retry: runs one offline no-bundle "
        "Tauri release build plus one bounded launch probe against the "
        "committed artifact with local fastembed model and ONNX Runtime on "
        "PATH, shell=False, no install, no network fetch, no untrusted "
        "payload execution, no product source mutation, and no authority "
        "grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/optional_vector_engine_startup_guard_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local rebuild and startup smoke: runs one offline no-bundle "
        "Tauri release build plus one bounded launch probe against the "
        "committed artifact with vector initialization disabled by default, "
        "shell=False, no install, no network fetch, no untrusted payload "
        "execution, no product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/onnxruntime_runtime_api_alignment_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local runtime alignment and vector smoke: runs one offline "
        "no-bundle Tauri release build plus one bounded vector-enabled "
        "launch probe against the committed artifact with an existing local "
        "ONNX Runtime DLL co-located beside the app, shell=False, no install, "
        "no network fetch, no untrusted payload execution, no product source "
        "mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/companion_seeder_resource_path_alignment_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local companion seed smoke: runs one offline no-bundle "
        "Tauri release build plus one bounded vector-enabled companion "
        "seeding probe against the committed artifact with existing local "
        "ONNX Runtime DLLs and repo companion docs, shell=False, no install, "
        "no network fetch, no untrusted payload execution, no product source "
        "mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/local_rag_query_smoke_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local RAG query smoke: runs one offline Rust integration "
        "test against a copied seeded companion database to prove local "
        "sqlite-vec query shape, shell=False, no install, no network fetch, "
        "no untrusted payload execution, no product source mutation, and no "
        "authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/rag_natural_language_query_eval_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local natural-language RAG retrieval eval: runs one offline "
        "Rust integration test against a copied seeded companion database "
        "and local FastEmbed assets to prove top-k retrieval shape, "
        "shell=False, no install, no network fetch, no untrusted payload "
        "execution, no product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/companion_rag_product_smoke_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded frontend Companion RAG product-surface smoke: runs one "
        "repo-internal Vitest component test to prove query/render wiring, "
        "shell=False, no install, no network fetch, no untrusted payload "
        "execution, no product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/ide_release_ascent_reconciliation_next_proof_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded IDE release-ascent reconciliation: runs local Tauri CLI "
        "version checks only to distinguish project-local, global, and cargo "
        "Tauri routes, shell=False, no install, no network fetch, no "
        "untrusted payload execution, no product source mutation, and no "
        "authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/companion_rag_desktop_e2e_smoke_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded Companion RAG desktop command-boundary smoke: runs one "
        "offline repo-internal Rust/Tauri test with shell=False and timeout, "
        "no install, no network fetch, no untrusted payload execution, no "
        "product source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tauri_driver_gui_harness_install_admission_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded GUI harness dependency admission: runs only the explicitly "
        "authorized `cargo install tauri-driver --locked` command plus "
        "bounded tauri-driver presence probes, shell=False, no unrelated "
        "dependency install, no uncontrolled GUI launch, no untrusted "
        "payload execution, no product source mutation, and no authority "
        "grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tauri_driver_gui_e2e_harness_implementation_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded GUI harness implementation probe: runs local tauri-driver "
        "help/version and short-lived driver server probes with shell=False, "
        "explicit timeouts, no dependency install, no network fetch, no "
        "uncontrolled GUI launch, no untrusted payload execution, no product "
        "source mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tauri_release_build_proof_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded project-local Tauri release-build proof: runs the local "
        "Tauri CLI with shell=False, explicit timeout, offline npm/cargo "
        "guards, no dependency install, no network fetch, no untrusted "
        "payload execution, no real-user repo mutation, no GUI launch, and "
        "no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tauri_nsis_fallback_packaging_proof_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded project-local Tauri NSIS packaging proof: runs the local "
        "Tauri CLI with shell=False, explicit timeout, offline npm/cargo "
        "guards, no dependency install, no network fetch, no untrusted "
        "payload execution, no real-user repo mutation, no GUI launch, and "
        "no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/local_smoke_after_nsis_artifact_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded NSIS artifact metadata smoke: may run fixed local metadata "
        "inspection probes with shell=False, explicit timeout, no install, "
        "no network fetch, no GUI launch, no untrusted payload execution, "
        "no real-user repo mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/nsis_bounded_extract_or_operator_install_uninstall_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded NSIS extraction capability probe: may run fixed local "
        "artifact hash and extractor-listing probes with shell=False, "
        "explicit timeout, no install execution, no network fetch, no GUI "
        "launch, no untrusted payload execution, no real-user repo mutation, "
        "and no authority grant.",
    ),
    _Rule(
        re.compile(
            r"^scripts/status/nsis_single_event_approval_and_install_launch_uninstall_execution_001\.py$"
        ),
        "LEGACY_EXEMPT_READ_ONLY",
        "Single-event NSIS install/launch/uninstall harness: defaults to "
        "approval-packet emission and executes only with exact signed local "
        "HMAC approval, fixed argv, shell=False, explicit C:/tmp install "
        "scope, timeouts, rollback/cleanup, no dependency install, no "
        "network fetch, no real-user repo mutation, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/fresh_clone_bootstrap_proof_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local fresh-clone bootstrap probe: runs local git clone "
        "into C:/tmp plus evidence validation inside the clone with "
        "shell=False, explicit timeouts, no dependency install, no network "
        "fetch, no untrusted payload execution, no real-user repo mutation, "
        "and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/fresh_clone_bootstrap_proof_retry_001\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Bounded local fresh-clone retry probe: runs local git clone with "
        "command-scoped core.longpaths and safe.directory settings plus "
        "evidence validation inside the clone with shell=False, explicit "
        "timeouts, no dependency install, no network fetch, no untrusted "
        "payload execution, no real-user repo mutation, and no authority "
        "grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/splash_path_reconciliation_and_prep\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Codex splash-prep reconciliation probe: fixed argv `git status "
        "--porcelain=v1`, no shell, no payload execution, no authority grant.",
    ),
    _Rule(
        re.compile(
            r"^scripts/status/batch_004_sync_first_promotion_programbench_release_family\.py$"
        ),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only status probe: runs fixed git/python argv to inspect release "
        "promotion state; capture_output=True, no authority grant, no payload "
        "execution.",
    ),
    _Rule(
        re.compile(r"^scripts/status/status_runtime_closure_batch_003\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only status runtime closure probe: runs fixed argv to collect "
        "test suite runtime evidence; capture_output=True, no authority grant, "
        "no payload execution.",
    ),
    _Rule(
        re.compile(
            r"^scripts/status/status_suite_runtime_segmentation_and_monolithic_closure_001\.py$"
        ),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only status suite runtime segmentation probe: fixed argv to "
        "measure segmented vs monolithic test runtime; capture_output=True, "
        "no authority grant, no payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/status/idea_lab_python_cli_verified_splash_demo\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex fixture/demo verifier: fixed Python argv for local demo "
        "acceptance and smoke checks inside the allowed demo workspace, no "
        "shell, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/idea_lab_end_to_end_artifact_proof_001\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Idea Lab fixture verifier: fixed Python argv for py_compile, "
        "unittest, smoke, and failure-injection capture inside the committed "
        ".determinex_tmp fixture workspace only; no shell, no dependency "
        "install, no network fetch, no real user repo mutation, no authority "
        "grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/react_vite_scaffold_build_test_smoke_release_cell_001\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex React/Vite scaffold fixture verifier: fixed Vite, Node, and "
        "Python argv execute only inside the lane-owned evidence fixture, "
        "using existing frontend/node_modules, shell=False, no dependency "
        "install, no network fetch, no real user repo mutation, no GUI "
        "launch, and no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/repo_clinic_fixture_repair_splash_demo\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Repo Clinic fixture verifier: fixed Python argv for local "
        "baseline and repair pytest checks inside the allowed demo workspace, "
        "no shell, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/maintenance_bay_dry_run_update_splash_demo\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Maintenance Bay fixture verifier: fixed Python argv for local "
        "baseline and compatibility pytest checks inside the allowed demo "
        "workspace, no shell, no real user repo mutation, no authority grant.",
    ),
    # ── IDE state model (IDE_REPAIR_STATE_MODEL_LOCK_001) ─────────────────
    _Rule(
        re.compile(r"^scripts/status/universal_100_matrix_probe_execution_batch\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 fixture probe runner: fixed argv build/test/smoke "
        "commands execute only inside assurance/demo_workspaces fixture roots, "
        "shell=False, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_matrix_probe_execution_batch_003\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 Batch 003 fixture probe runner: fixed argv "
        "build/test/smoke commands execute only inside the Batch 003 "
        "assurance/demo_workspaces fixture root, shell=False, no real user "
        "repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/typescript_node_cli_adapter_probe\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex TypeScript Node CLI adapter probe: fixed argv tsc/node "
        "commands execute only inside the fixture-local TypeScript adapter "
        "workspace, shell=False, no network install, no real user repo "
        "mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_matrix_probe_execution_batch_004\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 Batch 004 fixture probe runner: fixed argv "
        "build/test/smoke commands execute only inside the Batch 004 "
        "assurance/demo_workspaces fixture root, shell=False, no network "
        "install, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_sector_gulp_batch_005\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 Sector Gulp Batch 005 fixture probe runner: "
        "fixed argv build/test/smoke commands execute only inside the Batch "
        "005 assurance/demo_workspaces fixture root, shell=False, no network "
        "install, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_sector_gulp_batch_006\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 Sector Gulp Batch 006 fixture probe runner: "
        "fixed argv build/test/smoke commands execute only inside the Batch "
        "006 assurance/demo_workspaces fixture root, shell=False, no network "
        "install, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_sector_gulp_batch_007\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 Sector Gulp Batch 007 fixture probe runner: "
        "fixed argv build/test/smoke, repair, and dry-run maintenance "
        "commands execute only inside the Batch 007 assurance/demo_workspaces "
        "fixture root, shell=False, no network install, no real user repo "
        "mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/universal_100_tandem_climb\.py$"),
        "LEGACY_EXEMPT_TEST_FIXTURE",
        "Codex Universal 100 tandem fixture runner: bounded fixture-local "
        "build/test/smoke probes plus fixed git rev-parse status read, "
        "shell=False, no real user repo mutation, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/status/tandem_post_claude_binding_reconciliation\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Codex tandem reconciliation status writer: fixed argv `git rev-parse "
        "--short=9 HEAD` only, no shell, no payload execution, no authority grant.",
    ),
    _Rule(
        re.compile(r"^scripts/ide/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "IDE repair state model (IDE_REPAIR_STATE_MODEL_LOCK_001): pure "
        "state assembly from VerifiedRepairTrace + ApprovalGateDecision; "
        "no I/O, no model invocation.",
    ),
    # ── Safe patch workspace (SAFE_PATCH_DIFF_ROLLBACK_LOCK_001) ──────────
    # Earlier than the generic scripts/repair/ rule so this file is exempt
    # from the MUST_MIGRATE_TO_HARDENED_RUNNER classification that applies
    # to the language-specific repair pipelines.
    _Rule(
        re.compile(r"^scripts/repair/safe_patch_"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Safe-patch temp-workspace applier (SAFE_PATCH_DIFF_ROLLBACK_LOCK_001): "
        "writes only to caller-supplied temp root; original source is "
        "treated as immutable. No subprocess; verifier is an injected callable.",
    ),
    # ── Validators (DATA ENGINE ONLY per scripts/validators/__init__.py) ──
    _Rule(
        re.compile(r"^scripts/validators/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "DATA ENGINE ONLY: filters training samples; not invoked on user payload.",
    ),
    # ── Browser / Desktop / Mobile agents — sandbox-enforced by Sentinel ──
    _Rule(
        re.compile(r"^scripts/browser/"),
        "HIVE_SANDBOXED_PATH",
        "Browser controller — SENTINEL_LOCK_001 mandates sandbox/VM.",
    ),
    _Rule(
        re.compile(r"^scripts/desktop/"),
        "HIVE_SANDBOXED_PATH",
        "Desktop controller — SENTINEL_LOCK_001 requires VM (DETERMINEX_REQUIRE_VM=1 default).",
    ),
    _Rule(
        re.compile(r"^scripts/mobile/"),
        "HIVE_SANDBOXED_PATH",
        "Mobile controller — SENTINEL_LOCK_001 requires emulator.",
    ),
    # ── Agents (policy/safety helpers, not payload execution) ─────────────
    _Rule(
        re.compile(r"^scripts/agents/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Agent policy / safety helpers; do not execute user payload.",
    ),
    # ── Intake adapters (new BuildAdapter._run) ───────────────────────────
    _Rule(
        re.compile(r"^scripts/intake/build_adapters\.py$"),
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "BuildAdapter._run shells out via raw subprocess.run; should route "
        "through hive/compiler.py's hardened runner (rung 5 target).",
    ),
    # ── codebase_explorer ShadowCompiler ──────────────────────────────────
    _Rule(
        re.compile(r"^scripts/codebase_explorer\.py$"),
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "ShadowCompiler / inference-side subprocess; should route through "
        "hive/compiler.py's hardened runner.",
    ),
    # ── Repair pipelines ──────────────────────────────────────────────────
    _Rule(
        re.compile(r"^scripts/repair/"),
        "MUST_MIGRATE_TO_HARDENED_RUNNER",
        "Repair pipelines execute compilers via direct subprocess; should "
        "route through hive/compiler.py's hardened runner.",
    ),
    # ──────────────────────────────────────────────────────────────────────
    # Classification sweep — SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001
    # The following rules triage what was previously a 121-site
    # UNKNOWN_REQUIRES_REVIEW bucket of top-level scripts/ helpers. Rule
    # order matters: more specific rules MUST come before more general ones.
    # ──────────────────────────────────────────────────────────────────────
    # verified_task/command_runner.py — migrated to intake.hardened_runner
    # in HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001. Previously
    # BLOCKED_UNSAFE (shell=True with user-supplied strings); now composes
    # with the hardened runner via /bin/sh -c (POSIX) or cmd.exe /c
    # (Windows) argv-list invocation. Workspace bounding, env scrub, and
    # Docker/network blocking are inherited.
    _Rule(
        re.compile(r"^scripts/verified_task/command_runner\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "verified_task/command_runner.py routes through "
        "intake.hardened_runner (HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001); "
        "no longer uses shell=True or raw subprocess.",
    ),
    # determinex_codeclash_agent.py — migrated to intake.hardened_runner in
    # HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001. The arena agent's
    # py_compile call now routes through the hardened runner so the
    # user-controlled codebase path is workspace-bounded and env-scrubbed.
    _Rule(
        re.compile(r"^scripts/determinex_codeclash_agent\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "CodeClash arena agent routes py_compile through "
        "intake.hardened_runner (HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001).",
    ),
    # HIVE_SANDBOXED_PATH — Hetzner remote family-repair runner
    _Rule(
        re.compile(r"^scripts/hetzner_family_loop\.py$"),
        "HIVE_SANDBOXED_PATH",
        "Remote repair-loop runner that executes ON the Hetzner Linux box — not on the "
        "dev machine. Uses bash -c (not shell=True) to compose shell pipelines. All "
        "commands run against operator-controlled config JSON, not arbitrary user input.",
    ),
    # HIVE_SANDBOXED_PATH — SWE-bench integration (Docker-bound per harness)
    _Rule(
        re.compile(r"^scripts/swe_run/"),
        "HIVE_SANDBOXED_PATH",
        "SWE-bench repo helpers (clone + worktree); SWE-bench evaluation "
        "runs in Docker per harness contract.",
    ),
    _Rule(
        re.compile(r"^scripts/setup_swebench\.py$"),
        "HIVE_SANDBOXED_PATH",
        "SWE-bench environment setup (clones repos, installs deps for the "
        "SWE-bench sandboxed harness).",
    ),
    _Rule(
        re.compile(r"^scripts/smoke_test_swebench\.py$"),
        "HIVE_SANDBOXED_PATH",
        "SWE-bench smoke driver — composes with the Docker-bound harness.",
    ),
    _Rule(
        re.compile(r"^scripts/benchmarks/windows/swebench_live_windows\.py$"),
        "HIVE_SANDBOXED_PATH",
        "Windows SWE-bench live driver — same sandbox stance.",
    ),
    # HIVE_SANDBOXED_PATH — ProgramBench eval orchestrator (Docker-bound per harness)
    _Rule(
        re.compile(r"^scripts/run_pb_eval\.py$"),
        "HIVE_SANDBOXED_PATH",
        "ProgramBench eval orchestrator: provisions Docker sidecar containers per "
        "eval_requirements.json, then runs the official PB harness. All execution "
        "is bounded by the PB harness contract; no arbitrary user payload.",
    ),
    # LEGACY_EXEMPT_READ_ONLY — orchestrators, model utilities, health probes,
    # analysis, security scans. These drive documented vendor tools / local
    # determinex binaries; they do NOT execute arbitrary user payload.
    # Repo acquisition (git clones — no payload execution)
    _Rule(
        re.compile(r"^scripts/download_swebench_repos\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "git clone of SWE-bench repos — no user payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/download_multilang_repos\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "git clone of multilingual corpus repos — no user payload execution.",
    ),
    # Benchmark orchestrators
    _Rule(
        re.compile(r"^scripts/determinex_ask\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Local model query helper.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_benchmark"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Benchmark orchestrators (drive documented determinex/external benchmarks).",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_route_ab\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Model Router A/B orchestrator, same shape as the benchmark drivers above: it "
        "spawns determinex_hive.py with FIXED argv ([sys.executable, hive, subcommand, "
        "--session ...]), no shell=True and no interpolated payload. It does cause "
        "model-generated code to run, but only by invoking the hive, which is the "
        "component that sandboxes it (validate_project -> Docker); the harness itself "
        "executes nothing the model produced.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_bigcode_run\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "BigCodeBench runner — drives the BigCodeBench harness binary.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_fullbench\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Full benchmark suite orchestrator.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_livecode_run\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "LiveCodeBench runner — drives the LiveCodeBench harness.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_flywheel\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Model retraining trigger (orchestration, not payload execution).",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_limits_test\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Compiler Oracle limits test — internal hive limit smoke.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_projector\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Local model projector utility.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_commit_training_capture\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Commit-history training capture — read-only `git log`/`git show` "
        "against the local repo, no user payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_local_model_bench\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Local model benchmark harness — fixed-argument `nvidia-smi` "
        "hardware probe, no user payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_ingest\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "`_git_tracked_files` — read-only `git ls-files` against the "
        "local repo, no user payload execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_toolchain_installer\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Opt-in oracle-toolchain enablement (winget/choco install) — "
        "operator-initiated, fixed package-ID dict, never arbitrary/"
        "user-controlled command text; same posture as "
        "determinex_local_model_bench.py's fixed-argument hardware probe.",
    ),
    _Rule(
        re.compile(r"^scripts/setup/install_determinex_models\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Operator-initiated model provisioning, same posture as "
        "determinex_toolchain_installer.py. Two execution sites, both read before "
        "classifying: `ollama list` (read-only probe) and `ollama create <tag> -f "
        "<generated Modelfile>`. Argv is fixed; the only interpolated values come from "
        "the module-level MODELS tuple and a tempfile path this script writes itself. "
        "It downloads published GGUF weights over HTTPS and hands them to Ollama — it "
        "never executes model-generated code, so it does not need the hardened runner.",
    ),
    # Sprint orchestration drivers
    _Rule(
        re.compile(r"^scripts/sprint4_"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Sprint orchestration: preflight, smoke-pass, factory-validation, "
        "bulk-generate, subtype-smoke-pass.",
    ),
    # Model maintenance / GGUF
    _Rule(
        re.compile(r"^scripts/fix_retrain_"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Per-model retraining helper.",
    ),
    _Rule(
        re.compile(r"^scripts/fix_corpus\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Corpus maintenance helper.",
    ),
    _Rule(
        re.compile(r"^scripts/fix_sen_merge_gguf\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "GGUF merge helper for Sentinel models.",
    ),
    _Rule(
        re.compile(r"^scripts/sentinel_gguf_and_fetch\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Sentinel GGUF fetch + register.",
    ),
    _Rule(
        re.compile(r"^scripts/verify_gguf\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "GGUF file verification (read-only model artifact check).",
    ),
    _Rule(
        re.compile(r"^scripts/gguf_sentinel_only\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Sentinel-only GGUF helper.",
    ),
    # Analysis tools
    _Rule(
        re.compile(r"^scripts/analysis/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Analysis tools — read-only inspection of corpus / results.",
    ),
    # Security scans
    _Rule(
        re.compile(r"^scripts/security/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Security scanning helpers (SBOM, container/dep scans) — invoke "
        "documented vendor tools on local artifacts.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_safety\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Semgrep OSS static-analysis call (audit 2026-07-19): shells out to "
        "the documented `semgrep` binary via shutil.which guard, fail-open "
        "if absent — same pattern as scripts/security/, not payload execution.",
    ),
    # Modal burst-compute workers (audit 2026-07-19): PB eval / K-search
    # candidate execution is real, but it runs inside Modal's own isolated
    # remote cloud containers, not on this machine — same sandboxed-behind-
    # a-hardened-boundary stance as the SWE-bench Docker sandbox below.
    _Rule(
        re.compile(r"^scripts/modal_pb_worker\.py$"),
        "HIVE_SANDBOXED_PATH",
        "ProgramBench eval worker — runs in a Modal-provisioned, isolated "
        "Docker-compatible remote container per instance.",
    ),
    _Rule(
        re.compile(r"^scripts/modal_verified_search\.py$"),
        "HIVE_SANDBOXED_PATH",
        "VerifiedSearch K-search amplifier — runs in a Modal-provisioned "
        "remote GPU container, same sandboxing property as local Docker.",
    ),
    # Windows / other bench harnesses
    _Rule(
        re.compile(r"^scripts/benchmarks/windows/deepeval_humaneval\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "HumanEval portability driver.",
    ),
    _Rule(
        re.compile(r"^scripts/benchmark_runner\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Generic benchmark runner.",
    ),
    _Rule(
        re.compile(r"^scripts/quality_benchmark_agent\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Quality benchmark agent.",
    ),
    # Hardware / health probes (read-only)
    _Rule(
        re.compile(r"^scripts/hardware_profiler\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only hardware probe (nvidia-smi / cpu info).",
    ),
    _Rule(
        re.compile(r"^scripts/health_monitor\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only health probe.",
    ),
    _Rule(
        re.compile(r"^scripts/vram_monitor\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Read-only GPU memory probe.",
    ),
    # Eval / iteration drivers
    _Rule(
        re.compile(r"^scripts/micro_eval\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Fast model eval driver.",
    ),
    _Rule(
        re.compile(r"^scripts/patch_iterate\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Patch iteration driver.",
    ),
    _Rule(
        re.compile(r"^scripts/full_sweep_iterate\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Full corpus iteration driver.",
    ),
    _Rule(
        re.compile(r"^scripts/three_speed_gate\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Three-speed gate eval helper.",
    ),
    _Rule(
        re.compile(r"^scripts/rosetta_vs_text_eval\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Rosetta vs text eval comparison.",
    ),
    _Rule(
        re.compile(r"^scripts/tonight_launch\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Overnight benchmark launch orchestrator.",
    ),
    _Rule(
        re.compile(r"^scripts/preflight_mass_run\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Mass-run preflight check.",
    ),
    # Data engine + corpus tooling
    _Rule(
        re.compile(r"^scripts/deepseek_data_engine\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "DeepSeek-driven data-engine for corpus expansion.",
    ),
    _Rule(
        re.compile(r"^scripts/convert_failures_to_sft\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Failure-log -> SFT data converter.",
    ),
    _Rule(
        re.compile(r"^scripts/run_corpus_to_100k\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Corpus growth orchestrator.",
    ),
    _Rule(
        re.compile(r"^scripts/register_v1_1\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Model registration helper.",
    ),
    _Rule(
        re.compile(r"^scripts/reference_diff\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Reference diff tool.",
    ),
    _Rule(
        re.compile(r"^scripts/run_ledger\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Local run ledger reader/writer.",
    ),
    _Rule(
        re.compile(r"^scripts/_batch_apply_pending\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Batch-apply-pending helper.",
    ),
    # verified_task — everything else under it is harness library code
    # (command_runner.py is separately classified BLOCKED_UNSAFE above)
    _Rule(
        re.compile(r"^scripts/verified_task/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Verified-task harness helpers (command_runner.py is separately "
        "flagged BLOCKED_UNSAFE; other modules in this tree are read-only "
        "data wiring).",
    ),
    # ── SWE-bench / agent runners ─────────────────────────────────────────
    _Rule(
        re.compile(r"^scripts/determinex_swebench"),
        "HIVE_SANDBOXED_PATH",
        "SWE-bench agent runs in Docker-controlled sandbox per ablation harness.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_swelancer"),
        "HIVE_SANDBOXED_PATH",
        "SWE-lancer feature agent — same sandbox stance.",
    ),
    # ── Cloak / verification ──────────────────────────────────────────────
    _Rule(
        re.compile(r"^scripts/determinex_cloak"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Cloak pipeline — AST transform + audit only; does not execute payload.",
    ),
    _Rule(
        re.compile(r"^scripts/verify_cloak\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Cloak audit verifier — read-only scan of API request logs.",
    ),
    # ── Doctor / status / setup / settings ────────────────────────────────
    _Rule(
        re.compile(r"^scripts/determinex_doctor\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Health check — runs `--version` style probes only.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_status\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Status reader — read-only over event log.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_setup\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Setup helper — installs declared toolchains; never executes user payload.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_settings\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Settings module — no subprocess execution.",
    ),
    _Rule(
        re.compile(r"^scripts/determinex_cli\.py$"),
        "LEGACY_EXEMPT_READ_ONLY",
        "CLI dispatcher — invokes documented sibling scripts.",
    ),
    # ── Corpus manager / non-PB corpus code ───────────────────────────────
    _Rule(
        re.compile(r"^scripts/corpus/"),
        "LEGACY_EXEMPT_READ_ONLY",
        "Corpus management code; never executes payload.",
    ),
    # ── Catch-all for scripts/ root (top-level helpers) ───────────────────
    _Rule(
        re.compile(r"^scripts/"),
        "UNKNOWN_REQUIRES_REVIEW",
        "scripts/ root-level helper; no specific rule matched — review required.",
    ),
)


# ---------------------------------------------------------------------------
# Execution-site detection
# ---------------------------------------------------------------------------

# subprocess attribute calls we flag
_SUBPROCESS_FN = frozenset(
    {
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    }
)

# os module call sites that execute commands
_OS_EXEC_FN = frozenset(
    {
        "system",
        "popen",
        # spawn family
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
    }
)


@dataclass
class ExecutionSite:
    file_path: str  # repo-relative, forward-slash
    line: int
    column: int
    kind: str  # e.g. "subprocess.run", "os.system", "shell=True"
    snippet: str  # the source line, trimmed
    classification: str  # one of CLASSIFICATIONS
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file_path": self.file_path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "snippet": self.snippet,
            "classification": self.classification,
            "rationale": self.rationale,
        }


class _CallFinder(ast.NodeVisitor):
    """Visit a parsed module and collect every execution-site call."""

    def __init__(self, file_lines: list[str]) -> None:
        self.sites: list[tuple[int, int, str, str]] = []  # (line, col, kind, snippet)
        self._lines = file_lines

    # subprocess.run(...), os.system(...), subprocess.Popen(...), etc.
    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        kind = self._classify_call(node.func)
        if kind:
            self.sites.append((node.lineno, node.col_offset, kind, self._snippet(node)))

        # shell=True keyword on ANY call — high-signal regardless of receiver
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                self.sites.append((node.lineno, node.col_offset, "shell=True", self._snippet(node)))

        self.generic_visit(node)

    def _classify_call(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            mod = func.value.id
            attr = func.attr
            if mod == "subprocess" and attr in _SUBPROCESS_FN:
                return f"subprocess.{attr}"
            if mod == "os" and attr in _OS_EXEC_FN:
                return f"os.{attr}"
        # bare Popen() / system() after `from subprocess import Popen`
        if isinstance(func, ast.Name):
            if func.id == "Popen":
                return "subprocess.Popen (imported)"
            # `run` and `system` are too common to flag without import tracking
        return None

    def _snippet(self, node: ast.AST) -> str:
        if not hasattr(node, "lineno"):
            return ""
        idx = node.lineno - 1
        if 0 <= idx < len(self._lines):
            return self._lines[idx].strip()[:200]
        return ""


# ---------------------------------------------------------------------------
# File enumeration + scanning
# ---------------------------------------------------------------------------

# Don't enumerate Python files inside known fenced dirs.
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "site-packages",
        "fine_tuning",
        "node_modules",
        ".pytest_cache",
        "build",
        "dist",
        "target",
        ".git",
        "archive",
        "archive_streamlit",
    }
)


def _enumerate_python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(REPO_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        out.append(p)
    return out


def _classify_path(rel: str) -> tuple[str, str]:
    """Apply CLASSIFICATION_RULES in order; first match wins."""
    for rule in CLASSIFICATION_RULES:
        if rule.pattern.search(rel):
            return rule.classification, rule.rationale
    return "UNKNOWN_REQUIRES_REVIEW", "No classification rule matched."


def scan_file(path: Path) -> list[ExecutionSite]:
    """Parse one Python file and return all execution sites it contains.
    Never executes anything. Tolerates SyntaxError by returning [].

    Kind-aware override (SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001):
    if a site's kind is in ``_ALWAYS_BLOCKED_KINDS`` (``shell=True``,
    ``os.system``, ``os.popen``), it is unconditionally classified
    BLOCKED_UNSAFE regardless of the file's path-rule. The path-rule's
    rationale is preserved in the site's rationale for context. This
    enforces safety-by-default: shell=True can never be exempted by a
    path-rule.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    path_classification, path_rationale = _classify_path(rel)

    finder = _CallFinder(source.splitlines())
    finder.visit(tree)

    # Kind-override carve-outs are defined at module level
    # (_KIND_OVERRIDE_EXEMPT) so tests can introspect them.
    out: list[ExecutionSite] = []
    for ln, col, kind, snip in finder.sites:
        if kind in _ALWAYS_BLOCKED_KINDS and path_classification not in _KIND_OVERRIDE_EXEMPT:
            site_classification = "BLOCKED_UNSAFE"
            site_rationale = (
                f"{kind} is unconditionally BLOCKED_UNSAFE — must migrate to "
                f"intake.hardened_runner. (path-rule was: {path_rationale})"
            )
        else:
            site_classification = path_classification
            site_rationale = path_rationale
        out.append(
            ExecutionSite(
                file_path=rel,
                line=ln,
                column=col,
                kind=kind,
                snippet=snip,
                classification=site_classification,
                rationale=site_rationale,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class AuditReport:
    lock_id: str
    generated_at: str
    repo_root: str
    scope: list[str]
    sites: list[ExecutionSite] = field(default_factory=list)

    @property
    def total_sites(self) -> int:
        return len(self.sites)

    def counts_by_classification(self) -> dict[str, int]:
        out: dict[str, int] = {c: 0 for c in CLASSIFICATIONS}
        for s in self.sites:
            out[s.classification] = out.get(s.classification, 0) + 1
        return out

    def counts_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.sites:
            out[s.kind] = out.get(s.kind, 0) + 1
        return dict(sorted(out.items()))

    def top_must_migrate(self, limit: int = 10) -> list[dict[str, object]]:
        per_file: dict[str, int] = {}
        for s in self.sites:
            if s.classification == "MUST_MIGRATE_TO_HARDENED_RUNNER":
                per_file[s.file_path] = per_file.get(s.file_path, 0) + 1
        ranked = sorted(per_file.items(), key=lambda x: (-x[1], x[0]))
        return [{"file_path": f, "sites": n} for f, n in ranked[:limit]]

    def blocked_unsafe(self) -> list[dict[str, object]]:
        return [s.to_dict() for s in self.sites if s.classification == "BLOCKED_UNSAFE"]

    def unknown_requires_review(self) -> list[dict[str, object]]:
        # Limit verbose output: file -> count
        per_file: dict[str, int] = {}
        for s in self.sites:
            if s.classification == "UNKNOWN_REQUIRES_REVIEW":
                per_file[s.file_path] = per_file.get(s.file_path, 0) + 1
        ranked = sorted(per_file.items(), key=lambda x: (-x[1], x[0]))
        return [{"file_path": f, "sites": n} for f, n in ranked]

    def to_dict(self) -> dict[str, object]:
        return {
            "lock_id": self.lock_id,
            "generated_at": self.generated_at,
            "repo_root": self.repo_root,
            "scope": self.scope,
            "totals": {
                "files_scanned_with_sites": len({s.file_path for s in self.sites}),
                "total_sites": self.total_sites,
                "counts_by_classification": self.counts_by_classification(),
                "counts_by_kind": self.counts_by_kind(),
            },
            "top_must_migrate": self.top_must_migrate(),
            "blocked_unsafe": self.blocked_unsafe(),
            "unknown_requires_review": self.unknown_requires_review(),
            "sites": [s.to_dict() for s in self.sites],
        }


def run_audit(root: Path = SCRIPTS_DIR) -> AuditReport:
    """Walk root, scan every Python file, return classified report. Read-only."""
    files = _enumerate_python_files(root)
    sites: list[ExecutionSite] = []
    for f in files:
        sites.extend(scan_file(f))
    return AuditReport(
        lock_id="PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001",
        generated_at=_dt.datetime.now(_dt.UTC).isoformat(),
        repo_root=str(REPO_ROOT).replace("\\", "/"),
        scope=[str(root.relative_to(REPO_ROOT)).replace("\\", "/")],
        sites=sites,
    )


# ---------------------------------------------------------------------------
# Markdown emission
# ---------------------------------------------------------------------------

_MD_PREAMBLE = """# Parallel Execution Layer Audit

> Generated by `scripts/dev/parallel_execution_layer_audit.py`.
> Locked under `locks/sentinel/PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001.json`.
> Do not edit by hand — regenerate via:
>
> ```
> python scripts/dev/parallel_execution_layer_audit.py --md docs/audits/PARALLEL_EXECUTION_LAYER_AUDIT.md
> ```

This document is a **read-only inventory** of every Python subprocess /
shell-out call site under `scripts/`. It does NOT execute any discovered
command and does NOT migrate any execution path.

Classification:

- **HARDENED_COMPILER_PATH** — `hive/compiler.py`'s sandboxed oracle (Job Object + Docker backend + WSL2 backend + output sanitisation).
- **HIVE_SANDBOXED_PATH** — other hive/* and browser/desktop/mobile modules that compose with hardened isolation (Sentinel-enforced sandbox / VM).
- **LEGACY_EXEMPT_READ_ONLY** — validators (DATA ENGINE ONLY), dev tools, agent helpers, the CLI dispatcher, doctor/status/setup/settings — do not execute user payload.
- **LEGACY_EXEMPT_TEST_FIXTURE** — `tests/*` — fixture-local shell-out.
- **MUST_MIGRATE_TO_HARDENED_RUNNER** — intake / repair / `ShadowCompiler` sites that bypass `hive/compiler.py` and should be routed through the hardened runner in a future rung.
- **BLOCKED_UNSAFE** — sites flagged as raw `shell=True` or `os.system` that have no documented exemption.
- **PROGRAMBENCH_OUT_OF_SCOPE** — Codex/ProgramBench trail (`scripts/corpus/programbench/`, `scripts/pb_*`, `scripts/determinex_programbench*`, `scripts/corpus/legacy_recovery/`).
- **UNKNOWN_REQUIRES_REVIEW** — site matched a known execution kind but no classification rule applied; flagged for human triage.

The audit is intentionally narrow in scope: this rung **inventories** the
problem; the next rung (`HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001`) will
migrate the MUST_MIGRATE sites.
"""


def to_markdown(report: AuditReport) -> str:
    counts = report.counts_by_classification()
    kinds = report.counts_by_kind()

    lines: list[str] = [_MD_PREAMBLE.rstrip(), ""]
    lines.append(f"**Audit timestamp:** `{report.generated_at}`")
    lines.append(f"**Scope:** `{', '.join(report.scope)}`")
    lines.append(f"**Total sites found:** **{report.total_sites}**")
    lines.append("")
    lines.append("## Counts by classification")
    lines.append("")
    lines.append("| Classification | Count |")
    lines.append("|---|---:|")
    for cls in sorted(CLASSIFICATIONS):
        lines.append(f"| {cls} | {counts.get(cls, 0)} |")
    lines.append("")
    lines.append("## Counts by kind")
    lines.append("")
    lines.append("| Kind | Count |")
    lines.append("|---|---:|")
    for k, n in kinds.items():
        lines.append(f"| `{k}` | {n} |")
    lines.append("")

    # Migration targets
    top = report.top_must_migrate()
    lines.append("## Top MUST_MIGRATE_TO_HARDENED_RUNNER targets")
    lines.append("")
    if top:
        lines.append("| File | Sites |")
        lines.append("|---|---:|")
        for row in top:
            lines.append(f"| `{row['file_path']}` | {row['sites']} |")
    else:
        lines.append("_None._")
    lines.append("")

    # BLOCKED_UNSAFE — surface every one of these immediately
    unsafe = report.blocked_unsafe()
    lines.append("## BLOCKED_UNSAFE sites")
    lines.append("")
    if unsafe:
        lines.append("| File | Line | Kind | Snippet |")
        lines.append("|---|---:|---|---|")
        for s in unsafe:
            lines.append(
                f"| `{s['file_path']}` | {s['line']} | `{s['kind']}` | `{str(s['snippet'])[:80]}` |"
            )
    else:
        lines.append("_None._")
    lines.append("")

    # UNKNOWN
    unknowns = report.unknown_requires_review()
    lines.append("## UNKNOWN_REQUIRES_REVIEW (top-level scripts/ with no rule)")
    lines.append("")
    if unknowns:
        lines.append("| File | Sites |")
        lines.append("|---|---:|")
        for row in unknowns:
            lines.append(f"| `{row['file_path']}` | {row['sites']} |")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Related: `locks/sentinel/PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001.json`, "
        "`scripts/hive/compiler.py`, `scripts/intake/build_adapters.py`, "
        "`scripts/codebase_explorer.py`.*"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None, help="Write full JSON report to this path")
    ap.add_argument(
        "--md", type=Path, default=None, help="Write human-readable Markdown report to this path"
    )
    ap.add_argument(
        "--strict", action="store_true", help="Exit 1 if any BLOCKED_UNSAFE site is found"
    )
    args = ap.parse_args(argv)

    report = run_audit()
    counts = report.counts_by_classification()

    print(f"Parallel Execution Layer Audit — {report.total_sites} sites")
    for cls in sorted(CLASSIFICATIONS):
        print(f"  {cls:<35} {counts.get(cls, 0)}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nWrote JSON: {args.json}")

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(to_markdown(report), encoding="utf-8")
        print(f"Wrote Markdown: {args.md}")

    if args.strict and counts.get("BLOCKED_UNSAFE", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
