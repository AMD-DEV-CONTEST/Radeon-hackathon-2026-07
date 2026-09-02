from scripts import pb_collection_probe as probe


def test_normalize_pytest_nodeid_to_programbench_id():
    assert (
        probe.normalize_nodeid("eval/tests/test_cli.py::TestHelp::test_usage[arg0]")
        == "eval.tests.test_cli.TestHelp.test_usage[arg0]"
    )
    assert probe.normalize_nodeid("tests/test_basic.py::test_ok") == "tests.test_basic.test_ok"


def test_branch_probe_classifies_collection_emission_and_behavioral(tmp_path):
    expected = {
        "branch1": {
            "tests.test_demo.test_collected_pass",
            "tests.test_demo.test_collected_fail",
            "tests.test_demo.test_never_collected",
            "tests.test_demo.test_lost_emission",
        }
    }
    rows = [
        {"branch": "branch1", "name": "tests.test_demo.test_collected_pass", "status": "passed"},
        {"branch": "branch1", "name": "tests.test_demo.test_collected_fail", "status": "failure"},
        {"branch": "branch1", "name": "tests.test_demo.test_never_collected", "status": "not_run"},
        {"branch": "branch1", "name": "tests.test_demo.test_lost_emission", "status": "not_run"},
        {
            "branch": "branch1",
            "name": "branch-log",
            "status": "log",
            "extra": {
                "output": "\n".join(
                    [
                        "tests/test_demo.py::test_collected_pass PASSED [ 25%]",
                        "tests/test_demo.py::test_collected_fail FAILED [ 50%]",
                        "tests/test_demo.py::test_lost_emission PASSED [ 75%]",
                    ]
                )
            },
        },
    ]
    emitted = {
        "branch1": {
            "tests.test_demo.test_collected_pass",
            "tests.test_demo.test_collected_fail",
        }
    }

    collected = {"branch1": probe.parse_collected_ids(rows)}

    result = probe.probe_branch("branch1", expected["branch1"], rows, collected, {}, emitted)

    assert result.expected_count == 4
    assert result.collected_count == 3
    assert result.emitted_count == 2
    assert result.expected_not_collected == ["tests.test_demo.test_never_collected"]
    assert result.collected_not_emitted == ["tests.test_demo.test_lost_emission"]
    assert result.collected_failed == ["tests.test_demo.test_collected_fail"]
    assert result.branch_class == "MIXED"


def test_branch_probe_marks_collected_unknown_when_no_verbose_output():
    rows = [
        {"branch": "branch1", "name": "tests.test_demo.test_a", "status": "not_run"},
    ]

    result = probe.probe_branch(
        "branch1",
        {"tests.test_demo.test_a"},
        rows,
        {"branch1": set()},
        {},
        {"branch1": set()},
    )

    assert result.collected_reconstructable is False
    assert result.branch_class == "UNKNOWN_COLLECTED_SET"


def test_collected_by_branch_reads_top_level_programbench_logs():
    logs = [
        {
            "step": "pytest",
            "output": "\n".join(
                [
                    "collecting ... collected 2 items",
                    "tests/test_demo.py::test_a PASSED [ 50%]",
                    "tests/test_demo.py::test_b RERUN [100%]",
                    "tests/test_demo.py::test_b FAILED [100%]",
                ]
            ),
        },
        {"branch": "branch1", "step": "results_read", "output": "<testsuite />"},
    ]

    assert probe.collected_by_branch(logs, []) == {
        "branch1": {
            "tests.test_demo.test_a",
            "tests.test_demo.test_b",
        }
    }


def test_collection_error_without_nodeids_is_marked_unmapped():
    logs = [
        {
            "step": "run_tests",
            "output": "collecting ... collected 0 items / 1 error\nERROR collecting tests/test_demo.py",
        },
        {"branch": "branch1", "step": "results_read", "output": "<testsuite />"},
    ]
    rows = [{"branch": "branch1", "name": "tests.test_demo", "status": "error"}]

    result = probe.probe_branch(
        "branch1",
        {"tests.test_demo.test_a", "tests.test_demo.test_b"},
        rows,
        probe.collected_by_branch(logs, rows),
        probe.collection_summary_by_branch(logs),
        {"branch1": {"tests.test_demo"}},
    )

    assert result.branch_class == "COLLECTION_WALL_UNMAPPED"
    assert result.collection_summary_count == 0
    assert result.collection_error_count == 1
