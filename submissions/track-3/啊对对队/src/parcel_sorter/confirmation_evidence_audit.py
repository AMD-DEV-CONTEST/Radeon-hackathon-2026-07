"""Independent structural audit for a completed V5 confirmation result."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


TERMINAL_DECISIONS = frozenset({"confirmation_passed", "confirmation_failed"})


def expected_confirmation_keys(
    protocol: Mapping[str, Any],
) -> tuple[tuple[str, int], ...]:
    """Extract the exact confirmation population from the frozen split tables."""

    keys: list[tuple[str, int]] = []
    for split in protocol.get("splits", ()):
        if not isinstance(split, Mapping) or str(split.get("name")) != "confirmation":
            continue
        profile = str(split["profile_id"])
        keys.extend((profile, int(episode)) for episode in split["episode_ids"])
    if not keys:
        raise ValueError("confirmation protocol contains no confirmation split keys")
    if len(set(keys)) != len(keys):
        raise ValueError("confirmation protocol repeats a profile/episode key")
    expected_groups = int(protocol["population"]["expected_groups"])
    if len(keys) != expected_groups:
        raise ValueError("confirmation split keys differ from expected_groups")
    return tuple(keys)


def audit_confirmation_evidence(
    protocol: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dataset: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit population identity and terminal claim boundaries without re-selection."""

    expected_keys = expected_confirmation_keys(protocol)
    expected_set = set(expected_keys)
    expected_profiles = sorted({profile for profile, _ in expected_keys})
    episodes_per_profile = int(protocol["population"]["episodes_per_profile"])
    errors: list[str] = []

    platform = protocol.get("platform")
    if not isinstance(platform, Mapping):
        platform = {}
        errors.append("protocol_platform_missing")
    if str(platform.get("backend")) != "rocm":
        errors.append("protocol_backend_mismatch")
    if str(platform.get("device")) != "cuda:0":
        errors.append("protocol_device_mismatch")
    if platform.get("single_gpu") is not True or int(platform.get("gpu_count", -1)) != 1:
        errors.append("protocol_single_gpu_mismatch")

    manifest_rows = manifest.get("runs")
    if not isinstance(manifest_rows, Sequence) or isinstance(manifest_rows, (str, bytes)):
        manifest_rows = ()
        errors.append("manifest_runs_missing")
    observed_keys: list[tuple[str, int]] = []
    for row in manifest_rows:
        if not isinstance(row, Mapping):
            errors.append("manifest_run_malformed")
            continue
        try:
            observed_keys.append((str(row["profile"]), int(row["episode"])))
        except (KeyError, TypeError, ValueError):
            errors.append("manifest_run_key_malformed")
            continue
        if str(row.get("status")) not in {"complete", "reused"}:
            errors.append("manifest_run_incomplete")
        if str(row.get("source_status")) != "complete":
            errors.append("manifest_source_incomplete")
        if not str(row.get("sha256", "")):
            errors.append("manifest_source_hash_missing")

    observed_counter = Counter(observed_keys)
    if any(count != 1 for count in observed_counter.values()):
        errors.append("manifest_duplicate_key")
    if set(observed_keys) != expected_set or len(observed_keys) != len(expected_keys):
        errors.append("manifest_population_mismatch")
    if int(manifest.get("planned_episode_count", -1)) != len(expected_keys):
        errors.append("manifest_planned_count_mismatch")
    if int(manifest.get("complete_episode_count", -1)) != len(expected_keys):
        errors.append("manifest_complete_count_mismatch")
    if str(manifest.get("split")) != "confirmation":
        errors.append("manifest_split_mismatch")
    if str(manifest.get("planning_activation_policy")) != "all-boxes":
        errors.append("manifest_activation_policy_mismatch")
    if str(manifest.get("backend")) != "rocm":
        errors.append("manifest_backend_mismatch")
    if manifest.get("dry_run") is not False:
        errors.append("manifest_not_physical_run")

    manifest_sources = {
        (str(row.get("output", "")), str(row.get("sha256", "")))
        for row in manifest_rows
        if isinstance(row, Mapping)
    }
    dataset_sources = dataset.get("source_artifacts")
    if not isinstance(dataset_sources, Sequence) or isinstance(
        dataset_sources, (str, bytes)
    ):
        dataset_sources = ()
        errors.append("dataset_sources_missing")
    observed_dataset_sources: list[tuple[str, str]] = []
    for source in dataset_sources:
        if not isinstance(source, Mapping):
            errors.append("dataset_source_malformed")
            continue
        path = str(source.get("path", ""))
        digest = str(source.get("sha256", ""))
        if not path or not digest:
            errors.append("dataset_source_identity_missing")
        observed_dataset_sources.append((path, digest))
    if len(set(observed_dataset_sources)) != len(observed_dataset_sources):
        errors.append("dataset_duplicate_source")
    if (
        set(observed_dataset_sources) != manifest_sources
        or len(observed_dataset_sources) != len(expected_keys)
    ):
        errors.append("dataset_source_manifest_mismatch")

    dataset_profiles = sorted(str(value) for value in dataset.get("profiles", ()))
    if dataset_profiles != expected_profiles:
        errors.append("dataset_profiles_mismatch")
    if int(dataset.get("group_count", -1)) != len(expected_keys):
        errors.append("dataset_group_count_mismatch")
    if str(dataset.get("split")) != "confirmation":
        errors.append("dataset_split_mismatch")
    if str(dataset.get("policy")) != "veto-static":
        errors.append("dataset_policy_mismatch")

    summary = result.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
        errors.append("result_summary_missing")
    if int(summary.get("group_count", -1)) != len(expected_keys):
        errors.append("result_group_count_mismatch")
    profile_summaries = summary.get("by_profile")
    if not isinstance(profile_summaries, Mapping):
        profile_summaries = {}
        errors.append("result_profile_summaries_missing")
    if sorted(str(value) for value in profile_summaries) != expected_profiles:
        errors.append("result_profiles_mismatch")
    for profile in expected_profiles:
        row = profile_summaries.get(profile)
        if not isinstance(row, Mapping) or int(row.get("group_count", -1)) != episodes_per_profile:
            errors.append(f"result_profile_count:{profile}")

    if int(result.get("source_artifact_count", -1)) != len(expected_keys):
        errors.append("result_source_count_mismatch")
    if str(result.get("policy")) != "veto-static":
        errors.append("result_policy_mismatch")
    decision = result.get("decision")
    if not isinstance(decision, Mapping):
        decision = {}
        errors.append("decision_missing")
    decision_status = str(decision.get("status", ""))
    if decision_status not in TERMINAL_DECISIONS:
        errors.append("decision_not_terminal")
    expected_passes = decision_status == "confirmation_passed"
    if decision.get("passes") is not expected_passes:
        errors.append("decision_pass_flag_inconsistent")
    if bool(decision.get("runtime_activation_authorized")):
        errors.append("runtime_activation_boundary_violated")
    if bool(decision.get("v2_holdout_opened")):
        errors.append("holdout_boundary_violated")
    if bool(decision.get("online_parallel_probe_authorized")) != expected_passes:
        errors.append("online_authorization_inconsistent")

    profile_counts = Counter(profile for profile, _ in observed_keys)
    return {
        "schema_version": "1.0",
        "status": "evidence_valid" if not errors else "evidence_invalid",
        "expected_group_count": len(expected_keys),
        "observed_manifest_group_count": len(observed_keys),
        "expected_profiles": expected_profiles,
        "observed_profile_counts": dict(sorted(profile_counts.items())),
        "decision_status": decision_status,
        "errors": list(dict.fromkeys(errors)),
        "contract": {
            "candidate_rows_read": False,
            "policy_reselected": False,
            "decision_recomputed": False,
            "structural_and_hash_audit_only": True,
        },
    }
