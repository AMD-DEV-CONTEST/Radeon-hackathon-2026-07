from radeonvla.paths import ASSETS_DIR, ROBOT_DIR, YCB_DIR
from radeonvla.protocol import BOWL_YCB, FRUIT_YCB
from radeonvla.setup_assets import REQUIRED_OBJECT_FILES, setup_assets, verify_checksums


def test_required_ycb_objects_present_after_setup() -> None:
    setup_assets(force=False, download=False)
    for name in (*FRUIT_YCB.values(), BOWL_YCB):
        folder = YCB_DIR / name
        assert folder.is_dir(), name
        for fname in REQUIRED_OBJECT_FILES:
            assert (folder / fname).is_file(), f"{name}/{fname}"
    assert (ROBOT_DIR / "panda.xml").is_file()


def test_sha256sums_verify_when_present() -> None:
    if not (ASSETS_DIR / "SHA256SUMS").is_file():
        return
    verify_checksums(strict=True)
