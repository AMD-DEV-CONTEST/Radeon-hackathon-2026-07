"""Does the model installer actually install the models the product needs?

WHY THIS EXISTS
---------------
Until 2026-07-29 a fresh install could not reach a working state: `roles.rs` defaults
builder and monitor to `determinex/engineer` and `determinex/observer`, and nothing could
obtain those models. `model_puller.rs` pulls only public qwen base models and pointed at
GitHub Releases that hold no GGUF; the HuggingFace repos were private; `register_models.ps1`
registers from disk and told the user to "run the RunPod training pipeline first". There was
no download step anywhere.

`scripts/setup/install_determinex_models.py` closes that gap. The failure mode worth
guarding is subtle: the installer could succeed loudly while installing tags that no role
resolves to, leaving `work-readiness` still reporting missing coverage. So these tests pin
the installer's tags against the SAME sources the product reads, imported rather than
restated -- a copied list is exactly what drifts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

_INSTALLER = REPO_ROOT / "scripts" / "setup" / "install_determinex_models.py"


def _installer():
    """Load the installer by path.

    It must be registered in sys.modules BEFORE exec_module: the module defines a
    `@dataclass` under `from __future__ import annotations`, and dataclasses resolves the
    annotation namespace via `sys.modules.get(cls.__module__).__dict__`. Without the
    registration that lookup returns None and every test here dies with
    `AttributeError: 'NoneType' object has no attribute '__dict__'` from inside
    dataclasses.py -- an error that says nothing about the actual code under test.
    """
    name = "determinex_model_installer"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, _INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_installer_exists_and_declares_models():
    mod = _installer()
    assert len(mod.MODELS) == 3, "one model per fine-tuned role"


def test_every_installed_tag_is_a_current_model_id():
    """THE regression. Installing tags nothing resolves to would leave a fresh install just
    as broken while reporting success."""
    from scripts.models.model_router import CURRENT_MODEL_IDS

    mod = _installer()
    current = set(CURRENT_MODEL_IDS)
    installed = {m.tag for m in mod.MODELS}
    assert installed == current, (
        f"installer tags {sorted(installed)} != CURRENT_MODEL_IDS {sorted(current)}"
    )


def test_the_installer_covers_the_roles_ctx_config_assigns():
    """hive/ctx_config.py is what the running hive reads. Every model it assigns must be
    something the installer can actually provide."""
    from hive.ctx_config import _MODEL_TAGS

    mod = _installer()
    installed = {m.tag for m in mod.MODELS}
    for role, tag in _MODEL_TAGS.items():
        assert tag in installed, (
            f"ctx_config assigns {role}={tag}, which the installer cannot install"
        )


def test_no_installed_tag_is_a_superseded_model():
    from scripts.models.model_router import STALE_MODEL_IDS

    mod = _installer()
    stale = set(STALE_MODEL_IDS)
    for spec in mod.MODELS:
        assert spec.tag not in stale, f"{spec.tag} is a superseded model id"


def test_download_urls_are_well_formed():
    """The `/resolve/main/` segment is easy to omit -- I did exactly that while spot-checking
    these by hand and got three 404s, which briefly looked like the repos were still
    private. The URL the script builds is the one that matters."""
    mod = _installer()
    for spec in mod.MODELS:
        assert spec.url.startswith("https://huggingface.co/"), spec.url
        assert "/resolve/main/" in spec.url, f"missing /resolve/main/ in {spec.url}"
        assert spec.url.endswith(".gguf"), spec.url
        assert spec.repo in spec.url and spec.gguf in spec.url


def test_check_mode_reports_missing_without_touching_the_network(monkeypatch, capsys):
    """--check must be a fast, side-effect-free report. It is what a UI would call to decide
    whether to offer the install at all."""
    mod = _installer()
    monkeypatch.setattr(mod, "installed_tags", lambda: set())
    monkeypatch.setattr(mod, "ollama_available", lambda: True)
    monkeypatch.setattr(sys, "argv", ["prog", "--check"])
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 1, "missing models must be a non-zero exit so a caller can branch on it"
    assert "3 of 3 missing" in out
    for spec in mod.MODELS:
        assert spec.tag in out


def test_check_mode_is_clean_when_everything_is_present(monkeypatch, capsys):
    mod = _installer()
    monkeypatch.setattr(mod, "installed_tags", lambda: {m.tag for m in mod.MODELS})
    monkeypatch.setattr(mod, "ollama_available", lambda: True)
    monkeypatch.setattr(sys, "argv", ["prog", "--check"])
    assert mod.main() == 0
    assert "0 of 3 missing" in capsys.readouterr().out


def test_missing_ollama_is_reported_rather_than_crashing(monkeypatch, capsys):
    """A new user may not have Ollama yet. That deserves an instruction, not a traceback."""
    mod = _installer()
    monkeypatch.setattr(mod, "installed_tags", lambda: set())
    monkeypatch.setattr(mod, "ollama_available", lambda: False)
    monkeypatch.setattr(sys, "argv", ["prog"])
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "ollama.com" in out.lower()


def test_dry_run_downloads_nothing(monkeypatch, capsys, tmp_path):
    mod = _installer()
    called = []
    monkeypatch.setattr(mod, "installed_tags", lambda: set())
    monkeypatch.setattr(mod, "ollama_available", lambda: True)
    monkeypatch.setattr(mod, "download", lambda *a, **k: called.append(a))
    monkeypatch.setattr(mod, "register", lambda *a, **k: called.append(a))
    monkeypatch.setattr(sys, "argv", ["prog", "--dry-run", "--dest", str(tmp_path)])
    assert mod.main() == 0
    assert called == [], "dry run performed real work"
    assert "would download" in capsys.readouterr().out


def test_a_checksum_mismatch_fails_rather_than_registering(tmp_path):
    """A truncated multi-gigabyte GGUF fails inside `ollama create` with what looks like a
    corrupt-model error. Catching it at the checksum keeps the diagnosis honest."""
    mod = _installer()
    f = tmp_path / "x.gguf"
    f.write_bytes(b"not the real weights")
    assert mod.verify(f, "0" * 64) is False
    # No published checksum is not a failure -- it is an unverifiable download, reported.
    assert mod.verify(f, None) is True


def test_checksum_lookup_queries_the_endpoint_that_actually_carries_lfs_data():
    """Structural, so it holds without network.

    The first version of remote_sha256 queried /api/models/<repo> and read `lfs` off the
    sibling entry. That endpoint returns siblings with only `rfilename`, so it ALWAYS
    returned None and verify() fell through to "no published checksum, skipping" -- the
    integrity check was a no-op on every real download. Found by running a 1.65 GB fetch and
    noticing the digest print as (none).

    Also pins the header fallback away from plain `etag`: for these files that is the
    xetHash, a different digest (49c736f8... vs the real cca14e35...), so trusting it would
    fail every comparison and look like universal corruption.
    """
    src = _INSTALLER.read_text(encoding="utf-8")
    assert "blobs=true" in src, "checksum lookup must query the endpoint that returns lfs data"
    assert "X-Linked-ETag" in src, "header fallback must use X-Linked-ETag"
    body = src[src.index("def remote_sha256") : src.index("def download")]
    assert '"etag"' not in body.lower().replace("x-linked-etag", ""), (
        "must not fall back to the plain etag header, which is the xetHash"
    )


def test_subprocess_output_is_decoded_as_utf8():
    """`text=True` alone decodes with the locale codepage. On Windows that is cp1252, and
    ollama emits non-ASCII progress, which raised
    `UnicodeDecodeError: charmap codec can't decode byte 0x8f` during a real ollama create --
    the command had SUCCEEDED and the crash was purely in reading its output. Worst possible
    place to drop a user: mid-install, after the download."""
    src = _INSTALLER.read_text(encoding="utf-8")
    run_body = src[src.index("def _run") : src.index("def ollama_available")]
    assert 'encoding="utf-8"' in run_body
    assert 'errors="replace"' in run_body


def test_the_frozen_sidecar_does_not_store_weights_under_temp(monkeypatch):
    """The shipped path, which is the one that mattered and the one nothing checked.

    ROOT is derived from __file__, and inside the PyInstaller onefile sidecar that is the
    extraction directory under %TEMP%. So the default storage location in the SHIPPED product
    was a temp path -- verified live, the sidecar reported
    `gguf storage : C:\\Users\\<user>\\AppData\\Local\\Temp\\.determinex-models`. Several GB of
    weights, plus resumable .part files, sitting somewhere a temp cleaner or a reboot removes.
    """
    mod = _installer()
    monkeypatch.delenv("DETERMINEX_MODELS_DIR", raising=False)
    monkeypatch.setattr(mod.sys, "frozen", True, raising=False)
    # A real checkout has a .env that would short-circuit the fallback; ignore it here so the
    # frozen branch is what gets exercised.
    monkeypatch.setattr(mod, "ROOT", Path("C:/Users/x/AppData/Local/Temp/_MEI123456"))

    resolved = str(mod.models_dir()).lower()
    assert "temp" not in resolved and "_mei" not in resolved, (
        f"frozen sidecar would store GGUFs at {resolved}, which is ephemeral"
    )


def test_an_explicit_models_dir_always_wins():
    mod = _installer()
    import os as _os

    prior = _os.environ.get("DETERMINEX_MODELS_DIR")
    _os.environ["DETERMINEX_MODELS_DIR"] = r"D:\somewhere\models"
    try:
        assert str(mod.models_dir()) == r"D:\somewhere\models"
    finally:
        if prior is None:
            _os.environ.pop("DETERMINEX_MODELS_DIR", None)
        else:
            _os.environ["DETERMINEX_MODELS_DIR"] = prior


@pytest.mark.network
def test_every_published_model_exposes_a_checksum_and_is_public():
    """Opt-in network check. Proves the three repos are reachable ANONYMOUSLY (no token) and
    that each publishes a usable sha256 -- the two facts a fresh install depends on."""
    import urllib.error

    mod = _installer()
    for spec in mod.MODELS:
        try:
            digest = mod.remote_sha256(spec)
        except urllib.error.URLError as exc:
            pytest.skip(f"network unavailable: {exc}")
        assert digest and len(digest) == 64, f"{spec.tag}: no usable checksum ({digest})"
