"""启动 Gradio Web UI"""
import os
import sys
sys.path.insert(0, ".")

import gradio as gr
from src.agent import load_config, InventoryDocAgent
from src.ui import create_ui, APP_CSS

host = os.getenv("GRADIO_SERVER_HOST", "0.0.0.0")
port = int(os.getenv("GRADIO_SERVER_PORT", "7862"))

print("Loading config...")
config = load_config()

print("Initializing agent...")
agent = InventoryDocAgent(config)

print("Creating UI...")
ui = create_ui(agent)

print(f"Starting server on http://{host}:{port}")
ui.launch(server_name=host, server_port=port, share=False, theme=gr.themes.Soft(), css=APP_CSS)
