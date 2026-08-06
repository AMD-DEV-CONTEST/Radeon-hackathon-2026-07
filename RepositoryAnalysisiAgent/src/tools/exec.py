"""Test execution tool: run_tests (disabled by default for security).

WARNING: pytest collection imports conftest.py and test modules,
which is equivalent to arbitrary code execution. Only enable this
for trusted repositories.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from .registry import ToolRegistry

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)


def register_exec_tools(
    registry: ToolRegistry,
    config: Config,
) -> None:
    """Register run_tests tool."""

    async def run_tests(args: str = "") -> str:
        """Run the project's test suite.

        WARNING: Running tests executes code from the repository. Only use
        on trusted repositories.

        Args:
            args: Additional arguments to pass to the test runner.
        """
        if not config.security.run_tests_enabled:
            return (
                "run_tests is disabled. To enable, set security.run_tests_enabled=true "
                "in config.yaml. WARNING: running tests on untrusted repositories "
                "executes arbitrary code (pytest imports conftest.py during collection)."
            )

        command = config.security.test_commands[0].split()
        if args:
            command.extend(args.split())

        root = str(config.repo_root)
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=config.security.max_test_timeout,
            )
            output = result.stdout + result.stderr
            if len(output) > 8000:
                output = output[:4000] + "\n... [truncated] ...\n" + output[-3000:]
            return f"Exit code: {result.returncode}\n\n{output}"
        except subprocess.TimeoutExpired:
            return f"Tests timed out after {config.security.max_test_timeout}s"
        except FileNotFoundError:
            return f"Test runner not found: {command[0]}"

    registry.register(
        name="run_tests",
        description=(
            "Run the project test suite (pytest). "
            "Disabled by default for security. "
            "WARNING: pytest collection executes code from the repository."
        ),
        parameters={
            "type": "object",
            "properties": {
                "args": {
                    "type": "string",
                    "description": "Additional arguments (e.g. '-v -x tests/test_foo.py').",
                    "default": "",
                },
            },
        },
        handler=run_tests,
    )
