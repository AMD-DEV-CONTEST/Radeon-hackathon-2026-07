from __future__ import annotations

import re

TOOL_ALIASES: dict[str, list[str]] = {
    "7zip": ["7z", "p7zip", "mcmilk__7-zip", "ip7z__7zip"],
    "angle": ["angle-grinder", "angle_grinder", "ag", "rcoh__angle-grinder"],
    "rg": ["ripgrep", "burntsushi__ripgrep"],
    "fd": ["fd-find", "sharkdp__fd"],
    "bat": ["batcat", "sharkdp__bat", "astaxie__bat"],
    "gdu": ["dundee__gdu"],
    "fzf": ["junegunn__fzf"],
    "peco": ["peco__peco"],
    "xsv": ["burntsushi__xsv"],
    "mdbook": ["rust-lang__mdbook"],
    "atlas": ["ariga__atlas"],
    "fx": ["antonmedv__fx"],
}


def aliases_for_tool(tool: str) -> list[str]:
    key = normalized_tool_name(tool)
    aliases = set()
    aliases.add(key)
    aliases.add(normalized_repo_name(tool))
    for canonical, values in TOOL_ALIASES.items():
        normalized_values = {normalized_tool_name(value) for value in values}
        normalized_values.update(normalized_slug(value) for value in values)
        if (
            key == canonical
            or key in normalized_values
            or normalized_repo_name(tool) in normalized_values
        ):
            aliases.add(canonical)
            aliases.update(normalized_values)
    return sorted(alias for alias in aliases if alias)


def normalized_tool_name(value: str) -> str:
    value = value.strip().lower()
    if "__" in value:
        value = value.split("__", 1)[1]
    value = value.split(".", 1)[0]
    return _normalize(value)


def normalized_repo_name(value: str) -> str:
    value = value.strip().lower()
    if "__" in value:
        value = value.split("__", 1)[1]
    return _normalize(value)


def normalized_slug(value: str) -> str:
    return _normalize(value.strip().lower())


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value)
