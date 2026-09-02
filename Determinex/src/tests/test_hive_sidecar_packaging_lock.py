import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flat(text: str) -> str:
    """Collapse whitespace runs so a source grep survives the formatter.

    These guards match exact source text. `ruff format` changed the exact whitespace they
    keyed on and every one of them went silently vacuous -- reporting "found in no files",
    which is also what they print when the thing they guard has been deleted. Comparing
    flattened text keeps the check identical (same tokens, same order) while removing the
    dependency on spacing that a formatter is entitled to change at any time.
    """
    return re.sub(r"\s+", " ", text)


def test_hive_sidecar_builder_bundles_litellm_and_tiktoken_runtime_data():
    source = (ROOT / "bundler" / "build_hive_sidecar.py").read_text(encoding="utf-8")

    assert _flat('"--collect-data", "litellm"') in _flat(source)
    assert _flat('"--hidden-import", "tiktoken_ext"') in _flat(source)
    assert _flat('"--hidden-import", "tiktoken_ext.openai_public"') in _flat(source)


def test_hive_sidecar_runtime_modules_honor_determinex_root_env():
    modules = [
        ROOT / "scripts" / "hive" / "api_client.py",
        ROOT / "scripts" / "hive" / "budget.py",
        ROOT / "scripts" / "hive" / "compiler.py",
        ROOT / "scripts" / "hive" / "executor.py",
        ROOT / "scripts" / "hive" / "forge_daemon.py",
        ROOT / "scripts" / "hive" / "offline_observer.py",
    ]

    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "DETERMINEX_ROOT" in source, module
