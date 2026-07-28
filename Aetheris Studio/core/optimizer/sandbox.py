"""
HIP Template Sandbox & Immutable Isolation Manager.
Handles template cloning into an isolated sandbox folder and maintains immutable .orig backups to guarantee zero corruption of official production templates.
"""

import shutil
from pathlib import Path
from typing import Optional


class PathContainmentError(RuntimeError):
    """A resolved template/backup path fell outside vte_templates_dir --
    refuses to touch it rather than risk writing/reading outside the
    directory this sandbox is scoped to (see _require_contained)."""


class TemplateSandbox:
    def __init__(self, sandbox_dir: Optional[Path] = None):
        current_file = Path(__file__).resolve()
        studio_root = current_file.parent.parent.parent
        hackathon_root = studio_root.parent

        possible_vte_dir = hackathon_root / "VTE" / "vte" / "compiler" / "templates" / "rdna"
        if possible_vte_dir.exists():
            self.vte_templates_dir = possible_vte_dir
        else:
            self.vte_templates_dir = studio_root / "vte" / "compiler" / "templates" / "rdna"

        self.sandbox_dir = sandbox_dir or (current_file.parent / "sandbox")
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

    def _require_contained(self, path: Path) -> Path:
        """Resolves `path` and refuses it unless it lives inside
        self.vte_templates_dir -- a cheap, real check (not just string
        prefixing: resolve() follows symlinks and normalizes ../ segments)
        against a crafted kernel_name escaping the templates directory, or
        a symlink swapped in after the fact. Same defensive posture as
        Hyperloom's own backup-restore path revalidation."""
        resolved = path.resolve()
        try:
            resolved.relative_to(self.vte_templates_dir.resolve())
        except ValueError:
            raise PathContainmentError(
                f"Refusing to touch path outside vte_templates_dir: {resolved}"
            )
        return resolved

    def clone_official_template(self, kernel_name: str) -> Path:
        official_file = self._require_contained(self.vte_templates_dir / f"{kernel_name}.hip.template")
        if not official_file.exists():
            raise FileNotFoundError(f"Official template not found: {official_file}")

        # Always refreshed (no "only if missing" guard): .orig must always
        # reflect the official template as it stood immediately before THIS
        # test/candidate cycle started. The old guard left .orig pinned to
        # whichever version existed the very first time a candidate was ever
        # cloned -- after a later promotion changed the official file, a
        # rollback would silently jump all the way back past that promotion
        # instead of undoing just the most recent one, and an official file
        # edited by any other means between clones would leave .orig stale
        # with no way to notice.
        orig_backup = self._require_contained(self.vte_templates_dir / f"{kernel_name}.hip.template.orig")
        shutil.copy2(official_file, orig_backup)

        target_sandbox_file = self.sandbox_dir / f"{kernel_name}_candidate.hip.template"
        shutil.copy2(official_file, target_sandbox_file)
        return target_sandbox_file

    def restore_official_from_backup(self, kernel_name: str) -> bool:
        official_file = self._require_contained(self.vte_templates_dir / f"{kernel_name}.hip.template")
        orig_backup = self._require_contained(self.vte_templates_dir / f"{kernel_name}.hip.template.orig")
        if orig_backup.exists():
            shutil.copy2(orig_backup, official_file)
            return True
        return False

    def cleanup_sandbox(self) -> None:
        if self.sandbox_dir.exists():
            for item in self.sandbox_dir.glob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                    except OSError:
                        pass
