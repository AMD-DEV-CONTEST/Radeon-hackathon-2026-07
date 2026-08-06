"""L2 tuner: turn a PlanResult into a concrete, safe deployment spec.

Enforces the 阵容铁律 (never pretend to run experts you can't fit) and derives
a conservative context size from available VRAM. Pure stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from screwshell.autotune.hardware import HardwareProfile
from screwshell.autotune.planner import PlanResult


@dataclass
class DeploymentSpec:
    base_model: str
    quant: str | None
    lora_pack_names: list[str]
    ctx_tokens: int
    degrade_level: str
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = ["== 部署规格 (tuner) =="]
        lines.append(f"底模：{self.base_model} @ {self.quant or '默认'}")
        if self.lora_pack_names:
            lines.append("挂载 LoRA：" + ", ".join(self.lora_pack_names))
        else:
            lines.append("挂载 LoRA：（无，纯基座）")
        lines.append(f"上下文窗口：{self.ctx_tokens} tokens")
        lines.append(f"降级档位：{self.degrade_level}")
        for n in self.notes:
            lines.append(f"· {n}")
        return "\n".join(lines)


def _ctx_for(vram_total: float | None, quant: str | None = None) -> int:
    """Context window derived from real VRAM via the documented capacity model.

    Replaces the old hardcoded 8192 ceiling (Layer2 §8.4): a 48 GB W7900 can run
    a much larger context. Falls back to 4096 when VRAM is unknown.
    """
    if vram_total is None:
        return 4096
    from screwshell.gateway.capacity import max_ctx_tokens
    return max_ctx_tokens(vram_total, quant or "Q4_K_M")


def resolve(plan: PlanResult,
            profile: HardwareProfile | None = None) -> DeploymentSpec:
    notes: list[str] = []
    lora_pack_names = list(plan.selected)

    # 阵容铁律: degrade honestly, never pretend to run experts we can't fit.
    if plan.degrade_level == "base_only":
        lora_pack_names = []
        notes.append("阵容铁律：显存不足挂载任何 LoRA，已退为纯基座（native "
                     "thinking），不强行挂载专家。")
    elif plan.degrade_level == "reduced":
        notes.append("显存有限，仅保留装得下的专家；未覆盖技能回退底模原生能力。")
    else:
        notes.append("全量阵容可用，所有调查技能均有专属专家。")

    if not plan.quant:
        notes.append("未推荐量化（无 GPU 探测），将使用底模默认量化。")

    ctx = _ctx_for(profile.vram_total_gb if profile else None, plan.quant)
    return DeploymentSpec(
        base_model=plan.base_model, quant=plan.quant,
        lora_pack_names=lora_pack_names, ctx_tokens=ctx,
        degrade_level=plan.degrade_level, notes=notes,
    )
