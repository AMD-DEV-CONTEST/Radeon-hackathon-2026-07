# WhatsApp Priority Agent

**Track:** 2 - Development & Local Deployment of Private AI Agents  
**Team:** Sandeep Kumar  
**GitHub:** Qisanxi

## Project Links
- **Source Code:** https://github.com/Qisanxi/Whatsapp_priority_agent.git
  

## What It Does
AI-powered WhatsApp Business agent that automatically classifies incoming messages by priority (URGENT/HIGH/NORMAL/LOW) and generates contextual replies. URGENT/HIGH messages get instant auto-replies. NORMAL/LOW queue for human approval.

## AMD Radeon GPU / ROCm Usage
- Dedicated vLLM instance running Qwen2.5-7B-Instruct on AMD Radeon Cloud
- Core inference executes on AMD Radeon GPU via ROCm software stack
- OpenAI-compatible API endpoint served by vLLM

## Core Capabilities (Track 2)
- ✅ Priority Classification (LLM-based)
- ✅ Contextual Reply Generation  
- ✅ Auto-reply for URGENT/HIGH priority
- ✅ Human-in-the-loop approval for NORMAL/LOW
- ✅ Multi-turn conversation memory (PostgreSQL)
- ✅ Real-time analytics dashboard

## Tech Stack
- **Backend:** Python, FastAPI, PostgreSQL, SQLAlchemy
- **Frontend:** React 18, Tailwind CSS v4, Recharts, Lucide React
- **AI:** Qwen2.5-7B-Instruct via vLLM on AMD Radeon Cloud (ROCm)
- **Database:** PostgreSQL

## Architecture
See `docs/architecture.png` in source repo.

## Demo
3-minute video demonstrating:
- Message priority classification on AMD Radeon GPU
- Instant auto-reply for URGENT messages
- Human approval queue for NORMAL messages
- WhatsApp-style contact grouping and conversation threads
- Real-time priority analytics
