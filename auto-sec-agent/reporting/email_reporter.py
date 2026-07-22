"""
Email Reporter — Gmail Integration via Himalaya
Sends security reports automatically via email
"""
import subprocess
import json
from pathlib import Path

class EmailReporter:
    """Send security reports via Gmail using Himalaya CLI"""
    
    def __init__(self, himalaya_path=None, from_addr=None):
        self.himalaya = himalaya_path or str(
            Path.home() / "tools/himalaya/himalaya.exe"
        )
        self.from_addr = from_addr or "alizafarbati@gmail.com"
    
    def send_report(self, to, subject, body, attachment=None):
        """Send a security report via email"""
        try:
            # Create email content
            email_content = f"""From: {self.from_addr}
To: {to}
Subject: {subject}

{body}
"""
            # Send via Himalaya
            r = subprocess.run(
                [self.himalaya, "template", "send"],
                input=email_content,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {"success": r.returncode == 0, "output": r.stdout[:200]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def send_scan_alert(self, target, findings_summary):
        """Send quick alert about critical findings"""
        subject = f"🚨 AutoSec Alert: {target} — {findings_summary['risk_level']} Risk"
        body = f"""AutoSec Agent — Security Alert

Target: {target}
Risk Level: {findings_summary['risk_level']}
Vulnerabilities: {findings_summary['total_vulnerabilities']}
Risk Score: {findings_summary['risk_score']}/100

Key Recommendations:
{chr(10).join('- ' + r for r in findings_summary.get('recommendations', []))}

Full report attached.

— AutoSec Agent
"""
        return self.send_report(self.from_addr, subject, body)
