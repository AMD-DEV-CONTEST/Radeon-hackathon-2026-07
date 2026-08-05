#!/bin/bash
cd /app
python3 -c "
import sys
sys.path.insert(0, '.')
from src.ui import create_ui, APP_CSS
from src.agent import load_config, InventoryDocAgent

config = load_config()
agent = InventoryDocAgent(config)
ui = create_ui(agent)

ui.launch(server_name='0.0.0.0', server_port=7860, share=False, prevent_thread_lock=False, css=APP_CSS)
"
