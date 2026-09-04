#!/usr/bin/env python3
"""Structural enforcement of the repository's exact workflow policy."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"ci.yml", "phreeqc-qualification.yml"}
EXPECTED_WORKFLOW_SHA256 = {
    "ci.yml": "ce2b07e84a0f95cab186bcbdd62609e5046b43687c6a901d7856f5c0c00ee900",
    "phreeqc-qualification.yml": "b9faf81b4b3c8ae1faa54bbea729206f8508af8d1acb46349d168119941c2f1a",
}
SHA_ACTION = re.compile(r"^actions/(?:checkout|setup-python)@[0-9a-f]{40}$")
LOCK_INSTALL = "python -m pip install --disable-pip-version-check --no-input --only-binary=:all: --require-hashes -r requirements/ci.txt"
LOCAL_INSTALL = "python -m pip install --disable-pip-version-check --no-input --no-deps --no-build-isolation -e ."


class PolicyError(ValueError):
    pass


def _convert(node):
    if isinstance(node, ScalarNode):
        value = node.value
        if value in {"true", "false"}:
            return value == "true"
        if re.fullmatch(r"[0-9]+", value):
            return int(value)
        return value
    if isinstance(node, SequenceNode):
        return [_convert(item) for item in node.value]
    if isinstance(node, MappingNode):
        result = {}
        for key_node, value_node in node.value:
            key = _convert(key_node)
            if not isinstance(key, str) or key in result:
                raise PolicyError("duplicate or non-string mapping key")
            if key == "<<":
                raise PolicyError("YAML merge keys are forbidden")
            result[key] = _convert(value_node)
        return result
    raise PolicyError("unsupported YAML node")


def load_workflow(path: Path):
    if path.is_symlink() or not path.is_file():
        raise PolicyError("workflow must be a regular non-symlink file")
    text = path.read_text(encoding="utf-8")
    try:
        for token in yaml.scan(text):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise PolicyError("anchors, aliases, and explicit tags are forbidden")
        node = yaml.compose(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        raise PolicyError(f"invalid YAML: {exc}") from exc
    if not isinstance(node, MappingNode):
        raise PolicyError("workflow must be a mapping")
    return _convert(node)


def _common(name: str, workflow: dict, expected_job: str):
    if workflow.get("permissions") != {"contents": "read"}:
        raise PolicyError(f"{name}: permissions must be exactly contents: read")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or set(jobs) != {expected_job}:
        raise PolicyError(f"{name}: unexpected jobs")
    job = jobs[expected_job]
    if "permissions" in job or not isinstance(job.get("timeout-minutes"), int):
        raise PolicyError(f"{name}: job permissions/timeout policy")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise PolicyError(f"{name}: steps must be a list")
    checkout = 0
    run_text = []
    for step in steps:
        if not isinstance(step, dict):
            raise PolicyError(f"{name}: invalid step")
        if "uses" in step:
            action = step["uses"]
            if not isinstance(action, str) or SHA_ACTION.fullmatch(action) is None:
                raise PolicyError(f"{name}: unapproved or unpinned action")
            if action.startswith("actions/checkout@"):
                checkout += 1
                if step.get("with", {}).get("persist-credentials") is not False:
                    raise PolicyError(f"{name}: checkout credentials must not persist")
        if "run" in step:
            run_text.append(str(step["run"]))
        if "secrets" in str(step).lower():
            raise PolicyError(f"{name}: secrets forbidden")
    if checkout != 1:
        raise PolicyError(f"{name}: exactly one checkout required")
    commands = "\n".join(run_text)
    pip_lines = [line.strip() for line in commands.splitlines() if "pip install" in line]
    if pip_lines != [LOCK_INSTALL, LOCAL_INSTALL]:
        raise PolicyError(f"{name}: dependency installation policy mismatch")
    return job, commands


def validate(root: Path = ROOT) -> None:
    directory = root / ".github/workflows"
    paths = sorted({*directory.glob("*.yml"), *directory.glob("*.yaml")})
    if {path.name for path in paths} != ALLOWED or any(path.is_symlink() for path in paths):
        raise PolicyError("workflow file set mismatch")
    workflows = {path.name: load_workflow(path) for path in paths}
    for name, workflow in workflows.items():
        encoded = json.dumps(workflow, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        if not hmac_compare_digest(hashlib.sha256(encoded).hexdigest(),
                                   EXPECTED_WORKFLOW_SHA256[name]):
            raise PolicyError(f"{name}: workflow structure differs from the exact policy")
    ci = workflows["ci.yml"]
    ci_job, ci_commands = _common("ci.yml", ci, "test")
    if ci_job.get("runs-on") != "ubuntu-24.04":
        raise PolicyError("ci.yml: runner must be ubuntu-24.04")
    if set(ci.get("on", {})) != {"push", "pull_request", "workflow_dispatch"}:
        raise PolicyError("ci.yml: trigger policy mismatch")
    for required in ("python scripts/check_workflow_security.py", "python -m compileall -q src tests",
                     "python -m pytest -q", "python -m build --wheel --no-isolation", "git diff --check",
                     "node --check scripts/generate_deck.js", "npm ci --no-audit --no-fund"):
        if required not in ci_commands:
            raise PolicyError(f"ci.yml: missing command {required}")
    manual = workflows["phreeqc-qualification.yml"]
    manual_job, manual_commands = _common("phreeqc-qualification.yml", manual, "qualify")
    if manual_job.get("runs-on") != ["self-hosted", "nuclidepath"]:
        raise PolicyError("manual workflow runner mismatch")
    trigger = manual.get("on")
    if not isinstance(trigger, dict) or set(trigger) != {"workflow_dispatch"}:
        raise PolicyError("manual workflow must be dispatch-only")
    inputs = trigger["workflow_dispatch"].get("inputs", {})
    if set(inputs) != {"phreeqc_executable", "phreeqc_database", "phreeqc_executable_sha256", "phreeqc_database_sha256"}:
        raise PolicyError("manual workflow input policy mismatch")
    if "refs/heads/main" not in manual_commands or "--run-external-solver" not in manual_commands:
        raise PolicyError("manual workflow trusted-ref/test policy mismatch")


def hmac_compare_digest(actual: str, expected: str) -> bool:
    """Keep policy digest comparison explicit without accepting partial values."""
    import hmac
    return hmac.compare_digest(actual, expected)


if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else ROOT)
    except PolicyError as exc:
        print(f"workflow security policy: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("workflow security policy: PASS")
