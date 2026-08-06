import logging
import gradio as gr
import uuid
import pandas as pd
from typing import Optional, Tuple, Any

from .components.chat_interface import create_chat_interface
from .components.privacy_dashboard import create_privacy_dashboard
from .components.agent_thoughts import create_agent_thoughts_display

logger = logging.getLogger(__name__)


def _apply_gradio_client_compat_shim() -> None:
    """Guard gradio_client's schema parser against boolean schema nodes.

    gradio 4.44.1 pins gradio_client==1.3.0, whose
    ``_json_schema_to_python_type`` crashes on boolean JSON Schema 2020-12
    nodes (e.g. ``additionalProperties: true/false``) while rendering the
    API-info used behind the ``/`` page. Boolean nodes simply map to ``bool``.
    """
    import gradio_client.utils as gcu

    if getattr(gcu, "_bunker_bool_schema_shim", False):
        return

    _orig_get_type = gcu.get_type

    def _get_type(schema):
        if isinstance(schema, bool):
            return "boolean"
        return _orig_get_type(schema)

    gcu.get_type = _get_type
    gcu._bunker_bool_schema_shim = True


_apply_gradio_client_compat_shim()

class BunkerGradioApp:
    """Bunker Gradio web interface with privacy dashboard."""
    
    REFRESH_INTERVAL = 2  # seconds
    
    def __init__(self, agent: Any, privacy_dashboard: Any, 
                 session_store: Any, context_manager: Any,
                 permission_controller: Any):
        self.agent = agent
        self.dashboard = privacy_dashboard
        self.session_store = session_store
        self.context_manager = context_manager
        self.permission_controller = permission_controller
        self.current_session_id: Optional[str] = None
        self.app: Optional[gr.Blocks] = None
        
        logger.info("BunkerGradioApp initialized.")
    
    def get_or_create_session(self, session_id: str = "") -> str:
        """Reuse an existing persisted session or create a new SessionStore row.

        The UI's chat flow hands out a per-browser session id (via
        ``gr.State``). The first message with a fresh id creates the SQLite
        session row so every subsequent turn, including follow-ups, is
        attributable to the same persisted conversation.

        Args:
            session_id: The session id from the client state, if any.

        Returns:
            The active session id (the client's when given, otherwise a new
            one), persisted in the SessionStore.
        """
        candidate = session_id or uuid.uuid4().hex
        if self.session_store is None or not hasattr(self.session_store, "get_session"):
            self.current_session_id = candidate
            return candidate
        if self.session_store.get_session(candidate) is None:
            self.session_store.create_session(title="Bunker Chat", session_id=candidate)
            logger.info("Created persisted session: %s", candidate)
        self.current_session_id = candidate
        return candidate

    def handle_message(self, message: str, history: list, session_id: str) -> Tuple[list, str, str]:
        """Handle incoming user message and generate agent response.

        Each turn is persisted to the SessionStore by the orchestrator, which
        also rebuilds the bounded conversation history (via ContextManager) so
        follow-up turns receive prior context from SQLite rather than only from
        Gradio's in-memory chat history.

        Args:
            message: The user's input string.
            history: Chatbot history list.
            session_id: The session ID (None on the very first message).

        Returns:
            Tuple of (updated_history, thoughts_text, cleared_input)
        """
        if not message.strip():
            return history, "", ""

        s_id = self.get_or_create_session(session_id)

        try:
            response, thoughts = self.agent.run(message, s_id)
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            response = f"❌ Error processing request: {str(e)}"
            thoughts = "Execution failed."

        history.append((message, response))

        return history, thoughts, ""

    def refresh_dashboard(self) -> Tuple[float, int, int, int, str, str, pd.DataFrame]:
        """Fetch updated data for the privacy dashboard.
        
        Returns:
            Tuple of updated values for dashboard components:
            (local_pct, local_inferences, external_inferences,
             failed_inferences, local_bytes, external_bytes, recent_flows_df).
        """
        data = self.dashboard.get_dashboard_data()
        
        # Format recent events for dataframe
        recent = data.get("recent_events", [])
        formatted_recent = []
        for e in reversed(recent):
            formatted_recent.append({
                "Timestamp": e.get("timestamp", "").split("T")[-1][:8], # Just time
                "Event": e.get("event_type", "unknown"),
                "Type": "Local" if e.get("is_local") else "External",
                "Bytes": e.get("bytes_processed", 0)
            })
            
        df = pd.DataFrame(formatted_recent) if formatted_recent else pd.DataFrame(columns=["Timestamp", "Event", "Type", "Bytes"])
        
        return (
            data.get("local_inference_pct", 100.0),
            data.get("local_inferences", 0),
            data.get("external_inferences", 0),
            data.get("failed_inferences", 0),
            str(data.get("local_bytes", 0)),
            str(data.get("external_bytes", 0)),
            df
        )

    def build_ui(self) -> gr.Blocks:
        """Construct the Gradio UI layout."""
        theme = gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="slate",
            neutral_hue="slate",
            font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"]
        )
        
        with gr.Blocks(theme=theme, title="Bunker AI") as self.app:
            # Session State: created lazily on the first message so an empty
            # page load never leaves an orphan session row in SQLite.
            session_state = gr.State(None)
            
            gr.Markdown("# 🔒 Bunker\n*Your Private AI Agent. Local-first, telemetry-verified.*")
            
            with gr.Row():
                # Left Column: Chat & Reasoning (2/3 width)
                with gr.Column(scale=2):
                    chatbot, msg_input, send_btn = create_chat_interface(None)
                    thoughts_accordion, thoughts_text = create_agent_thoughts_display()
                    
                # Right Column: Privacy Dashboard (1/3 width)
                with gr.Column(scale=1):
                    local_pct, local_inf, ext_inf, failed_inf, local_bytes, ext_bytes, recent_flows, refresh_btn = create_privacy_dashboard(self.dashboard.get_dashboard_data)
                    
                    with gr.Accordion("⚙️ Permissions", open=True):
                        file_write = gr.Checkbox(label="File System Write", value=True)
                        email_access = gr.Checkbox(label="Email Access", value=False)
                        calendar_access = gr.Checkbox(label="Calendar Access", value=False)
                        web_search = gr.Checkbox(label="Web Search", value=False)
                        
            # Wiring Chat
            submit_event = msg_input.submit(
                self.handle_message,
                inputs=[msg_input, chatbot, session_state],
                outputs=[chatbot, thoughts_text, msg_input]
            )
            
            send_click_event = send_btn.click(
                self.handle_message,
                inputs=[msg_input, chatbot, session_state],
                outputs=[chatbot, thoughts_text, msg_input]
            )
            
            # Wiring Dashboard Refresh
            refresh_outputs = [local_pct, local_inf, ext_inf, failed_inf, local_bytes, ext_bytes, recent_flows]
            
            refresh_btn.click(
                self.refresh_dashboard,
                inputs=[],
                outputs=refresh_outputs
            )
            
            # Auto-refresh the privacy dashboard every 2 seconds so live audit /
            # data-flow changes are visible without a manual click.
            timer = gr.Timer(value=2.0, active=True)
            timer.tick(
                self.refresh_dashboard,
                inputs=[],
                outputs=refresh_outputs
            )
            
        return self.app

    def launch(self, **kwargs) -> None:
        """Launch the Gradio application."""
        if self.app is None:
            self.build_ui()
        logger.info("Launching Bunker UI...")
        self.app.launch(**kwargs)
        
    def get_gradio_app(self) -> gr.Blocks:
        """Get the constructed Gradio Blocks instance."""
        if self.app is None:
            self.build_ui()
        return self.app
