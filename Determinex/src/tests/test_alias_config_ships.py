"""The alias map must be findable in a shipped build, or no model call can resolve.

WHY THIS EXISTS
---------------
Found 2026-07-30. `litellm_config.yaml` is the alias map: it turns `determinex/engineer` into
`ollama/determinex-engineer-v11-dsl`. Without it, `_resolve_model` returns the alias UNCHANGED, and
`determinex/` is not a provider litellm knows — so the hive build loop cannot call any model at all.

It was shipped by NEITHER packaging path: absent from `bundle.resources` (Tauri) and absent from the
sidecar's PyInstaller data. And `_ROOT` is `resolve_repo_root()`, which in a PyInstaller sidecar is a
temp extraction directory rather than a checkout — so the single location the loader checked could
never hold it in a shipped build.

Measured by pointing `_ROOT` at an empty directory: **0 alias entries**, and every role alias resolved
to an unusable string. Third defect of this exact shape found today — works on the dev box because the
file is in the checkout, fails everywhere else. The other two were the agent-chat default model and the
safety gate blocking local calls, both of which depended on `.env`.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hive.api_client as A  # noqa: E402


def test_the_repo_config_resolves_role_aliases_to_ollama_tags():
    """Baseline: in a checkout this works, which is why the shipped-build failure was invisible."""
    A._alias_map = None
    assert len(A._load_alias_map()) > 0, "no aliases parsed from the repo's litellm_config.yaml"
    for alias in ("determinex/engineer", "determinex/observer", "determinex/sentinel"):
        real, _ = A._resolve_model(alias)
        assert real.startswith("ollama/"), (
            f"{alias!r} resolved to {real!r}, which is not an Ollama tag litellm can call"
        )


def test_an_unresolvable_alias_is_what_a_missing_config_produces():
    """Pins the failure mode, so the severity is not re-litigated later.

    With no config, the alias comes back unchanged — and `determinex/` is not a litellm provider, so
    the call fails. This asserts the mechanism rather than trusting the description of it.
    """
    saved_root, saved_map = A._ROOT, A._alias_map
    try:
        A._ROOT = Path(tempfile.mkdtemp())
        A._alias_map = None
        # Force the candidate list to the empty root only, so no real file is found.
        original = A._alias_config_candidates
        A._alias_config_candidates = lambda: [A._ROOT / "litellm_config.yaml"]  # type: ignore[assignment]
        try:
            assert A._load_alias_map() == {}
            real, _ = A._resolve_model("determinex/engineer")
            assert real == "determinex/engineer", "expected the alias to come back unchanged"
            assert not real.startswith("ollama/"), (
                "an unresolved alias must NOT look like a usable Ollama tag"
            )
        finally:
            A._alias_config_candidates = original  # type: ignore[assignment]
    finally:
        A._ROOT, A._alias_map = saved_root, saved_map
        A._alias_map = None


def test_the_loader_searches_beyond_the_repo_root():
    """The fix. One hardcoded location is what made a shipped build unable to resolve anything."""
    candidates = A._alias_config_candidates()
    assert len(candidates) > 1, (
        "the loader checks a single location again; in a PyInstaller sidecar that location is a temp "
        "extraction dir and will not contain the config"
    )
    joined = " ".join(str(c).lower() for c in candidates)
    # Beside the executable, and the ../../ layout Tauri preserves for bundle.resources.
    assert "_up_" in joined, "the Tauri '../../' resource layout is not searched"
    assert all(c.name == "litellm_config.yaml" for c in candidates)


def test_the_sidecar_build_actually_ships_the_config():
    """Searching for a file nobody ships would be the same bug with more code."""
    src = (ROOT / "bundler" / "build_hive_sidecar.py").read_text(encoding="utf-8")
    assert "--add-data" in src, "the sidecar build bundles no data files at all"
    assert "litellm_config.yaml" in src, (
        "build_hive_sidecar.py does not ship litellm_config.yaml, so the alias map will be absent "
        "from the sidecar and no role alias will resolve"
    )


def test_the_shipped_config_carries_no_literal_secrets():
    """It is safe to ship only because every credential is an os.environ reference. If a literal key
    ever lands here, bundling it would publish that key in every installer."""
    text = (ROOT / "litellm_config.yaml").read_text(encoding="utf-8")
    import re

    for match in re.finditer(r"api_key:\s*(\S+)", text):
        value = match.group(1)
        assert value.startswith("os.environ/"), (
            f"api_key {value!r} is not an os.environ reference. This file is bundled into the "
            f"installer, so a literal credential here ships to every user."
        )
    for marker in ("sk-", "ghp_", "sk-ant-"):
        assert marker not in text, f"literal {marker!r} credential in a file that ships"
