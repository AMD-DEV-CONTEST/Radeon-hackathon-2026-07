"""Does the UI claim only what it has actually established?

This project's entire value proposition is that it does not overstate what it has proven, so a
surface that asserts an unverified fact is a product defect, not a cosmetic one. Every check below
corresponds to a claim this app really made.

Source-level checks on purpose. These are cheap, they run in the Python suite alongside the release
gates, and the failure mode they guard against is a *string* being rendered unconditionally --
which is exactly what source text shows and what a mounted-component test tends to miss.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments.

    Load-bearing. These checks look for claim STRINGS in source, and the comments explaining why a
    claim was removed necessarily quote the old wording -- so an un-stripped scan reports the
    explanation as the defect. That happened on the first run of every check in this file. Stripping
    comments also means a future author can document a fix without breaking its guard.

    Deliberately crude: it does not parse strings, so a `//` inside a string literal is also
    dropped. For grepping claim text out of TSX that is acceptable and errs toward false negatives
    on comment-like literals rather than false positives on prose.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _read(rel: str) -> str:
    return _strip_comments((FRONTEND / rel).read_text(encoding="utf-8"))


def test_no_surface_probes_the_tauri_global_that_this_app_never_sets():
    """`window.__TAURI__` exists only when `app.withGlobalTauri: true`, which this app never sets.

    Three separate surfaces used it as their "is the runtime present?" test, so each was
    permanently false inside the real packaged app. The Repair Panel showed
    BLOCKED_FRONTEND_MISSING unconditionally (found live 2026-07-19, "repair doesnt work"), and the
    Proof Center silently never performed its live read -- telling a user sitting in the desktop app
    that a live read required the desktop app, while every ProgramBench figure stayed at a module
    constant.

    The real Tauri v2 marker is `__TAURI_INTERNALS__`, which `lib/api.ts::isTauri()` already checks
    correctly. Any new probe must use that.
    """
    offenders: list[str] = []
    for path in FRONTEND.rglob("*.ts*"):
        if "__tests__" in path.parts or "wireframes" in path.parts:
            continue
        text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        for i, line in enumerate(text.splitlines(), 1):
            # `__TAURI_INTERNALS__` is correct; a bare `__TAURI__` is the bug.
            if re.search(r"__TAURI__(?!_)", line) and "withGlobalTauri" not in line:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{i}")
    assert not offenders, (
        "these read window.__TAURI__, which is never populated in this app, so the guarded code "
        f"never runs: {offenders}. Use isTauri() from @/lib/api instead."
    )


def test_the_git_banner_distinguishes_a_clean_tree_from_a_failed_read():
    """`git_status` throws on any non-zero git exit, and the catch reset files to [] -- which the
    banner could not tell apart from a genuinely clean repo. A repo with uncommitted work whose
    read failed (git not on PATH, locked index, timeout) rendered an emerald tick and the words
    "Working tree clean" on the landing screen."""
    text = _read("app/page.tsx")
    assert "explorerGitUnavailable" in text, (
        "page.tsx has no failed-read state, so a git_status failure is indistinguishable from a "
        "clean working tree"
    )
    assert "Git status unavailable" in text, "no honest label for a failed git read"
    # The failure state must be consulted where the claim is rendered, not merely stored.
    clean_idx = text.index("Working tree clean")
    window = text[max(0, clean_idx - 1200) : clean_idx]
    assert "explorerGitUnavailable" in window, (
        "'Working tree clean' is rendered without consulting the failed-read state"
    )


def test_the_wizard_does_not_assert_an_api_key_it_has_not_checked():
    """The OpenRouter card rendered "Already Configured ✓ / Your OPENROUTER_API_KEY is already in
    .env" unconditionally on step 2 of first-run setup, with no key check. For an installed user
    that is false twice: they have entered no key, and neither .env nor litellm_config.yaml ships in
    the installer -- both are repository files."""
    text = _read("components/SetupWizard.tsx")
    assert "Already Configured" not in text, (
        "the wizard again asserts a provider key is configured without checking"
    )
    assert "get_api_key_status" in text, "the wizard never probes real key status"
    assert "openRouterKeyPresent" in text, "the OpenRouter card is not driven by probed status"


def test_the_offline_setup_path_cannot_report_ready_after_a_failed_init():
    """`await invoke("initialize_system").catch(() => {})` sat INSIDE the try, so the outer catch
    that sets step="error" was unreachable for the offline branch: a real failure was swallowed and
    the wizard went straight to the green "System Ready" screen."""
    text = _read("components/SetupWizard.tsx")
    assert 'invoke("initialize_system").catch(() => {})' not in text, (
        "the offline branch swallows initialize_system failure and still reports System Ready"
    )
    assert re.search(r'invoke\("initialize_system"\)', text), "offline path no longer initialises"


def test_the_model_readiness_gate_is_actually_wired():
    """ConceptLab has always gated spec generation on `specGenerationBlockMessage(workReadiness)` --
    but page.tsx never passed the prop, and that helper returns null for `undefined`, so the branch
    was dead in every build. The Work tab would generate a spec and launch a hive session on an
    install whose Builder and Monitor roles resolve to absent models, with no warning of any kind:
    the string "Missing local model coverage for N roles" could never appear.

    `evaluateWorkReadiness` was called nowhere outside its own unit test, and the registered
    `get_work_readiness` command was never invoked from anywhere in src/.
    """
    page = _read("app/page.tsx")
    assert "workReadiness={workReadiness}" in page, (
        "page.tsx renders ConceptLab without passing workReadiness, so its spec-generation gate "
        "receives undefined and never fires"
    )
    assert "get_work_readiness" in page, "nothing invokes the get_work_readiness command"
    # The gate is useless if the user cannot act on it.
    assert "onOpenModelSettings" in page, (
        "the readiness block tells the user to fix model settings but no handler is wired to open "
        "them"
    )

    lab = _read("components/ConceptLab.tsx")
    assert "specGenerationBlockMessage(workReadiness)" in lab, (
        "ConceptLab no longer consults the readiness gate"
    )


def test_a_benchmark_is_scored_against_the_tasks_it_actually_attempts():
    """BigCodeBench declared `defaultTotal: 1140` (the full suite) while its args launched
    `--n 500`, and score is `resolved / defaultTotal` -- so a run that solved every task it
    attempted displayed as 43.9%."""
    text = _read("components/BenchmarkRunner.tsx")
    block = text[text.index('id: "bigcode"') :]
    block = block[: block.index("},")]
    n_arg = re.search(r'"--n",\s*"(\d+)"', block)
    total = re.search(r"defaultTotal:\s*(\d+)", block)
    assert n_arg and total, block[:300]
    assert n_arg.group(1) == total.group(1), (
        f"bigcode launches --n {n_arg.group(1)} but scores against {total.group(1)}; a perfect run "
        f"would display as {int(n_arg.group(1)) / int(total.group(1)):.1%}"
    )


def test_stopping_a_benchmark_reports_whether_the_kill_was_confirmed():
    """`invokeSafe` never rejects, so the old `.catch(showError)` was dead code -- and the state flip
    plus the "Stopped" log ran synchronously before the promise settled, asserting the process had
    stopped regardless of whether Rust killed anything."""
    text = _read("components/BenchmarkRunner.tsx")
    assert "const stopBenchmark = async" in text, "stop handler must await the kill"
    assert 'await invokeSafe("stop_benchmark_run"' in text, (
        "the stop result is not awaited, so the log runs before the kill resolves"
    )
    assert 'invokeSafe("stop_benchmark_run", { benchmarkId: id }).catch(' not in text, (
        "invokeSafe never rejects; a .catch here is dead code"
    )


def test_a_failed_read_is_not_rendered_as_a_measurement():
    """FlywheelFeed substituted an all-zeros summary on failure (`result ?? EMPTY_SUMMARY`) and then
    rendered "0" under a tooltip reading "Exact line count." -- a failed IPC read presented as an
    exact measurement."""
    text = _read("components/FlywheelFeed.tsx")
    assert "unavailable" in text, "no failed-read state in FlywheelFeed"
    assert "result === null" in text, "the failure case is not distinguished from an empty result"
    # The "exact count" claim must be conditional on the read having succeeded.
    exact_at = text.index("Exact line count.")
    assert "unavailable" in text[max(0, exact_at - 400) : exact_at], (
        "the 'Exact line count.' tooltip is not gated on the read having succeeded"
    )


def test_maintenance_bay_does_not_assert_work_it_has_not_done():
    """Three unconditional claims: `UPDATE_PROPOSED_QUARANTINED` as a bare literal (a change set
    stated as proposed and quarantined on a fresh mount), "impact plan present" gated only on
    `riskClassification !== "unknown"` (which becomes "none_found" after any clean scan), and a
    compatibility verifier defaulted from the SECURITY scan -- a security scan is not a
    compatibility verifier for a dependency update."""
    text = _read("components/ide-product-shell/MaintenanceBayPanel.tsx")
    assert "<dd>UPDATE_PROPOSED_QUARANTINED</dd>" not in text, (
        "the quarantine row is unconditional again"
    )
    assert '"impact plan present"' not in text, (
        "an impact plan is asserted present when none is produced anywhere"
    )
    assert "compatibilityVerifierPresentProp ?? scanRan" not in text, (
        "the compatibility verifier is again defaulted from the security scan"
    )


def test_repo_clinic_does_not_report_analysis_without_a_workspace():
    """ "<dd>analyzed</dd>" was the one unconditional row in a table of twelve. With no workspace
    open, resolvedWorkspacePath is "" so no diagnosis is attempted -- and it still said analyzed."""
    text = _read("components/ide-product-shell/RepoClinicPanel.tsx")
    assert "<dd>analyzed</dd>" not in text, "repo analysis status is unconditional again"
    assert "not analyzed" in text, "there is no honest label for the un-analyzed case"


def test_the_project_hub_does_not_ship_invented_activity():
    """Three seeded cards shipped with the development machine's paths AND literal
    `lastOpened: "Today"` / `lastRun: "Frontend IA pass"` / `proof: "Proof gated"`, so a fresh
    install described recent activity and proof state on drives the user does not have."""
    text = _read("components/ProjectHub.tsx")
    seeds = text[text.index("const SEEDED_PROJECTS") :]
    seeds = seeds[: seeds.index("\n];")]
    for invented in (
        "Frontend IA pass",
        "PB shard review",
        "Ablation evidence",
        '"Today"',
        '"This week"',
    ):
        assert invented not in seeds, (
            f"seeded project data still contains invented activity: {invented}"
        )


def test_both_setup_paths_probe_fine_tuned_model_coverage():
    """The model-gap panel existed only on the online/cloaked path, so anyone choosing Offline never
    saw "N of M fine-tuned models are not installed" -- the gap it exists to close, left open for
    precisely the installs least likely to have any models."""
    text = _read("components/SetupWizard.tsx")
    assert "probeDeterminexModels" in text, "no shared model probe"
    # Called at least twice: once per branch.
    assert text.count("probeDeterminexModels()") >= 2, (
        "the model probe is not run on both the online and offline setup paths"
    )
