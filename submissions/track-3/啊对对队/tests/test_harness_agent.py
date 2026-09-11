import unittest

from parcel_sorter.harness_agent import (
    AgentIdentity,
    HarnessAgentConfig,
    RuleBasedFailureAnalyst,
    authorize_agent_checkpoint_promotion,
    build_failure_packet,
    quarantine_correction,
    plan_task_with_agent,
    sha256_json,
    training_admission_gate,
    validate_failure_packet,
    validate_task_directive,
    verify_replayed_correction,
)


def _identity(agent_id: str, role: str) -> AgentIdentity:
    return AgentIdentity(
        agent_id=agent_id,
        role=role,
        provider="test",
        model=f"fake-{role}",
        version="1",
    )


def _config() -> HarnessAgentConfig:
    return HarnessAgentConfig(
        task_agent=_identity("task", "task_agent"),
        failure_analyst=_identity("analyst", "failure_analyst"),
        independent_verifier=_identity("verifier", "independent_verifier"),
    )


def _failed_run() -> dict:
    return {
        "episode_id": "parcel-17",
        "profile": "medium_carton",
        "success": False,
        "failure_stage": "lift_success",
        "terminal_reason": "suction lost before lift gate",
        "completed_stages": ["grasp_success"],
        "suction": {"max_contact_force_n": 12.4, "break_count": 1},
        "frame_count": 321,
        "rgbd_nonempty": True,
        "action_attribution": "pure_vla",
    }


def _candidate(config: HarnessAgentConfig) -> dict:
    packet = build_failure_packet(_failed_run(), source_audit_sha256="a" * 64)
    analysis = RuleBasedFailureAnalyst(config.failure_analyst).analyze(packet)
    return quarantine_correction(
        packet, analysis, analyst=config.failure_analyst
    )


def _successful_replay(candidate: dict) -> dict:
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": sha256_json(candidate),
        "status": "passed",
        "success": True,
        "action_attribution": "autonomous_agent_vla",
        "expert_fallback_used": False,
        "action_replacement_used": False,
        "frame_count": 412,
        "rgbd_nonempty": True,
        "grasp_success": True,
        "lift_success": True,
        "transport_success": True,
        "placement_success": True,
        "correct_destination_success": True,
        "release_success": True,
        "peak_forces_n": {
            "left_suction": 14.2,
            "right_cradle": 18.7,
            "parcel_contact": 22.1,
        },
        "dataset_saved": True,
        "dataset_storage_format": "video",
        "dataset_bytes": 7_800_000,
        "video_modalities": [
            "overhead_rgb",
            "overhead_depth",
            "wrist_left_rgb",
            "wrist_left_depth",
            "wrist_right_rgb",
            "wrist_right_depth",
        ],
        "pyav_audit_status": "passed",
        "image_parquet_used": False,
        "torchcodec_used": False,
    }


class HarnessAgentAuthorityTests(unittest.TestCase):
    def test_agent_identities_must_be_separate(self) -> None:
        with self.assertRaisesRegex(ValueError, "identities must be distinct"):
            HarnessAgentConfig(
                task_agent=_identity("shared", "task_agent"),
                failure_analyst=_identity("shared", "failure_analyst"),
                independent_verifier=_identity("verifier", "independent_verifier"),
            )

    def test_task_agent_can_only_emit_high_level_directives(self) -> None:
        config = _config()
        directive = validate_task_directive(
            {
                "schema_version": 1,
                "protocol": "parcel-harness-task-directive-v1",
                "directive_id": "directive-1",
                "agent_id": "task",
                "goal": "sort the parcel to lane B",
                "grasp_mode": "auto",
                "recovery_strategy": "reobserve",
                "memory_refs": ["episode:parcel-17"],
            },
            task_agent=config.task_agent,
        )
        self.assertEqual(directive["authority"], "high_level_only")
        unsafe = dict(directive)
        unsafe["raw_action"] = [0.0] * 19
        with self.assertRaisesRegex(ValueError, "forbidden Agent authority"):
            validate_task_directive(unsafe, task_agent=config.task_agent)

    def test_config_cannot_grant_agent_safety_override(self) -> None:
        config = _config()
        payload = {
            "protocol": "parcel-harness-agent-config-v1",
            "task_agent": config.task_agent.to_dict(),
            "failure_analyst": config.failure_analyst.to_dict(),
            "independent_verifier": config.independent_verifier.to_dict(),
            "control_authority": {
                "task_agent_hz": [0.1, 1.0],
                "vla_executor_hz": [3.0, 10.0],
                "servo_hz": 240,
                "agent_may_emit_servo_actions": False,
                "agent_may_override_safety": True,
                "agent_may_activate_checkpoint": False,
            },
        }
        with self.assertRaisesRegex(ValueError, "explicitly disable"):
            HarnessAgentConfig.from_dict(payload)

    def test_task_adapter_receives_only_declared_non_privileged_observation(self) -> None:
        config = _config()

        class FakePlanner:
            identity = config.task_agent

            def plan(self, observation: dict) -> dict:
                return {
                    "schema_version": 1,
                    "protocol": "parcel-harness-task-directive-v1",
                    "directive_id": "directive-2",
                    "agent_id": self.identity.agent_id,
                    "goal": observation["goal"],
                    "grasp_mode": "side",
                    "recovery_strategy": "hold",
                    "memory_refs": observation["memory_refs"],
                }

        observation = {
            "schema_version": 1,
            "protocol": "parcel-harness-task-observation-v1",
            "episode_id": "parcel-21",
            "goal": "sort to lane C",
            "stage": "approach",
            "available_grasp_modes": ["top", "side", "cradle"],
            "perception_summary": {"parcel_class": "flat_mailer"},
            "force_margin_n": 35.0,
            "memory_refs": [],
        }
        directive = plan_task_with_agent(
            observation, planner=FakePlanner(), config=config
        )
        self.assertEqual(directive["grasp_mode"], "side")
        self.assertEqual(len(directive["task_observation_sha256"]), 64)

    def test_privileged_simulator_state_is_rejected(self) -> None:
        run = _failed_run()
        run["parcel_pose"] = [0.4, 0.0, 0.1]
        packet = build_failure_packet(run, source_audit_sha256="a" * 64)
        self.assertNotIn("parcel_pose", str(packet))
        packet["parcel_pose"] = run["parcel_pose"]
        with self.assertRaisesRegex(ValueError, "privileged fields"):
            validate_failure_packet(packet)


class HarnessAgentAdmissionTests(unittest.TestCase):
    def test_proposal_starts_quarantined_and_not_executable(self) -> None:
        candidate = _candidate(_config())
        self.assertEqual(candidate["status"], "quarantined_unverified")
        self.assertFalse(candidate["executable"])
        self.assertFalse(candidate["positive_training_eligible"])

    def test_proposer_cannot_verify_own_candidate(self) -> None:
        config = _config()
        candidate = _candidate(config)
        replay = _successful_replay(candidate)
        same_agent = _identity("analyst", "independent_verifier")
        with self.assertRaisesRegex(ValueError, "identities must be distinct"):
            HarnessAgentConfig(
                task_agent=config.task_agent,
                failure_analyst=config.failure_analyst,
                independent_verifier=same_agent,
            )
        with self.assertRaisesRegex(ValueError, "must be distinct"):
            verify_replayed_correction(
                candidate, replay, verifier=same_agent, config=config
            )

    def test_expert_fallback_cannot_be_counted_as_pure_vla(self) -> None:
        config = _config()
        candidate = _candidate(config)
        replay = _successful_replay(candidate)
        replay["expert_fallback_used"] = True
        verification = verify_replayed_correction(
            candidate,
            replay,
            verifier=config.independent_verifier,
            config=config,
        )
        admission = training_admission_gate(candidate, verification)
        self.assertFalse(verification["verified"])
        self.assertIn("no_expert_fallback", verification["rejection_reasons"])
        self.assertFalse(admission["admitted"])

    def test_missing_storage_gate_stays_quarantined(self) -> None:
        config = _config()
        candidate = _candidate(config)
        replay = _successful_replay(candidate)
        replay["dataset_storage_format"] = "image_parquet"
        replay["image_parquet_used"] = True
        verification = verify_replayed_correction(
            candidate,
            replay,
            verifier=config.independent_verifier,
            config=config,
        )
        self.assertFalse(training_admission_gate(candidate, verification)["admitted"])

    def test_forged_verification_boolean_is_not_enough_for_admission(self) -> None:
        config = _config()
        candidate = _candidate(config)
        verification = verify_replayed_correction(
            candidate,
            _successful_replay(candidate),
            verifier=config.independent_verifier,
            config=config,
        )
        verification["checks"]["task_success"] = False
        self.assertFalse(training_admission_gate(candidate, verification)["admitted"])

    def test_independent_success_is_admitted(self) -> None:
        config = _config()
        candidate = _candidate(config)
        verification = verify_replayed_correction(
            candidate,
            _successful_replay(candidate),
            verifier=config.independent_verifier,
            config=config,
        )
        admission = training_admission_gate(candidate, verification)
        self.assertTrue(verification["verified"])
        self.assertTrue(admission["admitted"])
        self.assertEqual(admission["training_label"], "verified_positive_correction")

    def test_agent_cannot_bypass_checkpoint_promotion_gate(self) -> None:
        config = _config()
        candidate = _candidate(config)
        verification = verify_replayed_correction(
            candidate,
            _successful_replay(candidate),
            verifier=config.independent_verifier,
            config=config,
        )
        admission = training_admission_gate(candidate, verification)
        checkpoint_sha = "b" * 64
        rejected = authorize_agent_checkpoint_promotion(
            {
                "promoted": False,
                "pairing": {"candidate_checkpoint_sha256": checkpoint_sha},
            },
            [admission],
            candidate_checkpoint_sha256=checkpoint_sha,
        )
        self.assertFalse(rejected["authorized"])
        accepted = authorize_agent_checkpoint_promotion(
            {
                "promoted": True,
                "pairing": {"candidate_checkpoint_sha256": checkpoint_sha},
            },
            [admission],
            candidate_checkpoint_sha256=checkpoint_sha,
        )
        self.assertTrue(accepted["authorized"])
        self.assertIn("cannot activate", accepted["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
