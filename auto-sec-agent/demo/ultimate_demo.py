#!/usr/bin/env python3
"""
AutoSec Agent — ULTIMATE DEMO
Full pipeline with timing, benchmarks, ROCm simulation
AMD AI DevMaster Hackathon 2026 — Track: Agentic AI
"""
import sys, time, json, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

R = '\033[91m'; G = '\033[92m'; Y = '\033[93m'; B = '\033[94m'; M = '\033[95m'; C = '\033[96m'; N = '\033[0m'; BOLD = '\033[1m'

def print_header():
    print(f"""{R}{BOLD}
╔══════════════════════════════════════════════════════════════╗
║           AUTO-SEC AGENT — ULTIMATE DEMO                    ║
║     AMD AI DevMaster Hackathon 2026 — Agentic AI Track      ║
║                                                              ║
║  📋 Complete Pipeline | ⚡ ROCm Accelerated  | 📊 4-Phase   ║
╚══════════════════════════════════════════════════════════════╝{N}
    """)

def print_step(num, title, status, detail=""):
    icon = {"ok": "✅", "running": "🔄", "pending": "⏳", "fail": "❌", "info": "ℹ️"}
    c = {"ok": G, "running": Y, "pending": C, "fail": R, "info": B}
    print(f"  {icon.get(status, 'ℹ️')} {c.get(status, C)}{BOLD}Step {num}:{N} {c.get(status, C)}{title}{N}")
    if detail: print(f"     {detail}")

def demo_all_features():
    print_header()
    
    # Phase 1: Environment Check
    print(f"\n{C}{BOLD}[ PHASE 0: Environment ]{N}")
    print_step("0a", "Python Version", "ok", f"{sys.version[:30]}")
    print_step("0b", "Platform", "ok", f"{os.name} / {sys.platform}")
    print_step("0c", "ROCm Detection", "running")
    
    from ai.analyzer import ROCmAccelerator
    rocm = ROCmAccelerator()
    specs = rocm.get_specs()
    rocm_status = "ok" if not "simulation" in specs["engine"] else "info"
    print_step("0c", f"Engine: {specs['engine']}", rocm_status, f"Device: {specs['device']}")
    print_step("0d", f"Benchmark: {specs['benchmark']['operations']}", "ok", 
               f"CPU: {specs['benchmark']['cpu_time_ms']}ms | Simulated GPU: {specs['benchmark']['simulated_gpu_time_ms']}ms | Speedup: {specs['benchmark']['speedup']}")
    
    # Phase 2: Recon
    print(f"\n{C}{BOLD}[ PHASE 1: Reconnaissance ]{N}")
    from core.agent import AutoSecAgent
    target = input(f"\n{Y}Enter target domain to scan (or press Enter for 'tesla.com'):{N} ").strip() or "tesla.com"
    print(f"\n{C}[*] Target: {BOLD}{target}{N}")
    
    agent = AutoSecAgent(verbose=True)
    t1 = time.time()
    results = agent.scan_target(target)
    t2 = time.time()
    subs = results.get("phases", {}).get("subdomains", [])
    live = results.get("phases", {}).get("live_hosts", [])
    print_step("1a", "Subdomain Enumeration", "ok" if subs else "info", f"{len(subs)} subdomains found")
    print_step("1b", "Port Scanning + HTTP Probing", "ok" if len(results.get("phases",{}).keys()) > 1 else "info", 
               f"{len(live)} live hosts")
    print_step("1c", "Recon Time", "ok", f"{t2-t1:.1f}s")
    
    # Phase 3: Vulnerability Scan
    print(f"\n{C}{BOLD}[ PHASE 2: Vulnerability Detection ]{N}")
    t1 = time.time()
    vulns = agent.scan_vulnerabilities()
    t2 = time.time()
    print_step("2a", "Nuclei Scan", "ok" if vulns else "info", f"{len(vulns)} potential vulnerabilities")
    print_step("2b", "Scan Time", "ok", f"{t2-t1:.1f}s")
    
    # Phase 3: AI Analysis
    print(f"\n{C}{BOLD}[ PHASE 3: AI Analysis — AMD ROCm{specs['benchmark']['speedup']} ]{N}")
    from ai.analyzer import AIAnalyzer
    analyzer = AIAnalyzer(use_rocm=rocm.available)
    t1 = time.time()
    analysis = analyzer.analyze_scan_results(target, subs, live, vulns)
    t2 = time.time()
    
    risk = analysis["phases"]["risk"]
    print_step("3a", "Attack Surface Analysis", "ok", f"{analysis['phases']['attack_surface']['analysis']}")
    print_step("3b", "Vulnerability Correlation", "ok", 
               f"{analysis['phases']['vuln_correlation']['total_unique']} unique vulns across {len(analysis['phases']['vuln_correlation']['by_severity'])} severity levels")
    print_step("3c", f"Risk Score: {risk['score']}/100 — {risk['level']}", 
               "fail" if risk['score'] > 40 else "ok", 
               f"Subdomain Risk: {risk['factors']['subdomain_risk']} | Live Host Risk: {risk['factors']['live_host_risk']} | Vuln Risk: {risk['factors']['vulnerability_risk']}")
    print_step("3d", f"Calculation Time: {risk['calculation_time_ms']}ms", "ok", 
               f"Accelerated by: {risk['accelerated_by']}")
    
    for rec in analysis["phases"]["recommendations"]:
        print(f"     {rec}")
    
    # Phase 4: Report
    print(f"\n{C}{BOLD}[ PHASE 4: Multi-Channel Reporting ]{N}")
    t1 = time.time()
    report = agent.generate_report()
    t2 = time.time()
    report_file = Path(agent.config.OUTPUT_DIR) / f"{target}_report.md"
    print_step("4a", "Markdown Report", "ok", f"Saved to: {report_file}")
    print_step("4b", "Report Generation Time", "ok", f"{t2-t1:.1f}s")
    
    # Email
    print_step("4c", "Email Report (Gmail)", "info", "Ready via Himalaya CLI")
    
    # Notion
    print_step("4d", "Notion Documentation", "info", "Ready via Notion API")
    
    # Grand Finale
    total_time = time.time() - agent.start_time if agent.start_time else 0
    print(f"""
{Y}{BOLD}{'='*55}{N}
{R}{BOLD}╔══════════════════════════════════════════════════════════╗{N}
{R}{BOLD}║         🏆  AUTO-SEC AGENT — DEMO COMPLETE  🏆        ║{N}
{R}{BOLD}╚══════════════════════════════════════════════════════════╝{N}
{G}
  📊 Target: {BOLD}{target}{N}
  {'🔍 Subdomains: ' + BOLD + str(len(subs)) + N + ' found' if subs else 'ℹ️ No subdomains found'}
  {'🛡️ Vulnerabilities: ' + BOLD + str(len(vulns)) + N + ' detected' if vulns else '✅ No vulnerabilities found'}
  📈 Risk Score: {BOLD}{risk['score']}/100 — {risk['level']}{N}
  ⚡ ROCm Engine: {BOLD}{specs['engine']}{N}
  {BOLD}🚀 Speedup: {specs['benchmark']['speedup']}{N}
  ⏱️ Total Time: {BOLD}{total_time:.1f}s{N}
  
{C}  🎯 AMD AI DevMaster Hackathon 2026 — Agentic AI Track{N}
{M}  📅 Deadline: August 6, 2026{N}
{Y}  🏆 Prize Pool: $30,000 — Top Prize: $5,000 per track{N}
{N}""")
    
    # Interactive
    print(f"{B}Would you like to:{N}")
    print(f"  {G}[1]{N} Send report via email")
    print(f"  {G}[2]{N} Save to Notion")
    print(f"  {G}[3]{N} View full report")
    print(f"  {G}[Enter]{N} Exit")
    
    choice = input(f"\n{Y}Choice:{N} ").strip()
    if choice == "1":
        from reporting.email_reporter import EmailReporter
        emailer = EmailReporter()
        result = emailer.send_scan_alert(target, risk)
        print(f"\n{G}[+] Email result: {result}{N}")
    elif choice == "2":
        from reporting.notion_reporter import NotionReporter
        notifier = NotionReporter()
        result = notifier.create_scan_page(target, risk, report)
        print(f"\n{G}[+] Notion result: {result}{N}")
    elif choice == "3":
        print(f"\n{Y}{report[:2000]}{N}")

if __name__ == "__main__":
    demo_all_features()
