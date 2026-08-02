"""
AutoSec Agent Core — Autonomous Security Agent with AMD ROCm Acceleration
"""
import json
import time
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import Config

R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
M = '\033[95m'; C = '\033[96m'; N = '\033[0m'; BOLD = '\033[1m'

class AutoSecAgent:
    def __init__(self, verbose=True):
        self.config = Config()
        self.verbose = verbose
        self.results = {}
        self.target = ""
        self.start_time = None
        Config.setup()
        
    def log(self, msg, color=C):
        if self.verbose: print(f"{color}[*] {msg}{N}")
    def success(self, msg): print(f"{G}[+] {msg}{N}")
    def error(self, msg): print(f"{R}[-] {msg}{N}")
    
    def banner(self):
        print(f"""{R}{BOLD}
╔══════════════════════════════════════════════════════════════╗
║  █████╗ ██╗   ██╗████████╗ ██████╗ ███████╗███████╗        ║
║ ██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗██╔════╝██╔════╝        ║
║ ███████║██║   ██║   ██║   ██║   ██║███████╗█████╗          ║
║ ██╔══██║██║   ██║   ██║   ██║   ██║╚════██║██╔══╝          ║
║ ██║  ██║╚██████╔╝   ██║   ╚██████╔╝███████║███████╗        ║
║ ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚══════╝╚══════╝        ║
║  Agentic AI · AMD ROCm Accelerated · AutoSec                ║
║  AMD AI DevMaster Hackathon 2026 — Track 2                  ║
╚══════════════════════════════════════════════════════════════╝{N}
        """)
    
    def run_command(self, cmd, timeout=120):
        """Run a command and return output (no shell=True — avoids cmd.exe issues)"""
        try:
            env = os.environ.copy()
            env["MSYS_NO_PATHCONV"] = "1"
            # Split command string into list for subprocess
            parts = cmd.split()
            r = subprocess.run(parts, capture_output=True, text=True, timeout=timeout, env=env)
            return {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}
    
    def scan_target(self, target):
        self.target = target
        self.start_time = time.time()
        self.log(f"Starting recon on: {BOLD}{target}{N}", Y)
        
        self.results = {"target": target, "timestamp": datetime.now().isoformat(), "phases": {}}
        
        # Phase 1a: Subdomain Enumeration
        self.log("Phase 1a: Subdomain enumeration...")
        r = self.run_command(f"{Config.SUBFINDER_PATH} -d {target}")
        subdomains = []
        for line in r["stdout"].split("\n"):
            line = line.strip()
            if not line or line.startswith(("_", "[", "\t")): continue
            if "projectdiscovery" in line.lower() or "subfinder" in line.lower(): continue
            if "." in line and not line.startswith("http"):
                subdomains.append(line.split()[0])
        
        self.results["phases"]["subdomains"] = subdomains[:100]
        self.success(f"Found {len(subdomains)} subdomains")
        
        if subdomains:
            sub_file = Config.OUTPUT_DIR / f"{target}_subs.txt"
            sub_file.write_text("\n".join(subdomains))
            
            # Phase 1b: Port scanning
            self.log("Phase 1b: Port scanning with naabu...")
            self.run_command(f"{Config.NAABU_PATH} -list {sub_file} -top-ports 100")
            
            # Phase 1c: HTTP probing
            self.log("Phase 1c: HTTP probing...")
            r = self.run_command(f"{Config.HTTPX_PATH} -l {sub_file} -status-code -title")
            live = [l.strip() for l in r["stdout"].split("\n") if l.strip() and "http" in l.lower()]
            self.results["phases"]["live_hosts"] = live[:50]
            self.success(f"Found {len(live)} live hosts")
        
        return self.results
    
    def scan_vulnerabilities(self):
        self.log("Phase 2: Vulnerability scanning...", Y)
        sub_file = Config.OUTPUT_DIR / f"{self.target}_subs.txt"
        if not sub_file.exists():
            self.error("No subdomains. Run scan_target() first.")
            return []
        
        r = self.run_command(
            f"{Config.NUCLEI_PATH} -l {sub_file} -t {Config.NUCLEI_TEMPLATES} "
            f"-severity critical,high,medium -json -silent 2>&1", timeout=300
        )
        vulns = []
        for line in r["stdout"].split("\n"):
            line = line.strip()
            if line:
                try: vulns.append(json.loads(line))
                except: pass
        
        self.results["phases"]["vulnerabilities"] = vulns[:50]
        self.success(f"Found {len(vulns)} potential vulns")
        return vulns
    def analyze_with_ai(self, use_rocm=False):
        """Phase 3: AI-powered risk analysis"""
        self.log("Phase 3: AI analysis with risk scoring...", M)
        from ai.analyzer import AIAnalyzer
        subs = self.results.get("phases", {}).get("subdomains", [])
        live = self.results.get("phases", {}).get("live_hosts", [])
        vulns = self.results.get("phases", {}).get("vulnerabilities", [])
        analyzer = AIAnalyzer(use_rocm=use_rocm)
        analysis = analyzer.analyze_scan_results(self.target, subs, live, vulns)
        risk = analysis["phases"]["risk"]
        recs = analysis["phases"]["recommendations"]
        self.results["phases"]["ai_analysis"] = risk
        self.results["phases"]["ai_recommendations"] = recs
        self.results["phases"]["attack_surface"] = analysis["phases"]["attack_surface"]
        self.results["phases"]["vuln_correlation"] = analysis["phases"]["vuln_correlation"]
        self.results["acceleration"] = analysis.get("acceleration", {"engine": "CPU"})
        self.success(f"Risk Score: {risk['score']}/100 — Level: {risk['level']}")
        return analysis
    
    def generate_report(self):
        """Phase 4: Generate comprehensive report"""
        self.log("Phase 4: Generating report...", G)
        elapsed = time.time() - self.start_time
        phases = self.results.get("phases", {})
        subs = phases.get("subdomains", [])
        live = phases.get("live_hosts", [])
        vulns = phases.get("vulnerabilities", [])
        risk = phases.get("ai_analysis", {})
        recs = phases.get("ai_recommendations", [])
        accel = self.results.get("acceleration", {})
        attack_surface = phases.get("attack_surface", {})
        
        report = f"""# AutoSec Agent — Security Assessment Report
## Target: {self.target} | Duration: {elapsed:.1f}s
## Track: Agentic AI — AMD AI DevMaster Hackathon 2026

### 📊 Executive Summary

| Metric | Value |
|--------|-------|
| 🔍 Subdomains Discovered | {len(subs)} |
| 🌐 Live Hosts | {len(live)} |
| 🛡️ Vulnerabilities Found | {len(vulns)} |
| 📈 Risk Score | {risk.get('score', 'N/A')}/100 |
| ⚠️ Risk Level | **{risk.get('level', 'N/A')}** |
| ⚡ Processing Engine | {accel.get('engine', 'CPU')} |

### 🎯 Key Recommendations
{chr(10).join(f"- {r}" for r in recs) if recs else "- None generated"}

### 🔍 Subdomains ({len(subs)} total)
```
{chr(10).join(subs[:30])}
{f'... and {len(subs)-30} more' if len(subs) > 30 else ''}
```

### 🌐 Live Services ({len(live)} total)
```
{chr(10).join(live[:15])}
```

### 🛡️ Vulnerability Summary
| Severity | Count |
|----------|:-----:|
{f"| 🔴 Critical | {phases.get('vuln_correlation',{}).get('by_severity',{}).get('critical', 0)} |"}
{f"| 🟠 High | {phases.get('vuln_correlation',{}).get('by_severity',{}).get('high', 0)} |"}
{f"| 🟡 Medium | {phases.get('vuln_correlation',{}).get('by_severity',{}).get('medium', 0)} |"}
{f"| 🔵 Low | {phases.get('vuln_correlation',{}).get('by_severity',{}).get('low', 0)} |"}
| Total | {len(vulns)} |

### 🚀 AMD ROCm Acceleration
| Metric | Value |
|--------|-------|
| Engine | {accel.get('engine', 'CPU')} |
| Device | {accel.get('device', 'N/A')} |
{f"| Benchmark | {accel.get('benchmark',{}).get('operations', 'N/A')} |"}
{f"| Speedup | {accel.get('benchmark',{}).get('speedup', 'N/A')} |"}

### 📋 Risk Factor Breakdown
| Factor | Score |
|--------|:----:|
{f"| Subdomain Risk | {risk.get('factors',{}).get('subdomain_risk', 'N/A')}/25 |"}
{f"| Live Host Risk | {risk.get('factors',{}).get('live_host_risk', 'N/A')}/25 |"}
{f"| Vulnerability Risk | {risk.get('factors',{}).get('vulnerability_risk', 'N/A')}/50 |"}
| **Total** | **{risk.get('score', 'N/A')}/100** |

---
*Generated by **AutoSec Agent** — AMD AI DevMaster Hackathon 2026*
*Track: Agentic AI · {accel.get('engine', 'Standalone')}*
"""
        report_file = Config.OUTPUT_DIR / f"{self.target}_report.md"
        report_file.write_text(report)
        self.success(f"Report saved: {report_file}")
        return report
    
    def run_full_scan(self, target, use_rocm=False):
        self.banner()
        self.log(f"Full scan: {BOLD}{target}{N}", Y)
        self.scan_target(target)
        self.scan_vulnerabilities()
        self.analyze_with_ai(use_rocm)
        self.generate_report()
        elapsed = time.time() - self.start_time
        print(f"\n{G}{BOLD}[✓] Scan Complete! {elapsed:.1f}s — Risk: {self.results.get('phases',{}).get('ai_analysis',{}).get('risk_level','N/A')}{N}")
        return self.results

def main():
    import argparse, os
    parser = argparse.ArgumentParser(description="AutoSec Agent")
    parser.add_argument("target", help="Target domain")
    parser.add_argument("--rocm", action="store_true", help="AMD ROCm mode")
    parser.add_argument("--quiet", "-q", action="store_true")
    args = parser.parse_args()
    agent = AutoSecAgent(verbose=not args.quiet)
    agent.run_full_scan(args.target, use_rocm=args.rocm)

if __name__ == "__main__":
    main()
