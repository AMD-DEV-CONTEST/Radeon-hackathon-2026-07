# Private SOC Triage Agent

Locally-deployed AI agent for security alert triage, running on AMD Radeon GPU.
Built for AMD AI DevMaster Hackathon — Track 2: Agentic AI.

## What it does

Ingests alerts from Wazuh / Suricata / Greenbone, retrieves relevant context
from a local knowledge base (MITRE ATT&CK, CVE data), reasons over the
incident in multi-turn conversation, and recommends triage actions — all with
core inference running locally on an AMD Radeon GPU via vLLM. No alert data
leaves the network.

See [PROJECT_SPEC.md](./PROJECT_SPEC.md) for architecture, scenarios, and the
Radeon optimization writeup.

## Requirements

- AMD Radeon GPU with ROCm 6.x
- Python 3.10+
- vLLM (ROCm build)
- Access to Wazuh / Suricata / Greenbone instances (or use `data/sample_alerts/`
  for demo mode without live connections)

## Environment setup

```bash
git clone <this-repo-url>
cd soc-triage-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --break-system-packages

cp .env.example .env
# edit .env: set WAZUH_URL, WAZUH_TOKEN, GREENBONE_URL, MODEL_NAME, etc.
```

## Starting the model server (on the Radeon GPU instance)

```bash
bash scripts/check_env.sh          # verify GPU / ROCm / vLLM are ready
bash scripts/start_vllm.sh         # serves the model on port 8000
```

## Building the RAG index (one-time, before first run)

```bash
python scripts/build_rag_index.py
```

## Running the agent

```bash
python -m src.main --mode demo      # uses data/sample_alerts/, no live connectors
python -m src.main --mode live      # connects to real Wazuh/Suricata/Greenbone
```

Chat UI available at http://localhost:7860 once running.

## Project structure

```
src/
  orchestrator/   agent loop: planning, tool routing, memory, permissions
  tools/          connectors to Wazuh, Suricata, Greenbone
  rag/            knowledge base ingestion + retrieval (MITRE ATT&CK, CVE)
  llm/            vLLM client wrapper (OpenAI-compatible API)
  ui/             chat interface
data/
  knowledge_base/ source docs for RAG index
  sample_alerts/  sample alert exports for demo mode
scripts/          env check, vLLM launch, RAG index build
docs/             architecture diagram, demo video link
supplementary/    poster / slides
```

## Dependencies

See `requirements.txt`. Core: `vllm`, `chromadb`, `fastapi`, `gradio`,
`sentence-transformers`, `requests`, `python-dotenv`.

## License / hackathon notes

Submitted for AMD AI DevMaster Hackathon, Track 2. See hackathon Rules &
Conditions for IP terms.
