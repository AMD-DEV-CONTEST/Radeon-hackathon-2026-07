# Track 2 — Development & Local Deployment of Private AI Agents

**Hackathon Track:** Track 2 — Development & Local Deployment of Private AI Agents  
**Goal:** Build and deploy a fully private, locally-running AI agent for parcel tracking using AMD GPUs (ROCm), vLLM, and containerized microservices.

> 🎥 **Demo Video:** [Watch the full demo on YouTube](https://youtu.be/ibtcmalu6101)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Cloning the Repository](#cloning-the-repository)
5. [Pulling the GHCR Container Image](#pulling-the-ghcr-container-image)
6. [ROCm + vLLM Integration](#rocm--vllm-integration)
7. [Running the Application](#running-the-application)
   - [Full Stack with Docker Compose](#full-stack-with-docker-compose)
   - [Local Development (H2 + Ollama)](#local-development-h2--ollama)
   - [Remote Access (AMD Team Server)](#remote-access-amd-team-server)
8. [Environment Variables](#environment-variables)
9. [API Endpoints](#api-endpoints)

---

## Overview

This project is a **private AI agent** for parcel tracking that runs entirely on your own hardware — no external API calls, no data leaving your machine. It combines:

- **Spring Boot 3** backend with **Pekko actor system** for concurrent message processing
- **vLLM** serving LLMs (e.g., Llama 3.2) via an OpenAI-compatible API on **AMD GPUs using ROCm**
- **PostgreSQL + pgvector** for structured order data and RAG (Retrieval-Augmented Generation) vector embeddings
- **Swagger UI** for interactive API exploration
- **GitHub Container Registry (GHCR)** for pre-built Docker images

The agent can answer questions like:
- *"Where is my package TRK-00001?"*
- *"What is the status of order TRK-00005?"*
- *"What is your refund policy?"* (via RAG on ingested documents)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Stack                         │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐   │
│  │   Frontend    │    │   Spring Boot    │    │   vLLM Server    │   │
│  │  (Any HTTP    │───▶│   Backend        │───▶│  (ROCm / AMD)    │   │
│  │   Client)     │    │  :8080           │    │  :8000           │   │
│  └──────────────┘    └────────┬─────────┘    └──────────────────┘   │
│                               │                                     │
│                               ▼                                     │
│                     ┌──────────────────┐                            │
│                     │   PostgreSQL     │                            │
│                     │   + pgvector     │                            │
│                     │   :5432          │                            │
│                     └──────────────────┘                            │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Internal Data Flow                                │
│                                                                     │
│  HTTP Request ──▶ ChatController ──▶ SupervisorActorEngine          │
│                                          │                          │
│                                          ▼                          │
│                                   GatewayActor                      │
│                                    /        \                       │
│                                   ▼          ▼                      │
│                          Worker Actors    Session Actors            │
│                              │                  │                   │
│                              ▼                  ▼                   │
│                       OrderTracking DB    RAG Vector Store          │
│                       (PostgreSQL)        (pgvector)                │
└─────────────────────────────────────────────────────────────────────┘
```

**How the AI Agent Processes a Request:**

```
User: "Where is my package TRK-00001?"

  1. POST /api/chat  { message, sessionId }
  2. ChatController receives request
  3. SupervisorActorEngine sends message to GatewayActor (Pekko)
  4. GatewayActor routes to SessionActor for this session
  5. SessionActor calls Spring AI ChatClient with the message
  6. ChatClient sends prompt to vLLM (OpenAI-compatible endpoint)
  7. vLLM runs Llama 3.2 on AMD GPU via ROCm
  8. LLM decides to call tool: trackParcel("TRK-00001")
  9. AgentTools.trackParcel() queries OrderTracking DB via Pekko actor
  10. Result returned to LLM → LLM formulates natural language reply
  11. Reply flows back: SessionActor → GatewayActor → Engine → Controller → User

Response: "Your package TRK-00001 is currently in transit from New York, NY
           to Los Angeles, CA. Estimated delivery is August 5, 2026."
```

---

## Prerequisites

- **AMD GPU** with ROCm support (tested on Radeon RX 7900 XTX, MI250, etc.)
- **ROCm 6.x** installed and configured ([ROCm installation guide](https://rocm.docs.amd.com/en/latest/))
- **Docker** 24+ with `compose` plugin
- **Docker** configured for AMD GPU access (see [ROCm Docker support](https://rocm.docs.amd.com/en/latest/deploy/docker.html))
- **Git**
- **Java 21+** (only for local development without Docker)
- **Maven 3.9+** (only for local development without Docker)

---

## Cloning the Repository

```bash
git clone https://github.com/malu2555/parceltracking.git
cd parceltracking
```

---

## Pulling the GHCR Container Image

The backend Docker image is published to **GitHub Container Registry (GHCR)**. You can pull it directly without building from source:

```bash
# Pull the latest backend image
docker pull ghcr.io/malu2555/parceltracking:latest
```

The image is built automatically by the CI/CD pipeline (`.github/workflows/ci.yml`) on every push to the `main` branch. The pipeline:

1. Checks out the repository
2. Builds the Java application with Maven
3. Runs tests
4. Logs in to GHCR using `GITHUB_TOKEN`
5. Builds and pushes the Docker image to `ghcr.io/malu2555/parceltracking:latest`

> **Note:** The `docker-compose.yml` references this image directly (`image: ghcr.io/malu2555/parceltracking:latest`), so `docker compose up` will pull it automatically if not present locally.

---

## ROCm + vLLM Integration

This project uses **vLLM** with **ROCm** support to run large language models locally on AMD GPUs. The `docker-compose.yml` configures the `rocm-vllm-server` service with AMD GPU device reservations:

```yaml
rocm-vllm-server:
  image: vllm/vllm:<CHOOSE_YOUR_TARGET_ROCM_AND_GPU_TAG>
  container_name: rocm-vllm-server
  environment:
    MODEL: meta-llama/Meta-Llama-3.2-1B-Instruct
  deploy:
    resources:
      reservations:
        devices:
          - driver: amd
            count: all
            capabilities: [gpu]
  volumes:
    - /dev/shm:/dev/shm
  ipc: host
```

**Key points:**

- The vLLM container uses `driver: amd` to access AMD GPUs via ROCm
- The image is `vllm/vllm:<CHOOSE_YOUR_TARGET_ROCM_AND_GPU_TAG>` — replace the tag with the appropriate ROCm + GPU combination for your hardware (e.g., `rocm-6.2.0-mi300` for MI300 series, `rocm-6.2.0-mi250` for MI250, etc.). See [vLLM ROCm installation docs](https://docs.vllm.ai/en/latest/getting_started/amd-installation.html) for available tags.
- The model is specified via the `MODEL` environment variable (default: `meta-llama/Meta-Llama-3.2-1B-Instruct`)
- vLLM exposes an **OpenAI-compatible API** at port `8000`
- The Spring Boot backend connects to vLLM via `OPENAI_BASE_URL=http://rocm-vllm-server:8000/v1`
- Shared memory (`/dev/shm`) and `ipc: host` are required for vLLM's tensor parallelism

**How the backend connects to vLLM:**

```yaml
# In docker-compose.yml (backend service)
environment:
  OPENAI_BASE_URL: http://rocm-vllm-server:8000/v1
  OPENAI_CHAT_MODEL: meta-llama/Meta-Llama-3.2-1B-Instruct
```

```yaml
# In application.yml (Spring Boot config)
spring:
  ai:
    openai:
      base-url: ${OPENAI_BASE_URL:http://localhost:8000/v1}
      chat:
        model: ${OPENAI_CHAT_MODEL:llama3.2}
```

The Spring AI `OpenAI` starter auto-configures a `ChatClient` bean that points to the local vLLM endpoint. No external API keys are needed — the `api-key` is set to `not-needed` by default.

---

## Running the Application

### Full Stack with Docker Compose (Production)

This starts all three services: PostgreSQL, Spring Boot backend, and vLLM with ROCm GPU acceleration.

```bash
# 1. Clone the repo
git clone https://github.com/malu2555/parceltracking.git
cd parceltracking

# 2. Start all services
docker compose up -d

# 3. Check logs
docker compose logs -f

# 4. Verify services are running
docker compose ps
```

**What happens:**

| Service | Container Name | Port | Description |
|---------|---------------|------|-------------|
| `db` | `parceltracking-db` | 5432 | PostgreSQL 18 with pgvector |
| `backend` | `parceltracking` | 8080 | Spring Boot AI agent |
| `rocm-vllm-server` | `rocm-vllm-server` | 8000 | vLLM with ROCm on AMD GPU |

**Access the application:**

| Interface | URL |
|-----------|-----|
| Swagger UI (local) | http://localhost:8080/swagger-ui.html |
| Swagger UI (AMD team server) | http://<AMD_SERVER_IP>:8080/swagger-ui.html |
| OpenAPI docs | http://localhost:8080/api-docs |
| Chat API | `POST http://localhost:8080/api/chat` |
| Auth API | `POST http://localhost:8080/api/auth/session` |

### Remote Access (AMD Team Server)

To access the application from another machine on the same network (e.g., an AMD team server), start the stack as usual and use the server's IP address:

```bash
# On the AMD server with GPU
git clone https://github.com/malu2555/parceltracking.git
cd parceltracking
docker compose up -d

# From any machine on the same network, open in browser:
# http://<AMD_SERVER_IP>:8080/swagger-ui.html
```

Replace `<AMD_SERVER_IP>` with the actual IP address of the machine running Docker. For example:

```bash
# If the AMD server IP is 192.168.1.100
# Open http://192.168.1.100:8080/swagger-ui.html in your browser
```

All API endpoints are accessible remotely via `http://<AMD_SERVER_IP>:8080/...` — no additional configuration needed.

### Local Development (H2 + Ollama)

For development without Docker or AMD GPU, use the `dev` profile with H2 database and Ollama:

```bash
# 1. Start Ollama with a model
ollama pull llama3.2
ollama serve

# 2. Run the Spring Boot app with dev profile
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_CHAT_MODEL=llama3.2
./mvnw spring-boot:run -Dspring-boot.run.profiles=dev

# 3. Access Swagger UI at http://localhost:8080/swagger-ui.html
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPRING_PROFILES_ACTIVE` | `prod` | Spring profile (`prod` = PostgreSQL, `dev` = H2) |
| `SPRING_DATASOURCE_URL` | `jdbc:postgresql://localhost:5432/parceltracking` | Database JDBC URL |
| `SPRING_DATASOURCE_USERNAME` | `parcel` | Database username |
| `SPRING_DATASOURCE_PASSWORD` | `secret` | Database password |
| `OPENAI_BASE_URL` | `http://localhost:8000/v1` | vLLM/Ollama endpoint URL |
| `OPENAI_CHAT_MODEL` | `llama3.2` | LLM model name |
| `OPENAI_API_KEY` | `not-needed` | API key (not needed for local inference) |
| `X-Admin-Key` | `admin-secret-key` | Admin API key for document ingestion |

---

## API Endpoints

### 1. Create a Session

```bash
curl -X POST http://localhost:8080/api/auth/session
```

**Response:**
```json
{
  "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 2. Chat with the AI Agent

```bash
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Where is my package TRK-00001?",
    "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }'
```

**Response:**
```json
{
  "reply": "Your package TRK-00001 is currently in transit from New York, NY to Los Angeles, CA. Estimated delivery is August 5, 2026.",
  "sessionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 3. Ingest a Document (Admin)

```bash
curl -X POST http://localhost:8080/api/admin/ingest \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: admin-secret-key" \
  -d '{
    "content": "Our refund policy allows returns within 30 days of delivery...",
    "documentId": "refund-policy-v1"
  }'
```

---

# Parcel Tracking AI Agent

## How the Application Works

The Parcel Tracking AI Agent is a **conversational AI assistant** that answers questions about package shipments using a combination of structured database queries and RAG (Retrieval-Augmented Generation) on policy documents. It runs entirely on local infrastructure with AMD GPU acceleration.

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                                   │
│                                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────────┐   ┌─────────────────────┐  │
│  │  Swagger UI   │   │  Headless    │   │  Custom Frontend    │   │  AMD Team Server     │  │
│  │  (Browser)    │   │  CLI (curl)  │   │  (React/Vue/etc.)  │   │  (Remote Access)     │  │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬──────────┘   └──────────┬──────────┘  │
│         │                  │                       │                          │              │
│         └──────────────────┼───────────────────────┼──────────────────────────┘              │
│                            │                                             │
│                            ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    REST API (Port 8080)                         │    │
│  │  POST /api/auth/session    POST /api/chat    POST /api/admin/*  │    │
│  └────────────────────────────┬────────────────────────────────────┘    │
│                               │                                         │
│                               ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    SPRING BOOT BACKEND                          │    │
│  │                                                                 │    │
│  │  ┌────────────────┐    ┌──────────────────────────────────┐     │    │
│  │  │ ChatController  │───▶│  SupervisorActorEngine          │     │    │
│  │  │ AuthController  │    │  (Pekko Actor Bridge)           │     │    │
│  │  │ AdminController │    └──────────────┬───────────────────┘     │    │
│  │  └────────────────┘                   │                         │    │
│  │                                       ▼                         │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │              PEKKO ACTOR SYSTEM                          │   │    │
│  │  │                                                          │   │    │
│  │  │  ┌──────────────┐                                       │   │    │
│  │  │  │ GatewayActor  │── Routes messages to appropriate      │   │    │
│  │  │  └──────┬───────┘   workers and session actors           │   │    │
│  │  │         │                                                │   │    │
│  │  │    ┌────┴──────────────┐                                 │   │    │
│  │  │    ▼                   ▼                                 │   │    │
│  │  │  ┌────────────┐  ┌────────────┐                         │   │    │
│  │  │  │ Worker      │  │ Session    │                         │   │    │
│  │  │  │ Actors      │  │ Actors     │                         │   │    │
│  │  │  │ (Track,     │  │ (Per-User  │                         │   │    │
│  │  │  │  Status,    │  │  Chat)     │                         │   │    │
│  │  │  │  RAG)       │  │            │                         │   │    │
│  │  │  └──────┬──────┘  └──────┬─────┘                         │   │    │
│  │  └─────────┼────────────────┼───────────────────────────────┘   │    │
│  │            │                │                                    │    │
│  │            ▼                ▼                                    │    │
│  │  ┌────────────────┐  ┌────────────────┐                         │    │
│  │  │ AgentTools      │  │ Spring AI      │                         │    │
│  │  │ (@Tool methods) │  │ ChatClient     │                         │    │
│  │  └───────┬────────┘  └───────┬────────┘                         │    │
│  └──────────┼───────────────────┼──────────────────────────────────┘    │
│             │                   │                                       │
│             ▼                   ▼                                       │
│  ┌────────────────┐  ┌────────────────────┐                            │
│  │  PostgreSQL     │  │  vLLM (ROCm/AMD)   │                            │
│  │  + pgvector     │  │  OpenAI-compatible  │                            │
│  │  :5432          │  │  :8000              │                            │
│  └────────────────┘  └────────────────────┘                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Interaction Flow Diagram

```
┌──────┐     ┌──────────┐     ┌──────────┐     ┌────────┐     ┌──────────┐
│User  │     │Swagger/  │     │Spring    │     │Pekko   │     │vLLM +    │
│      │     │CLI/Front │     │Boot      │     │Actors  │     │DB        │
└──┬───┘     └────┬─────┘     └────┬─────┘     └───┬────┘     └────┬─────┘
   │              │                │                │               │
   │ 1. POST      │                │                │               │
   │ /api/auth/   │                │                │               │
   │ session      │                │                │               │
   │─────────────▶│                │                │               │
   │              │ 2. Create UUID │                │               │
   │              │ session        │                │               │
   │              │───────────────▶│                │               │
   │              │                │ 3. Save session│               │
   │              │                │───────────────▶│               │
   │              │                │◀───────────────│               │
   │              │◀───────────────│                │               │
   │◀─────────────│                │                │               │
   │              │                │                │               │
   │ 4. POST      │                │                │               │
   │ /api/chat    │                │                │               │
   │ {message,    │                │                │               │
   │  sessionId}  │                │                │               │
   │─────────────▶│                │                │               │
   │              │ 5. Forward to  │                │               │
   │              │ Engine         │                │               │
   │              │───────────────▶│                │               │
   │              │                │ 6. Ask         │               │
   │              │                │ GatewayActor   │               │
   │              │                │───────────────▶│               │
   │              │                │                │               │
   │              │                │ 7. Route to    │               │
   │              │                │ SessionActor   │               │
   │              │                │◀───────────────│               │
   │              │                │                │               │
   │              │                │ 8. ChatClient  │               │
   │              │                │ send()         │               │
   │              │                │───────────────────────────────▶│
   │              │                │                │               │
   │              │                │ 9. LLM calls   │               │
   │              │                │ tool:          │               │
   │              │                │ trackParcel()  │               │
   │              │                │◀───────────────────────────────│
   │              │                │                │               │
   │              │                │ 10. Query DB   │               │
   │              │                │ via Worker     │               │
   │              │                │───────────────▶│               │
   │              │                │◀───────────────│               │
   │              │                │                │               │
   │              │                │ 11. LLM        │               │
   │              │                │ formulates     │               │
   │              │                │ reply          │               │
   │              │                │◀───────────────────────────────│
   │              │                │                │               │
   │              │                │ 12. Return     │               │
   │              │                │ reply          │               │
   │              │◀───────────────│                │               │
   │              │                │                │               │
   │ 13. JSON     │                │                │               │
   │ response     │                │                │               │
   │◀─────────────│                │                │               │
   │              │                │                │               │
```

### Three Ways to Interact

#### 1. Swagger UI (Interactive Browser Interface)

Swagger UI provides a visual, interactive documentation page where you can explore and test all API endpoints directly from your browser.

**How to use:**

1. Start the application (see [Running the Application](#running-the-application))
2. Open http://localhost:8080/swagger-ui.html in your browser
3. You'll see all available endpoints organized by tags:
   - **Chat** — Send messages to the AI assistant
   - **Auth** — Create and validate sessions
   - **Admin** — Ingest documents into the knowledge base
4. Click on an endpoint to expand it
5. Click **"Try it out"** to send a live request
6. Fill in the required parameters and click **"Execute"**
7. View the response directly in the browser

**Example Swagger UI workflow:**

```
1. Open http://localhost:8080/swagger-ui.html
2. Expand POST /api/auth/session
3. Click "Try it out" → "Execute"
4. Copy the sessionId from the response
5. Expand POST /api/chat
6. Click "Try it out"
7. Paste sessionId and type: "Where is my package TRK-00001?"
8. Click "Execute" → See the AI reply
```

#### 2. Headless CLI (curl / Scripts)

For automation, scripting, or integration with other tools, use the REST API directly with `curl` or any HTTP client.

**Complete CLI workflow:**

```bash
#!/bin/bash

# Step 1: Create a session
echo "=== Creating session ==="
SESSION=$(curl -s -X POST http://localhost:8080/api/auth/session)
echo "$SESSION" | python -m json.tool

# Extract session ID
SESSION_ID=$(echo "$SESSION" | python -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")
echo "Session ID: $SESSION_ID"

# Step 2: Ask about a package
echo -e "\n=== Asking about package TRK-00001 ==="
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"Where is my package TRK-00001?\",
    \"sessionId\": \"$SESSION_ID\"
  }" | python -m json.tool

# Step 3: Ask about another package
echo -e "\n=== Asking about package TRK-00005 ==="
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"What is the status of TRK-00005?\",
    \"sessionId\": \"$SESSION_ID\"
  }" | python -m json.tool

# Step 4: Ask about refund policy (RAG)
echo -e "\n=== Asking about refund policy ==="
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d "{
    \"message\": \"What is your refund policy?\",
    \"sessionId\": \"$SESSION_ID\"
  }" | python -m json.tool
```

**One-liner examples:**

```bash
# Create session
SESSION_ID=$(curl -s -X POST http://localhost:8080/api/auth/session | python -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")

# Ask a question
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"Track TRK-00010\",\"sessionId\":\"$SESSION_ID\"}" | python -m json.tool
```

#### 3. Custom Frontend (Any HTTP Client)

Since the backend exposes a standard REST API with CORS enabled for all origins, you can build any frontend (React, Vue, Angular, Svelte, mobile app, etc.) that communicates with the API.

**CORS configuration** (from `SecurityConfig.java`):
- Allowed origins: `*` (any origin)
- Allowed methods: `GET, POST, PUT, DELETE, OPTIONS`
- Allowed headers: `*`
- Credentials: enabled

**Example React component:**

```jsx
import { useState } from 'react';

function ParcelTracker() {
  const [sessionId, setSessionId] = useState(null);
  const [message, setMessage] = useState('');
  const [reply, setReply] = useState('');

  const createSession = async () => {
    const res = await fetch('http://localhost:8080/api/auth/session', { method: 'POST' });
    const data = await res.json();
    setSessionId(data.sessionId);
  };

  const sendMessage = async () => {
    const res = await fetch('http://localhost:8080/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, sessionId })
    });
    const data = await res.json();
    setReply(data.reply);
  };

  return (
    <div>
      <button onClick={createSession}>Start Session</button>
      <input value={message} onChange={e => setMessage(e.target.value)} />
      <button onClick={sendMessage}>Send</button>
      <p>Reply: {reply}</p>
    </div>
  );
}
```

### Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                    END-TO-END DATA FLOW                              │
│                                                                     │
│  User Message                                                        │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. HTTP POST /api/chat                                      │   │
│  │    Body: { "message": "...", "sessionId": "..." }           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 2. ChatController receives request                           │   │
│  │    - Validates session via AuthService                       │   │
│  │    - Delegates to SupervisorActorEngine                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 3. SupervisorActorEngine sends ActorMessage.ChatMessage      │   │
│  │    to GatewayActor via Pekko ask pattern                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 4. GatewayActor routes to SessionActor for this sessionId    │   │
│  │    - Creates SessionActor if it doesn't exist                │   │
│  │    - Forwards ChatMessage to SessionActor                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 5. SessionActor calls Spring AI ChatClient.send()            │   │
│  │    - Sends prompt to vLLM (OpenAI-compatible endpoint)       │   │
│  │    - vLLM runs Llama 3.2 on AMD GPU via ROCm                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 6. LLM decides which tool to call based on user message      │   │
│  │                                                              │   │
│  │    "Where is my package?"  ──▶ trackParcel(trackingNumber)   │   │
│  │    "What is the status?"   ──▶ getParcelStatus(trackingNum)  │   │
│  │    "What is your policy?"  ──▶ searchRag(query, sessionId)   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 7. AgentTools.@Tool method executes:                        │   │
│  │    - Sends ActorMessage to GatewayActor                     │   │
│  │    - GatewayActor routes to appropriate WorkerActor         │   │
│  │    - WorkerActor queries database or vector store           │   │
│  │    - Result returned to LLM                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 8. LLM formulates natural language reply                    │   │
│  │    - Incorporates tool result into conversational response   │   │
│  │    - Returns reply text                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 9. Reply flows back through the chain:                      │   │
│  │    SessionActor → GatewayActor → Engine → Controller → User  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│      │                                                               │
│      ▼                                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 10. User receives JSON response:                             │   │
│  │     { "reply": "Your package...", "sessionId": "..." }       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **ChatController** | Spring Boot REST | HTTP endpoint for chat messages |
| **SupervisorActorEngine** | Pekko Actor Bridge | Synchronous & async bridge between HTTP and actor system |
| **GatewayActor** | Pekko Actor | Central message router — dispatches to workers and session actors |
| **SessionActor** | Pekko Actor | Per-user conversation state and AI interaction |
| **WorkerActor** | Pekko Actor | Handles specific tasks: tracking, status, RAG queries |
| **AgentTools** | Spring AI @Tool | Exposes callable tools for the LLM (trackParcel, searchRag, etc.) |
| **ChatClient** | Spring AI | Sends prompts to vLLM and receives LLM responses |
| **vLLM** | ROCm/AMD | Serves LLM with OpenAI-compatible API on AMD GPU |
| **PostgreSQL + pgvector** | Database | Stores order data and RAG vector embeddings |
| **AuthService** | Spring Boot | Manages guest session lifecycle (UUID-based) |
| **RagRetrievalWorker** | Pekko Actor | Handles RAG queries against the vector store |

### Available AI Tools

The LLM has access to these tools (defined in `AgentTools.java`):

| Tool | Description | Example Call |
|------|-------------|-------------|
| `trackParcel` | Track a parcel by tracking number | `trackParcel("TRK-00001")` |
| `getParcelStatus` | Get current delivery status | `getParcelStatus("TRK-00005")` |
| `searchRag` | Search ingested documents via RAG | `searchRag("refund policy", sessionId)` |
| `ingestDocument` | Ingest a document into knowledge base | `ingestDocument("content...", "doc-id")` |

### Seed Data

The application comes pre-loaded with **50 synthetic orders** (TRK-00001 through TRK-00050) in `data.sql`, covering various statuses:

| Status | Count | Description |
|--------|-------|-------------|
| `IN_TRANSIT` | 10 | Package is moving through the network |
| `DELIVERED` | 10 | Package has been delivered |
| `PENDING` | 10 | Package is awaiting pickup or processing |
| `OUT_FOR_DELIVERY` | 10 | Package is on the final delivery route |
| `DELAYED` | 5 | Package is behind schedule |
| `EXCEPTION` | 5 | Package has an issue (damage, address problem, etc.) |

You can ask about any of these tracking numbers to test the AI agent.

---

## License

This project is part of a hackathon submission for **Track 2 — Development & Local Deployment of Private AI Agents**.
