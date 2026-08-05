from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_benchmark_docker_environment_disables_host_support_mounts(tmp_path):
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner.env_type = "docker"
    runner.image = "test-image"
    runner.cwd = str(tmp_path)
    runner.command_timeout = 30
    captured = {}

    with patch("mini_swe_runner.create_environment") as create:
        create.side_effect = lambda **kwargs: captured.update(kwargs) or MagicMock()
        runner._create_env()

    assert captured["network"] is False
    assert captured["mount_support_files"] is False
    assert captured["host_cwd"] == str(tmp_path)


def test_agent_command_normalizes_swebench_testbed_alias():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner._loop_guard_enabled = False
    runner._inspection_gate_active = False
    runner._path_alias_rewrites = 0
    runner._execute_command = MagicMock(
        return_value={"output": "", "exit_code": 0, "error": None}
    )

    runner._execute_agent_command("cd /testbed && cat /testbed/pkg/core.py", 30)

    runner._execute_command.assert_called_once_with(
        "cd . && cat ./pkg/core.py", 30
    )
    assert runner._path_alias_rewrites == 2


def test_inspection_gate_blocks_read_only_command_until_patch_exists():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner._loop_guard_enabled = False
    runner._inspection_gate_active = True
    runner._inspection_gate_rejections = 0
    runner._path_alias_rewrites = 0
    runner._execute_command = MagicMock(
        return_value={"output": "", "exit_code": 0, "error": None}
    )

    result = runner._execute_agent_command("grep -R formatter_class django", 30)

    assert result["exit_code"] == 2
    assert "INSPECTION_BUDGET_EXHAUSTED" in result["output"]
    assert runner._inspection_gate_rejections == 1
    runner._execute_command.assert_called_once_with("git diff --quiet -- .", 20)


def test_inspection_gate_allows_explicit_file_write():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner._loop_guard_enabled = False
    runner._inspection_gate_active = True
    runner._inspection_gate_rejections = 0
    runner._path_alias_rewrites = 0
    runner._execute_command = MagicMock(
        side_effect=[
            {"output": "", "exit_code": 0, "error": None},
            {"output": "", "exit_code": 0, "error": None},
        ]
    )

    result = runner._execute_agent_command(
        "python3 -c \"from pathlib import Path; Path('x.py').write_text('x=1')\"", 30
    )

    assert result["exit_code"] == 0
    assert runner._execute_command.call_count == 2


def test_verifier_repair_is_queued_only_once():
    from swe_experiments.verifier import CheckResult, VerifierReport
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner.verifier_mode = "V1R1"
    runner._repair_attempts = 0
    report = VerifierReport(
        "reject",
        "V1",
        [CheckResult("changes_present", False, 1, "workspace has no changed files")],
    )
    runner._verify_current_workspace = lambda: report
    messages = []

    first, queued = runner._queue_verifier_repair("fix it", messages)
    second, queued_again = runner._queue_verifier_repair("fix it", messages)

    assert first is report
    assert queued is True
    assert second is report
    assert queued_again is False
    assert runner._repair_attempts == 1
    assert "VERIFIER_REJECTED" in messages[0]["content"]


def test_agent_command_blocks_network_and_absolute_paths():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner._loop_guard_enabled = False
    runner._inspection_gate_active = False
    runner._path_alias_rewrites = 0
    runner._execute_command = MagicMock()

    network = runner._execute_agent_command("pip install missing-package", 30)
    outside = runner._execute_agent_command("cd / && ls", 30)

    assert network["exit_code"] == 2
    assert "NETWORK_POLICY_GUARD" in network["output"]
    assert outside["exit_code"] == 2
    assert "OUTSIDE_REPO_GUARD" in outside["output"]
    runner._execute_command.assert_not_called()


def test_run_task_kimi_omits_temperature():
    """Kimi models should NOT have client-side temperature overrides.

    The Kimi gateway selects the correct temperature server-side.
    """
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="kimi-for-coding",
            base_url="https://api.kimi.com/coding/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("2+2")

    assert result["completed"] is True
    assert "temperature" not in client.chat.completions.create.call_args.kwargs


def test_run_task_public_moonshot_kimi_k2_5_omits_temperature():
    """kimi-k2.5 on the public Moonshot API should not get a forced temperature."""
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.base_url = "https://api.moonshot.ai/v1"
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))]
        )
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="kimi-k2.5",
            base_url="https://api.moonshot.ai/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("2+2")

    assert result["completed"] is True
    assert "temperature" not in client.chat.completions.create.call_args.kwargs


def test_transport_retry_does_not_consume_semantic_call_budget():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            TimeoutError("temporary gateway timeout"),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))]
            ),
        ]
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="test-model",
            base_url="https://example.invalid/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=1,
            api_transport_retries=1,
        )
        runner._create_env = MagicMock()
        runner._cleanup_env = MagicMock()

        result = runner.run_task("solve")

    assert result["completed"] is True
    assert result["api_calls"] == 1
    assert client.chat.completions.create.call_count == 2
    assert result["metadata"]["api"]["transport_attempts"] == 2
    assert len(result["metadata"]["api"]["errors"]) == 1


def test_json_action_mode_dispatches_and_uses_structured_output_body():
    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.base_url = "http://127.0.0.1:8000/v1"
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"execute","command":"echo hi","reason":"inspect"}',
                            tool_calls=[],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"finish","reason":"done"}',
                            tool_calls=[],
                        )
                    )
                ]
            ),
        ]
        mock_openai.return_value = client

        from mini_swe_runner import MiniSWERunner

        runner = MiniSWERunner(
            model="local-small-model",
            base_url="http://127.0.0.1:8000/v1",
            api_key="test-key",
            env_type="local",
            max_iterations=2,
            json_mode="J3",
        )

        class FakeEnv:
            def execute(self, command, timeout=None):
                return {"output": "hi\n", "returncode": 0}

            def cleanup(self):
                pass

        runner._create_env = lambda: setattr(runner, "env", FakeEnv())
        runner._cleanup_env = lambda: setattr(runner, "env", None)
        result = runner.run_task("inspect the repository")

    assert result["completed"] is True
    assert result["metadata"]["json_mode"] == "J3"
    assert client.chat.completions.create.call_args_list[0].kwargs["extra_body"]["structured_outputs"]
    assert "tools" not in client.chat.completions.create.call_args_list[0].kwargs


def test_apply_patch_normalizes_small_model_diff_noise():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner.command_timeout = 30
    captured = {}

    def execute(command, timeout):
        captured["command"] = command
        return {"output": "", "exit_code": 0, "error": None}

    runner._execute_command = execute
    result = runner._apply_patch(
        "```diff\n"
        "--git a/demo.py\n"
        "diff --git a/demo.py b/demo.py\n"
        "index 123fake..456fake 100644\n"
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1,99 +1,99 @@\n"
        "-pass\n"
        "+return 1\n"
        "```"
    )

    assert result["exit_code"] == 0
    assert "git apply --recount" in captured["command"]
    assert "\n--git a/demo.py\n" not in captured["command"]
    assert "index 123fake" not in captured["command"]
    assert "diff --git a/demo.py b/demo.py" in captured["command"]


def test_apply_patch_repairs_bare_added_lines_only_after_git_rejects_syntax():
    from mini_swe_runner import MiniSWERunner

    runner = object.__new__(MiniSWERunner)
    runner.command_timeout = 30
    commands = []

    def execute(command, timeout):
        commands.append(command)
        if len(commands) == 1:
            return {
                "output": "warning: recount: unexpected line: def helper():\nerror: corrupt patch at line 8",
                "exit_code": 128,
                "error": None,
            }
        return {"output": "", "exit_code": 0, "error": None}

    runner._execute_command = execute
    result = runner._apply_patch(
        "--- a/demo.py\n"
        "+++ b/demo.py\n"
        "@@ -1 +1,3 @@\n"
        "-pass\n"
        "def helper():\n"
        "    return 1\n"
    )

    assert result["exit_code"] == 0
    assert len(commands) == 2
    assert "\n+def helper():\n+    return 1\n" in commands[1]


def test_edit_v2_replace_is_exact_and_confined_to_repository(tmp_path):
    from mini_swe_runner import MiniSWERunner

    target = tmp_path / "demo.py"
    target.write_text("value = 1\n")
    runner = object.__new__(MiniSWERunner)
    runner.cwd = str(tmp_path)

    applied = runner._apply_replace("demo.py", "value = 1", "value = 2")
    assert applied["exit_code"] == 0
    assert target.read_text() == "value = 2\n"

    target.write_text("value = 2\nvalue = 2\n")
    duplicate = runner._apply_replace("demo.py", "value = 2", "other")
    assert duplicate["exit_code"] == 2
    outside = runner._apply_replace("../outside.py", "x", "y")
    assert outside["exit_code"] == 2
    absolute = runner._apply_replace(str(target), "value = 2", "other")
    assert absolute["exit_code"] == 2


def test_edit_v2_duplicate_feedback_is_actionable(tmp_path):
    from mini_swe_runner import MiniSWERunner

    target = tmp_path / "demo.py"
    target.write_text("def first():\n    return 1\n\ndef second():\n    return 1\n")
    runner = object.__new__(MiniSWERunner)
    runner.cwd = str(tmp_path)

    result = runner._apply_replace("demo.py", "    return 1", "    return 2")

    assert result["exit_code"] == 2
    assert "matched 2 times" in result["output"]
    assert "function-specific old_text" in result["output"]
    assert "occurrence 1" in result["output"]
    assert "occurrence 2" in result["output"]


def test_structured_inspect_recovers_directory_and_missing_paths(tmp_path):
    from mini_swe_runner import MiniSWERunner
    from swe_experiments.actions import parse_action_envelope

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "logistic.py").write_text("class LogisticRegression:\n    pass\n")
    runner = object.__new__(MiniSWERunner)
    runner.cwd = str(tmp_path)
    runner.max_tool_calls = 10
    runner._tool_call_count = 0
    runner._tool_budget_rejections = 0
    runner._action_counts = {}
    runner._path_recovery_events = []

    directory = runner._dispatch_json_action(
        parse_action_envelope({
            "action": "inspect", "path": ".", "query": None, "command": None,
            "patch": None, "old_text": None, "new_text": None, "reason": "list files",
        })
    )
    missing = runner._dispatch_json_action(
        parse_action_envelope({
            "action": "inspect", "path": "pkg/_logistic.py", "query": None, "command": None,
            "patch": None, "old_text": None, "new_text": None, "reason": "find source",
        })
    )

    assert directory["exit_code"] == 0
    assert "pkg/logistic.py" in directory["output"]
    assert missing["exit_code"] == 2
    assert "pkg/logistic.py" in missing["output"]
    assert runner._tool_call_count == 2
    assert len(runner._path_recovery_events) == 2


def test_structured_actions_increment_action_and_edit_metrics(tmp_path):
    from mini_swe_runner import MiniSWERunner
    from swe_experiments.actions import parse_action_envelope

    target = tmp_path / "demo.py"
    target.write_text("value = 1\n")
    runner = object.__new__(MiniSWERunner)
    runner.cwd = str(tmp_path)
    runner.edit_protocol = "replace-v2"
    runner.max_tool_calls = 4
    runner._tool_call_count = 0
    runner._tool_budget_rejections = 0
    runner._action_counts = {}
    runner._replace_attempts = 0
    runner._replace_successes = 0
    runner._replace_errors = []
    runner._patch_apply_results = []

    result = runner._dispatch_json_action(
        parse_action_envelope(
            {
                "action": "replace",
                "path": "demo.py",
                "query": None,
                "command": None,
                "patch": None,
                "old_text": "value = 1",
                "new_text": "value = 2",
                "reason": "fix",
            }
        )
    )
    assert result["exit_code"] == 0
    assert runner._action_counts["replace"] == 1
    assert runner._replace_attempts == runner._replace_successes == 1
    assert runner._tool_call_count == 1


def test_compact_code_text_truncates_lines():
    from mini_swe_runner import compact_code_text

    text = "\n".join(f"line {i}" for i in range(30))
    compact = compact_code_text(text, max_lines=24)
    assert compact.count("\n") == 24
    assert "… (+6 more lines)" in compact
    assert "line 29" not in compact


def test_compact_code_text_truncates_chars():
    from mini_swe_runner import compact_code_text

    text = "x" * 2000
    compact = compact_code_text(text, max_lines=24, max_chars=200)
    assert len(compact) <= 230
    assert "… (output truncated)" in compact
