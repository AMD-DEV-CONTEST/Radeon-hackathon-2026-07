# AutoSec Agent — AMD AI DevMaster Hackathon 2026
# Track: Agentic AI
# An intelligent autonomous security agent powered by AMD ROCm

"""
AutoSec Agent: AI-Powered Autonomous Security Reconnaissance & Reporting Agent

This agent combines:
1. Industry-standard security tools (subfinder, nuclei, naabu, httpx)
2. Local AI analysis via AMD Radeon GPU + ROCm
3. Automated reporting via Gmail + Notion
4. Multi-step reasoning and planning

Architecture:
  User Input (target) → Agent Planner → Tool Executor → AI Analyzer → Reporter
                                                      ↓
                                              AMD ROCm GPU (local inference)
"""

__version__ = "1.0.0"
__track__ = "Agentic AI"
__team__ = "AutoSec"
