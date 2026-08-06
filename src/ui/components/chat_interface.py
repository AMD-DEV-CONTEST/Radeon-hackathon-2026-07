import gradio as gr
from typing import Callable, Tuple

def create_chat_interface(agent_runner_fn: Callable) -> Tuple[gr.Chatbot, gr.Textbox, gr.Button, gr.Markdown]:
    """Build the Gradio chat interface component.
    
    Args:
        agent_runner_fn: Callable(message, history, session_id) -> (response, thoughts)
    
    Returns:
        Tuple of (chatbot, message_input, send_btn, thoughts_display)
    """
    with gr.Column(scale=1):
        chatbot = gr.Chatbot(
            label="💬 Agent Chat",
            height=500,
            show_copy_button=True,
            bubble_full_width=False
        )
        
        with gr.Row():
            message_input = gr.Textbox(
                show_label=False,
                placeholder="Type your message here...",
                scale=4,
                container=False
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)
            
    return chatbot, message_input, send_btn
