import gradio as gr
from typing import Callable, Tuple, Any

def create_privacy_dashboard(get_status_fn: Callable[[], dict]) -> Tuple[gr.Number, gr.Number, gr.Textbox, gr.Dataframe, gr.Button]:
    """Build the Gradio privacy dashboard component.
    
    Args:
        get_status_fn: Callable() -> dict (returns PrivacyDashboard.get_dashboard_data())
    
    Returns:
        Tuple of (local_pct_display, inference_count, external_bytes, recent_flows, refresh_btn)
    """
    with gr.Column():
        gr.Markdown("### 🔒 Privacy Dashboard")
        
        with gr.Row():
            local_pct_display = gr.Number(
                label="Local Inference %",
                value=100.0,
                precision=1,
                interactive=False
            )
            
        with gr.Row():
            inference_count = gr.Number(
                label="Total Inferences",
                value=0,
                precision=0,
                interactive=False
            )
            
        with gr.Row():
            external_bytes = gr.Textbox(
                label="External Data Sent (bytes)",
                value="0",
                interactive=False
            )
            
        with gr.Row():
            gr.Markdown("#### Recent Data Flows")
            recent_flows = gr.Dataframe(
                headers=["Timestamp", "Event", "Type", "Bytes"],
                interactive=False,
                row_count=5
            )
            
        with gr.Row():
            refresh_btn = gr.Button("🔄 Refresh Dashboard")
            
    return local_pct_display, inference_count, external_bytes, recent_flows, refresh_btn
