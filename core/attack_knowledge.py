"""MITRE ATT&CK Knowledge Base

Simplified mapping from MITRE ATT&CK techniques to CWE vulnerabilities.
Inspired by Anthropic-Cybersecurity-Skills (817 skills, 6 frameworks).

This module provides:
1. CWE → ATT&CK technique mapping for reports
2. Attack pattern descriptions for Agent 3 verification
3. Compliance framework references
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AttackTechnique:
    """MITRE ATT&CK technique mapped to CWE."""
    technique_id: str       # e.g. "T1059"
    name: str               # e.g. "Command and Scripting Interpreter"
    tactic: str             # e.g. "Execution"
    cwe_ids: list[str]      # Related CWEs
    description: str
    detection: str          # How to detect
    mitigation: str         # How to prevent


# ─── ATT&CK Techniques → CWE Mapping ────────────────────────────

ATTACK_TECHNIQUES: dict[str, AttackTechnique] = {
    "T1059": AttackTechnique(
        technique_id="T1059",
        name="Command and Scripting Interpreter",
        tactic="Execution",
        cwe_ids=["CWE-78", "CWE-95"],
        description="Adversaries may abuse command-line interpreters to execute commands, scripts, or binaries.",
        detection="Monitor command-line activity, script execution logs",
        mitigation="Restrict command-line access, use application whitelisting",
    ),
    "T1190": AttackTechnique(
        technique_id="T1190",
        name="Exploit Public-Facing Application",
        tactic="Initial Access",
        cwe_ids=["CWE-89", "CWE-79", "CWE-95", "CWE-502"],
        description="Adversaries may attempt to exploit vulnerabilities in public-facing applications.",
        detection="Web application firewall logs, intrusion detection systems",
        mitigation="Regular patching, input validation, web application firewall",
    ),
    "T1055": AttackTechnique(
        technique_id="T1055",
        name="Process Injection",
        tactic="Defense Evasion",
        cwe_ids=["CWE-120", "CWE-415", "CWE-476"],
        description="Adversaries may inject code into processes to evade defenses and escalate privileges.",
        detection="Monitor process memory operations, API calls",
        mitigation="Code signing, memory protection, least privilege",
    ),
    "T1105": AttackTechnique(
        technique_id="T1105",
        name="Ingress Tool Transfer",
        tactic="Command and Control",
        cwe_ids=["CWE-78", "CWE-95"],
        description="Adversaries may transfer tools to compromised systems.",
        detection="Network traffic monitoring, file integrity monitoring",
        mitigation="Network segmentation, egress filtering",
    ),
    "T1053": AttackTechnique(
        technique_id="T1053",
        name="Scheduled Task/Job",
        tactic="Execution",
        cwe_ids=["CWE-78"],
        description="Adversaries may abuse task scheduling to execute code.",
        detection="Monitor scheduled task creation and modification",
        mitigation="Restrict task scheduling permissions",
    ),
    "T1078": AttackTechnique(
        technique_id="T1078",
        name="Valid Accounts",
        tactic="Initial Access",
        cwe_ids=["CWE-798", "CWE-287"],
        description="Adversaries may use valid credentials to gain initial access.",
        detection="Authentication logs, anomaly detection",
        mitigation="Multi-factor authentication, credential management",
    ),
    "T1071": AttackTechnique(
        technique_id="T1071",
        name="Application Layer Protocol",
        tactic="Command and Control",
        cwe_ids=["CWE-295", "CWE-327"],
        description="Adversaries may use application layer protocols for C2 communication.",
        detection="Network traffic analysis, protocol anomaly detection",
        mitigation="Network monitoring, TLS inspection",
    ),
    "T1003": AttackTechnique(
        technique_id="T1003",
        name="OS Credential Dumping",
        tactic="Credential Access",
        cwe_ids=["CWE-798", "CWE-256"],
        description="Adversaries may dump credentials from operating systems.",
        detection="Monitor credential access, memory reads",
        mitigation="Credential guard, least privilege",
    ),
    "T1057": AttackTechnique(
        technique_id="T1057",
        name="Process Discovery",
        tactic="Discovery",
        cwe_ids=["CWE-200"],
        description="Adversaries may enumerate processes to find security tools.",
        detection="Monitor process enumeration API calls",
        mitigation="Least privilege, process hiding",
    ),
    "T1082": AttackTechnique(
        technique_id="T1082",
        name="System Information Discovery",
        tactic="Discovery",
        cwe_ids=["CWE-200"],
        description="Adversaries may gather system information for reconnaissance.",
        detection="Monitor system information queries",
        mitigation="Least privilege, information hiding",
    ),
    "T1083": AttackTechnique(
        technique_id="T1083",
        name="File and Directory Discovery",
        tactic="Discovery",
        cwe_ids=["CWE-22"],
        description="Adversaries may enumerate files and directories.",
        detection="Monitor file system queries",
        mitigation="Access control, directory permissions",
    ),
    "T1005": AttackTechnique(
        technique_id="T1005",
        name="Data from Local System",
        tactic="Collection",
        cwe_ids=["CWE-200", "CWE-22"],
        description="Adversaries may search local systems for data of interest.",
        detection="File access monitoring",
        mitigation="Data encryption, access control",
    ),
    "T1021": AttackTechnique(
        technique_id="T1021",
        name="Remote Services",
        tactic="Lateral Movement",
        cwe_ids=["CWE-287", "CWE-798"],
        description="Adversaries may use remote services to move laterally.",
        detection="Network connection monitoring",
        mitigation="Network segmentation, strong authentication",
    ),
    "T1566": AttackTechnique(
        technique_id="T1566",
        name="Phishing",
        tactic="Initial Access",
        cwe_ids=["CWE-79", "CWE-89"],
        description="Adversaries may use phishing to gain access.",
        detection="Email filtering, user awareness training",
        mitigation="Email security, user training",
    ),
    "T1499": AttackTechnique(
        technique_id="T1499",
        name="Endpoint Denial of Service",
        tactic="Impact",
        cwe_ids=["CWE-400", "CWE-770"],
        description="Adversaries may perform DoS to disrupt availability.",
        detection="Traffic analysis, resource monitoring",
        mitigation="Rate limiting, DDoS protection",
    ),
}

# ─── Reverse Mapping: CWE → ATT&CK ──────────────────────────────

CWE_TO_ATTACK: dict[str, list[str]] = {}
for tech in ATTACK_TECHNIQUES.values():
    for cwe in tech.cwe_ids:
        if cwe not in CWE_TO_ATTACK:
            CWE_TO_ATTACK[cwe] = []
        CWE_TO_ATTACK[cwe].append(tech.technique_id)


def get_attack_context(cwe_id: str) -> Optional[AttackTechnique]:
    """Get ATT&CK context for a CWE ID."""
    tech_ids = CWE_TO_ATTACK.get(cwe_id, [])
    if tech_ids:
        return ATTACK_TECHNIQUES[tech_ids[0]]
    return None


def get_attack_description(cwe_id: str) -> str:
    """Get a human-readable attack description for a CWE."""
    tech = get_attack_context(cwe_id)
    if tech:
        return f"[ATT&CK {tech.technique_id}] {tech.name}: {tech.description}"
    return ""


def get_compliance_references(cwe_id: str) -> dict[str, str]:
    """Get compliance framework references for a CWE."""
    tech = get_attack_context(cwe_id)
    if not tech:
        return {}

    refs = {
        "MITRE ATT&CK": f"{tech.technique_id} - {tech.name}",
        "Tactic": tech.tactic,
        "Detection": tech.detection,
        "Mitigation": tech.mitigation,
    }

    # Add framework-specific references
    if cwe_id in ["CWE-78", "CWE-95", "CWE-89"]:
        refs["OWASP Top 10"] = "A03:2021 - Injection"
        refs["NIST CSF"] = "DE.CM-1: Networks monitored"
    elif cwe_id in ["CWE-120", "CWE-415", "CWE-476"]:
        refs["OWASP Top 10"] = "A06:2021 - Vulnerable Components"
        refs["NIST CSF"] = "PR.DS-1: Data-at-rest protected"
    elif cwe_id in ["CWE-798", "CWE-287"]:
        refs["OWASP Top 10"] = "A07:2021 - Identification Failures"
        refs["NIST CSF"] = "PR.AC-1: Identity credentials managed"
    elif cwe_id in ["CWE-502", "CWE-611"]:
        refs["OWASP Top 10"] = "A08:2021 - Software Integrity Failures"
        refs["NIST CSF"] = "PR.DS-6: Integrity checking mechanisms"
    elif cwe_id in ["CWE-327", "CWE-328"]:
        refs["OWASP Top 10"] = "A02:2021 - Cryptographic Failures"
        refs["NIST CSF"] = "PR.DS-1: Data-at-rest protected"

    return refs
