#!/usr/bin/env python3
"""
End-to-end test for native runtime launcher and handle.

Creates a minimal package stub and verifies the native launcher can prepare
a valid launch plan with correct environment and path configuration.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from agent_factory.native_runtime import NativeAgentRuntimeLauncher


class _MockManifest:
    """Minimal manifest stub exposing only what the launcher reads."""

    runtime: dict = {}


class _MockPackage:
    """Minimal package stub with package_root for launcher testing.

    The native launcher only reads package.package_root (for the environment
    lock) and package.manifest.runtime, so a full LoadedAgentPackage with its
    ten required contracts is unnecessary here.
    """

    def __init__(self, package_id: str, package_root: Path) -> None:
        self.package_id = package_id
        self.package_root = package_root
        self.manifest = _MockManifest()


def create_minimal_package(package_root: Path):
    """Create a minimal test package structure with a valid environment lock."""
    package_root.mkdir(parents=True, exist_ok=True)

    # Minimal environment lock (no dependencies) — this is what the launcher reads
    from agent_factory.environment_system.versions import (
        DEPENDENCY_POOL_VERSION,
        ENVIRONMENT_LOCK_VERSION,
    )
    env_lock_data = {
        "version": ENVIRONMENT_LOCK_VERSION,
        "status": "ready",  # Required by _is_ready_lock
        "image": "native-runtime",
        "pool": {
            "version": DEPENDENCY_POOL_VERSION,
            "python_entries": [],
            "system_entries": [],
            "npm_profile": None,
        },
    }
    (package_root / "environment.lock.json").write_text(
        json.dumps(env_lock_data, indent=2), encoding="utf-8"
    )

    return _MockPackage("test-native-runtime", package_root)


def test_native_runtime_stdio():
    """Test native runtime launch plan preparation."""
    print("Testing native runtime launch plan preparation...")

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        package_root = workspace / "package"
        runtime_root = workspace / "runtime"
        artifacts_root = runtime_root / "artifacts"
        workdir_root = runtime_root / "workdir"

        # Create minimal package
        package = create_minimal_package(package_root)

        # Prepare runtime directories
        for path in [runtime_root, artifacts_root, workdir_root]:
            path.mkdir(parents=True, exist_ok=True)

        # Launch native runtime
        launcher = NativeAgentRuntimeLauncher()
        print(f"✓ Launcher created: {type(launcher).__name__}")

        try:
            plan = launcher.prepare(
                package=package,
                runtime_root=runtime_root,
                artifacts_root=artifacts_root,
                workdir_root=workdir_root,
                runtime_instance_id="test-instance-001",
            )
            print(f"✓ Launch plan prepared: {plan.isolation} mode")
            print(f"  Command: {' '.join(plan.command)}")
            print(f"  Environment keys: {len(plan.environment)}")

            # Verify environment has expected bridge variables
            assert "AGENTFACTORY_BRIDGE_WORKDIR_ROOT" in plan.environment
            assert "AGENTFACTORY_BRIDGE_RUNTIME_ROOT" in plan.environment
            assert "AGENTFACTORY_BRIDGE_PACKAGE_ROOT" in plan.environment
            assert "AGENTFACTORY_BRIDGE_RUNTIME_INSTANCE_ID" in plan.environment
            assert plan.environment["AGENTFACTORY_BRIDGE_WORKDIR_ROOT"] == str(
                workdir_root.resolve()
            )
            assert plan.environment["AGENTFACTORY_BRIDGE_RUNTIME_INSTANCE_ID"] == "test-instance-001"
            print(f"✓ Environment variables configured correctly")
            print(f"  WORKDIR_ROOT: {plan.environment['AGENTFACTORY_BRIDGE_WORKDIR_ROOT']}")
            print(f"  RUNTIME_INSTANCE_ID: {plan.environment['AGENTFACTORY_BRIDGE_RUNTIME_INSTANCE_ID']}")

            # Verify PYTHONPATH is built (even if empty for no dependencies)
            pythonpath = plan.environment.get("PYTHONPATH", "")
            print(f"  PYTHONPATH entries: {len(pythonpath.split(':')) if pythonpath else 0}")

            # Verify command structure
            assert plan.command[0] == sys.executable  # Uses current Python
            assert "-m" in plan.command
            assert "agent_factory.agent_runtime_bridge.stdio_server" in plan.command
            print(f"✓ Command structure valid (Python + stdio_server module)")

            # Verify preflight status
            assert plan.preflight["status"] == "ok"
            assert plan.preflight["runtime_type"] == "native"
            assert plan.preflight["isolation"] == "native"
            print(f"✓ Preflight checks passed")

        except Exception as exc:
            print(f"✗ Test failed: {type(exc).__name__}: {exc}")
            import traceback

            traceback.print_exc()
            raise

    print("\n✅ Native runtime launch plan test passed!")
    print("Plan preparation validated without requiring full stdio_server initialization.")


if __name__ == "__main__":
    test_native_runtime_stdio()
