import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Bunker guarantees zero data exfiltration: keep Gradio's telemetry/analytics
# pings local before the UI is first constructed.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr

from .config import get_config
from .inference import VLLMServer, ModelManager, RadeonCloudAPI
from . import dspy_runtime  # noqa: F401 — configures the DSPy LM at startup
from .agent import BunkerOrchestrator, DspyReActAgent, PermissionController
from .privacy import AuditLogger, DataFlowMonitor, PrivacyDashboard
from .rag.embeddings import ROCEmbeddings
from .rag.vector_store import VectorStore
from .rag.document_loader import DocumentLoader
from .rag.multihop_rag import load_bunker_rag_program, make_chromadb_search
from .memory.session_store import SessionStore
from .memory.context_manager import ContextManager
from .ui.gradio_app import BunkerGradioApp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
config = get_config()
model_manager = None
data_flow_monitor = None
react_agent = None
bunker_rag = None
orchestrator = None

class _GradioAgentAdapter:
    """Adapts ``DspyReActAgent.run`` (dict) to the UI's (response, thoughts) contract.

    ``BunkerGradioApp.handle_message`` expects ``agent.run(...)`` to return a
    ``(response, thoughts)`` tuple, while ``DspyReActAgent.run`` returns a
    result dict with ``status``/``response`` keys. This adapter bridges the two
    without coupling the UI layer to the agent's internal result shape.
    """

    def __init__(self, agent):
        self._agent = agent

    def run(self, message: str, session_id: str = ""):
        result = self._agent.run(message, session_id=session_id)
        if isinstance(result, dict):
            return (
                result.get("response", "No response produced."),
                result.get("status", "Completed."),
            )
        return result


def build_gradio_app() -> gr.Blocks:
    """Builds the full Bunker Gradio UI (chat + reasoning + privacy dashboard)."""
    audit_logger = AuditLogger(log_path=config.privacy.audit_log_path)
    monitor = DataFlowMonitor()
    dashboard = PrivacyDashboard(audit_logger=audit_logger, data_flow_monitor=monitor)
    controller = PermissionController()
    session_store = SessionStore(db_path=config.memory.db_path)
    context_manager = ContextManager(
        session_store=session_store,
        max_tokens=config.memory.max_context_tokens,
        chars_per_token=config.memory.chars_per_token,
    )
    agent = _GradioAgentAdapter(
        DspyReActAgent(
            permission_controller=controller,
            data_flow_monitor=monitor,
            audit_logger=audit_logger,
        )
    )
    return BunkerGradioApp(
        agent=agent,
        privacy_dashboard=dashboard,
        session_store=session_store,
        context_manager=context_manager,
        permission_controller=controller,
    ).get_gradio_app()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events for the FastAPI app."""
    global model_manager, data_flow_monitor, react_agent, bunker_rag, orchestrator
    logger.info("Starting Bunker AI Agent...")
    
    try:
        audit_logger = AuditLogger(log_path=config.privacy.audit_log_path)
        data_flow_monitor = DataFlowMonitor()
        
        # Initialize Inference
        try:
            model_manager = ModelManager(config.inference, audit_logger=audit_logger)
            model_manager.initialize()
        except Exception as e:
            logger.warning(f"Inference model_manager initialization deferred or degraded: {e}")
        
        # Initialize RAG components with graceful fallback
        search = None
        try:
            embeddings = ROCEmbeddings(model_name=config.rag.embedding_model)
            vector_store = VectorStore(embeddings=embeddings, persist_dir=config.rag.vector_db_path)
            doc_loader = DocumentLoader(chunk_size=config.rag.chunk_size, chunk_overlap=config.rag.chunk_overlap)
            if hasattr(vector_store, "search"):
                search = make_chromadb_search(vector_store)
        except Exception as e:
            logger.warning(f"VectorStore / ROCEmbeddings uninitialized (degraded RAG mode): {e}")

        # Initialize the DSPy RAG program
        bunker_rag = load_bunker_rag_program(
            search=search,
            num_hops=config.rag.num_hops,
            num_docs=config.rag.num_docs,
            max_backtracks=config.rag.max_backtracks,
        )
        
        # Initialize Memory
        session_store = SessionStore(db_path=config.memory.db_path)
        context_manager = ContextManager(session_store=session_store, max_tokens=config.memory.max_context_tokens, chars_per_token=config.memory.chars_per_token)
        
        # Initialize the DSPy agent.
        react_agent = DspyReActAgent(
            permission_controller=PermissionController(),
            data_flow_monitor=data_flow_monitor,
            audit_logger=audit_logger,
        )
        orchestrator = BunkerOrchestrator(rag=bunker_rag, agent=react_agent)
        logger.info("All services initialized successfully.")
    except Exception as e:
        logger.error(f"Error during service initialization: {e}")
        # Allow app to start even if some services fail, for graceful degradation
    
    yield
    
    logger.info("Shutting down Bunker AI Agent...")
    if model_manager and hasattr(model_manager, "shutdown"):
        try:
            model_manager.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down model manager: {e}")

app = FastAPI(title="Bunker API", lifespan=lifespan)

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}

@app.get("/api/privacy/status")
async def privacy_status():
    """Returns the current data flow and privacy status."""
    if data_flow_monitor:
        # Assuming data_flow_monitor has this method
        try:
            return data_flow_monitor.get_current_status()
        except Exception as e:
            logger.error(f"Error getting privacy status: {e}")
    return {"status": "unknown", "message": "DataFlowMonitor not initialized"}

# Mount Gradio app
gradio_app = build_gradio_app()
app = gr.mount_gradio_app(app, gradio_app, path="/")

if __name__ == "__main__":
    uvicorn.run("src.main:app", host=config.server.host, port=config.server.port, reload=config.server.debug)
