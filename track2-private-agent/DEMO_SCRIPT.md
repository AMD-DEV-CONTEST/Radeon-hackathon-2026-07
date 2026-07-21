# Track 2 Demo Script — 1bit Jarvis Private AI Agent
## Duration: ~3-5 minutes

### Scene 1: Starting the Agent (30s)
```bash
# Show the agent starting up
cd 1bit-systems
JARVIS_PORT=8080 python3 -m jarvis.server
# Output shows: "Listening on http://0.0.0.0:8080"
```

### Scene 2: Basic Chat & Multi-Turn Memory (60s)
```bash
# First message — introduce yourself
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"Hi! My name is Alice. I work at a tech startup."}],"max_tokens":100}'
# → Agent responds, remembers the conversation

# Second message — demonstrate memory recall
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"What is my name and where do I work?"}],"session_id":"alice_demo","max_tokens":100}'
# → "Your name is Alice and you work at a tech startup"
```

### Scene 3: Tool Invocation — Knowledge Search (60s)
```bash
# Upload a document to the knowledge base
curl http://localhost:8080/v1/rag/upload \
  -F "file=@docs/startup-guide.md" \
  -F "title=Startup Guide"

# Ask about it
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"Search the knowledge base for information about startup funding"}],"max_tokens":150}'
# → Agent searches knowledge base and returns grounded answer
```

### Scene 4: Tool Invocation — Time & Notes (60s)
```bash
# Agent uses get_time tool
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"What time is it right now? Also add a note to buy groceries"}],"max_tokens":150}'
# → Agent calls TOOL_CALL: get_time and TOOL_CALL: add_note
```

### Scene 5: MI300X Cloud Deployment (30s)
Show the DigitalOcean/AMD DevCloud dashboard with the MI300X droplet running,
then SSH into it and show the GPU:
```bash
ssh root@165.245.136.91
rocm-smi
# Shows: AMD Instinct MI300X VF — 192 GB VRAM
```

### Scene 6: Multi-Step Planning (30s)
```bash
# Complex request that requires decomposition
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"Plan my day: check the time, search for coffee shops near me, and save a reminder"}],"max_tokens":200}'
# → Agent decomposes into subtasks, routes each to the right model, synthesizes result
```
