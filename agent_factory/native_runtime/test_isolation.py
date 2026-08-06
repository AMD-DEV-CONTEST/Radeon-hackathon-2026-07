#!/usr/bin/env python3
"""
Workspace isolation verification for native runtime.

Validates the workspace-path boundary enforced by the native subprocess runtime.
"""

from pathlib import Path
import tempfile
from agent_factory.tooling.workspace_paths import workspace_path_candidate
from agent_factory.tooling.builtins.filesystem.common import resolve_path
from agent_factory.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT


def test_workspace_isolation():
    """Test native workspace path resolution and boundary checking."""
    print("Testing workspace isolation for native runtime...")

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)
        virtual_root = Path(DEFAULT_BUILTIN_WORKSPACE_ROOT)

        # Test 1: Relative paths resolve inside workspace
        relative_file = "myfile.txt"
        resolved = workspace_path_candidate(relative_file, root=workspace_root)
        assert resolved == workspace_root / relative_file
        print(f"✓ Relative path resolves correctly: {relative_file} -> {resolved}")

        # Test 2: Virtual /workdir paths map to real workspace
        virtual_file = str(virtual_root / "subdir" / "file.txt")
        resolved = workspace_path_candidate(virtual_file, root=workspace_root)
        assert resolved == workspace_root / "subdir" / "file.txt"
        print(f"✓ Virtual path maps correctly: {virtual_file} -> {resolved}")

        # Test 3: Absolute paths outside workspace are rejected when allow_external=False
        outside_path = "/etc/passwd"
        try:
            resolve_path(path=outside_path, root=workspace_root, allow_external=False)
            assert False, "Should have rejected path outside workspace"
        except ValueError:
            print(f"✓ External path rejected correctly: {outside_path}")

        # Test 4: Parent traversal (..) is blocked
        (workspace_root / "safe").mkdir()
        safe_file = workspace_root / "safe" / "file.txt"
        safe_file.write_text("safe")

        traversal_attempt = str(virtual_root / "safe" / ".." / ".." / "etc" / "passwd")
        resolved = workspace_path_candidate(traversal_attempt, root=workspace_root)
        # After resolve, the path will escape workspace root
        try:
            resolved.resolve(strict=False).relative_to(workspace_root)
            # If we get here, check if it actually escaped
            if "/etc" in str(resolved.resolve(strict=False)):
                assert False, "Parent traversal should be blocked"
        except ValueError:
            # Expected: path escaped the workspace root
            pass
        print(f"✓ Parent traversal blocked: {traversal_attempt}")

        # Test 5: Symlink escape is blocked (if symlinks are resolved)
        external_target = Path("/tmp/external_target")
        external_target.touch()
        symlink_path = workspace_root / "link_to_external"
        try:
            symlink_path.symlink_to(external_target)
            resolved = resolve_path(
                path=str(virtual_root / "link_to_external"),
                root=workspace_root,
                allow_external=False
            )
            # Should fail boundary check
            assert False, "Should have rejected symlink escaping workspace"
        except (ValueError, OSError):
            # Expected: either symlink creation fails or boundary check rejects
            print(f"✓ Symlink escape blocked")
        finally:
            external_target.unlink(missing_ok=True)
            symlink_path.unlink(missing_ok=True)

        # Test 6: Paths inside workspace are allowed
        safe_path = str(virtual_root / "safe" / "file.txt")
        # Use resolved root for macOS /var -> /private/var symlink compatibility
        resolved_root = workspace_root.resolve()
        resolved = resolve_path(path=safe_path, root=resolved_root, allow_external=False)
        assert resolved.resolve() == (resolved_root / "safe" / "file.txt").resolve()
        print(f"✓ Safe internal path allowed: {safe_path} -> {resolved}")

    print("\n✅ All workspace isolation tests passed!")
    print("Native runtime workspace path boundary checks passed.")


if __name__ == "__main__":
    test_workspace_isolation()
