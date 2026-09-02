"""IDE backend command surface.

Single entry point the IDE/Tauri layer calls. Commands:

  inspect_workspace
  route_model
  generate_llm_program_advisory
  diagnose_dry_run
  diagnose_live_opt_in
  generate_patch_plan_opt_in
  verify_temp_patch
  get_repair_state
  get_human_approval_packet

Read-only/status commands cannot mutate source. Live commands require
opt_in=True. Patch commands operate temp-only. Approval packet command
does not approve automatically. Deterministic JSON output.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from intake.build_adapter_registry import BuildAdapterRegistry  # noqa: E402
from intake.build_adapters import UnknownAdapter  # noqa: E402
from models.local_model_config_record import LocalModelConfigRecord  # noqa: E402
from models.model_inventory import LocalModelInventory  # noqa: E402
from models.model_router import (  # noqa: E402
    CURRENT_MODEL_IDS,
    ModelRouter,
    RouterMode,
    TaskClass,
)

from .backend_command_record import (
    IDE_BACKEND_COMMAND_STATUS_TOKENS,
    CommandResult,
)
from .human_approval_ui_model import build_packet

_COMMANDS = frozenset(
    {
        "inspect_workspace",
        "source_apply_dry_run",
        "route_model",
        # Greenfield Idea Lab seam (2026-06-14). Both commands are thin delegates to
        # the ONE canonical greenfield module (scripts/determinex_build_from_idea.py);
        # no synthesis/solve logic is reimplemented here.
        #  - synthesize_oracle_preview: deterministic, read-only. Shows the SOUND
        #    oracle (tests) the idea will be verified against. No model, no mutation.
        #  - build_from_idea_opt_in: live, opt-in, TEMP-ONLY. Runs the amplified solve
        #    against that synthesized oracle and returns a verified program. Does NOT
        #    mutate user source (that stays behind a separate apply opt-in).
        "synthesize_oracle_preview",
        "build_from_idea_opt_in",
        # Repo Clinic seam (2026-06-14): brownfield diagnosis through the ONE canonical
        # repair engine (scripts/determinex_repair.py = ingest+oracle+adjudicator+validator
        # +explainer+amplifier). Read-only diagnosis: runs the workspace's own oracle,
        # returns blame (CODE/ENVIRONMENT/TEST) + moves + proven-slop. No source mutation.
        # Replaces the legacy diagnose path with the same proven engine as everything else.
        "repair_diagnose",
        "generate_llm_program_advisory",
        # Proof Center live binding (2026-06-14): reads the consolidated governance/
        # authority anchors (the live source of truth) instead of the archived
        # apparatus view-models. Read-only; the dashboard DISPLAYS authority, never
        # grants it. all_closed=True means no claim has outrun its proof.
        "get_governance_status",
        # What this machine can actually do, and what it has actually spent. Added 2026-07-30 because
        # nothing reported either: the accelerator was detected only via nvidia-smi (so AMD and Apple
        # rigs reported CPU-only and were driven at the lowest tier), and determinex_usage_ledger was
        # referenced by passport.rs but its latency/cost figures never reached a user-visible surface.
        # Read-only: it reports capability, it does not change routing.
        "get_runtime_capability_status",
        "diagnose_dry_run",
        "diagnose_live_opt_in",
        "generate_patch_plan_opt_in",
        "verify_temp_patch",
        "get_repair_state",
        "get_human_approval_packet",
        # DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES rung 1.
        # Read-only commands that surface the locked unified-product
        # backend view-models to the frontend. Each returns a JSON-
        # serialized view-model record from its lock module. NONE of
        # these commands mutate source, write training rows, grant
        # approval, or authorize execution.
        "get_unified_product_navigation_model",
        "get_idea_lab_workflow_state",
        "get_repo_clinic_workflow_state",
        "get_maintenance_bay_workflow_state",
        "get_learning_studio_workflow_state",
        # Rung 7 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES: content generation for
        # Learning Studio. Read-only (grounds explanations in the verified corpus + real files),
        # non-authorizing (every output is still gated through learning_studio_workflow.evaluate()).
        # Never mutates source, never approves, never opens training eligibility. Deliberately NOT
        # in UNIFIED_PRODUCT_READ_ONLY_COMMANDS below -- that set is capability-description-only
        # (no args, no per-call computation), same reason preview_idea_oracle/repair_diagnose aren't.
        "generate_learning_studio_content",
        # Maintenance Bay live scan: composes the 5 existing security_gate.py scanners
        # (secret_scan, dependency_scan, verify_lockfiles, license_scan, container_scan) into
        # one read-only advisory result. Never applies an update, never authorizes anything --
        # a "blocked" gate here is a finding to review, not source mutation. Same reasoning as
        # generate_learning_studio_content for staying out of UNIFIED_PRODUCT_READ_ONLY_COMMANDS.
        "run_maintenance_bay_scan",
        "get_proof_operator_center_state",
        "get_user_level_teaching_windows",
        "get_unified_splash_demo_spec",
        # DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001 (rung 2).
        # Read-only binding to the Codex Idea Lab verified Python CLI
        # splash demo evidence. Returns a render-safe scoped status that
        # the React Idea Lab panel displays. The handler never broadens
        # the scoped demo claim; it returns AWAITING_EVIDENCE if the
        # evidence file is not present locally.
        "get_idea_lab_verified_demo_status",
        # DETERMINEX_REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
        # Read-only binding to the Codex Repo Clinic fixture-repair
        # splash demo evidence. Returns a render-safe scoped status that
        # the React Repo Clinic panel displays. The handler never opens
        # source mutation, broadens claims, or authorizes anything.
        "get_repo_clinic_verified_demo_status",
        # DETERMINEX_REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
        # Read-only binding to the Codex Maintenance Bay dry-run/update
        # splash demo evidence. Returns a render-safe scoped status that
        # the React Maintenance Bay panel displays. The handler never
        # opens source mutation, broadens claims, or authorizes anything.
        "get_maintenance_bay_verified_demo_status",
        # DETERMINEX_REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.
        # Read-only binding to the Codex Learning Studio teaching splash
        # demo evidence. Returns a render-safe NON-AUTHORIZING scoped
        # status that the React Learning Studio panel displays. The
        # handler never opens source mutation, approval, training,
        # release, or any broad claim.
        "get_learning_studio_verified_demo_status",
        # DETERMINEX_REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_LOCK_001.
        # Read-only binding to the Codex Proof / Operator Center
        # milestone dashboard evidence. Returns a render-safe view-model
        # the React Proof / Operator Center panel displays. The dashboard
        # DISPLAYS authority; it does NOT grant authority. Source
        # mutation, approval, proof-execution authority, training,
        # release, broad claims all remain False. Roadmap items
        # (Cathedral Index, Columbia House, Scale-to-100, Full Cathedral,
        # Windows-first matrix) remain pending/draft; the binding refuses
        # to widen them into product truth.
        "get_proof_operator_center_milestone_dashboard_status",
        # Direct corpus query surface (2026-07-16): exposes the ONE canonical read-only
        # corpus API (scripts/determinex_corpus_api.py -- ask/maturity_report/timeline)
        # as a live command, instead of leaving it reachable only through the two
        # Learning Studio modes that happen to call ask() internally. No new query
        # logic lives here; this is wiring, same reasoning as run_maintenance_bay_scan.
        # Excluded from UNIFIED_PRODUCT_READ_ONLY_COMMANDS for the same reason as that
        # command: real per-call computation (a fresh corpus load + search), not a
        # static capability-description view-model.
        "query_corpus",
    }
)


UNIFIED_PRODUCT_READ_ONLY_COMMANDS = frozenset(
    {
        "get_unified_product_navigation_model",
        "get_idea_lab_workflow_state",
        "get_repo_clinic_workflow_state",
        "get_maintenance_bay_workflow_state",
        "get_learning_studio_workflow_state",
        "get_proof_operator_center_state",
        "get_user_level_teaching_windows",
        "get_unified_splash_demo_spec",
        "get_idea_lab_verified_demo_status",
        "get_repo_clinic_verified_demo_status",
        "get_maintenance_bay_verified_demo_status",
        "get_learning_studio_verified_demo_status",
        "get_proof_operator_center_milestone_dashboard_status",
    }
)


def commands() -> frozenset[str]:
    return _COMMANDS


class IDEBackendCommandSurface:
    """Stateless command dispatch."""

    def call(
        self,
        command: str,
        *,
        workspace: Path | None = None,
        task_class: str = "BUILD_DIAGNOSIS",
        opt_in: bool = False,
        config: LocalModelConfigRecord | None = None,
        verifier_status: str = "",
        unified_diff: str = "",
        files_changed: tuple[str, ...] = (),
        idea_text: str = "",
        user_request: str = "",
        learning_mode: str = "",
        learning_context: str = "",
        corpus_query: str = "",
        corpus_mode: str = "ask",
    ) -> CommandResult:
        if command not in _COMMANDS:
            return self._result(
                command, "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND", notes=("unknown command",)
            )

        if command == "inspect_workspace":
            return self._inspect(workspace)

        if command == "synthesize_oracle_preview":
            return self._synthesize_oracle_preview(idea_text)

        if command == "build_from_idea_opt_in":
            return self._build_from_idea(idea_text, opt_in, config)

        if command == "repair_diagnose":
            return self._repair_diagnose(workspace)

        if command == "generate_llm_program_advisory":
            return self._llm_program_advisory(workspace, user_request or idea_text)

        if command == "get_governance_status":
            return self._governance_status()

        if command == "get_runtime_capability_status":
            return self._runtime_capability_status()

        if command == "route_model":
            return self._route(task_class)

        if command == "diagnose_dry_run":
            return self._diagnose_dry_run(task_class)

        if command == "diagnose_live_opt_in":
            return self._diagnose_live(task_class, opt_in, config)

        if command == "generate_patch_plan_opt_in":
            return self._patch_plan(opt_in, config, workspace, user_request or idea_text)

        if command == "verify_temp_patch":
            return self._verify_temp_patch(workspace)

        if command == "get_repair_state":
            return self._repair_state()

        if command == "get_human_approval_packet":
            return self._approval_packet(workspace, unified_diff, files_changed, verifier_status)

        if command == "source_apply_dry_run":
            return self._source_apply_dry_run(workspace)

        # Read-only unified-product view-model commands.
        if command == "get_unified_product_navigation_model":
            return self._unified_navigation_model()
        if command == "get_idea_lab_workflow_state":
            return self._idea_lab_workflow_state()
        if command == "get_repo_clinic_workflow_state":
            return self._repo_clinic_workflow_state()
        if command == "get_maintenance_bay_workflow_state":
            return self._maintenance_bay_workflow_state()
        if command == "get_learning_studio_workflow_state":
            return self._learning_studio_workflow_state()
        if command == "generate_learning_studio_content":
            return self._learning_studio_generate(learning_mode, learning_context, workspace)
        if command == "run_maintenance_bay_scan":
            return self._maintenance_bay_run_scan()
        if command == "get_proof_operator_center_state":
            return self._proof_operator_center_state()
        if command == "get_user_level_teaching_windows":
            return self._user_level_teaching_windows()
        if command == "get_unified_splash_demo_spec":
            return self._unified_splash_demo_spec()
        if command == "get_idea_lab_verified_demo_status":
            return self._idea_lab_verified_demo_status()
        if command == "get_repo_clinic_verified_demo_status":
            return self._repo_clinic_verified_demo_status()
        if command == "get_maintenance_bay_verified_demo_status":
            return self._maintenance_bay_verified_demo_status()
        if command == "get_learning_studio_verified_demo_status":
            return self._learning_studio_verified_demo_status()
        if command == "get_proof_operator_center_milestone_dashboard_status":
            return self._proof_operator_center_milestone_dashboard_status()
        if command == "query_corpus":
            return self._query_corpus(corpus_query, corpus_mode)

        return self._result(command, "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND")

    # ------------------------------------------------------------------
    # Individual commands
    # ------------------------------------------------------------------

    def _inspect(self, workspace: Path | None) -> CommandResult:
        if workspace is None or not Path(workspace).is_dir():
            return self._result(
                "inspect_workspace",
                "IDE_COMMAND_OK",
                payload={"adapter": "Unknown", "supported": False},
            )
        reg = BuildAdapterRegistry()
        sel = reg.select(Path(workspace))
        supported = sel.primary is not UnknownAdapter
        return self._result(
            "inspect_workspace",
            "IDE_COMMAND_OK",
            payload={
                "adapter": sel.primary.name,
                "build_system_id": sel.primary.build_system_id,
                "supported": supported,
            },
        )

    @staticmethod
    def _greenfield_module():
        """Import the ONE canonical greenfield module (no logic lives here)."""
        import sys as _sys

        _scripts = str(Path(__file__).resolve().parent.parent)
        if _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        import determinex_build_from_idea as _g  # noqa: E402

        return _g

    def _synthesize_oracle_preview(self, idea_text: str) -> CommandResult:
        """Deterministic, read-only: show the SOUND oracle for an idea. Delegate."""
        if not idea_text.strip():
            return self._result(
                "synthesize_oracle_preview",
                "IDE_COMMAND_OK",
                payload={"n_checks": 0, "note": "empty idea"},
            )
        try:
            g = self._greenfield_module()
            spec = g.parse_spec(idea_text)
            tests = g.synthesize_oracle_tests(spec)
            ok, why = g.validate_oracle(tests, spec)
        except NotImplementedError as e:
            return self._result(
                "synthesize_oracle_preview",
                "IDE_COMMAND_OK",
                payload={"n_checks": 0, "note": str(e)},
            )
        except Exception as e:  # never let preview crash the surface
            return self._result(
                "synthesize_oracle_preview",
                "IDE_COMMAND_OK",
                payload={"n_checks": 0, "note": f"preview error: {e}"},
            )
        return self._result(
            "synthesize_oracle_preview",
            "IDE_COMMAND_OK",
            payload={
                "name": spec.name,
                "examples": len(spec.examples),
                "invariants": list(spec.invariants),
                "n_checks": tests.count("def test_"),
                "oracle_sound": ok,
                "oracle_tests": tests,
                "note": why,
                "source_mutation": False,
            },
        )

    def _build_from_idea(
        self, idea_text: str, opt_in: bool, config: LocalModelConfigRecord | None
    ) -> CommandResult:
        """Live, opt-in, TEMP-ONLY: amplified build against the synthesized oracle.
        Delegate to the canonical module; never mutate user source here."""
        if not opt_in:
            return self._result("build_from_idea_opt_in", "IDE_COMMAND_BLOCKED_NOT_OPTED_IN")
        if config is None:
            return self._result("build_from_idea_opt_in", "IDE_COMMAND_BLOCKED_NO_MODEL")
        if not idea_text.strip():
            return self._result(
                "build_from_idea_opt_in",
                "IDE_COMMAND_OK",
                payload={"solved": False, "note": "empty idea"},
            )
        try:
            g = self._greenfield_module()
            gen = g.ollama_generator(
                getattr(config, "model_id", "") or "determinex-coder-base-tiny:latest"
            )
            res = g.build_from_idea(idea_text, gen, k=6)
        except Exception as e:
            return self._result(
                "build_from_idea_opt_in",
                "IDE_COMMAND_OK",
                payload={"solved": False, "note": f"build error: {e}"},
            )
        return self._result(
            "build_from_idea_opt_in",
            "IDE_COMMAND_TEMP_ONLY",
            payload={
                "solved": res.solved,
                "n_checks": res.n_checks,
                "samples": res.samples,
                "proof": res.proof,
                "program": res.code if res.solved else "",
                "oracle_tests": res.oracle_tests,
                "next_moves": res.next_moves,
                "source_mutation": False,
                # "the model tried N times and was wrong" and "the model was never reached" are
                # different facts, and only the first is evidence about the model. Without these the
                # UI renders both as `solved: false, samples: N` -- which is how a misconfigured
                # provider looked exactly like a capability ceiling until 2026-07-31.
                "generation_errors": getattr(res, "generation_errors", 0),
                "generator_never_answered": getattr(res, "generator_never_answered", False),
            },
        )

    def _governance_status(self) -> CommandResult:
        """Live no-overclaim state from governance/ (the source of truth). Delegate."""
        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            import governance as _g

            anchors = dict(_g.AUTHORITY_FALSE)
            violations = [k for k, v in anchors.items() if v is not False]
        except Exception as e:
            return self._result(
                "get_governance_status",
                "IDE_COMMAND_OK",
                payload={"all_closed": None, "note": f"governance error: {e}"},
            )
        return self._result(
            "get_governance_status",
            "IDE_COMMAND_OK",
            payload={
                "authority_anchors": anchors,
                "all_closed": len(violations) == 0,
                "violations": violations,
                "negative_invariants": list(_g.AUTHORITY_NEGATIVE_INVARIANTS),
                "displays_authority_only": True,
                "source_mutation": False,
            },
        )

    def _runtime_capability_status(self) -> CommandResult:
        """What this machine can actually do, and what it has actually spent.

        Two things were invisible before this existed.

        THE ACCELERATOR. `hive.hardware` probed `nvidia-smi` and nothing else, so an AMD or Apple
        machine fell through to tier -1 "CPU-only" -- `max_local_models()` 0, `max_parallel_steps` 1,
        nothing kept resident -- while sitting on more memory than the tier-2 threshold. Multi-vendor
        detection now answers the question; this surfaces the answer, including the device string a
        caller should hand PyTorch ("cuda" for both NVIDIA and a ROCm build, "mps" for Metal).

        THE LEDGER. `determinex_usage_ledger` was referenced by passport.rs but its latency and cost
        figures never reached a user-visible surface, so "local is free and fast" was a claim rather
        than a reading.

        Every field is either measured or explicitly null. Where a probe cannot answer, the reason is
        carried instead of a zero -- a zero here would read as "measured, and it was nothing", which
        is the failure mode this repo keeps finding.
        """
        payload: dict[str, object] = {"read_only": True}

        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            from hive.hardware import get_hw_profile

            hw = get_hw_profile()
            payload["accelerator"] = {
                "vendor": hw.accelerator,
                "label": hw.accelerator_label,
                "torch_device": hw.torch_device,
                "vram_gb": round(hw.vram_gb, 2),
                "device_count": hw.gpu_count,
                "ram_gb": round(hw.ram_gb, 2),
                "tier": hw.tier,
                "tier_label": hw.tier_label,
                "max_local_models": hw.max_local_models(),
                "max_parallel_steps": hw.max_parallel_steps,
                "models_kept_resident": list(hw.lifecycle.keep_hot),
                # Which memory pool the tier was derived from. "tier 1" on 16 GB of VRAM and
                # "tier 1" on 24 GB of system RAM are different machines, and a reader of this
                # surface should not have to infer which one they are looking at.
                "capacity_basis": hw.capacity_basis,
                # Display-only, and empty on x86. Named so a Snapdragon user can see their machine
                # WAS recognised -- Determinex simply has no NPU/GPU path on Windows ARM64 and runs
                # the ARM64 CPU path, which is a different statement from "detection failed".
                "platform_note": hw.platform_note,
            }
        except Exception as exc:
            payload["accelerator"] = None
            payload["accelerator_error"] = f"{type(exc).__name__}: {exc}"

        try:
            import sys as _sys2

            _scripts2 = str(Path(__file__).resolve().parent.parent)
            if _scripts2 not in _sys2.path:
                _sys2.path.insert(0, _scripts2)
            import determinex_usage_ledger as _ledger

            payload["usage"] = _ledger.summarize_ledger()
        except Exception as exc:
            payload["usage"] = None
            payload["usage_error"] = f"{type(exc).__name__}: {exc}"

        return self._result("get_runtime_capability_status", "IDE_COMMAND_OK", payload=payload)

    def _repair_diagnose(self, workspace: Path | None) -> CommandResult:
        """Brownfield diagnosis via the ONE canonical repair engine. Delegate."""
        if workspace is None or not Path(workspace).is_dir():
            return self._result(
                "repair_diagnose",
                "IDE_COMMAND_OK",
                payload={"healthy": None, "note": "no workspace"},
            )
        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            import determinex_repair as _r

            res = _r.repair_workspace(Path(workspace))  # diagnosis only (no model)
        except Exception as e:
            return self._result(
                "repair_diagnose",
                "IDE_COMMAND_OK",
                payload={"healthy": None, "note": f"diagnose error: {e}"},
            )

        # A cost gate and a timeout are NOT diagnoses. Reporting them as IDE_COMMAND_OK with
        # healthy=None told the frontend "we looked, and the answer is inconclusive" when the
        # truth was "we never looked". Found 2026-08-02: this command blocked for 10 minutes
        # on a real repository and then reported a pytest collection error that did not exist.
        if res.oracle == "needs_approval":
            return self._result(
                "repair_diagnose",
                "IDE_COMMAND_NEEDS_APPROVAL",
                payload={
                    "healthy": None,
                    "requires_approval": True,
                    "estimate_note": res.notes[0] if res.notes else "",
                    "note": "verification not started: cost exceeds the budget",
                },
                notes=tuple(res.notes),
            )
        if res.oracle == "timed_out":
            return self._result(
                "repair_diagnose",
                "IDE_COMMAND_TIMED_OUT",
                payload={
                    "healthy": None,
                    "timed_out": True,
                    "note": "verification exceeded its budget; no verdict was reached",
                },
                notes=tuple(res.notes),
            )
        return self._result(
            "repair_diagnose",
            "IDE_COMMAND_OK",
            payload={
                "language": res.language,
                "oracle": res.oracle,
                "healthy": res.healthy,
                "n_failures": res.n_failures,
                "blame": res.blame,
                "moves": res.verdicts,
                "proven_slop": res.proven_slop,
                "notes": list(res.notes),
                "explanations": res.explanations,
                "source_mutation": False,
            },
        )

    def _llm_program_advisory(self, workspace: Path | None, user_request: str) -> CommandResult:
        from .llm_program_advisor import build_advisory_packet

        packet = build_advisory_packet(user_request=user_request, workspace=workspace)
        return self._result(
            "generate_llm_program_advisory",
            "IDE_COMMAND_OK",
            payload=packet.to_dict(),
            notes=(
                "model-neutral advisory packet only",
                "deterministic verifier remains source of truth",
                "no source mutation, no live model call, no training eligibility",
            ),
        )

    def _route(self, task_class: str) -> CommandResult:
        inv = LocalModelInventory.of(sorted(CURRENT_MODEL_IDS))
        try:
            tc = TaskClass(task_class)
        except ValueError:
            return self._result(
                "route_model",
                "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND",
                notes=(f"unknown task_class {task_class!r}",),
            )
        rec = ModelRouter(inventory=inv).route(tc, mode=RouterMode.DRY_RUN)
        return self._result("route_model", "IDE_COMMAND_OK", payload=rec.to_dict())

    def _diagnose_dry_run(self, task_class: str) -> CommandResult:
        return self._result(
            "diagnose_dry_run",
            "IDE_COMMAND_TEMP_ONLY",
            payload={"task_class": task_class, "mode": "dry_run"},
        )

    def _diagnose_live(
        self, task_class: str, opt_in: bool, config: LocalModelConfigRecord | None
    ) -> CommandResult:
        if not opt_in:
            return self._result("diagnose_live_opt_in", "IDE_COMMAND_BLOCKED_NOT_OPTED_IN")
        if config is None:
            return self._result("diagnose_live_opt_in", "IDE_COMMAND_BLOCKED_NO_MODEL")
        return self._result(
            "diagnose_live_opt_in",
            "IDE_COMMAND_TEMP_ONLY",
            payload={"task_class": task_class, "mode": "opt_in_live"},
        )

    def _patch_plan(
        self,
        opt_in: bool,
        config: LocalModelConfigRecord | None,
        workspace: Path | None = None,
        issue_text: str = "",
    ) -> CommandResult:
        if not opt_in:
            return self._result("generate_patch_plan_opt_in", "IDE_COMMAND_BLOCKED_NOT_OPTED_IN")
        if config is None:
            return self._result("generate_patch_plan_opt_in", "IDE_COMMAND_BLOCKED_NO_MODEL")
        # Real patch generation. This used to return {"mode": "quarantine_only"}
        # -- no patch, no verification -- while the UI described it as
        # BLOCKED_PENDING_HUMAN_APPROVAL, which read as a working capability
        # held back for safety rather than as unbuilt. Ryan: "so unblock it. i
        # dont understand why its gated?"
        #
        # PatchPipeline (codebase_explorer) genuinely locates the bug, generates
        # a patch, validates it against the oracle, and reverts on failure. The
        # one thing it does NOT do is leave your source alone on success -- it
        # writes the fix in place. So here we snapshot the target files, let it
        # run, capture what it produced, and restore the snapshot. The result is
        # a PROPOSAL, and the only path to disk stays the Review queue's
        # human-approved apply_staged_diff (which also enforces the workspace
        # boundary). One source-mutation path, not two.
        if workspace is None or not Path(workspace).is_dir():
            return self._result(
                "generate_patch_plan_opt_in",
                "IDE_COMMAND_OK",
                payload={"proposed": [], "note": "no workspace"},
            )
        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            from codebase_explorer import CodebaseExplorer  # noqa: PLC0415
        except Exception as e:
            return self._result(
                "generate_patch_plan_opt_in",
                "IDE_COMMAND_OK",
                payload={"proposed": [], "note": f"engine unavailable: {e}"},
            )

        ws = Path(workspace)
        before: dict[Path, str] = {}

        def _snapshot(paths):
            for f in paths:
                try:
                    before[f] = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        try:
            explorer = CodebaseExplorer(ws)
            # Snapshot every tracked source file the pipeline could touch, so a
            # write anywhere can be undone. Cheap next to running a model.
            candidates = [
                f
                for f in ws.rglob("*")
                if f.is_file()
                and f.suffix in {".py", ".rs", ".go", ".ts", ".tsx", ".js"}
                and not any(
                    part.startswith(".")
                    or part in {"node_modules", "__pycache__", "target", "dist"}
                    for part in f.parts
                )
            ]
            _snapshot(candidates)
            result = explorer.fix(issue_text or "fix the failing tests")
        except Exception as e:
            return self._result(
                "generate_patch_plan_opt_in",
                "IDE_COMMAND_OK",
                payload={"proposed": [], "note": f"patch error: {e}"},
            )

        proposed = []
        try:
            for f, original in before.items():
                try:
                    now = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if now != original:
                    proposed.append(
                        {
                            "path": str(f),
                            "original_content": original,
                            "proposed_content": now,
                        }
                    )
        finally:
            # Always restore. A proposal must never be a silent apply, and this
            # runs even if the diff-collection above raises.
            for f, original in before.items():
                try:
                    if f.read_text(encoding="utf-8", errors="replace") != original:
                        f.write_text(original, encoding="utf-8")
                except Exception:
                    pass

        return self._result(
            "generate_patch_plan_opt_in",
            "IDE_COMMAND_TEMP_ONLY",
            payload={
                "proposed": proposed,
                "n_files": len(proposed),
                "solved": bool(getattr(result, "success", False)),
                "diff": getattr(result, "patch_diff", "") or "",
                "source_mutation": False,
                "note": (
                    "no change produced"
                    if not proposed
                    else f"{len(proposed)} file(s) proposed -- approve in Review to apply"
                ),
            },
        )

    def _verify_temp_patch(self, workspace: Path | None = None) -> CommandResult:
        """Real oracle verdict for the workspace, not a mode string.

        This returned {"mode": "temp_only"} -- no verdict at all -- while the
        UI presented the step as a verification gate. repair_workspace IS the
        canonical oracle run and is already used by repair_diagnose, so this
        reports what it actually finds.
        """
        if workspace is None or not Path(workspace).is_dir():
            # Status stays TEMP_ONLY even with nothing to verify: the lock on
            # this verb asserts it never implies source mutation, which is
            # independent of whether a verdict was produced.
            return self._result(
                "verify_temp_patch",
                "IDE_COMMAND_TEMP_ONLY",
                payload={"verified": None, "note": "no workspace"},
            )
        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            import determinex_repair as _r

            res = _r.repair_workspace(Path(workspace))
        except Exception as e:
            return self._result(
                "verify_temp_patch",
                "IDE_COMMAND_TEMP_ONLY",
                payload={"verified": None, "note": f"verify error: {e}"},
            )
        return self._result(
            "verify_temp_patch",
            "IDE_COMMAND_TEMP_ONLY",
            payload={
                "verified": bool(res.healthy),
                "n_failures": res.n_failures,
                "oracle": res.oracle,
                "language": res.language,
                "source_mutation": False,
                "note": (
                    "oracle passes" if res.healthy else f"{res.n_failures} failing check(s) remain"
                ),
            },
        )

    def _repair_state(self) -> CommandResult:
        return self._result(
            "get_repair_state",
            "IDE_COMMAND_OK",
            payload={
                "source_mutation": "BLOCKED_PENDING_HUMAN_APPROVAL",
                "training_eligible": False,
            },
        )

    def _source_apply_dry_run(self, workspace: Path | None) -> CommandResult:
        """Explicit source-apply dry-run check.

        CLAUDE-AUTH-006 remediation: this command used to alias
        get_repair_state. It now returns a dedicated dry-run record
        with a clear `mode: dry_run_only` payload so the verb in the
        Tauri protocol matches what actually happens.
        """
        ws = str(workspace) if workspace else ""
        return self._result(
            "source_apply_dry_run",
            "IDE_COMMAND_SOURCE_MUTATION_BLOCKED",
            payload={
                "workspace": ws,
                "mode": "dry_run_only",
                "source_apply_attempted": False,
                "source_mutation": "BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
                "training_eligible": False,
            },
            notes=(
                "source_apply_dry_run inspected the gate ladder; no real apply was attempted",
                "real source mutation requires the locked apply gate "
                "(REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001)",
            ),
        )

    # ------------------------------------------------------------------
    # Unified-product read-only view-model commands.
    # DETERMINEX_TAURI_UNIFIED_PRODUCT_COMMAND_SURFACE_LOCK_001 (rung 1).
    #
    # Each handler returns a deterministic JSON-serializable
    # snapshot of its locked view-model record. NONE of these
    # mutate source, grant approval, write training rows, or call
    # the network. Source-mutation and training stay False on every
    # CommandResult; the dispatcher emits IDE_COMMAND_OK only.
    # ------------------------------------------------------------------
    def _unified_navigation_model(self) -> CommandResult:
        from . import unified_product_navigation_model as _mod

        rec = _mod.build_record()
        return self._result(
            "get_unified_product_navigation_model",
            "IDE_COMMAND_OK",
            payload=rec.to_dict(),
            notes=("read-only view-model; no authorization granted",),
        )

    def _idea_lab_workflow_state(self) -> CommandResult:
        from . import idea_lab_workflow as _mod

        # Surface the canonical inventory (flow steps + UI states).
        # The actual runtime state is supplied by the operator session
        # at evaluate-time; this command returns the *capability*
        # description, not a runtime gate decision.
        return self._result(
            "get_idea_lab_workflow_state",
            "IDE_COMMAND_OK",
            payload={
                "flow_steps": list(_mod.canonical_flow_steps()),
                "ui_states": list(_mod.canonical_states()),
                "build_it_disabled_until_support_check": True,
                "working_label_disabled_until_evidence": True,
                "unsupported_features_visible_required": True,
                "external_caveats_visible_required": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "Idea Lab workflow definition; no source mutation",
                "Build It disabled until support check; Working requires build+test+smoke evidence",
            ),
        )

    def _repo_clinic_workflow_state(self) -> CommandResult:
        from . import repo_clinic_workflow as _mod

        return self._result(
            "get_repo_clinic_workflow_state",
            "IDE_COMMAND_OK",
            payload={
                "flow_steps": list(_mod.canonical_flow_steps()),
                "ui_states": list(_mod.canonical_states()),
                "verifier_required": True,
                "diagnosis_is_not_authorization": True,
                "admission_is_not_source_authorization": True,
                "fixed_label_requires_post_apply_verifier": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "Repo Clinic workflow definition",
                "diagnosis is not authorization; fixed label requires post-apply verifier pass",
            ),
        )

    def _maintenance_bay_workflow_state(self) -> CommandResult:
        from . import maintenance_bay_workflow as _mod

        return self._result(
            "get_maintenance_bay_workflow_state",
            "IDE_COMMAND_OK",
            payload={
                "maintenance_types": list(_mod.canonical_maintenance_types()),
                "ui_states": list(_mod.canonical_states()),
                "compatibility_verifier_required": True,
                "updated_label_requires_post_apply_verifier": True,
                "dependency_security_require_risk_visible": True,
                "advisory_status_caveated_required": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "Maintenance Bay workflow definition",
                "updated/maintained label requires post-apply verifier pass",
            ),
        )

    def _maintenance_bay_run_scan(self) -> CommandResult:
        """Live read-only security/maintenance advisory: composes the 5 EXISTING
        scripts/security/*.py scanners (secret_scan, dependency_scan, verify_lockfiles,
        license_scan, container_scan) via security_gate.run_all() -- the same canonical
        entry point CI would use. A 'blocked' gate is a finding to review; this command
        never applies an update, patches a dependency, or authorizes anything."""
        try:
            import sys as _sys

            _sec_dir = str(Path(__file__).resolve().parent.parent / "security")
            if _sec_dir not in _sys.path:
                _sys.path.insert(0, _sec_dir)
            import security_gate as _gate

            result = _gate.run_all()
        except Exception as e:
            return self._result(
                "run_maintenance_bay_scan",
                "IDE_COMMAND_OK",
                payload={"overall_passed": None, "gates": [], "scan_error": str(e)},
                notes=("scan crashed; treat as an unrun scan, not a pass",),
            )
        return self._result(
            "run_maintenance_bay_scan",
            "IDE_COMMAND_OK",
            payload=result,
            notes=(
                "advisory scan only; no update applied, no source mutation",
                "a blocked gate is a finding to review, not an automatic action",
            ),
        )

    def _query_corpus(self, query: str, mode: str) -> CommandResult:
        """Live, read-only direct query surface over the ONE canonical corpus API
        (scripts/determinex_corpus_api.py). No search/ranking/maturity logic lives
        here -- this only calls ask()/maturity_report()/timeline() and shapes the
        dataclass result into JSON. Never mutates build_knowledge.json, never
        authorizes anything; a caller still has to route through Repo Clinic /
        Idea Lab to act on anything this surfaces, same as Learning Studio."""
        try:
            import sys as _sys

            _scripts = str(Path(__file__).resolve().parent.parent)
            if _scripts not in _sys.path:
                _sys.path.insert(0, _scripts)
            import determinex_corpus_api as _corpus
        except Exception as e:
            return self._result(
                "query_corpus",
                "IDE_COMMAND_OK",
                payload={"mode": mode, "query": query, "query_error": str(e)},
                notes=("corpus module failed to import; treat as unanswered, not empty",),
            )

        try:
            if mode == "maturity":
                report = _corpus.maturity_report(topic_filter=query or None)
                payload = {"mode": mode, "query": query, **report.to_dict()}
            elif mode == "timeline":
                entries = _corpus.timeline(topic_filter=query or None)
                payload = {"mode": mode, "query": query, "entries": [e.__dict__ for e in entries]}
            else:
                if not query.strip():
                    payload = {
                        "mode": "ask",
                        "query": query,
                        "hits": [],
                        "top_hit_related": {"outbound": [], "inbound": []},
                        "warnings": [],
                    }
                else:
                    result = _corpus.ask(query)
                    payload = {"mode": "ask", **result.to_dict()}
        except Exception as e:
            return self._result(
                "query_corpus",
                "IDE_COMMAND_OK",
                payload={"mode": mode, "query": query, "query_error": str(e)},
                notes=("corpus query crashed; treat as unanswered, not empty",),
            )

        return self._result(
            "query_corpus",
            "IDE_COMMAND_OK",
            payload=payload,
            notes=(
                "read-only corpus query; no mutation, no authorization",
                "route anything actionable to Repo Clinic / Idea Lab",
            ),
        )

    def _learning_studio_workflow_state(self) -> CommandResult:
        from . import learning_studio_workflow as _mod

        return self._result(
            "get_learning_studio_workflow_state",
            "IDE_COMMAND_OK",
            payload={
                "modes": list(_mod.canonical_modes()),
                "non_authorizing": True,
                "routes_fix_suggestions_to": "repo_clinic",
                "routes_new_project_suggestions_to": "idea_lab",
                "forbidden_phrases_blocked": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "Learning Studio definition",
                "learning explains; does not authorize",
            ),
        )

    def _learning_studio_generate(
        self, mode: str, context_text: str, workspace: Path | None
    ) -> CommandResult:
        """Rung 7: produce a REAL LearningStudioOutput grounded in the verified corpus (and, for
        explain_this_repo/explain_this_file, the real workspace), then run it through the SAME
        non-authorizing gate (learning_studio_workflow.evaluate()) the workflow-state command
        already enforces. A generator bug that somehow produced a false-success claim would be
        caught here, not trusted through."""
        from . import learning_studio_content as _content
        from . import learning_studio_workflow as _workflow

        ctx: dict[str, str] = {"text": context_text}
        if workspace is not None:
            ctx["workspace"] = str(workspace)
            ctx["path"] = str(workspace)
        try:
            output = _content.generate(mode, ctx)
        except Exception as e:
            return self._result(
                "generate_learning_studio_content",
                "IDE_COMMAND_OK",
                payload={
                    "decision": "LEARNING_STUDIO_GENERATION_ERROR",
                    "output": None,
                    "error": str(e),
                },
            )
        record = _workflow.evaluate(output)
        return self._result(
            "generate_learning_studio_content",
            "IDE_COMMAND_OK",
            payload=record.to_dict(),
            notes=(
                "teaching output only; non-authorizing gate enforced",
                "grounded in the verified corpus / real files; no fabrication",
            ),
        )

    def _proof_operator_center_state(self) -> CommandResult:
        from . import proof_operator_center_viewmodel as _mod

        return self._result(
            "get_proof_operator_center_state",
            "IDE_COMMAND_OK",
            payload={
                "required_sections": list(_mod.canonical_sections()),
                "read_only_surface": True,
                "operator_queue_request_is_not_grant": True,
                "programbench_provenance_read_only_from_claude_lane": True,
                "training_status_always_reads_false": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "Proof / Operator Center view-model definition",
                "read-only and non-authorizing",
            ),
        )

    def _user_level_teaching_windows(self) -> CommandResult:
        from . import user_levels_and_teaching_windows as _mod

        # Surface the level names only; full per-level profiles are
        # rendered by the panel via a build_record() call.
        return self._result(
            "get_user_level_teaching_windows",
            "IDE_COMMAND_OK",
            payload={
                "user_levels": list(_mod.USER_LEVELS),
                "beginner_does_not_hide_proof": True,
                "power_user_does_not_loosen_gates": True,
                "teaching_window_explains_blocked_reason": True,
                "training_stays_false_at_every_level": True,
                "source_mutation_authorized": False,
                "training_eligible": False,
            },
            notes=(
                "user-level / teaching-window definition",
                "no level loosens authority gates",
            ),
        )

    def _idea_lab_verified_demo_status(self) -> CommandResult:
        from . import idea_lab_verified_demo_status as _mod

        status = _mod.load()
        return self._result(
            "get_idea_lab_verified_demo_status",
            "IDE_COMMAND_OK",
            payload=status.to_dict(),
            notes=(
                "scoped to the fixture Idea Lab Python CLI demo only",
                "no broadening of claim; training stays false; no source mutation",
            ),
        )

    def _repo_clinic_verified_demo_status(self) -> CommandResult:
        from . import repo_clinic_verified_demo_status as _mod

        status = _mod.load()
        return self._result(
            "get_repo_clinic_verified_demo_status",
            "IDE_COMMAND_OK",
            payload=status.to_dict(),
            notes=(
                "scoped to the fixture Repo Clinic Python repair demo only",
                "no real user repo mutation; no broadening of claim; "
                "training stays false; no source mutation",
            ),
        )

    def _maintenance_bay_verified_demo_status(self) -> CommandResult:
        from . import maintenance_bay_verified_demo_status as _mod

        status = _mod.load()
        return self._result(
            "get_maintenance_bay_verified_demo_status",
            "IDE_COMMAND_OK",
            payload=status.to_dict(),
            notes=(
                "scoped to the fixture Maintenance Bay dry-run/update demo only",
                "no real user repo mutation; no broadening of claim; "
                "training stays false; no source mutation; "
                "updated/maintained label gated on compatibility verifier + "
                "post-change tests",
            ),
        )

    def _learning_studio_verified_demo_status(self) -> CommandResult:
        from . import learning_studio_verified_demo_status as _mod

        status = _mod.load()
        return self._result(
            "get_learning_studio_verified_demo_status",
            "IDE_COMMAND_OK",
            payload=status.to_dict(),
            notes=(
                "scoped to the fixture Learning Studio teaching splash demo only",
                "teaching outputs are non-authorizing by construction",
                "explanations are grounded in existing verified Repo Clinic + "
                "Maintenance Bay evidence; no broadening of claim",
                "source mutation, approval, training, release all remain False",
            ),
        )

    def _proof_operator_center_milestone_dashboard_status(self) -> CommandResult:
        from . import proof_operator_center_milestone_dashboard_status as _mod

        status = _mod.load()
        return self._result(
            "get_proof_operator_center_milestone_dashboard_status",
            "IDE_COMMAND_OK",
            payload=status.to_dict(),
            notes=(
                "Proof / Operator Center milestone dashboard DISPLAYS "
                "authority; it does not grant authority",
                "source mutation, approval, proof-execution, training, "
                "release, broad claims all remain False",
                "Scale-to-100 remains roadmap draft, not current C&T lock",
                "Columbia House Tracker remains pending, not built",
                "Full Cathedral roadmap is audit input only, not validated by this binding",
            ),
        )

    def _unified_splash_demo_spec(self) -> CommandResult:
        from repair import unified_product_splash_demo_spec as _mod

        rec = _mod.build_record()
        payload = rec.to_dict()
        # Add the required marketing strings explicitly so the panel
        # can render them without re-importing the constants module.
        payload["required_tagline"] = _mod.REQUIRED_TAGLINE
        payload["required_phrases"] = list(_mod.REQUIRED_PHRASES)
        payload["required_negative_caveats"] = list(_mod.REQUIRED_NEGATIVE_CAVEATS)
        return self._result(
            "get_unified_splash_demo_spec",
            "IDE_COMMAND_OK",
            payload=payload,
            notes=(
                "splash demo spec; declarative, fixture-only",
                "no network, no Docker, no ProgramBench, no real user repo",
            ),
        )

    def _approval_packet(
        self,
        workspace: Path | None,
        unified_diff: str,
        files_changed: tuple[str, ...],
        verifier_status: str,
    ) -> CommandResult:
        ws = str(workspace) if workspace else ""
        packet = build_packet(
            trace_id="ide-trace",
            workspace_identity=ws,
            unified_diff=unified_diff,
            files_changed=files_changed,
            verifier_status=verifier_status or "PATCH_VERIFIER_PASSED_TEMP_ONLY",
        )
        # Approval packet command never authorizes mutation.
        return self._result(
            "get_human_approval_packet",
            "IDE_COMMAND_SOURCE_MUTATION_BLOCKED",
            payload=packet.to_dict(),
            notes=("packet returned; source mutation remains BLOCKED",),
        )

    @staticmethod
    def _result(
        command: str,
        status: str,
        *,
        payload: Mapping[str, object] | None = None,
        evidence_refs: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
    ) -> CommandResult:
        return CommandResult(
            command=command,
            status=status,
            payload=dict(payload or {}),
            evidence_refs=evidence_refs,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=notes,
        )


__all__ = [
    "IDEBackendCommandSurface",
    "CommandResult",
    "IDE_BACKEND_COMMAND_STATUS_TOKENS",
    "commands",
]
