from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import eval_ab  # noqa: E402
import recompute_ab  # noqa: E402
import seal_interrupted_arm  # noqa: E402
import summarize_ab  # noqa: E402


class EvaluationContractTest(unittest.TestCase):
    def test_portable_independent_rescore_matches_published_summary(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        run = ROOT / "runs/model-ab-heldout113-20260805-v2"
        rows = summarize_ab.load_frozen_rows(test_path)
        base, base_captured = recompute_ab.load_independently_scored_prefix(
            run / "arms/base.raw.jsonl", "base", rows
        )
        sft, sft_captured = recompute_ab.load_independently_scored_prefix(
            run / "arms/sft.raw.jsonl", "sft", rows
        )
        published = json.loads((run / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(base_captured, 171)
        self.assertEqual(sft_captured, 170)
        self.assertEqual(len(base), 170)
        self.assertEqual(len(sft), 170)
        self.assertEqual(
            summarize_ab.group_summary(base, sft),
            published["groups"]["all"]["all"],
        )

    def test_portable_independent_rescore_rejects_stored_score_drift(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        source = ROOT / "runs/model-ab-heldout113-20260805-v2/arms/base.raw.jsonl"
        rows = summarize_ab.load_frozen_rows(test_path)
        records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
        records[0]["scores"]["tool_calls_exact"] = not records[0]["scores"][
            "tool_calls_exact"
        ]

        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "base.raw.jsonl"
            tampered.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(recompute_ab.RecomputeError, "stored score drift"):
                recompute_ab.load_independently_scored_prefix(tampered, "base", rows)

    def test_portable_independent_rescore_rejects_reference_drift(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        source = ROOT / "runs/model-ab-heldout113-20260805-v2/arms/sft.raw.jsonl"
        rows = summarize_ab.load_frozen_rows(test_path)
        records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
        records[0]["reference"]["tool_calls"][0]["name"] = "tampered_tool"

        with tempfile.TemporaryDirectory() as temporary:
            tampered = Path(temporary) / "sft.raw.jsonl"
            tampered.write_text(
                "".join(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                recompute_ab.RecomputeError, "frozen Test reference mismatch"
            ):
                recompute_ab.load_independently_scored_prefix(tampered, "sft", rows)

    def test_frozen_test_inventory(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        rows = eval_ab.load_rows(test_path)
        plan = eval_ab.build_plan(rows, "base")
        tool_turns = 0
        tool_calls = 0
        promoted_tasks = 0
        for row in rows:
            promoted_tasks += row.get("metadata", {}).get("promoted_from_needs_review") is True
            for message in row["messages"]:
                calls = message.get("tool_calls") or []
                if message.get("role") == "assistant" and calls:
                    tool_turns += 1
                    tool_calls += len(calls)
        self.assertEqual(len(rows), 113)
        self.assertEqual(len(plan), 413)
        self.assertEqual(tool_turns, 300)
        self.assertEqual(tool_calls, 467)
        self.assertEqual(promoted_tasks, 80)
        self.assertEqual(test_path.stat().st_size, 3_562_357)
        self.assertEqual(
            hashlib.sha256(test_path.read_bytes()).hexdigest(),
            "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283",
        )

    def test_frozen_contracts_and_independent_scorers_align(self) -> None:
        self.assertEqual(eval_ab.FROZEN_TEST_SHA256, summarize_ab.FROZEN_TEST_SHA256)
        self.assertEqual(eval_ab.FROZEN_TEST_BYTES, summarize_ab.FROZEN_TEST_BYTES)
        self.assertEqual(eval_ab.FROZEN_TASKS, summarize_ab.FROZEN_TASKS)
        self.assertEqual(eval_ab.FROZEN_RECORDS, summarize_ab.FROZEN_RECORDS)
        self.assertNotEqual(
            eval_ab.FROZEN_ARMS["base"]["response_model"],
            eval_ab.FROZEN_ARMS["sft"]["response_model"],
        )
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        for row in eval_ab.load_rows(test_path):
            for reference in row["messages"]:
                if reference.get("role") != "assistant":
                    continue
                calls = reference.get("tool_calls") or []
                response = {
                    "content": reference.get("content"),
                    "tool_calls": calls,
                }
                finish_reason = "tool_calls" if calls else "stop"
                self.assertEqual(
                    eval_ab.score_turn(reference, response, finish_reason),
                    summarize_ab.independently_score(
                        reference, response, finish_reason
                    ),
                )

    def test_multi_call_scoring_checks_every_call(self) -> None:
        reference = {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "read", "arguments": {"path": "a"}}},
                {"function": {"name": "bash", "arguments": {"command": "true"}}},
            ],
        }
        response = {
            "tool_calls": [
                {"function": {"name": "read", "arguments": '{"path":"a"}'}},
                {"function": {"name": "bash", "arguments": '{"command":"false"}'}},
            ]
        }
        scores = eval_ab.score_turn(reference, response, "tool_calls")
        self.assertTrue(scores["tool_call_count_exact"])
        self.assertTrue(scores["tool_names_exact"])
        self.assertFalse(scores["tool_arguments_exact"])
        self.assertFalse(scores["tool_calls_exact"])

    def test_tool_call_contract_requires_finish_reason(self) -> None:
        reference = {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "read", "arguments": {"path": "a"}}}
            ],
        }
        response = {
            "tool_calls": [
                {"function": {"name": "read", "arguments": '{"path":"a"}'}}
            ]
        }
        self.assertTrue(
            eval_ab.score_turn(reference, response, "tool_calls")["tool_calls_exact"]
        )
        self.assertFalse(
            eval_ab.score_turn(reference, response, "stop")["tool_calls_exact"]
        )

    def test_final_clean_rejects_empty_or_spurious_tool_call(self) -> None:
        reference = {"role": "assistant", "content": "done"}
        self.assertFalse(
            eval_ab.score_turn(reference, {"content": ""}, "stop")["final_clean"]
        )
        self.assertFalse(
            eval_ab.score_turn(
                reference,
                {
                    "content": "done",
                    "tool_calls": [
                        {"function": {"name": "bash", "arguments": "{}"}}
                    ],
                },
                "stop",
            )["final_clean"]
        )
        self.assertTrue(
            eval_ab.score_turn(reference, {"content": "done"}, "stop")["final_clean"]
        )
        self.assertFalse(
            eval_ab.score_turn(reference, {"content": "done"}, "length")["final_clean"]
        )
        self.assertFalse(
            eval_ab.score_turn(reference, {"content": "done"}, "length")[
                "final_text_exact"
            ]
        )

    def test_to_openai_preserves_multiple_call_ids(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_a",
                        "function": {"name": "read", "arguments": {"path": "a"}},
                    },
                    {
                        "id": "call_b",
                        "function": {"name": "read", "arguments": {"path": "b"}},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "A"},
            {"role": "tool", "tool_call_id": "call_b", "content": "B"},
        ]
        converted = eval_ab.to_openai(messages)
        self.assertEqual(converted[1]["tool_call_id"], "call_a")
        self.assertEqual(converted[2]["tool_call_id"], "call_b")

    def test_to_openai_rejects_missing_tool_call_id(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_a",
                        "function": {"name": "read", "arguments": {"path": "a"}},
                    }
                ],
            },
            {"role": "tool", "content": "A"},
        ]
        with self.assertRaises(eval_ab.EvaluationError):
            eval_ab.to_openai(messages)

    def test_canonical_argument_normalization(self) -> None:
        left = eval_ab.normalize_arguments({"b": 2, "a": 1})
        right = eval_ab.normalize_arguments('{"a":1,"b":2}')
        self.assertEqual(left, right)

    def test_paired_summary_reports_task_level_outcome(self) -> None:
        def record(label: str, turn: int, tool_pass: bool) -> dict:
            is_tool = turn == 0
            return {
                "task_index": 0,
                "turn_index": turn,
                "task_id": "agent_000001",
                "key": f"{label}:0:{turn}",
                "stratum": "curated",
                "task_kind": "live_diagnostic",
                "category": "service",
                "latency_seconds": 1.0,
                "reference": {"tool_calls": [{}] if is_tool else []},
                "response": {
                    "model": label,
                    "system_fingerprint": label,
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
                "scores": {
                    "reference_kind": "tool_calls" if is_tool else "final",
                    "structured": True if is_tool else None,
                    "tool_call_count_exact": tool_pass if is_tool else None,
                    "tool_names_exact": tool_pass if is_tool else None,
                    "tool_arguments_exact": tool_pass if is_tool else None,
                    "tool_finish_reason_exact": tool_pass if is_tool else None,
                    "tool_calls_exact": tool_pass if is_tool else None,
                    "final_clean": True if not is_tool else None,
                    "final_text_exact": False if not is_tool else None,
                },
            }

        base = [record("base", 0, False), record("base", 1, True)]
        sft = [record("sft", 0, True), record("sft", 1, True)]
        summary = summarize_ab.group_summary(base, sft)
        self.assertEqual(summary["base"]["scores"]["task_all_turns_contract"]["passed"], 0)
        self.assertEqual(summary["sft"]["scores"]["task_all_turns_contract"]["passed"], 1)
        self.assertEqual(
            summary["paired"]["task_all_turns_contract"],
            {"both": 0, "sft_only": 1, "base_only": 0, "neither": 0, "total": 1},
        )

    def test_resume_requires_a_strict_plan_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "base.raw.jsonl"
            manifest = root / "base.manifest.json"
            contract = "a" * 64
            planned = ["base:0:1", "base:0:3", "base:1:1"]
            records = [
                {
                    "schema_version": eval_ab.RECORD_SCHEMA,
                    "contract_sha256": contract,
                    "key": planned[0],
                },
                {
                    "schema_version": eval_ab.RECORD_SCHEMA,
                    "contract_sha256": contract,
                    "key": planned[1],
                },
            ]
            raw.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": eval_ab.MANIFEST_SCHEMA,
                        "contract_sha256": contract,
                        "completed_records": 1,
                        "status": "INTERRUPTED",
                    }
                ),
                encoding="utf-8",
            )
            _payload, completed = eval_ab.load_resume_records(
                raw, manifest, contract, planned
            )
            self.assertEqual(completed, set(planned[:2]))

            records.reverse()
            raw.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            with self.assertRaises(eval_ab.EvaluationError):
                eval_ab.load_resume_records(raw, manifest, contract, planned)

    def test_complete_raw_drift_cannot_be_resealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "base.raw.jsonl"
            manifest = root / "base.manifest.json"
            contract = "b" * 64
            planned = ["base:0:1"]
            record = {
                "schema_version": eval_ab.RECORD_SCHEMA,
                "contract_sha256": contract,
                "key": planned[0],
            }
            raw.write_text(json.dumps(record) + "\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": eval_ab.MANIFEST_SCHEMA,
                        "contract_sha256": contract,
                        "completed_records": 1,
                        "status": "COMPLETE",
                        "raw_sha256": eval_ab.sha256_file(raw),
                    }
                ),
                encoding="utf-8",
            )
            _payload, completed = eval_ab.load_resume_records(
                raw, manifest, contract, planned
            )
            self.assertEqual(completed, set(planned))
            record["tampered"] = True
            raw.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(eval_ab.EvaluationError):
                eval_ab.load_resume_records(raw, manifest, contract, planned)

    def test_summarizer_independently_rejects_score_and_reference_drift(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        rows = summarize_ab.load_frozen_rows(test_path)
        plan = summarize_ab.build_frozen_plan(rows, "base")
        records = []
        for item in plan:
            row = rows[item["task_index"]]
            reference = row["messages"][item["turn_index"]]
            calls = reference.get("tool_calls") or []
            response_message = {
                "content": reference.get("content"),
                "tool_calls": calls,
            }
            finish_reason = "tool_calls" if calls else "stop"
            metadata = row.get("metadata") or {}
            records.append(
                {
                    **item,
                    "stratum": (
                        "promoted"
                        if metadata.get("promoted_from_needs_review") is True
                        else "curated"
                    ),
                    "task_kind": metadata.get("task_kind"),
                    "category": metadata.get("category"),
                    "failed_checks": metadata.get("failed_checks") or [],
                    "reference": {
                        "content": reference.get("content"),
                        "tool_calls": summarize_ab.normalize_tool_calls(calls),
                    },
                    "response": {
                        "message": response_message,
                        "finish_reason": finish_reason,
                        "tool_calls": summarize_ab.normalize_tool_calls(calls),
                    },
                    "scores": summarize_ab.independently_score(
                        reference, response_message, finish_reason
                    ),
                }
            )
        manifest = {
            "label": "base",
            "contract": {"plan_sha256": eval_ab.canonical_digest(plan)},
        }
        summarize_ab.validate_records_against_test(manifest, records, rows)
        first_scores = records[0]["scores"]
        score_name = (
            "tool_calls_exact"
            if first_scores["reference_kind"] == "tool_calls"
            else "final_clean"
        )
        first_scores[score_name] = not first_scores[score_name]
        with self.assertRaises(summarize_ab.SummaryError):
            summarize_ab.validate_records_against_test(manifest, records, rows)
        records[0]["scores"] = summarize_ab.independently_score(
            rows[0]["messages"][plan[0]["turn_index"]],
            records[0]["response"]["message"],
            records[0]["response"]["finish_reason"],
        )
        records[0]["reference"]["content"] = "tampered"
        with self.assertRaises(summarize_ab.SummaryError):
            summarize_ab.validate_records_against_test(manifest, records, rows)

    def test_capped_prefix_is_fixed_and_task_complete(self) -> None:
        test_path = ROOT.parent / "data/releases/rdk-sft-v1-20260803/agentic/test.jsonl"
        rows = summarize_ab.load_frozen_rows(test_path)
        records = summarize_ab.build_frozen_plan(rows, "base")

        selected = summarize_ab.select_capped_prefix(records[:170], "base")
        self.assertEqual(len(selected), 170)
        self.assertEqual(len({record["task_id"] for record in selected}), 49)
        self.assertEqual(selected[-1]["task_index"], 48)

        selected_after_drain = summarize_ab.select_capped_prefix(records[:171], "base")
        self.assertEqual(selected_after_drain, selected)
        self.assertEqual(records[170]["task_index"], 49)

        for invalid in (records[:169], records[:172]):
            with self.assertRaises(summarize_ab.SummaryError):
                summarize_ab.select_capped_prefix(invalid, "base")

        wrong_drain = [*records[:170], {**records[170], "task_index": 50}]
        with self.assertRaises(summarize_ab.SummaryError):
            summarize_ab.select_capped_prefix(wrong_drain, "base")

    def test_sft_identity_rejects_a_second_base_arm(self) -> None:
        base = eval_ab.FROZEN_ARMS["base"]
        fake_manifest = {
            "contract": {
                "test_sha256": summarize_ab.FROZEN_TEST_SHA256,
                "config": {
                    "label": "sft",
                    "request_model": base["request_model"],
                    "expected_response_model": base["response_model"],
                    "expected_system_fingerprint": base["system_fingerprint"],
                    "expected_health": base["health"],
                    "expected_tasks": 113,
                    "expected_records": 413,
                    "expected_test_sha256": summarize_ab.FROZEN_TEST_SHA256,
                    "expected_test_bytes": 3_562_357,
                    "temperature": 0,
                    "expected_file_sha256": {},
                    "expected_process_arguments": [],
                    "forbidden_process_arguments": [],
                },
            }
        }
        with self.assertRaises(summarize_ab.SummaryError):
            summarize_ab.validate_arm_identity(fake_manifest, "sft")

    def test_adapter_file_binds_its_checkpoint_directory(self) -> None:
        adapter_file = Path("/models/checkpoint-000119/adapter_model.safetensors")
        identity = {str(adapter_file): eval_ab.ADAPTER_SHA256}
        self.assertEqual(
            eval_ab.adapter_runtime_path(identity),
            "/models/checkpoint-000119",
        )
        self.assertEqual(
            summarize_ab.adapter_runtime_path(identity),
            "/models/checkpoint-000119",
        )
        relative = {
            "checkpoint-000119/adapter_model.safetensors": eval_ab.ADAPTER_SHA256
        }
        with self.assertRaises(eval_ab.EvaluationError):
            eval_ab.adapter_runtime_path(relative)
        with self.assertRaises(summarize_ab.SummaryError):
            summarize_ab.adapter_runtime_path(relative)

    def test_output_path_rejects_symlink_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(eval_ab.EvaluationError):
                eval_ab.reject_symlink_ancestors(link / "result.json")

    def test_recovery_seal_snapshot_requires_read_only_input(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            evidence = Path(temporary) / "evidence.jsonl"
            evidence.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(seal_interrupted_arm.SealError):
                seal_interrupted_arm.readonly_snapshot(evidence)
            evidence.chmod(0o444)
            snapshot = seal_interrupted_arm.readonly_snapshot(evidence)
            self.assertEqual(snapshot["mode"], "0444")
            self.assertEqual(snapshot["bytes"], 3)

    def test_recovery_seal_output_is_new_read_only_and_has_no_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "base.recovery-seal.json"
            directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                seal_interrupted_arm.write_new_readonly_json(
                    output, {"status": "RECOVERY_SEALED"}, directory_fd
                )
                self.assertEqual(
                    json.loads(output.read_text(encoding="utf-8")),
                    {"status": "RECOVERY_SEALED"},
                )
                self.assertEqual(output.stat().st_mode & 0o777, 0o444)
                with self.assertRaises(FileExistsError):
                    seal_interrupted_arm.write_new_readonly_json(
                        output, {"status": "changed"}, directory_fd
                    )
                self.assertEqual(list(root.glob(".*.tmp-*")), [])
            finally:
                os.close(directory_fd)

    def test_capped_arm_requires_matching_recovery_raw_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            raw = root / "base.raw.jsonl"
            manifest_path = root / "base.manifest.json"
            contract = {
                "config": {
                    "expected_response_model": "base-model",
                    "expected_system_fingerprint": "base-fingerprint",
                }
            }
            contract_sha256 = eval_ab.canonical_digest(contract)
            record = {
                "schema_version": eval_ab.RECORD_SCHEMA,
                "contract_sha256": contract_sha256,
                "label": "base",
                "run_id": "run",
                "key": "base:0:1",
                "response": {
                    "model": "base-model",
                    "system_fingerprint": "base-fingerprint",
                },
            }
            raw.write_text(json.dumps(record) + "\n", encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": eval_ab.MANIFEST_SCHEMA,
                        "status": "INTERRUPTED",
                        "last_error": "SIGTERM",
                        "training_use": False,
                        "api_key_persisted": False,
                        "label": "base",
                        "run_id": "run",
                        "raw_file": raw.name,
                        "raw_sha256": None,
                        "completed_records": 1,
                        "contract": contract,
                        "contract_sha256": contract_sha256,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(summarize_ab.SummaryError):
                summarize_ab.load_arm(manifest_path, capped_prefix=True)
            with self.assertRaises(summarize_ab.SummaryError):
                summarize_ab.load_arm(
                    manifest_path,
                    capped_prefix=True,
                    recovery_raw_sha256="0" * 64,
                )
            _manifest, records, loaded_raw = summarize_ab.load_arm(
                manifest_path,
                capped_prefix=True,
                recovery_raw_sha256=eval_ab.sha256_file(raw),
            )
            self.assertEqual(records, [record])
            self.assertEqual(loaded_raw, raw)


if __name__ == "__main__":
    unittest.main()
