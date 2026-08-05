"""Entrypoint for the SOC Triage Agent.

Usage:
    python -m src.main --mode demo   # uses data/sample_alerts/, no live connectors
    python -m src.main --mode live   # connects to real Wazuh/Suricata/Greenbone
"""
import argparse

from src.orchestrator.agent import SOCTriageAgent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    args = parser.parse_args()

    agent = SOCTriageAgent(mode=args.mode)
    agent.run()  # TODO: wire up to src/ui/app.py chat interface


if __name__ == "__main__":
    main()
