# Decentralized Security Auditor Agent
**AMD AI DevMaster Hackathon Submission - Track 2: Agentic AI**

## Project Overview
This project deploys an intelligent multi-agent workflow to automate Web3 security auditing. Utilizing CrewAI and LangChain, it features specialized agents that reason through complex Solidity smart contract logic to identify vulnerabilities (e.g., reentrancy, access control) and autonomously generate actionable developer reports.

## Architecture & AMD ROCm Target Deployment
This agentic pipeline is explicitly architected to be hardware-agnostic at the orchestration layer while targeting **AMD Radeon GPUs** for local acceleration.

While this prototype repository is configured with a zero-local-storage cloud-based LLM configuration (via Google Gemini) for rapid prototyping and low-resource testing, the primary production target is designed to run locally using **Ollama compiled with the AMD ROCm v7 / HIP7 driver stack**.

* **ROCm Integration:** By switching the LLM provider in `main.py` from `ChatGoogleGenerativeAI` to `Ollama`, the agents seamlessly offload all inference to local Radeon VRAM.
* **VRAM Efficiency:** The multi-agent sequential process passes context sequentially rather than concurrently, ensuring that local AMD GPUs can process large codebases without hitting system memory bottlenecks.

## How to Run (Prototype Mode)
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure your API Key:**
   Create a `.env` file in the project root containing:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```
3. **Execute the agent crew:**
   ```bash
   python main.py
   ```
4. **View the results:**
   The agents will analyze `sample_contract.sol` and output the audit findings directly into `audit_report.md`.