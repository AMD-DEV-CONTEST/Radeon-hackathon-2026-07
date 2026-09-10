"""Exact key sets for formal calibration evidence documents."""

_SPLITS = ("calibration", "validation", "test")
_PLAN_KEYS = {
    "schema_version",
    "study_id",
    "target_cell_sha256",
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "targets",
    "split",
    "annotation_protocol_sha256",
}
_ITEM_KEYS = {
    "sample_id",
    "candidate_sha256",
    "source_family_sha256",
    "reference_family_sha256",
    "isolation_group_sha256",
    "split",
    "annotation_record_sha256",
    "provenance_record_sha256",
}
_BATCH_KEYS = {
    "sample_id",
    "cohort_sha256",
    "expected_count",
    "members",
    "isolation_group_sha256",
    "split",
    "annotation_record_sha256",
    "provenance_record_sha256",
}
_MEMBER_KEYS = {
    "member_id",
    "candidate_sha256",
    "source_family_sha256",
    "reference_family_sha256",
    "seed",
}
_OBSERVATION_KEYS = {
    "sample_id",
    "sample_binding_sha256",
    "score",
    "label_positive",
    "annotation_record_sha256",
}
_PREPARED_KEYS = {
    "schema_version",
    "target_cell_sha256",
    "study_id",
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "implementation_pin",
    "binding_pin",
    "verifier_pin",
    "preprocessor_pin",
    "targets",
    "study_plan_sha256",
    "sample_manifest_sha256",
    "annotation_protocol_sha256",
    "label_approval_receipt_sha256",
    "test_commitment_sha256",
    "sealed_test_observations_sha256",
    "test_sample_ids",
    "test_sample_bindings_sha256",
    "test_positive_count",
    "test_negative_count",
    "status",
    "reasons",
    "threshold",
    "calibration",
    "validation",
    "test_held",
}


def _pin_value(pin: object) -> dict[str, str]:
    return {
        "id": pin.id,  # type: ignore[union-attr]
        "revision": pin.revision,  # type: ignore[union-attr]
        "sha256": pin.sha256.value,  # type: ignore[union-attr]
    }


__all__ = ()
