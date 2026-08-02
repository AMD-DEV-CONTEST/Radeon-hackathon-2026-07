#!/usr/bin/env python3
"""
AutoSec Agent — Demo Script
Demonstrates the full pipeline with a sample target
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.agent import AutoSecAgent
from reporting.email_reporter import EmailReporter
from reporting.notion_reporter import NotionReporter

def demo():
    print("\033[96m\033[1m")
    print("╔══════════════════════════════════════════════════╗")
    print("║     AutoSec Agent — Interactive Demo Mode       ║")
    print("║     AMD AI DevMaster Hackathon 2026             ║")
    print("╚══════════════════════════════════════════════════╝")
    print("\033[0m")
    
    print("\nEnter a target to scan (or 'q' to quit): ")
    target = input("Target> ").strip()
    
    if not target or target.lower() == 'q':
        return
    
    print(f"\n[+] Starting AutoSec Agent against: {target}")
    
    # Create agent
    agent = AutoSecAgent(verbose=True)
    
    # Full scan
    results = agent.run_full_scan(target)
    
    # Send email report
    print("\n[✓] Sending email report...")
    emailer = EmailReporter()
    summary = results.get("phases", {}).get("ai_analysis", {})
    if summary:
        emailer.send_scan_alert(target, summary)
        print("[✓] Email sent!")
    
    # Notion
    print("\n[✓] Saving to Notion...")
    notifier = NotionReporter()
    if notifier.workspace_connected:
        report = agent.generate_report()
        notifier.create_scan_page(target, summary, report)
        print("[✓] Saved to Notion!")
    
    print("\n\033[92m[+] Demo Complete!\033[0m")

if __name__ == "__main__":
    demo()
