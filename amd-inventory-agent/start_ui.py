"""启动 Gradio Web UI"""
import sys
sys.path.insert(0, ".")

import gradio as gr
from src.agent import load_config, InventoryDocAgent
from src.ui import create_ui

print("Loading config...")
config = load_config()

print("Initializing agent...")
agent = InventoryDocAgent(config)

print("Creating UI...")
ui = create_ui(agent)

print("Starting server on http://localhost:7860")
ui.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=gr.themes.Soft())
