"""Agent 4: Report Generator

Generates structured audit reports in multiple formats:
- JSON (for API/programmatic use)
- Markdown (for human review)
- Rich terminal output (for CLI)
- CWE/CVE external references
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from core.models import AnalysisResult, Risk, Severity
from core.attack_knowledge import get_attack_description, get_compliance_references

console = Console()


def _cwe_url(cwe_id: str) -> str:
    """Generate CWE reference URL."""
    if not cwe_id or not cwe_id.startswith("CWE-"):
        return ""
    num = cwe_id.replace("CWE-", "")
    return f"https://cwe.mitre.org/data/definitions/{num}.html"


def _cve_url(cve_id: str) -> str:
    """Generate CVE reference URL."""
    if not cve_id or not cve_id.startswith("CVE-"):
        return ""
    return f"https://nvd.nist.gov/vuln/detail/{cve_id}"


def _extract_cve_ids(description: str) -> list[str]:
    """Extract CVE IDs from description text."""
    import re
    return re.findall(r"CVE-\d{4}-\d+", description)


class ReportGenerator:
    """Agent 4: Generate structured audit reports."""

    def generate_json(self, result: AnalysisResult) -> dict:
        """Generate structured JSON report with external references."""
        risks_out = []
        for r in sorted(result.risks, key=lambda r: list(Severity).index(r.severity)):
            cve_ids = _extract_cve_ids(r.description)
            refs = {
                "cwe_url": _cwe_url(r.cwe_id) if r.cwe_id else None,
                "cve_urls": [_cve_url(c) for c in cve_ids] if cve_ids else None,
            }
            # Add ATT&CK context
            if r.cwe_id:
                attack_desc = get_attack_description(r.cwe_id)
                compliance = get_compliance_references(r.cwe_id)
                if attack_desc:
                    refs["mitre_attack"] = attack_desc
                if compliance:
                    refs["compliance"] = compliance
            risks_out.append({
                "id": r.id,
                "title": r.title,
                "severity": r.severity.value,
                "confidence": r.confidence.value,
                "cwe": r.cwe_id,
                "file": str(r.file_path),
                "line_start": r.line_start,
                "line_end": r.line_end,
                "description": r.description,
                "suggestion": r.suggestion,
                "evidence_count": r.evidence_count,
                "evidence": [
                    {
                        "source": e.source,
                        "rule_id": e.rule_id,
                        "snippet": e.snippet[:200],
                        "reasoning": e.reasoning,
                    }
                    for e in r.evidence
                ],
                "references": refs,
            })

        return {
            "scan_id": result.request_id,
            "timestamp": result.timestamp.isoformat(),
            "summary": {
                "files_analyzed": result.files_analyzed,
                "total_risks": result.total_risks,
                "has_critical": result.has_critical,
                "risk_breakdown": result.risk_summary,
            },
            "risks": risks_out,
            "meta": {
                "model_used": result.model_used,
                "analysis_time_ms": result.analysis_time_ms,
                "version": "1.0",
            },
        }

    def generate_markdown(self, result: AnalysisResult) -> str:
        """Generate Markdown audit report with CWE/CVE links."""
        lines = [
            "# CodeRisk Agent - Security Audit Report",
            "",
            f"**Scan ID:** `{result.request_id}`",
            f"**Timestamp:** {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Files Analyzed:** {result.files_analyzed}",
            f"**Analysis Time:** {result.analysis_time_ms}ms",
            f"**Model:** {result.model_used}",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Risks | **{result.total_risks}** |",
            f"| Critical | **{result.risk_summary.get('critical', 0)}** |",
            f"| High | **{result.risk_summary.get('high', 0)}** |",
            f"| Medium | **{result.risk_summary.get('medium', 0)}** |",
            f"| Low | **{result.risk_summary.get('low', 0)}** |",
            f"| Info | **{result.risk_summary.get('info', 0)}** |",
            "",
        ]

        if result.has_critical:
            lines.extend([
                "> **WARNING:** Critical vulnerabilities detected! Immediate action required.",
                "",
            ])

        lines.extend(["## Risk Details", ""])

        for risk in sorted(result.risks, key=lambda r: list(Severity).index(r.severity)):
            severity_icon = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🔵",
                Severity.INFO: "⚪",
            }.get(risk.severity, "⚪")

            cwe_link = ""
            if risk.cwe_id:
                cwe_link = f"[{risk.cwe_id}]({_cwe_url(risk.cwe_id)})"

            cve_ids = _extract_cve_ids(risk.description)
            cve_links = ""
            if cve_ids:
                cve_links = " | ".join(
                    f"[{c}]({_cve_url(c)})" for c in cve_ids
                )

            lines.extend([
                f"### {risk.id}: {severity_icon} {risk.title}",
                "",
                "| Field | Value |",
                "|-------|-------|",
                f"| Severity | **{risk.severity.value.upper()}** |",
                f"| Confidence | {risk.confidence.value} |",
                f"| CWE | {cwe_link or 'N/A'} |",
                f"| CVE | {cve_links or 'N/A'} |",
                f"| File | `{risk.file_path}` |",
                f"| Lines | {risk.line_start}-{risk.line_end} |",
                f"| Evidence Sources | {risk.evidence_count} |",
                "",
                f"**Description:** {risk.description}",
                "",
                f"**Fix:** {risk.suggestion}",
                "",
            ])

            # Add ATT&CK context
            if risk.cwe_id:
                attack_desc = get_attack_description(risk.cwe_id)
                compliance = get_compliance_references(risk.cwe_id)
                if attack_desc:
                    lines.append(f"**MITRE ATT&CK:** {attack_desc}")
                    lines.append("")
                if compliance:
                    lines.append("**Compliance References:**")
                    for framework, ref in compliance.items():
                        lines.append(f"- {framework}: {ref}")
                    lines.append("")

            if risk.evidence:
                lines.append("**Evidence:**")
                for e in risk.evidence:
                    lines.append(f"- Source: `{e.source}` | {e.reasoning}")
                lines.append("")

        lines.extend([
            "---",
            "",
            "## References",
            "",
            "- [CWE List](https://cwe.mitre.org/data/index.html)",
            "- [NVD - National Vulnerability Database](https://nvd.nist.gov/)",
            "- [OWASP Top 10](https://owasp.org/www-project-top-ten/)",
            "",
            "---",
            "",
            f"*Generated by CodeRisk Agent v0.3.1 | {result.timestamp.isoformat()}*",
        ])

        return "\n".join(lines)

    def generate_sarif(self, result: AnalysisResult) -> dict:
        """Generate SARIF 2.1.0 report.

        Static Analysis Results Interchange Format — OASIS standard.
        Compatible with GitHub Code Scanning, VS Code SARIF Viewer,
        Azure DevOps, and other SARIF consumers.
        """
        # Severity -> SARIF level mapping
        level_map = {
            Severity.CRITICAL: "error",
            Severity.HIGH: "error",
            Severity.MEDIUM: "warning",
            Severity.LOW: "note",
            Severity.INFO: "none",
        }

        # Build rules from unique CWEs
        rules = []
        seen_cwes = set()
        for risk in result.risks:
            cwe = risk.cwe_id or "CWE-000"
            if cwe not in seen_cwes:
                seen_cwes.add(cwe)
                rules.append({
                    "id": cwe,
                    "name": risk.title,
                    "shortDescription": {"text": risk.title},
                    "fullDescription": {"text": risk.description[:500]},
                    "help": {"text": risk.suggestion},
                    "defaultConfiguration": {
                        "level": level_map.get(risk.severity, "warning")
                    },
                    "properties": {
                        "tags": ["security", cwe.lower().replace("cwe-", "cwe-")],
                    },
                })

        # Build results
        rule_index_map = {r["id"]: i for i, r in enumerate(rules)}
        sarif_results = []
        for risk in result.risks:
            cve_ids = _extract_cve_ids(risk.description)
            sarif_result = {
                "ruleId": risk.cwe_id or "CWE-000",
                "ruleIndex": rule_index_map.get(risk.cwe_id, 0),
                "level": level_map.get(risk.severity, "warning"),
                "message": {
                    "text": f"{risk.title}: {risk.description[:300]}"
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": str(risk.file_path),
                            "uriBaseId": "%SRCROOT%",
                        },
                        "region": {
                            "startLine": risk.line_start,
                            "endLine": risk.line_end,
                        },
                    },
                }],
                "fingerprints": {
                    "coderisk/v1": risk.id,
                },
            }

            # Add CWE as a property
            if risk.cwe_id:
                sarif_result["properties"] = {
                    "cwe": risk.cwe_id,
                    "confidence": risk.confidence.value,
                }

            # Add CVE references
            if cve_ids:
                sarif_result["relatedLocations"] = [
                    {
                        "id": i,
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": _cve_url(c),
                            },
                        },
                        "message": {"text": f"CVE reference: {c}"},
                    }
                    for i, c in enumerate(cve_ids)
                ]

            sarif_results.append(sarif_result)

        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "CodeRisk Agent",
                        "version": "1.0",
                        "informationUri": "https://github.com/a9320/code-risk-agent",
                        "semanticVersion": "1.0",
                        "rules": rules,
                    },
                },
                "results": sarif_results,
                "columnKind": "utf16CodeUnits",
            }],
        }

    def print_terminal(self, result: AnalysisResult) -> None:
        """Print rich terminal output."""
        summary_table = Table(
            title="Risk Summary",
            show_header=True,
            border_style="cyan",
        )
        summary_table.add_column("Severity", justify="center")
        summary_table.add_column("Count", justify="center")

        severity_style = {
            "critical": "bold red",
            "high": "red",
            "medium": "yellow",
            "low": "blue",
            "info": "dim",
        }
        severity_icon = {
            "critical": "C",
            "high": "H",
            "medium": "M",
            "low": "L",
            "info": "I",
        }

        for level in ["critical", "high", "medium", "low", "info"]:
            count = result.risk_summary.get(level, 0)
            if count > 0:
                summary_table.add_row(
                    f"[{severity_style[level]}]{severity_icon[level]} {level.upper()}[/]",
                    f"[{severity_style[level]}]{count}[/]",
                )

        console.print()
        console.print(summary_table)
        console.print()

        if result.risks:
            risk_table = Table(
                title="Risk Details",
                show_header=True,
                border_style="yellow",
            )
            risk_table.add_column("ID", style="bold")
            risk_table.add_column("Sev")
            risk_table.add_column("Conf")
            risk_table.add_column("CWE")
            risk_table.add_column("Title")
            risk_table.add_column("File")
            risk_table.add_column("Line", justify="center")
            risk_table.add_column("Evidence", justify="center")

            for risk in sorted(
                result.risks,
                key=lambda r: list(Severity).index(r.severity),
            ):
                style = severity_style.get(risk.severity.value, "")
                icon = severity_icon.get(risk.severity.value, "")
                conf_style = {
                    "high": "green",
                    "medium": "yellow",
                    "low": "red",
                }.get(risk.confidence.value, "")

                risk_table.add_row(
                    risk.id,
                    f"[{style}]{icon}[/]",
                    f"[{conf_style}]{risk.confidence.value[:1].upper()}[/]",
                    risk.cwe_id or "-",
                    risk.title[:45],
                    str(risk.file_path)[-25:],
                    str(risk.line_start),
                    str(risk.evidence_count),
                )

            console.print(risk_table)

            critical_high = [
                r for r in result.risks
                if r.severity in (Severity.CRITICAL, Severity.HIGH)
            ]
            if critical_high:
                console.print()
                tree = Tree("[bold red]Critical / High Risks - Fix Suggestions[/]", guide_style="cyan")
                for risk in critical_high:
                    node = tree.add(f"[red]{risk.id}[/] {risk.title}")
                    node.add(f"[yellow]Issue:[/] {risk.description[:120]}")
                    node.add(f"[green]Fix:[/] {risk.suggestion[:120]}")
                    if risk.cwe_id:
                        node.add(f"[cyan]CWE:[/] {_cwe_url(risk.cwe_id)}")
                console.print(tree)

        console.print()
        console.print(
            Panel(
                f"[bold]Files:[/] {result.files_analyzed}  |  "
                f"[bold]Risks:[/] {result.total_risks}  |  "
                f"[bold]Time:[/] {result.analysis_time_ms}ms  |  "
                f"[bold]Model:[/] {result.model_used}",
                border_style="cyan",
            )
        )

    def save_report(
        self,
        result: AnalysisResult,
        output_dir: str = ".",
        formats: list[str] = ["json", "md"],
    ) -> list[str]:
        """Save reports to files."""
        import os

        saved = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"coderisk_report_{timestamp}"

        os.makedirs(output_dir, exist_ok=True)

        if "json" in formats:
            json_path = os.path.join(output_dir, f"{base_name}.json")
            report = self.generate_json(result)
            with open(json_path, "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            saved.append(json_path)
            console.print(f"[dim]JSON report saved: {json_path}[/]")

        if "md" in formats:
            md_path = os.path.join(output_dir, f"{base_name}.md")
            md_content = self.generate_markdown(result)
            with open(md_path, "w") as f:
                f.write(md_content)
            saved.append(md_path)
            console.print(f"[dim]Markdown report saved: {md_path}[/]")

        if "sarif" in formats:
            sarif_path = os.path.join(output_dir, f"{base_name}.sarif")
            sarif_report = self.generate_sarif(result)
            with open(sarif_path, "w") as f:
                json.dump(sarif_report, f, indent=2, ensure_ascii=False)
            saved.append(sarif_path)
            console.print(f"[dim]SARIF report saved: {sarif_path}[/]")

        return saved
