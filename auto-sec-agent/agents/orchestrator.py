"""
AutoSec Multi-Agent System — 4 Specialized Security Agents + 1 Orchestrator
"""
import sys, os, json, time, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import AutoSecAgent
from db.database import Database
from config.settings import Config

R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'
M = '\033[95m'; C = '\033[96m'; N = '\033[0m'; BOLD = '\033[1m'

class BaseAgent(threading.Thread):
    """Base class for all specialized agents"""
    def __init__(self, name, agent_type):
        super().__init__()
        self.name = name
        self.agent_type = agent_type
        self.db = Database()
        self.running = False
        self.daemon = True
    
    def log(self, msg): print(f"{C}[{self.name}] {msg}{N}")
    
    def register(self):
        self.db.register_agent(self.name, self.agent_type)

class ReconAgent(BaseAgent):
    """Specialized in reconnaissance — subdomain enumeration, port scanning, HTTP probing"""
    def __init__(self):
        super().__init__("Recon-1", "recon")
        self.core = AutoSecAgent(verbose=False)
    
    def run_scan(self, target):
        self.log(f"{Y}Starting recon on {target}{N}")
        results = self.core.scan_target(target)
        return results

class VulnAgent(BaseAgent):
    """Specialized in vulnerability detection — nuclei scanning, CVE correlation"""
    def __init__(self):
        super().__init__("Vuln-1", "vulnerability")
        self.core = AutoSecAgent(verbose=False)
    
    def run_scan(self, target):
        self.log(f"{R}Scanning vulnerabilities on {target}{N}")
        self.core.target = target
        vulns = self.core.scan_vulnerabilities()
        return vulns

class AIAgent(BaseAgent):
    """Specialized in AI-powered analysis with ROCm acceleration"""
    def __init__(self):
        super().__init__("AI-1", "ai_analysis")
    
    def analyze(self, target, subdomains, live_hosts, vulns, use_rocm=False):
        self.log(f"{M}AI Analysis on {target} (ROCm: {use_rocm}){N}")
        from ai.analyzer import AIAnalyzer
        analyzer = AIAnalyzer(use_rocm=use_rocm)
        return analyzer.analyze_scan_results(target, subdomains, live_hosts, vulns)

class ReportAgent(BaseAgent):
    """Specialized in multi-channel reporting — email + Notion + file"""
    def __init__(self):
        super().__init__("Report-1", "reporting")
        self.core = AutoSecAgent(verbose=False)
    
    def generate_and_send(self, target, results):
        self.log(f"{G}Generating report for {target}{N}")
        self.core.target = target
        self.core.results = results
        report = self.core.generate_report()
        return report

class Orchestrator:
    """Master orchestrator that coordinates all agents"""
    def __init__(self):
        self.db = Database()
        self.recon = ReconAgent()
        self.vuln = VulnAgent()
        self.ai = AIAgent()
        self.report = ReportAgent()
        
    def scan_target_full(self, target, use_rocm=False):
        """Full orchestrated scan using all 4 agents"""
        print(f"\n{R}{BOLD}[ORCHESTRATOR] Full scan: {target}{N}")
        t0 = time.time()
        
        # Register agents
        for agent in [self.recon, self.vuln, self.ai, self.report]:
            agent.register()
        
        # Step 1: Add target to DB
        target_id = self.db.add_target(target)
        scan_id = self.db.start_scan(target_id, "full")
        
        # Step 2: Recon Agent
        t1 = time.time()
        print(f"{C}[ORCHESTRATOR] → Deploying Recon Agent...{N}")
        recon_results = self.recon.run_scan(target)
        subs = recon_results.get("phases", {}).get("subdomains", [])
        live = recon_results.get("phases", {}).get("live_hosts", [])
        print(f"{G}[ORCHESTRATOR] Recon complete: {len(subs)} subdomains, {len(live)} live{N}")
        
        # Step 3: Vuln Agent
        t2 = time.time()
        print(f"{C}[ORCHESTRATOR] → Deploying Vulnerability Agent...{N}")
        self.vuln.core.results = recon_results
        vulns = self.vuln.run_scan(target)
        print(f"{G}[ORCHESTRATOR] Vuln scan complete: {len(vulns)} findings{N}")
        
        # Step 4: AI Agent
        t3 = time.time()
        print(f"{C}[ORCHESTRATOR] → Deploying AI Analysis Agent...{N}")
        analysis = self.ai.analyze(target, subs, live, vulns, use_rocm=use_rocm)
        risk = analysis["phases"]["risk"]
        print(f"{G}[ORCHESTRATOR] AI analysis: Score {risk['score']}/100 — {risk['level']}{N}")
        
        # Step 5: Report Agent
        t4 = time.time()
        print(f"{C}[ORCHESTRATOR] → Deploying Report Agent...{N}")
        full_results = {
            "phases": {
                "subdomains": subs,
                "live_hosts": live,
                "vulnerabilities": vulns,
                "ai_analysis": risk,
                "ai_recommendations": analysis["phases"]["recommendations"],
                "attack_surface": analysis["phases"]["attack_surface"],
                "vuln_correlation": analysis["phases"]["vuln_correlation"],
            },
            "acceleration": analysis.get("acceleration", {"engine": "CPU"})
        }
        report = self.report.generate_and_send(target, full_results)
        
        # Step 6: Save to DB
        duration = time.time() - t0
        self.db.complete_scan(scan_id, subs, vulns, risk["score"], risk["level"], duration, full_results)
        
        # Summary
        print(f"\n{G}{BOLD}{'='*55}{N}")
        print(f"{R}{BOLD}[ORCHESTRATOR] MISSION COMPLETE!{N}")
        print(f"{C}  Target: {target}{N}")
        print(f"{C}  Agents Deployed: Recon-1, Vuln-1, AI-1, Report-1{N}")
        print(f"{C}  Subdomains: {len(subs)}  |  Vulns: {len(vulns)}{N}")
        print(f"{C}  Risk Score: {risk['score']}/100 — {risk['level']}{N}")
        print(f"{C}  Duration: {duration:.1f}s  |  Scan ID: {scan_id}{N}")
        print(f"{G}{BOLD}{'='*55}{N}")
        
        return {
            "scan_id": scan_id,
            "target_id": target_id,
            "target": target,
            "subdomains": len(subs),
            "vulnerabilities": len(vulns),
            "risk_score": risk["score"],
            "risk_level": risk["level"],
            "duration": duration,
            "report": report
        }
    
    def list_targets(self):
        """List all targets in database"""
        return self.db.get_targets()
    
    def get_stats(self):
        """Get system statistics"""
        return self.db.get_stats()
    
    def list_agents(self):
        """List all registered agents"""
        return self.db.get_agents()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="AutoSec Platform — Orchestrator")
    parser.add_argument("action", choices=["scan", "list", "stats", "agents"])
    parser.add_argument("target", nargs="?", help="Target domain for scan")
    parser.add_argument("--rocm", action="store_true", help="Enable ROCm")
    args = parser.parse_args()
    
    orch = Orchestrator()
    
    if args.action == "scan" and args.target:
        orch.scan_target_full(args.target, use_rocm=args.rocm)
    elif args.action == "list":
        targets = orch.list_targets()
        for t in targets:
            print(f"[{t['status']}] {t['domain']} — {t.get('last_scanned', 'Never')}")
    elif args.action == "stats":
        stats = orch.get_stats()
        for k, v in stats.items():
            if k != "recent_scans":
                print(f"{k}: {v}")
    elif args.action == "agents":
        agents = orch.list_agents()
        for a in agents:
            print(f"[{a['status']}] {a['name']} ({a['agent_type']})")

if __name__ == "__main__":
    main()
