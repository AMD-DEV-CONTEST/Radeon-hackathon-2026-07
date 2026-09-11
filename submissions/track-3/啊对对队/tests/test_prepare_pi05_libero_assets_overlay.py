import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_pi05_libero_assets_overlay.py"
SPEC = importlib.util.spec_from_file_location("prepare_pi05_libero_assets_overlay", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class PreparePI05LiberoAssetsOverlayTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Windows symlink creation requires elevation")
    def test_creates_idempotent_verified_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "official-assets"
            package = root / "overlay" / "libero"
            scene = assets / module.REQUIRED_SCENE
            scene.parent.mkdir(parents=True)
            scene.write_bytes(b"verified-scene")
            package.mkdir(parents=True)

            first = module.prepare_assets_link(
                assets,
                package,
                expected_files=1,
                expected_bytes=len(b"verified-scene"),
            )
            second = module.prepare_assets_link(
                assets,
                package,
                expected_files=1,
                expected_bytes=len(b"verified-scene"),
            )

            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual((package / "assets").resolve(), assets.resolve())

    def test_refuses_to_replace_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "official-assets"
            package = root / "overlay" / "libero"
            scene = assets / module.REQUIRED_SCENE
            scene.parent.mkdir(parents=True)
            scene.write_bytes(b"verified-scene")
            (package / "assets").mkdir(parents=True)

            with self.assertRaises(RuntimeError):
                module.prepare_assets_link(
                    assets,
                    package,
                    expected_files=1,
                    expected_bytes=len(b"verified-scene"),
                )


if __name__ == "__main__":
    unittest.main()
