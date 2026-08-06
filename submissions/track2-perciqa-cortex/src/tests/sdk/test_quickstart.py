from __future__ import annotations


def test_quickstart_module_imports():
    import importlib
    mod = importlib.import_module("examples.quickstart")
    assert hasattr(mod, "main")
