export type ReleaseGateStatus = "passed" | "partial" | "blocked" | "deferred" | "planned";

export type ReleaseGateView = {
  gateId: string;
  title: string;
  status: ReleaseGateStatus;
  releaseReady: false;
  evidence: string[];
  exactBlocker: string;
  nextAction: string;
  runbookCommands: string[];
};

export type ReleaseGateSnapshot = {
  schemaVersion: "determinex-release-gate-status-v1";
  generatedAtUtc: string;
  productName: "Determinex";
  releaseReady: false;
  authorityGranted: false;
  collector: string;
  evidenceSnapshot: string;
  gates: ReleaseGateView[];
};

export const DETERMINEX_RELEASE_GATES: ReleaseGateSnapshot = {
  schemaVersion: "determinex-release-gate-status-v1",
  generatedAtUtc: "2026-07-08T12:11:54Z",
  productName: "Determinex",
  releaseReady: false,
  authorityGranted: false,
  collector: "scripts/release/determinex_release_gates.py",
  evidenceSnapshot: "assurance/evidence/determinex_release_gate_status/release_gates_20260707.json",
  gates: [
    {
      gateId: "sbom",
      title: "SBOM coverage",
      status: "passed",
      releaseReady: false,
      evidence: [
        "assurance/sbom/determinex-python.spdx.json",
        "assurance/sbom/determinex-python.cyclonedx.json",
        "assurance/sbom/determinex-npm.cyclonedx.json",
      ],
      exactBlocker: "",
      nextAction: "Keep SBOMs regenerated for release artifacts and clean-host packets.",
      runbookCommands: [
        ".venv\\Scripts\\python.exe scripts\\security\\generate_sbom.py",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "installer",
      title: "Installer/package artifact matrix",
      status: "partial",
      releaseReady: false,
      evidence: [
        "assurance/evidence/installer_install_launch_uninstall_release_signoff_wave_001/public_distribution_go_no_go_20260602.json",
        "assurance/evidence/installer_release_packet_hardening/run_20260629.INSTALLER_RELEASE_PACKET_HARDENED_UNSIGNED.json",
        "assurance/evidence/determinex_download_bundle_20260707/download_manifest.json",
      ],
      exactBlocker: "windows_msi_not_bundled; linux_packages_not_bundled",
      nextAction:
        "Build the full package matrix: Windows NSIS, Windows MSI, and Linux package artifact(s), then refresh the download bundle.",
      runbookCommands: [
        "powershell -ExecutionPolicy Bypass -File scripts\\release\\build_release_package.ps1 -SkipDependencyRestore -SkipSbom -SkipSidecar -CargoTargetDir .tmp\\determinex-cargo-target -PackageDownloadBundle -TauriBundleTarget all -DownloadBundleOutputDir .tmp\\determinex-download-bundles",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "windows_trust",
      title: "Windows signing and SmartScreen trust",
      status: "deferred",
      releaseReady: false,
      evidence: [],
      exactBlocker: "No Windows signing and SmartScreen trust packet was found.",
      nextAction:
        "Sign the Windows installer, verify Authenticode and timestamp status, then run SmartScreen trust verification on the final artifact.",
      runbookCommands: [
        "powershell Get-AuthenticodeSignature <installer.exe>",
        "powershell -ExecutionPolicy Bypass -File scripts\\release\\build_release_package.ps1 -PackageDownloadBundle",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "legal_public_distribution",
      title: "Legal/IP public distribution packet",
      status: "partial",
      releaseReady: false,
      evidence: [
        "LICENSE",
        "pyproject.toml",
        "frontend/package.json",
        "frontend/src-tauri/Cargo.toml",
        "frontend/vscode-extension/package.json",
      ],
      exactBlocker:
        "AGPLv3 source license evidence is present, but public repo secret scan, repo scrub, model notices, and third-party notices have not been recorded in the legal public distribution packet.",
      nextAction:
        "Complete legal/IP review, license inventory, model notices, secret scan, and public repo scrub before public distribution.",
      runbookCommands: [
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
        "powershell # write assurance\\evidence\\public_distribution\\legal_public_distribution_YYYYMMDD.json after review",
      ],
    },
    {
      gateId: "windows_msi",
      title: "Windows MSI/WiX distribution",
      status: "blocked",
      releaseReady: false,
      evidence: [],
      exactBlocker: "No Windows MSI/WiX evidence packet was found.",
      nextAction:
        "Build an MSI with WiX, verify the MSI hash, run an installer smoke, and record the MSI evidence packet.",
      runbookCommands: [
        "powershell -ExecutionPolicy Bypass -File scripts\\release\\build_release_package.ps1 -TauriBundleTarget msi",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "linux_packages",
      title: "Linux package distribution",
      status: "blocked",
      releaseReady: false,
      evidence: ["assurance/evidence/determinex_download_bundle_20260707/download_manifest.json"],
      exactBlocker: "No Linux package artifact was found in the latest download bundle manifest.",
      nextAction:
        "Build Linux package artifact(s) on a Linux host and refresh the download bundle manifest.",
      runbookCommands: [
        "cd frontend; npm run tauri -- build --bundles appimage,deb,rpm",
        ".venv\\Scripts\\python.exe scripts\\release\\package_download_bundle.py --installer-dir frontend/src-tauri/target/release/bundle --output-dir .tmp/determinex-download-bundles --evidence-dir assurance/evidence/determinex_download_bundle_20260707",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "clean_host",
      title: "Clean-host install proof",
      status: "blocked",
      releaseReady: false,
      evidence: [
        "assurance/evidence/clean_host_fresh_install_runner_execution/run_20260531.CLEAN_HOST_FRESH_INSTALL_RUNNER_EXECUTION_BLOCKED_RUNNER_NOT_EXECUTED.json",
        "assurance/evidence/full_release_closure/clean_host_runner_preflight_20260708.json",
      ],
      exactBlocker:
        "Current runner cannot access Docker Desktop state; rerun the clean-host probe outside the sandbox.",
      nextAction:
        "Rerun the clean-host probe outside the sandbox, then execute the install/launch/uninstall transcript.",
      runbookCommands: [
        "docker info",
        ".venv\\Scripts\\python.exe scripts\\release\\clean_host_install_transcript.py --template-output assurance\\evidence\\full_release_closure\\clean_host_install_transcript_YYYYMMDD.json",
        ".venv\\Scripts\\python.exe scripts\\release\\full_release_closure.py --output assurance\\evidence\\full_release_closure\\run_20260707.json",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "first_e2e",
      title: "First end-to-end user workflow",
      status: "passed",
      releaseReady: false,
      evidence: [
        "assurance/evidence/first_end_to_end_user_workflow/result.json",
        "assurance/evidence/first_end_to_end_user_workflow/builder_health_probe_latest.json",
        "assurance/evidence/first_end_to_end_user_workflow/rerun_after_builder_health_latest.json",
      ],
      exactBlocker: "",
      nextAction: "Keep the passing first-E2E transcript current with the release commit.",
      runbookCommands: [
        ".venv\\Scripts\\python.exe scripts\\hive\\builder_health_probe.py --model determinex/engineer --output assurance\\evidence\\first_end_to_end_user_workflow\\builder_health_probe_latest.json",
        ".venv\\Scripts\\python.exe scripts\\determinex_hive.py run-session --session 5a502c3d-ce8b-43ef-a7c2-c6b3aab998f4",
      ],
    },
    {
      gateId: "programbench_200",
      title: "ProgramBench 200/200 strict locks",
      status: "deferred",
      releaseReady: false,
      evidence: ["corpus/programbench/eval_index.json"],
      exactBlocker:
        "ProgramBench strict official locks are 0/200; current non-authorizing status mix: native_rebuild=60, factory_accepted=54, board_cache_only=35, ceiling_confirmed=13, ceiling_certified=13, gated:reject=8.",
      nextAction:
        "Continue the official ProgramBench lock campaign; do not treat native rebuild, factory accepted, ceiling, or cache rows as strict locks.",
      runbookCommands: [
        ".venv\\Scripts\\python.exe scripts\\pb_doc_count_check.py --verbose",
        ".venv\\Scripts\\python.exe scripts\\pb_board_guard.py --guard",
        ".venv\\Scripts\\python.exe scripts\\pb_override_scan.py --guard",
      ],
    },
    {
      gateId: "swebench_fresh",
      title: "Fresh SWE-bench publication reruns",
      status: "deferred",
      releaseReady: false,
      evidence: [],
      exactBlocker: "No fresh official SWE-bench privacy-mode rerun packet was found.",
      nextAction:
        "Run fresh official SWE-bench Lite reruns for B-Uncloaked, RegionControl, and Cloaked, then record a publication evidence packet.",
      runbookCommands: [
        "python -m swebench.harness.run_evaluation --dataset_name princeton-nlp/SWE-bench_Lite --split test",
        ".venv\\Scripts\\python.exe scripts\\verified_task\\swebench_result_ingest.py --report <report.json> --predictions <predictions.jsonl>",
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "extension_compat",
      title: "VS Code/Open VSX compatibility",
      status: "deferred",
      releaseReady: false,
      evidence: [
        "frontend/vscode-extension",
        "docs/release/DETERMINEX_EXTENSION_COMPATIBILITY_CONTRACT.md",
      ],
      exactBlocker:
        "Extension compatibility contract exists, but runtime compatibility packet has not passed.",
      nextAction:
        "Run VSIX import, Open VSX metadata, activation-event, and sandbox permission smokes against the contract.",
      runbookCommands: [
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
    {
      gateId: "internal_rename",
      title: "Internal Determinex rename",
      status: "deferred",
      releaseReady: false,
      evidence: ["PROJECT.md", "docs/release/DETERMINEX_INTERNAL_RENAME_MIGRATION.md"],
      exactBlocker:
        "Legacy determinex_* and DETERMINEX_* implementation identifiers remain by project contract.",
      nextAction:
        "Execute the internal rename migration with compatibility aliases and migration tests.",
      runbookCommands: [
        'rg "determinex_|DETERMINEX_"',
        ".venv\\Scripts\\python.exe scripts\\release\\determinex_release_gates.py --output assurance\\evidence\\determinex_release_gate_status\\release_gates_20260707.json",
      ],
    },
  ],
};

// Raw shape of assurance/evidence/determinex_release_gate_status/release_gates_*.json
// (snake_case, written by scripts/release/determinex_release_gates.py).
type RawReleaseGateSnapshot = {
  schema_version: string;
  generated_at_utc: string;
  product_name: string;
  release_ready: boolean;
  authority_granted: boolean;
  gates: {
    gate_id: string;
    title: string;
    status: ReleaseGateStatus;
    release_ready: boolean;
    evidence: string[];
    exact_blocker: string;
    next_action: string;
    runbook_commands: string[];
  }[];
};

function mapRawSnapshot(raw: RawReleaseGateSnapshot): ReleaseGateSnapshot {
  return {
    schemaVersion: "determinex-release-gate-status-v1",
    generatedAtUtc: raw.generated_at_utc,
    productName: "Determinex",
    releaseReady: false,
    authorityGranted: false,
    collector: "scripts/release/determinex_release_gates.py",
    evidenceSnapshot: "assurance/evidence/determinex_release_gate_status/ (live)",
    gates: raw.gates.map((gate) => ({
      gateId: gate.gate_id,
      title: gate.title,
      status: gate.status,
      releaseReady: false,
      evidence: gate.evidence,
      exactBlocker: gate.exact_blocker,
      nextAction: gate.next_action,
      runbookCommands: gate.runbook_commands,
    })),
  };
}

/**
 * Reads the live release-gate evidence collector output via Tauri, so gate
 * status reflects the current repo instead of a hand-baked snapshot that goes
 * stale within days (see CLAUDE.md "Board staleness protocol"). Returns null
 * in browser/dev mode or on any read failure -- callers must fall back to
 * DETERMINEX_RELEASE_GATES in that case.
 */
export async function fetchLiveReleaseGateStatus(): Promise<ReleaseGateSnapshot | null> {
  if (typeof window === "undefined") return null;
  const internals = (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  if (!internals) return null; // browser/test mode -- never attempt the IPC call
  try {
    const { invokeSafe } = await import("@/lib/api");
    const raw = await invokeSafe<RawReleaseGateSnapshot>("get_release_gate_status");
    return raw ? mapRawSnapshot(raw) : null;
  } catch {
    return null;
  }
}

export function releaseGateStatusLabel(status: ReleaseGateStatus): string {
  switch (status) {
    case "passed":
      return "Passed";
    case "partial":
      return "Partial";
    case "blocked":
      return "Blocked";
    case "deferred":
      return "Deferred";
    case "planned":
      return "Planned";
  }
}
