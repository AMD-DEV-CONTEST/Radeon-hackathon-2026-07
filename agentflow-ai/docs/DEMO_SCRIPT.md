# Demo Script

## 60-second intro
“AgentFlow AI is an offline autonomous multi-agent platform. Instead of one chatbot answer, it coordinates five agents: Planner, Research, Memory, Tool, and Reviewer. Every response is grounded in local files, persistent SQLite memory, and transparent execution timelines.”

## Demo flow

### 1. Show the UI
- Open the app.
- Point out:
  - left sidebar for uploads and conversations
  - center workflow chat
  - right control tower for agent status, benchmark metrics, and hardware

### 2. Upload a sample PDF
- Upload `sample_data/agentflow_brief.pdf`
- Explain that the file is chunked locally and indexed into ChromaDB.

### 3. Ask for a complex autonomous task
Use a prompt like:

> Plan a hackathon demo strategy using the uploaded PDF, identify risks, propose milestones, and give me a final execution checklist.

### 4. Narrate the agent pipeline
Explain the visible workflow:
- Planner creates the task graph
- Research retrieves local evidence from ChromaDB
- Memory recalls prior chat context
- Tool Agent runs safe utilities if useful
- Reviewer polishes the answer

### 5. Highlight observability
Open the returned assistant card and show:
- task plan
- execution timeline
- citations
- tools executed
- latency benchmark

### 6. Show resilience
Stop Ollama or mention the offline fallback behavior:
- AgentFlow AI surfaces a friendly warning
- the app does not crash
- it still preserves deterministic orchestration and local context where possible

## Closing pitch
“AgentFlow AI makes agentic execution visible, local, auditable, and demo-ready — which is exactly what judges want to see in a serious multi-agent hackathon project.”
