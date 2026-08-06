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
    
    def get_or_create_session(self) -> str:
        """Return current session or create new one."""
        if not self.current_session_id:
            self.current_session_id = str(uuid.uuid4())
            logger.info(f"Created new UI session: {self.current_session_id}")
        return self.current_session_id

    def handle_message(self, message: str, history: list, session_id: str) -> Tuple[list, str, str]:
        """Handle incoming user message and generate agent response.
        
        Args:
            message: The user's input string.
            history: Chatbot history list.
            session_id: The session ID.
            
        Returns:
            Tuple of (updated_history, thoughts_text, cleared_input)
        """
        if not message.strip():
            return history, "", ""
            
        s_id = session_id or self.get_or_create_session()
        
        # In a real implementation, interact with self.session_store and self.context_manager here
        
        # Call agent
        try:
            # Assuming agent.run returns (response_string, thoughts_string)
            response, thoughts = self.agent.run(message, s_id)
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            response = f"❌ Error processing request: {str(e)}"
            thoughts = "Execution failed."

        history.append((message, response))
        
        return history, thoughts, ""

    def refresh_dashboard(self) -> Tuple[float, int, str, pd.DataFrame]:
        """Fetch updated data for the privacy dashboard.
        
        Returns:
            Tuple of updated values for dashboard components.
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
            data.get("total_inferences", 0),
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
            # Session State
            session_state = gr.State(self.get_or_create_session())
            
            gr.Markdown("# 🔒 Bunker\n*Your Private AI Agent. Zero Data Exfiltration.*")
            
            with gr.Row():
                # Left Column: Chat & Reasoning (2/3 width)
                with gr.Column(scale=2):
                    chatbot, msg_input, send_btn = create_chat_interface(None)
                    thoughts_accordion, thoughts_text = create_agent_thoughts_display()
                    
                # Right Column: Privacy Dashboard (1/3 width)
                with gr.Column(scale=1):
                    local_pct, inf_count, ext_bytes, recent_flows, refresh_btn = create_privacy_dashboard(self.dashboard.get_dashboard_data)
                    
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
            refresh_outputs = [local_pct, inf_count, ext_bytes, recent_flows]
            
            refresh_btn.click(
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
