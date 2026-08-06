import gradio as gr
from typing import Tuple

def create_agent_thoughts_display() -> Tuple[gr.Accordion, gr.Markdown]:
    """Build the agent reasoning/thoughts display component.
    
    Returns:
        Tuple of (thoughts_accordion, thoughts_text)
    """
    with gr.Accordion("🤔 Agent Reasoning Process", open=False) as thoughts_accordion:
        thoughts_text = gr.Markdown(
            "Waiting for agent activity...",
            elem_id="agent-thoughts-display"
        )
        
    return thoughts_accordion, thoughts_text
