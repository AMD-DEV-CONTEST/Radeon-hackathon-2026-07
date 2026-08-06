from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets


RESOURCE_KEY_NAME = "AGENTFACTORY_RESOURCE_MASTER_KEY"
ASSIGNMENT = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete generated values in the unified FastAgentFactory .env file"
    )
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    lines = args.env_file.read_text(encoding="utf-8").splitlines()
    resource_key = _last_value(lines, RESOURCE_KEY_NAME)
    if not resource_key:
        lines = _replace_value(
            lines,
            RESOURCE_KEY_NAME,
            secrets.token_urlsafe(48),
        )
        args.env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    args.env_file.chmod(0o600)


def _last_value(lines: list[str], name: str) -> str:
    value = ""
    for line in lines:
        match = ASSIGNMENT.match(line.strip())
        if match and match.group("name") == name:
            value = _strip_quotes(match.group("value").strip())
    return value


def _replace_value(lines: list[str], name: str, value: str) -> list[str]:
    rendered: list[str] = []
    replaced = False
    for line in lines:
        match = ASSIGNMENT.match(line.strip())
        if not match or match.group("name") != name:
            rendered.append(line)
            continue
        if not replaced:
            rendered.append(f"{name}={value}")
            replaced = True
    if not replaced:
        rendered.extend(["", f"{name}={value}"])
    return rendered


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    main()
