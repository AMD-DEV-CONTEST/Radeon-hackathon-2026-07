from textwrap import dedent

def files_for(title: str, source_url: str, transcript: str) -> dict[str, str]:
    feature = "Collaborative workspace" if "notion" in title.lower() else "Video-inspired product"
    return {
        "README.md": dedent(f"""\
        # {title}

        Generated locally by Decompile from [{source_url}]({source_url}).

        ## What is included
        - Next.js frontend and FastAPI service contracts
        - Product requirements, architecture, QA and deployment guidance
        - Docker Compose development environment

        ## Getting started
        Copy `.env.example` to `.env`, then run `docker compose up --build`.
        """),
        "docs/PRD.md": dedent(f"""\
        # Product requirements — {title}

        ## Problem
        People need a focused way to turn the workflow demonstrated in a video into an actionable product.

        ## Users
        Builders, operators, and teams who want a calm, collaborative workflow.

        ## Goals
        1. Capture and organize meaningful work.
        2. Make collaboration understandable at a glance.
        3. Keep every important action traceable.

        ## Acceptance criteria
        - A user can create, browse, and update an item.
        - Updates preserve validation and an audit-ready timestamp.
        - Empty, loading, and failure states provide a next action.

        ## Edge cases
        Invalid input, stale updates, empty collections, and interrupted network requests.
        """),
        "docs/architecture.md": dedent(f"""\
        # Architecture

        ```mermaid
        flowchart LR
          U[User] --> W[Next.js web]
          W --> A[FastAPI API]
          A --> D[(Postgres)]
          A --> Q[Worker queue]
          Q --> E[Local embedding + inference]
        ```

        ## Components
        The web client renders the {feature.lower()}. The API owns validation and authorization boundaries.
        Workers process long-running work and persist observable job state.

        ## API
        `GET /api/items`, `POST /api/items`, `PATCH /api/items/{{id}}`.

        ## Data model
        ```mermaid
        erDiagram
          USER ||--o{{ WORKSPACE : owns
          WORKSPACE ||--o{{ ITEM : contains
          ITEM ||--o{{ ACTIVITY : records
        ```
        """),
        "docs/QA.md": dedent("""\
        # Test plan

        ## API
        - Create item with valid and invalid payloads.
        - Reject unauthenticated mutations when auth is enabled.
        - Return stable error shapes.

        ## Manual checks
        - Keyboard navigation and visible focus.
        - Mobile layout at 320px.
        - Loading, empty, and retry states.
        """),
        "docs/deployment.md": dedent("""\
        # Deployment

        Build immutable images in CI, inject secrets from the deployment platform, and run migrations before switching traffic. Use health checks at `/health` and keep the model runtime on a private network.
        """),
        "backend/app/main.py": dedent("""\
        from fastapi import FastAPI
        app = FastAPI(title="Generated service")

        @app.get("/health")
        def health(): return {"status": "ok"}
        """),
        "frontend/app/page.tsx": dedent("""\
        export default function Page() {
          return <main><h1>Generated product</h1><p>Start building from this decompiled blueprint.</p></main>
        }
        """),
        "docker/Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nCMD [\"python\", \"-m\", \"uvicorn\", \"app.main:app\"]\n",
        ".env.example": "DATABASE_URL=postgresql://app:app@db:5432/app\n",
        "transcript/source.txt": transcript,
    }
