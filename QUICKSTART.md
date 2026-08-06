# EduCopilot Quickstart

This guide runs EduCopilot locally in Docker for AMD Hackathon evaluation.
EduCopilot connects to an **OpenAI-compatible API endpoint backed by AMD ROCm**.
The ROCm inference service can run on an AMD GPU host or be provided by a
ROCm-enabled model server elsewhere on the network. EduCopilot only needs its
OpenAI-compatible HTTP endpoint.

## Prerequisites

- Docker Desktop with the Linux engine running
- An OpenAI-compatible ROCm model endpoint
- The endpoint URL, API key, and model name

The endpoint must support the OpenAI Chat Completions API, including
`/v1/chat/completions` and `/v1/models`.

## 1. Configure the endpoint

An `.env` file is optional. If you do not create one, Docker Compose falls back
to the existing local Ollama setup using `gemma4` at
`http://host.docker.internal:11434/v1`. Start Ollama, make sure the model is
available, and skip to [Start EduCopilot](#2-start-educopilot).

Create a local `.env` file in the project folder. You can start from the
provided template:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with the endpoint backed by your AMD ROCm deployment:

```dotenv
OPENAI_BASE_URL=http://host.docker.internal:8000/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
SECRET_KEY=local-development-key
```

Examples of `OPENAI_BASE_URL`:

- `http://host.docker.internal:8000/v1` for a ROCm model server on the Docker host
- `http://192.168.1.50:8000/v1` for a ROCm model server on another machine
- `https://your-rocm-endpoint.example.com/v1` for a hosted ROCm endpoint

Do not commit `.env`; it may contain an API key. The repository includes
`.env.example` as a safe template.

## 2. Start EduCopilot

Run this single command from the project folder:

```powershell
docker compose up --build -d
```

Docker Compose automatically reads `.env` and passes the three LLM settings to
the container. EduCopilot stores its SQLite database and Chroma data in the
`educopilot_data` Docker volume.

## 3. Test the application

Open:

**http://localhost:7860**

Check startup logs if needed:

```powershell
docker compose logs -f educopilot
```

The dashboard reports whether the configured endpoint is reachable. Create a
small test course to verify that generation requests reach the AMD ROCm-backed
model.

## Stop and restart

Stop the container:

```powershell
docker compose down
```

Start it again without rebuilding:

```powershell
docker compose up -d
```

After changing `.env`, recreate the container so it receives the new values:

```powershell
docker compose up -d --force-recreate
```

## Troubleshooting

- **Docker engine unavailable:** Start Docker Desktop and confirm its Linux engine is running.
- **Endpoint unreachable:** Confirm the ROCm model server is running, listening on the configured host/interface, and reachable from Docker.
- **Model not found:** Check that `OPENAI_MODEL` exactly matches a model exposed by the endpoint.
- **401 or authentication errors:** Check `OPENAI_API_KEY` in `.env`.
- **Existing local data:** The local `educopilot.db` is excluded from the image. Use the persistent Docker volume or migrate the database explicitly if existing courses must be retained.
