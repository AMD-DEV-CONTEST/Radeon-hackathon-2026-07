# -*- coding: utf-8 -*-
"""Shell-level tests for scripts/setup_comfyui_radeon.sh (R02).

Covers what the R02 acceptance criteria actually require:

- ``bash -n`` (syntax only) passes.
- ``--help`` documents every SPRITE_WORKSHOP_* environment variable.
- ``--dry-run`` runs end to end against redirected, empty temp paths with
  zero filesystem/network side effects, and its output makes every
  mutating command inspectable (git clone/checkout, pip install, curl
  download) plus states the pinned ComfyUI ref and checkpoint SHA-256.
- The pure helper functions (sha256 compare, requirements filtering) are
  exercised directly by sourcing the script (which only defines functions;
  ``main`` is guarded and does not run on source), so hash-match,
  hash-mismatch and requirements-filtering behaviour is verified without
  any network access or a real ComfyUI/pip/git environment.

Deliberately NOT covered here (out of scope for this task / requires a
real Radeon box): actually cloning ComfyUI, creating a real venv, pip
installing requirements, or downloading the ~6.9 GB checkpoint. That is
exercised live by the later R04 task.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "setup_comfyui_radeon.sh"

BASH = shutil.which("bash")


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestScriptExists(unittest.TestCase):
    def test_script_file_present_and_executable_shebang(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file())
        with SCRIPT_PATH.open("r", encoding="utf-8") as fh:
            first_line = fh.readline()
        self.assertTrue(first_line.startswith("#!"))


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestSyntax(unittest.TestCase):
    def test_bash_dash_n_passes(self) -> None:
        result = _run([BASH, "-n", str(SCRIPT_PATH)])
        self.assertEqual(
            result.returncode,
            0,
            msg=f"bash -n failed:\nstdout={result.stdout}\nstderr={result.stderr}",
        )


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestHelp(unittest.TestCase):
    def test_help_documents_every_env_var(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--help"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        expected_vars = [
            "SPRITE_WORKSHOP_COMFY_ROOT",
            "SPRITE_WORKSHOP_COMFY_VENV",
            "SPRITE_WORKSHOP_ROCM_SITE",
            "SPRITE_WORKSHOP_BASE_PYTHON",
            "SPRITE_WORKSHOP_COMFY_REPO",
            "SPRITE_WORKSHOP_COMFY_REF",
            "SPRITE_WORKSHOP_MODEL_DIR",
            "SPRITE_WORKSHOP_MODEL_FILENAME",
            "SPRITE_WORKSHOP_MODEL_URL",
            "SPRITE_WORKSHOP_MODEL_SHA256",
            "SPRITE_WORKSHOP_MODEL_LICENSE_URL",
            "SPRITE_WORKSHOP_HF_TOKEN",
        ]
        for var in expected_vars:
            self.assertIn(var, result.stdout, msg=f"--help missing {var}")

    def test_help_never_mentions_apt(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--help"])
        self.assertNotIn("apt-get", result.stdout)
        self.assertNotIn("apt ", result.stdout)


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestDryRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="r02-dry-run-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.comfy_root = root / "ComfyUI"
        self.comfy_venv = root / "comfyui-venv"
        self.rocm_site = root / "rocm-site"
        self.model_dir = root / "models" / "checkpoints"
        self.env = {
            "PATH": __import__("os").environ.get("PATH", ""),
            "SPRITE_WORKSHOP_COMFY_ROOT": str(self.comfy_root),
            "SPRITE_WORKSHOP_COMFY_VENV": str(self.comfy_venv),
            "SPRITE_WORKSHOP_ROCM_SITE": str(self.rocm_site),
            "SPRITE_WORKSHOP_BASE_PYTHON": sys.executable or "python3",
            "SPRITE_WORKSHOP_MODEL_DIR": str(self.model_dir),
        }

    def test_dry_run_exits_zero_and_touches_nothing(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--dry-run"], env=self.env)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"--dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        # Zero side effects: none of the redirected paths should exist.
        self.assertFalse(self.comfy_root.exists())
        self.assertFalse(self.comfy_venv.exists())
        self.assertFalse(self.model_dir.exists())

    def test_dry_run_output_makes_key_commands_inspectable(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--dry-run"], env=self.env)
        combined = result.stdout + result.stderr
        # Pinned ComfyUI ref and checkpoint SHA-256 (copied from
        # PUBLIC_KNOWLEDGE.md) must be visible so a reviewer can check them.
        self.assertIn("0.30.0", combined)
        self.assertIn(
            "e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26",
            combined,
        )
        # Every mutating step must be represented as an inspectable command.
        self.assertIn("git", combined)
        self.assertIn("clone", combined)
        self.assertIn("checkout", combined)
        self.assertIn("venv", combined)
        self.assertIn("pip", combined)
        self.assertIn("curl", combined)
        # The redacted download header must never leak an actual token.
        # `printf %q` shell-quotes the dry-run command differently across
        # bash builds: a "typical" GNU/Linux bash wraps the whole string in
        # single quotes (`'<redacted>'`), while Cygwin's GNU bash instead
        # backslash-escapes each special character individually
        # (`\<redacted\>`). Undo that per-character backslash-escaping
        # before asserting so the check is robust to either quoting style,
        # while still failing if the placeholder text itself is missing.
        unescaped = combined.replace("\\<", "<").replace("\\>", ">")
        self.assertIn("<redacted>", unescaped)
        self.assertNotIn("Bearer hf_", combined)

    def test_dry_run_never_calls_apt(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--dry-run"], env=self.env)
        combined = result.stdout + result.stderr
        self.assertNotIn("apt-get", combined)
        self.assertNotIn("apt install", combined)
        self.assertNotIn("apt upgrade", combined)

    def test_dry_run_never_installs_torch(self) -> None:
        result = _run([BASH, str(SCRIPT_PATH), "--dry-run"], env=self.env)
        combined = result.stdout + result.stderr
        self.assertNotIn("install torch", combined)
        self.assertNotIn("pip install --no-input torch", combined)


@unittest.skipUnless(BASH, "bash not available on this machine")
class TestPureHelpersViaSource(unittest.TestCase):
    """Source the script (main() is guarded, so nothing runs) and call its
    pure helper functions directly with local fixtures -- no network, no
    real git/pip/ComfyUI required."""

    def _source_and_run(self, snippet: str, cwd: Path) -> subprocess.CompletedProcess:
        # The script sources under `set -euo pipefail`; sourcing it imports
        # that into this shell too. The snippets below deliberately call a
        # helper that returns non-zero (e.g. verify_model_file's documented
        # 10/20 exit codes) and then inspect "$?" on the *next* command --
        # under `set -e` that non-zero return would abort the script before
        # the trailing `echo "rc=$?"` ever runs. Disable `set -e` right
        # after sourcing (functions/exit-code conventions under test are
        # untouched) so the snippet's own commands run to completion.
        script = f'source "{SCRIPT_PATH}"\nset +e\n{snippet}\n'
        return _run([BASH, "-c", script], cwd=str(cwd))

    def test_verify_model_file_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r02-model-") as tmp:
            tmp_path = Path(tmp)
            result = self._source_and_run(
                'verify_model_file "missing.safetensors" "deadbeef"; echo "rc=$?"',
                cwd=tmp_path,
            )
            self.assertIn("missing", result.stdout)
            self.assertIn("rc=10", result.stdout)

    def test_verify_model_file_hash_match_is_idempotent_ok(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r02-model-") as tmp:
            tmp_path = Path(tmp)
            model = tmp_path / "model.bin"
            model.write_bytes(b"hello world")
            import hashlib

            digest = hashlib.sha256(b"hello world").hexdigest()
            result = self._source_and_run(
                f'verify_model_file "model.bin" "{digest}"; echo "rc=$?"',
                cwd=tmp_path,
            )
            self.assertIn("ok", result.stdout)
            self.assertIn("rc=0", result.stdout)

    def test_verify_model_file_hash_mismatch_fails_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r02-model-") as tmp:
            tmp_path = Path(tmp)
            model = tmp_path / "model.bin"
            model.write_bytes(b"hello world")
            result = self._source_and_run(
                'verify_model_file "model.bin" "0000000000000000000000000000000000000000000000000000000000000000"; echo "rc=$?"',
                cwd=tmp_path,
            )
            self.assertIn("mismatch", result.stdout)
            self.assertIn("rc=20", result.stdout)
            # The function itself must never delete or touch the file.
            self.assertTrue(model.exists())
            self.assertEqual(model.read_bytes(), b"hello world")

    def test_filter_requirements_drops_only_torch_stack(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r02-req-") as tmp:
            tmp_path = Path(tmp)
            req = tmp_path / "requirements.txt"
            req.write_text(
                "\n".join(
                    [
                        "numpy>=1.26",
                        "torch>=2.2",
                        "torchvision",
                        "torchaudio==2.9.1",
                        "Pillow",
                        "# a comment mentioning torch should survive",
                        "torchsde",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            result = self._source_and_run(
                'filter_requirements "requirements.txt"',
                cwd=tmp_path,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            kept = result.stdout
            self.assertIn("numpy>=1.26", kept)
            self.assertIn("Pillow", kept)
            self.assertIn("torchsde", kept)
            self.assertIn("a comment mentioning torch should survive", kept)
            self.assertNotIn("torch>=2.2", kept)
            self.assertNotIn("torchvision", kept)
            self.assertNotIn("torchaudio==2.9.1", kept)


if __name__ == "__main__":
    unittest.main()
