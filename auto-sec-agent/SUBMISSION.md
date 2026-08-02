# Track 2: Agentic AI — AutoSec Agent

## Team Name: AutoSec

## Project Title: AutoSec Agent — Autonomous Security Reconnaissance Agent

### Description
An intelligent AI agent that automates security reconnaissance, vulnerability detection, AI-powered analysis, and multi-channel reporting (Gmail + Notion). Optimized for AMD Radeon GPU via ROCm.

### Key Features
1. Automated recon pipeline (subdomain enumeration, port scanning, HTTP probing)
2. Vulnerability scanning with 13,000+ nuclei templates
3. AI-powered risk analysis with AMD ROCm GPU acceleration
4. Automated reporting via Gmail (Himalaya CLI)
5. Automated documentation via Notion API
6. Real-time CLI interface with colored output

### Architecture
```
User → Agent Planner → Tool Executor → AI Analyzer (ROCm) → Reporter
```
- Tools: subfinder, nuclei, naabu, httpx
- AI: Local inference on AMD Radeon GPU
- Reporting: Gmail + Notion

### Tech Stack
- Python 3.11+
- AMD ROCm 6.x
- Go tools (subfinder, nuclei, naabu, httpx)
- Himalaya CLI (Gmail)
- Notion API

### How ROCm Is Used
- Local LLM inference for vulnerability analysis
- GPU-accelerated batch processing of scan results
- Real-time risk scoring on AMD Radeon hardware

### Submission
- GitHub: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
- PR: Track 2, AutoSec, AutoSec Agent
