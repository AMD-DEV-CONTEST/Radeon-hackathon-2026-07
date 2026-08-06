from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_factory.create_agent.validator import CreateAgentPackageValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a create-agent workspace as an AgentPackage.")
    parser.add_argument("workspace", help="Path to the create-agent workspace/package root.")
    parser.add_argument("--out", help="Optional report path. Relative paths are resolved inside the workspace.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    report = CreateAgentPackageValidator().validate(workspace)
    payload = report.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        output = Path(args.out)
        if not output.is_absolute():
            output = workspace / output
        _assert_inside(workspace, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.status == "passed" else 1


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"output path escapes create-agent workspace: {path}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
