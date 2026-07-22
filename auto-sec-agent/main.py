#!/usr/bin/env python3
"""
AutoSec Agent — Entry Point
AMD AI DevMaster Hackathon 2026 | Track: Agentic AI
"""
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from core.agent import AutoSecAgent, main

if __name__ == "__main__":
    main()
