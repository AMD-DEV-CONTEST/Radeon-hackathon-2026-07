"""L1 SkillPack: a base model or LoRA packaged as a folder with manifest.json.

This replaces the hardcoded SkillRouter.DEFAULT_SKILL_MAP with directory scanning,
fulfilling the README "plug-and-play: drop a GGUF adapter in, gain a skill"
promise, and adds a base_fingerprint so a silent base mismatch (the hermes_s2
incident) is caught at load time instead of at runtime.

manifest.json schema
--------------------
{
  "name": "cybersec",
  "kind": "lora",                       // or "base"
  "skill": "security",                 // canonical skill tag this pack serves
  "base_fingerprint": "Qwen/Qwen3.6-27B",
  "vram_gb": 0.8,                      // extra VRAM this LoRA adds (GB)
  "domain_tags": ["security", "audit", "cve"],
  "route_keywords": ["audit", "vulnerab", "CVE", "injection"],
  "smoke_test": {"prompt": "audit this auth module",
                 "expect_contains": ["structured"]}
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillPack:
    name: str
    kind: str                      # "lora" | "base"
    skill: str | None = None       # legacy single skill tag (prefer `skills`)
    skills: list[str] = field(default_factory=list)  # canonical skill tags served (may be >1, e.g. btl3 -> tool+code)
    base_fingerprint: str = ""
    vram_gb: float = 0.0
    domain_tags: list[str] = field(default_factory=list)
    route_keywords: list[str] = field(default_factory=list)
    smoke_test: dict = field(default_factory=dict)
    path: str = ""

    @classmethod
    def load(cls, folder: str | Path) -> "SkillPack":
        folder = Path(folder)
        manifest = folder / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"no manifest.json in {folder}")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return cls(
            name=data["name"], kind=data.get("kind", "lora"),
            skill=data.get("skill"),
            skills=data.get("skills") or ([data["skill"]] if data.get("skill") else []),
            base_fingerprint=data.get("base_fingerprint", ""),
            vram_gb=float(data.get("vram_gb", 0.0)),
            domain_tags=data.get("domain_tags", []),
            route_keywords=data.get("route_keywords", []),
            smoke_test=data.get("smoke_test", {}),
            path=str(folder),
        )

    def validate_base(self, deployed_base: str) -> bool:
        """True if this pack's base_fingerprint matches the deployed base.
        An empty fingerprint is treated as 'unchecked' (legacy pack)."""
        if not self.base_fingerprint:
            return True
        return self.base_fingerprint == deployed_base


def scan_skillpacks(directory: str | Path) -> dict[str, SkillPack]:
    """Scan a directory for subfolders containing manifest.json.
    Returns {pack_name: SkillPack}. Folders without a manifest are skipped."""
    directory = Path(directory)
    packs: dict[str, SkillPack] = {}
    if not directory.exists():
        return packs
    for child in sorted(directory.iterdir()):
        if child.is_dir() and (child / "manifest.json").exists():
            try:
                pk = SkillPack.load(child)
                packs[pk.name] = pk
            except (json.JSONDecodeError, KeyError):
                # skip malformed packs rather than crash the whole scan
                continue
    return packs


def build_skill_map(packs: dict[str, SkillPack],
                    deployed_base: str = "") -> dict[str, str | None]:
    """Map canonical skill tag -> pack name (None = pure base).
    Mirrors DEFAULT_SKILL_MAP semantics but is generated from scanned packs.
    Base is always mapped to None (frozen base, no adapter). A pack whose
    base_fingerprint mismatches the deployed base is dropped (hermes_s2 guard)."""
    skill_map: dict[str, str | None] = {"base": None}
    for pk in packs.values():
        if pk.kind != "lora":
            continue
        if deployed_base and not pk.validate_base(deployed_base):
            continue
        for sk in pk.skills:
            skill_map[sk] = pk.name
    return skill_map
