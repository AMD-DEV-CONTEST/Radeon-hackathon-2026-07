"""L2 planner: choose the base quant + LoRA lineup for a given HardwareProfile.

Lightweight llmfit-style 4-dimension scoring:
  fit      : does base (+LoRAs) fit in usable VRAM?
  speed    : estimated decode tok/s from the hardware profile
  quality  : quant quality (Q8 > Q4 > Q2)
  coverage : fraction of the 5 investigation skills covered by selected packs
Then a degrade ladder: full -> reduced -> base_only. This is the "阵容铁律":
never pretend to run experts you can't fit; degrade honestly to pure base.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from screwshell.autotune.hardware import (
    HardwareProfile, QUANT_VRAM_GB, _QUANT_QUALITY, BASE_MODEL,
)
from screwshell.autotune.skillpack import SkillPack

CANONICAL_SKILLS = ["tool", "code", "agent", "security", "doc"]


@dataclass
class PlanResult:
    base_model: str
    quant: str | None
    base_vram_gb: float
    selected: list[str]            # selected LoRA pack names
    covered_skills: list[str]
    degrade_level: str             # "full" | "reduced" | "base_only"
    scores: dict = field(default_factory=dict)
    report: str = ""

    def human_report(self) -> str:
        return self.report


def plan(profile: HardwareProfile,
         packs: dict[str, SkillPack],
         target_base: str = BASE_MODEL,
         quant_map: dict | None = None) -> PlanResult:
    qmap = quant_map or QUANT_VRAM_GB
    quant = profile.recommend_quant(qmap)
    base_vram = qmap.get(quant, 18.9) if quant else 18.9
    usable = profile.vram_usable_gb or 0.0

    # budget left for LoRAs after the base
    budget = usable - base_vram
    # greedily add LoRA packs, prioritizing coverage of missing skills and
    # preferring smaller packs (fit more experts)
    candidates = [
        p for p in packs.values()
        if p.kind == "lora" and (not target_base or p.validate_base(target_base))
    ]
    candidates.sort(
        key=lambda p: (p.vram_gb, 0 if any(s in CANONICAL_SKILLS for s in p.skills) else 1))

    selected: list[str] = []
    covered: set[str] = set()
    for pk in candidates:
        if not pk.skills:
            continue
        # only pick a pack if it adds at least one uncovered canonical skill
        new_skills = [s for s in pk.skills if s not in covered]
        if budget - pk.vram_gb >= 0 and new_skills:
            selected.append(pk.name)
            covered.update(pk.skills)
            budget -= pk.vram_gb

    # 4-dimension scoring (each 0..1 except speed which is tok/s)
    fit = profile.fit_score(base_vram + sum(packs[n].vram_gb for n in selected))
    speed = profile.estimate_toks(quant) or 0.0
    quality = _QUANT_QUALITY.get(quant, 0.78) if quant else 0.0
    coverage = len(covered & set(CANONICAL_SKILLS)) / len(CANONICAL_SKILLS)

    if coverage >= 1.0:
        degrade = "full"
    elif coverage > 0.0:
        degrade = "reduced"
    else:
        degrade = "base_only"
        selected = []

    scores = {
        "fit": round(fit, 2), "speed_toks": speed,
        "quality": round(quality, 2), "coverage": round(coverage, 2),
    }
    report = _build_report(profile, target_base, quant, base_vram,
                           selected, covered, degrade, scores)
    return PlanResult(
        base_model=target_base, quant=quant, base_vram_gb=base_vram,
        selected=selected, covered_skills=sorted(covered),
        degrade_level=degrade, scores=scores, report=report,
    )


def _build_report(profile, base, quant, base_vram, selected, covered,
                  degrade, scores) -> str:
    lines = [
        "== ScrewShell 部署规划报告 ==",
        f"检测到显卡：{profile.name}（{profile.vendor}），显存 {profile.vram_total_gb} GB",
    ]
    if quant:
        lines.append(f"推荐底模量化：{base} @ {quant}（约占 {base_vram} GB）")
    else:
        lines.append("未探测到可用 GPU，按最低配处理。")
    lines.append(f"选中 LoRA 专家：{', '.join(selected) if selected else '（无）'}")
    lines.append(f"覆盖技能：{', '.join(sorted(covered)) if covered else '（无，仅底模）'}")
    lines.append(f"降级档位：{degrade}")
    if degrade == "base_only":
        lines.append("⚠️ 显存不足以加载任何 LoRA，已如实降级为纯基座（native thinking）。"
                     "不强行挂载专家。")
    elif degrade == "reduced":
        lines.append("ℹ️ 显存有限，仅保留可装下的专家；未覆盖技能回退到底模原生能力。")
    else:
        lines.append("✅ 全量阵容可用，所有调查技能均有专属专家。")
    lines.append(f"评分：fit={scores['fit']} speed={scores['speed_toks']}tok/s "
                 f"quality={scores['quality']} coverage={scores['coverage']}")
    return "\n".join(lines)
