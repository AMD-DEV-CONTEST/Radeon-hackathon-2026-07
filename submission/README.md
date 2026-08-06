# Werewolf Game

An AI-powered Werewolf social game built with Python, Streamlit, LangChain, LangGraph, RAG, and local LLM inference.

The application supports AI-controlled villagers and werewolves, multi-agent discussion, voting, role-based reasoning, long-term game memory, and human participation.

## Features

- Supports 5–8 players
- Supports a maximum of two werewolves
- AI-agent discussion and social reasoning
- Human player participation through Streamlit
- Day and night game phases
- Werewolf victim selection
- Player voting and elimination
- Agent personality profiles
- RAG-based background knowledge retrieval
- Long-term memory using game-turn summaries
- Structured game-state tools
- Role-based information access control
- Local LLM inference through vLLM
- AMD Radeon GPU acceleration through ROCm

## Source Code

Source code link: https://github.com/JimBeam2019/werewolf-game

## Demo Video

Demo Video link: [submission/demo-video/Werewolf Game.mp4](https://github.com/JimBeam2019/Radeon-hackathon-2026-07/blob/main/submission/demo-video/Werewolf%20Game.mp4)

## Team Details

- Team Name: **Coffee & Code**
- Team member: Jinbin Liang (Team lead/Deverloper/Researcher)
- Volunteer Contributor: David Coronel (Coder)

## Project Architecture

```text
streamlit_app.py
│
├── Presentation Layer
│   └── Streamlit user interface
│
├── Application Layer
│   ├── Game orchestration
│   ├── LangGraph workflows
│   └── Agent coordination
│
├── Domain Layer
│   ├── Game entities
│   ├── Game rules
│   ├── Player roles
│   └── Game state
│
└── Infrastructure Layer
    ├── LangChain LLM clients
    ├── vLLM integration
    ├── RAG retrieval
    ├── Vector store
    └── Long-term memory
```

## Environment Requirements

- Python 3.11 or later
- AMD Radeon GPU with ROCm support
- ROCm-compatible PyTorch
- vLLM with ROCm support
- Git

The application can also be developed using a CPU or another supported inference backend, although GPU inference is recommended for multi-agent interaction.

## Environment Setup

Clone the project:

```bash
git clone https://github.com/JimBeam2019/werewolf-game.git
cd werewolf-game
```

Create and activate a virtual environment:

Linux:

```bash
uv venv
source .venv/bin/activate
```

Windows:

```powershell
uv venv
.venv\Scripts\activate
```

Install the Python dependencies:

```bash
uv sync
```

## Model Deployment

Start the Qwen models using vLLM in **separate terminal tabs**:

- Embedding LLM Model

```bash
vllm serve Qwen/Qwen3-Embedding-0.6B --port 8001 --runner pooling --gpu-memory-utilization 0.15
```

- LLM Model

```bash
VLLM_ROCM_USE_AITER=1 \
vllm serve Qwen/Qwen2.5-7B-Instruct \
    --port 8000 \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 16 \
    --gpu-memory-utilization 0.75
```

After the server starts, verify the model API:

```bash
curl http://localhost:8000/v1/models
```

The model API should be available at:

```text
http://localhost:8000/v1
```

## Application Configuration

Create a `.env` file in the project root:

```env
USE_VLLM=True
AGENT_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
LLM_BASE_URL=http://localhost:8000/v1
EMBEDDING_LLM_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_LLM_BASE_URL=http://localhost:8001/v1
```

Update the URLs if the LLM or embedding services are deployed on different hosts or ports.

## Start the Application

Run the Streamlit application:

```bash
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501 --server.baseUrlPath ""
```

Expose RC Tunnel

```bash
"$HOME/.local/bin/rc-tunnel" expose --port 8501
```

Open the URL displayed by the RC Tunnel, usually:

```text
https://rc-0123456789abcdef.radeon.firstdg.ai
```

## Gameplay

1. Start a new game.
2. Select the number of players.
3. Assign villagers and werewolves at random.
4. During the discussion phase, AI agents exchange messages based on their roles, personalities, and available information.
5. Human players can submit messages through the chat interface.
6. Living players vote for a suspected werewolf.
7. The player with the most votes is eliminated.
8. During the night phase, werewolf agents select one victim.
9. A game-turn summary is generated and saved to long-term memory.
10. The game continues until either the villagers or werewolves meet the victory condition.

## Dependencies

Main application dependencies:

```text
streamlit
langchain
langchain-core
langchain-openai
langgraph
pydantic
python-dotenv
```

RAG and vector retrieval dependencies:

```text
langchain-community
langchain-text-splitters
```

Local inference dependencies:

```text
vllm
```

The exact package versions should be defined in `pyproject.toml`.

## Optimization Configuration

The recommended inference configuration is:

```text
VLLM_ROCM_USE_AITER=1: vllm serve mistralai/Mixtral-8x7B-Instruct-v0.1
Data type: BF16
Maximum context length: 4096 tokens
Maximum concurrent sequences: 16
GPU memory utilization: 0.75
```

The application also reduces inference cost by:

- limiting agent response length;
- using RAG to retrieve only relevant information;
- storing game-turn summaries instead of repeatedly sending the full game history;
- using asynchronous requests for independent agent actions;
- using one model service for multiple game functions.

## Future Improvements

- Add more player roles and game rules.
- Add persistent game sessions.
- Add a larger vector database for long-running games.
- Add model benchmarking and automated performance tests.
- Support multiple local inference backends.
- Add multi-GPU model deployment.
- Improve agent planning and strategic coordination.
