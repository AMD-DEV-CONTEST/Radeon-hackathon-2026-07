import os
from unittest.mock import patch

from track2_runtime import LocalEnvironment, make_tool_result_message


def test_tool_result_message_uses_openai_and_internal_names():
    message = make_tool_result_message("terminal", "ok", "call-1")
    assert message == {
        "role": "tool",
        "name": "terminal",
        "tool_name": "terminal",
        "content": "ok",
        "tool_call_id": "call-1",
    }


def test_local_environment_runs_in_workspace_without_provider_secrets(tmp_path):
    environment = LocalEnvironment(str(tmp_path), timeout=5)
    with patch.dict(
        os.environ,
        {"TRACK2_API_KEY": "do-not-leak", "TRACK2_SAFE_VALUE": "visible"},
        clear=False,
    ):
        result = environment.execute(
            "pwd; test -z \"${TRACK2_API_KEY:-}\"; printf '%s' \"$TRACK2_SAFE_VALUE\""
        )

    assert result["returncode"] == 0
    assert str(tmp_path) in result["output"]
    assert result["output"].rstrip().endswith("visible")
