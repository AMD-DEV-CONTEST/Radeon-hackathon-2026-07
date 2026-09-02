import json
import subprocess

from track2_qwen_code import (
    parse_qwen_stream,
    qwen_diagnostics,
    qwen_model_turns,
    qwen_settings,
    qwen_terminal_error,
    qwen_usage,
    run_qwen_code,
)


def test_settings_reference_environment_without_persisting_secret():
    settings = qwen_settings(
        base_url="https://example.invalid/v1",
        model="small-code-model",
        api_timeout=30,
        transport_retries=2,
    )

    serialized = json.dumps(settings)
    assert settings["$version"] == 5
    assert settings["modelProviders"]["openai"][0]["envKey"] == "TRACK2_API_KEY"
    assert settings["modelProviders"]["openai"][0]["generationConfig"]["timeout"] == 30_000
    assert "generationConfig" not in settings["model"]
    assert "secret-value" not in serialized
    assert settings["security"]["auth"]["selectedType"] == "openai"


def test_stream_parser_usage_and_diagnostics(tmp_path):
    stdout = "noise\n" + "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "_observed_ms": 12,
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "write_file",
                                "input": {"path": "src/a.py", "content": "x = 1"},
                            },
                            {
                                "type": "tool_use",
                                "name": "run_shell_command",
                                "input": {"command": "pytest -q"},
                            },
                        ],
                        "usage": {"prompt_tokens": 99, "completion_tokens": 9},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                }
            ),
        ]
    )

    events = parse_qwen_stream(stdout)
    usage = qwen_usage(events)
    diagnostics = qwen_diagnostics(events, tmp_path)

    assert usage == {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}
    assert qwen_model_turns(events) == 1
    assert diagnostics["tool_calls"] == 2
    assert diagnostics["edit_tool_calls"] == 1
    assert diagnostics["test_tool_calls"] == 1
    assert diagnostics["tests_after_edit"] is True
    assert diagnostics["integrity_eligible"] is True


def test_todo_write_is_not_counted_as_source_edit(tmp_path):
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "todo_write",
                        "input": {"todos": [{"id": "t1", "content": "inspect"}]},
                    }
                ]
            },
        }
    ]

    assert qwen_diagnostics(events, tmp_path)["edit_tool_calls"] == 0


def test_qwen_success_subtype_with_api_error_text_is_a_failure():
    event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "[API Error: Request timeout after 120s.]",
    }

    assert qwen_terminal_error(event) is True


def test_fake_headless_run_captures_patch_usage_and_redacts_key(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    (workspace / "a.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=workspace, check=True)

    fake = tmp_path / "fake-qwen"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "from pathlib import Path\n"
        "Path('a.py').write_text('VALUE = 2\\n')\n"
        "print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','name':'write_file','input':{'path':'a.py'}}]}}))\n"
        "print(json.dumps({'type':'result','subtype':'success','usage':{'input_tokens':7,'output_tokens':3,'total_tokens':10}}))\n"
    )
    fake.chmod(0o755)

    result = run_qwen_code(
        {"prompt": "Change the value."},
        workspace,
        tmp_path / "runtime",
        qwen_bin=fake,
        base_url="https://example.invalid/v1",
        api_key="secret-value",
        model="small-code-model",
        max_calls=8,
        max_tool_calls=40,
        max_wall_time=10,
        api_timeout=5,
        transport_retries=0,
    )

    assert result["semantic_calls"] == 1
    assert result["usage"]["total_tokens"] == 10
    assert result["final_patch"]
    assert result["patch_apply_results"] == [True]
    assert result["qwen_settings_contains_secret"] is False
    assert "secret-value" not in result["_stderr"]
    settings_text = (tmp_path / "runtime" / "home" / "settings.json").read_text()
    assert "secret-value" not in settings_text


def test_max_turn_exit_is_budget_completion_not_api_error(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    fake = tmp_path / "fake-qwen-budget"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "for _ in range(2):\n"
        " print(json.dumps({'type':'assistant','message':{'content':[], 'usage':{'input_tokens':1,'output_tokens':1}}}))\n"
        "print('Reached max session turns for this session.', file=sys.stderr)\n"
        "raise SystemExit(53)\n"
    )
    fake.chmod(0o755)

    result = run_qwen_code(
        {"prompt": "Inspect."},
        workspace,
        tmp_path / "runtime-budget",
        qwen_bin=fake,
        base_url="https://example.invalid/v1",
        api_key="secret-value",
        model="small-code-model",
        max_calls=2,
        max_tool_calls=4,
        max_wall_time=10,
        api_timeout=5,
        transport_retries=0,
    )

    assert result["api_errors"] == []
    assert result["agent_completed"] is True
    assert result["termination_reason"] == "max_model_turns"
    assert "secret-value" not in result["_stderr"]
    settings_text = (tmp_path / "runtime-budget" / "home" / "settings.json").read_text()
    assert "secret-value" not in settings_text
