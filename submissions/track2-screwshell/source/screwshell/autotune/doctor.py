"""L2 preflight checks (deployment guardrails).

Run BEFORE launching the server: verify the base GGUF exists, every selected
LoRA adapter exists on disk, base fingerprints match (hermes_s2 guard), and the
target port is free (or warn that --takeover will be needed). Pure stdlib.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

from screwshell.autotune.hardware import HardwareProfile
from screwshell.autotune.skillpack import SkillPack


@dataclass
class CheckItem:
    level: str          # "error" | "warn" | "ok"
    msg: str


@dataclass
class PreflightReport:
    items: list[CheckItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.items)

    def add(self, level: str, msg: str) -> None:
        self.items.append(CheckItem(level, msg))

    def report(self) -> str:
        lines = ["== 部署前预检 (doctor) =="]
        mark = {"error": "❌", "warn": "⚠️", "ok": "✅"}
        for it in self.items:
            lines.append(f"{mark.get(it.level, '-')} {it.msg}")
        lines.append("结论：通过，可以启动" if self.ok
                     else "结论：存在阻断项，请先解决再启动")
        return "\n".join(lines)


def _port_in_use(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def preflight(model_path: str, loras_dir: str, selected: list[str],
              packs: dict[str, SkillPack], deployed_base: str,
              port: int = 8080, profile: HardwareProfile | None = None
              ) -> PreflightReport:
    rep = PreflightReport()

    # 1. base model file
    if model_path:
        if Path(model_path).exists():
            rep.add("ok", f"底模文件存在：{model_path}")
        else:
            rep.add("error", f"底模文件缺失：{model_path}")
    else:
        rep.add("warn", "未提供 --model，跳过底模文件检查")

    # 2. LoRA adapters on disk
    ldir = Path(loras_dir) if loras_dir else None
    for name in (selected or []):
        pk = packs.get(name)
        if pk is None:
            rep.add("error", f"选中的技能包未扫描到：{name}")
            continue
        cand = Path(pk.path) / "adapter.gguf"
        if ldir:
            cand = cand if cand.exists() else ldir / name / "adapter.gguf"
        if cand.exists():
            rep.add("ok", f"LoRA 权重存在：{cand}")
        else:
            rep.add("error", f"LoRA 权重缺失：{cand}")

    # 3. fingerprint guard (hermes_s2): never load a LoRA on the wrong base
    for name in (selected or []):
        pk = packs.get(name)
        if (pk and deployed_base and pk.base_fingerprint
                and pk.base_fingerprint != deployed_base):
            rep.add("error", f"底模指纹不符（hermes_s2 风险）：{name} 要求 "
                             f"{pk.base_fingerprint}，部署底模 {deployed_base}")

    # 4. target port
    if _port_in_use("127.0.0.1", port):
        rep.add("warn", f"端口 {port} 已被占用，启动需 --takeover（会终止占用进程）")
    else:
        rep.add("ok", f"端口 {port} 空闲")

    # 5. GPU detection sanity
    if profile and profile.vendor == "unknown":
        rep.add("warn", "未探测到 GPU 工具（rocm-smi/nvidia-smi），规划为估值非实测")

    return rep
