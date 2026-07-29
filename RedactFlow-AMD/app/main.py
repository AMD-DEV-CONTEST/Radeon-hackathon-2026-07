from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import RedactFlowAgent
from .models import AgentPlan, DocumentCreate, ExecuteRequest, ExecutionResult, TaskRequest
from .store import Store


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("REDACTFLOW_DATA_DIR", BASE_DIR / "data"))
store = Store(DATA_DIR / "redactflow.db")
agent = RedactFlowAgent(store)

app = FastAPI(title="RedactFlow AMD", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "app" / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "privacy_mode": "local-only",
        "llm_backend": agent.llm.backend,
        "documents": len(store.list_documents()),
    }


@app.post("/api/documents")
def add_document(document: DocumentCreate) -> dict:
    document_id = hashlib.sha256(f"{document.name}\n{document.content}".encode()).hexdigest()[:16]
    store.put_document(document_id, document.name, document.content)
    store.remember("document_added", {"document_id": document_id, "name": document.name})
    return {"id": document_id, "name": document.name, "characters": len(document.content)}


@app.get("/api/documents")
def list_documents() -> list[dict]:
    return [
        {"id": doc["id"], "name": doc["name"], "characters": len(doc["content"])}
        for doc in store.list_documents()
    ]


@app.post("/api/plans", response_model=AgentPlan)
def create_plan(request: TaskRequest) -> AgentPlan:
    if not store.list_documents():
        raise HTTPException(status_code=409, detail="Add at least one document before planning.")
    return agent.create_plan(request.task)


@app.post("/api/execute", response_model=ExecutionResult)
def execute(request: ExecuteRequest) -> ExecutionResult:
    try:
        return agent.execute(request.plan_id, set(request.approved_tools))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Plan not found") from error


@app.get("/api/memories")
def memories() -> list[dict]:
    return store.recent_memories()

