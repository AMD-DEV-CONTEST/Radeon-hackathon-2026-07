import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

# Bunker guarantees zero data exfiltration: keep Gradio's telemetry/analytics
# pings local before the UI is first constructed.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr

from .config import get_config
from .inference import ModelManager
from . import dspy_runtime  # noqa: F401 — configures the DSPy LM at startup
from .runtime import BunkerRuntime
from .ui.gradio_app import BunkerGradioApp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances. A single BunkerRuntime backs both the mounted Gradio UI and
# the FastAPI lifespan, so the chat, privacy dashboard, audit log, and RAG/agent
# pipeline all share one set of services. The module-level aliases are kept for
# backwards-compatible imports and the /api/privacy/status endpoint.
config = get_config()
runtime = None
model_manager = None
audit_logger = None
data_flow_monitor = None
privacy_dashboard = None
react_agent = None
bunker_rag = None
orchestrator = None


def get_runtime() -> BunkerRuntime:
    """Return the single shared runtime, creating it on first use.

    Both ``build_gradio_app`` (called at import time for the mount) and the
    FastAPI ``lifespan`` resolve to the same instance, so the UI never sees a
    second copy of the audit logger, data-flow monitor, session store, or agent.
    """
    global runtime
    if runtime is None:
        runtime = BunkerRuntime(config=config)
    return runtime


def build_gradio_app() -> gr.Blocks:
    """Build the full Bunker Gradio UI backed by the shared orchestrator runtime.

    The chat handler is ``BunkerRuntime.adapter`` — a
    ``BunkerOrchestratorAdapter`` — so every user message is routed through the
    shared ``BunkerOrchestrator`` (RAG questions -> ``BunkerMultiHopRAG``,
    tool requests -> ``DspyReActAgent``) with multi-turn history persisted in
    the shared ``SessionStore``.
    """
    global audit_logger, data_flow_monitor, privacy_dashboard, react_agent, orchestrator
    rt = get_runtime()
    audit_logger = rt.audit_logger
    data_flow_monitor = rt.data_flow_monitor
    privacy_dashboard = rt.dashboard
    react_agent = rt.agent
    orchestrator = rt.orchestrator

    # Every DSPy LM call and ModelManager fallback feeds the same shared sinks.
    dspy_runtime.configure_telemetry(
        audit_logger=rt.audit_logger,
        data_flow_monitor=rt.data_flow_monitor,
    )

    return BunkerGradioApp(
        agent=rt.adapter,
        privacy_dashboard=rt.dashboard,
        session_store=rt.session_store,
        context_manager=rt.context_manager,
        permission_controller=rt.permission_controller,
    ).get_gradio_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events for the FastAPI app."""
    global model_manager, audit_logger, data_flow_monitor, privacy_dashboard
    global react_agent, bunker_rag, orchestrator
    logger.info("Starting Bunker AI Agent...")

    try:
        rt = get_runtime()
        audit_logger = rt.audit_logger
        data_flow_monitor = rt.data_flow_monitor
        privacy_dashboard = rt.dashboard
        react_agent = rt.agent
        orchestrator = rt.orchestrator
        dspy_runtime.configure_telemetry(
            audit_logger=rt.audit_logger,
            data_flow_monitor=rt.data_flow_monitor,
        )

        # Initialize Inference
        try:
            model_manager = ModelManager(
                config.inference,
                audit_logger=rt.audit_logger,
                data_flow_monitor=rt.data_flow_monitor,
            )
            model_manager.initialize()
        except Exception as e:
            logger.warning(f"Inference model_manager initialization deferred or degraded: {e}")

        if rt.dashboard is not None:
            rt.dashboard.model_manager = model_manager

        # Initialize RAG components with graceful fallback on the shared runtime.
        bunker_rag = rt.configure_rag(config)
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
