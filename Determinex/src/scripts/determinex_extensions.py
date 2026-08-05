#!/usr/bin/env python3
"""
determinex_extensions.py -- the addon/extension protocol (the VS Code-style host)
==============================================================================
What makes VS Code the go-to editor is not its features -- it is that anyone can
extend it. Determinex already has the three extension points that matter, each a
registry behind a stable contract:

    PROVIDERS  generate(prompt, temperature) -> str   (Claude, Codex, Gemini, local, addons)
    ORACLES    verify(workdir) -> OracleResult         (per-language ground truth)
    COMMANDS   the IDE command surface                 (panels call these)

This module formalizes them into ONE extension API and a loader, so a third
party -- or you -- drops a plugin that adds an AI provider, a language oracle, or
an IDE command, and Determinex hosts it. The correctness engine (oracle-bounded, no
hallucination, any-model-correct) stays the same; the ecosystem grows around it.

A plugin is any python module exposing `register(api)`:

    # plugins/my_addon.py
    def register(api):
        api.register_provider("myllm", env_key="MYLLM_KEY",
                              default_model="myllm/x", tier=3)
        api.register_oracle_hint("elixir", "mix test")
        # api.register_command(...)  # advanced

Loaded from: scripts/plugins/*.py, a DETERMINEX_PLUGINS dir, and Python entry-points
group "determinex.plugins". Nothing auto-grants authority; an addon provider is just
another generate() the oracle still judges.

CLI
---
    python scripts/determinex_extensions.py            # list loaded extensions
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


@dataclass
class ExtensionAPI:
    """What a plugin's register(api) receives. Thin, stable, additive."""

    loaded_providers: list[str] = field(default_factory=list)
    loaded_oracles: list[str] = field(default_factory=list)
    loaded_commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def register_provider(self, name: str, **kw) -> None:
        from determinex_providers import register_provider

        register_provider(name, **kw)
        self.loaded_providers.append(name)

    def register_oracle_hint(self, language: str, command: str, tier: int = 3) -> None:
        """Register a (planned) oracle for a language via the registry's stub path."""
        from determinex_oracle import Oracle, _stub, register

        probe = command.split()[0] if command else language
        register(
            Oracle(
                language,
                (language,),
                (probe,),
                f"addon oracle: {command}",
                _stub(language, command),
            )
        )
        self.loaded_oracles.append(language)

    def register_command(self, name: str, handler: Callable) -> None:
        """Advanced: register an out-of-band IDE command handler (addon panels)."""
        _ADDON_COMMANDS[name] = handler
        self.loaded_commands.append(name)


_ADDON_COMMANDS: dict[str, Callable] = {}


def _load_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(f"determinex_plugin_{path.stem}", path)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None


def load_extensions(api: ExtensionAPI | None = None) -> ExtensionAPI:
    """Discover + load all plugins. Safe: a broken plugin is skipped with a note."""
    api = api or ExtensionAPI()
    seen: set[str] = set()

    # 1. scripts/plugins/*.py and a DETERMINEX_PLUGINS dir
    dirs = [Path(_HERE) / "plugins"]
    if os.environ.get("DETERMINEX_PLUGINS"):
        dirs.append(Path(os.environ["DETERMINEX_PLUGINS"]))
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            if p.name.startswith("_") or p.stem in seen:
                continue
            seen.add(p.stem)
            try:
                mod = _load_module_from_path(p)
                if mod and hasattr(mod, "register"):
                    mod.register(api)
            except Exception as e:
                api.notes.append(f"plugin {p.name} failed: {e}")

    # 2. entry-points group "determinex.plugins"
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        group = (
            eps.select(group="determinex.plugins")
            if hasattr(eps, "select")
            else eps.get("determinex.plugins", [])
        )
        for ep in group:
            if ep.name in seen:
                continue
            seen.add(ep.name)
            try:
                reg = ep.load()
                reg(api)
            except Exception as e:
                api.notes.append(f"entry-point {ep.name} failed: {e}")
    except Exception:
        pass
    return api


def addon_commands() -> dict[str, Callable]:
    return dict(_ADDON_COMMANDS)


def main() -> int:
    api = load_extensions()
    print("=== Determinex extensions ===")
    print(f"  providers added by addons: {api.loaded_providers or '(none)'}")
    print(f"  oracles added by addons:   {api.loaded_oracles or '(none)'}")
    print(f"  commands added by addons:  {api.loaded_commands or '(none)'}")
    for n in api.notes:
        print(f"  ! {n}")
    # show the full provider roster after addons load
    from determinex_providers import available

    rdy = [k for k, v in available().items() if v]
    print(f"\n  AI providers ready (built-in + addons): {rdy}")
    print("  Drop a scripts/plugins/<name>.py with register(api) to add your own.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
