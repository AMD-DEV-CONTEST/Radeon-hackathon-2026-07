"""Domain expert packs — specialized private-agent personas beyond generic office QA."""

from __future__ import annotations


PACKS: dict[str, dict[str, str]] = {
    "hr": {
        "name": "HR Policy Expert",
        "hint": "Focus on leave, remote work, onboarding HR rules. Cite local policy docs only.",
        "keywords": "请假,年假,病假,入职,远程,HR,人事",
    },
    "security": {
        "name": "Security & Compliance Expert",
        "hint": "Focus on secrets handling, AI tool allowlists, phishing, access control. Never suggest uploading secrets to public AI.",
        "keywords": "涉密,合规,安全,VPN,MFA,钓鱼,权限,密码",
    },
    "it": {
        "name": "IT Service Expert",
        "hint": "Focus on ServiceDesk, licenses, VPN, printers, account unlock flows.",
        "keywords": "许可证,ServiceDesk,打印机,账号,解锁,IT",
    },
    "legal": {
        "name": "Legal / Contracts Lite Expert",
        "hint": "Focus on document retention, third-party data sharing, DPA reminders. Do not invent statutes.",
        "keywords": "合同,法务,DPA,供应商,保留,外发",
    },
    "research": {
        "name": "Research Synthesizer",
        "hint": "Compare multiple KB snippets, list agreements/conflicts, produce a short brief with open questions.",
        "keywords": "对比,综述,研究,简报,冲突",
    },
    "ops": {
        "name": "Ops Runbook Expert",
        "hint": "Produce executable checklists and rollback notes for operational tasks.",
        "keywords": "运维,runbook,故障,回滚,值班,on-call",
    },
}


def detect_pack(query: str) -> str | None:
    for pid, meta in PACKS.items():
        keys = [k.strip() for k in meta["keywords"].split(",") if k.strip()]
        if any(k.lower() in query.lower() or k in query for k in keys):
            return pid
    return None


def pack_system_prompt(pack_id: str | None) -> str:
    if not pack_id or pack_id not in PACKS:
        return ""
    meta = PACKS[pack_id]
    return f"Active domain pack: {meta['name']}. Guidance: {meta['hint']}"


def list_packs() -> str:
    lines = ["可用领域专家包（Domain Packs）："]
    for pid, meta in PACKS.items():
        lines.append(f"- {pid}: {meta['name']} — {meta['hint']}")
    return "\n".join(lines)
